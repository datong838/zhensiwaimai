#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""顶层收据解析器（P0-1 · 结构化收据驱动的失败分类）。

来源：docs/architecture/20261003-任务机制自进化优化方案.md §4 P0-1 与 docs/solutions/P0-1-实施细则.md。

解析判据（三踩坑换来的"三个不要"，务必遵守）：
1. 顶层收据 = **全文最后一个「整行以 { 开头、整行可 json.loads 解析为 dict」的对象**。
   - 不要只扫尾部 8000 字节：jinsha 的收据是超长单行 JSON，截断会误判"无 stage"；
   - 不要"从末尾往前找第一个 {"：会命中嵌套子对象（如 reviewSummary.wechat）；
   - 不要用全文件 grep 命中数当判据：会把 executor_integrity 等内部提及算进去。
2. 字段优先级（命中即停）：
   外层 stage → 外层 ok → 外层 reason → 嵌套 reason / 嵌套 stage+failed → 文本 Error:<code>。
   **`reason` 与 `stage` 同等重要**：全量实测 434 条 UNKNOWN 中 241 条只有 reason 没有
   stage，漏掉 reason 覆盖面从 99.8% 塌到 25%。
3. 内层 workflowReceipt.ok **仅供业务链参考，绝不用于成败分类**（外层 ok 与内层可以
   相反：业务成功、末段发送失败）。
4. 语义纪律：本模块**不改变** classify() 的既有返回值语义——只在失败路径上把
   UNKNOWN 的 detail 从"exit=1 未命中已知分类"升级为可读故障码，并可能把原本仅凭
   文本兜底误判的分类纠正为收据结论。exit=0 / timed_out 的处理保持不变。
   **唯一例外（P0-1b，2026-10-06）**：`legacy-marker-*` 由"文本命中即
   SKIPPED_IDEMPOTENT"改为"**必须先核实当日 verified 外发 marker**"，无证据不得静音。

兼容 Python 3.9+；零第三方依赖。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple

# 单次读取日志的最大字节数（防止把 14GB 级历史日志整个读进内存）。
# 足以覆盖实测最大收据（jinsha 超长单行 JSON 远小于此），同时保证不截断收据行：
# 若文件大于此值，从尾部取窗口并丢弃第一个不完整行。
LOG_READ_WINDOW = 1_000_000

_TEXT_ERROR_RE = re.compile(r"[Ee]rror:\s*([A-Za-z0-9_\-\.]+)")


# ---------------------------------------------------------------- 顶层收据提取

def parse_top_receipt_text(text: str) -> Optional[dict]:
    """从任意文本中取「最后一个整行 { 开头且可解析」的 JSON 对象 = 顶层收据。"""
    if not text:
        return None
    best: Optional[dict] = None
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                obj = json.loads(s)
            except (ValueError, RecursionError):
                continue
            if isinstance(obj, dict):
                best = obj
    return best


def parse_top_receipt_log(path, max_bytes: int = LOG_READ_WINDOW) -> Optional[dict]:
    """从日志文件取顶层收据。大文件只读尾部窗口，但丢弃首个不完整行。"""
    p = Path(path)
    try:
        size = p.stat().st_size
        with p.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
                blob = f.read(max_bytes)
                # 丢弃窗口开头第一个（很可能不完整的）行
                nl = blob.find(b"\n")
                if nl >= 0:
                    blob = blob[nl + 1:]
            else:
                blob = f.read()
    except OSError:
        return None
    return parse_top_receipt_text(blob.decode("utf-8", errors="replace"))


# ---------------------------------------------------------------- 嵌套搜索

def _nested_search(obj, key: str):
    """深度优先找任意层级的 str 型 key 值（非空）。"""
    if isinstance(obj, dict):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
        for child in obj.values():
            found = _nested_search(child, key)
            if found:
                return found
    elif isinstance(obj, list):
        for child in obj:
            found = _nested_search(child, key)
            if found:
                return found
    return None


def _nested_stage_failed(obj):
    """深度优先找「stage 为字符串且同层 status=='failed'」的组合。"""
    if isinstance(obj, dict):
        st = obj.get("stage")
        if isinstance(st, str) and st.strip() and obj.get("status") == "failed":
            return st.strip()
        for child in obj.values():
            found = _nested_stage_failed(child)
            if found:
                return found
    elif isinstance(obj, list):
        for child in obj:
            found = _nested_stage_failed(child)
            if found:
                return found
    return None


def _phase_history_last(obj) -> Optional[str]:
    """取 phaseHistory 末项（优先外层，其次嵌套，再嵌入收据）。供 P1-1 断点续跑参考。"""
    if isinstance(obj, dict):
        ph = obj.get("phaseHistory")
        if isinstance(ph, list) and ph:
            return str(ph[-1])
        for child in obj.values():
            found = _phase_history_last(child)
            if found:
                return found
    elif isinstance(obj, list):
        for child in obj:
            found = _phase_history_last(child)
            if found:
                return found
    for emb in _embedded_receipt_dicts(obj):
        found = _phase_history_last(emb)
        if found:
            return found
    return None


# ------------------------------------------------- 嵌入收据下钻（P0-1c · 2026-10-06）
# 背景（真数据实测 2026-10-06）：Node 包装层把子进程收据**转义成字符串**塞进
# `stdout` 字段，形如：
#   {"ok":false,"reason":"Command failed: <整条命令>",
#    "stdout":"{\"ok\":false,\"reason\":\"legacy-marker-binding-mismatch\",...}"}
# 于是顶层 reason 只值 "Command failed: <cmd>"（一整行命令），真业务码被埋进字符串，
# 被 `_nested_search`（只走 dict/list 结构）整段丢弃。
# 实测：今日 158 条含收据日志中 24 条（15%）属此类，真码如
#   windows-driver-local-network-blocked / legacy-marker-binding-mismatch 全部丢失，
# 告警退化为「一整条命令」，看护无法据以判断。
# 修法：顶层 reason 属「执行包装层文案」时，下钻解析字符串字段里的 JSON 收据。
# 纪律：**绝不覆盖已有有效 reason** —— 仅当顶层 reason 属包装层时才下钻；
#       包装层前缀与处置提示外置到「认知层」数据文件（可版本化/可回滚）。
_EMBEDDED_DEPTH = 3
_KNOWN_CODES_FILE = Path(__file__).resolve().parent / "experience" / "known_codes.json"
_DEFAULT_WRAPPER_PREFIXES = ("command failed:",)
_known_codes_cache: Optional[dict] = None


def load_known_codes(path=None) -> dict:
    """读「认知层」数据文件（experience/known_codes.json）。

    缺失 / 损坏 / 结构不符 ⇒ 返回 {}（行为零变化，退回内置默认）。
    新增认知只写数据文件，不覆盖本源码 —— 可版本化、可回滚。
    """
    global _known_codes_cache
    if path is None and _known_codes_cache is not None:
        return _known_codes_cache
    p = Path(path) if path else _KNOWN_CODES_FILE
    data: dict = {}
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(obj, dict):
            data = obj
    except (OSError, ValueError):
        data = {}
    if path is None:
        _known_codes_cache = data
    return data


def _wrapper_reason_prefixes():
    vals = load_known_codes().get("wrapperReasonPrefixes")
    if isinstance(vals, list) and vals and all(isinstance(v, str) for v in vals):
        return tuple(v.lower() for v in vals)
    return _DEFAULT_WRAPPER_PREFIXES


def is_wrapper_reason(code) -> bool:
    """某 reason 是否只是「执行包装层」文案（如 Node 的 `Command failed:`），而非业务码。"""
    if not isinstance(code, str) or not code.strip():
        return False
    low = code.strip().lower()
    return any(low.startswith(p) for p in _wrapper_reason_prefixes())


def _lookup_code_entry(code) -> Optional[dict]:
    """在认知层查该业务码的条目（容忍命名空间前缀：精确未命中则按最长子串匹配）。

    只读；不改变分类。查不到返回 None。
    """
    codes = load_known_codes().get("codes")
    if not isinstance(codes, dict) or not isinstance(code, str) or not code.strip():
        return None
    c = code.strip()
    ent = codes.get(c)
    if not isinstance(ent, dict):
        for known in sorted(codes, key=len, reverse=True):
            if known in c:
                ent = codes[known]
                break
    return ent if isinstance(ent, dict) else None


def code_note(code) -> Optional[str]:
    """查认知层里该业务码的「处置提示」（无则 None）。只读，不改分类。"""
    ent = _lookup_code_entry(code)
    if ent:
        note = ent.get("note")
        if isinstance(note, str) and note.strip():
            return note.strip()
    return None


def code_policy(code) -> dict:
    """查该业务码的处置策略（E3 机制占位，**默认零行为改变**）。

    返回 {note, tier, in_silence_allowlist, in_retry_allowlist, silence_allowed, retry_allowed}：
    - tier ∈ report-only / auto-retry-candidate / never-silence（缺省 report-only）；
    - silence/retry 是否放行 = 码在对应 allowlist 中 **且** tier != never-silence。
    allowlist 默认为空 ⇒ 本函数永远返回 silence_allowed=False / retry_allowed=False。
    启用某项须大同**逐条**批准后，把码填进 known_codes.json 的对应数组；消费方
    （自动静音/自动重试）须在批准后的波次里实现 —— 本波只就位机制、不动行为。
    """
    ent = _lookup_code_entry(code) or {}
    tier = ent.get("tier") if isinstance(ent.get("tier"), str) else "report-only"
    data = load_known_codes()
    c = str(code).strip() if isinstance(code, str) else ""
    silence_list = data.get("autoSilenceAllowlist")
    retry_list = data.get("autoRetryAllowlist")
    silence_list = silence_list if isinstance(silence_list, list) else []
    retry_list = retry_list if isinstance(retry_list, list) else []
    in_silence = c in silence_list
    in_retry = c in retry_list
    never = (tier == "never-silence")
    return {
        "note": code_note(code),
        "tier": tier,
        "in_silence_allowlist": in_silence,
        "in_retry_allowlist": in_retry,
        "silence_allowed": bool(in_silence and not never),
        "retry_allowed": bool(in_retry and not never),
    }


def _embedded_receipt_dicts(obj, max_depth: int = _EMBEDDED_DEPTH):
    """收集对象内「字符串字段里可解析成 dict 的 JSON」= 嵌入式收据（深度受限，先序）。"""
    out: list = []

    def walk(o, d: int):
        if d <= 0:
            return
        if isinstance(o, dict):
            for v in o.values():
                walk(v, d)
        elif isinstance(o, list):
            for v in o:
                walk(v, d)
        elif isinstance(o, str):
            s = o.strip()
            if s.startswith("{") and s.endswith("}"):
                try:
                    j = json.loads(s)
                except (ValueError, RecursionError):
                    return
                if isinstance(j, dict):
                    out.append(j)
                    walk(j, d - 1)

    walk(obj, max_depth)
    return out


def extract_signal(receipt: Optional[dict]) -> Optional[Dict[str, str]]:
    """按字段优先级从收据提取失败信号。返回 {kind, code} 或 None。

    kind ∈ stage / reason / nested_stage / nested_reason
           / embedded_stage / embedded_reason / embedded_nested_* （P0-1c 下钻）
    """
    if not isinstance(receipt, dict):
        return None
    stage = receipt.get("stage")
    if isinstance(stage, str) and stage.strip():
        return {"kind": "stage", "code": stage.strip()}
    reason = receipt.get("reason")
    reason_code = reason.strip() if isinstance(reason, str) and reason.strip() else None
    # 有效业务 reason 直接返回（包装层文案不算有效，留到最后兜底）
    if reason_code and not is_wrapper_reason(reason_code):
        return {"kind": "reason", "code": reason_code}
    nested_stage = _nested_stage_failed(receipt)
    if nested_stage:
        return {"kind": "nested_stage", "code": nested_stage}
    nested_reason = _nested_search(receipt, "reason")
    if nested_reason and not is_wrapper_reason(nested_reason):
        return {"kind": "nested_reason", "code": nested_reason}
    # P0-1c：下钻「被转义成字符串」的嵌入式收据，取真业务码
    for emb in _embedded_receipt_dicts(receipt):
        sig = extract_signal(emb)
        if sig is not None:
            return {"kind": "embedded_" + sig["kind"], "code": sig["code"]}
    if nested_reason:
        # 语义保持：`_nested_search` 会先命中外层同名键；当它与顶层 reason 相同时，
        # 旧实现在此前已按 kind="reason" 返回，故此处必须保持 "reason"（不得降级为 nested）。
        kind = "reason" if nested_reason == reason_code else "nested_reason"
        return {"kind": kind, "code": nested_reason}
    if reason_code:
        return {"kind": "reason", "code": reason_code}
    return None


def extract_text_error(text: str) -> Optional[str]:
    """文本兜底：取最后一个 `Error: <code>`（Node 崩溃栈形态）。"""
    if not text:
        return None
    last = None
    for m in _TEXT_ERROR_RE.finditer(text):
        last = m.group(1)
    return last


# ---------------------------------------------------------------- 分类（语义保持）

def _match_patterns(code: str, patterns) -> Optional[str]:
    low = (code or "").lower()
    for p in patterns:
        if p in low:
            return p
    return None


# --------------------------------------------------- 幂等证据（P0-1b · 2026-10-06）
# 背景：`legacy-marker-binding-mismatch` / `legacy-marker-type-mismatch` 是**二义码**——
#   (a) 良性：当日已有 verified 外发，重算内容 sha 变了被桥 check_old() 拒（防重复外发）
#   (b) 真故障：既有 marker 绑的是陈旧/占位载荷，从头到尾没发出去
# 桥在 check_old() 抛错前**不写 marker**，故 marker 会原样保留既有 state。判据因此是：
#   读 marker（attemptMarker / --ledger+--marker-name / <cwd>/.runtime/send-ledger/*.json），
#   `verified is True` 或 `state == 'verified'` 或 `ok is True` ⇒ 良性；否则 ⇒ 真故障。
# 找不到任何可读 marker 时**不得静音**（fail-closed），一律按真故障升级告警。
# 实测对照（2026-10-06，taobao-flash marker 目录）：
#   良性 state=verified/verified=True/sendAttempts=1；真故障 state=blocked/verified=False/sendAttempts=0。

_ATTEMPT_MARKER_RE = re.compile(r'"attemptMarker"\s*:\s*"([^"]+)"')
_LEDGER_FLAG_RE = re.compile(r"--(ledger|marker-name)\s+(\S+)")
_EVIDENCE_LOG_WINDOW = 200_000


def _all_nested(obj, key: str):
    """深度优先收集任意层级、任意数量的 str 型 key 值（非空）。"""
    out = []
    if isinstance(obj, dict):
        v = obj.get(key)
        if isinstance(v, str) and v.strip():
            out.append(v.strip())
        for child in obj.values():
            out.extend(_all_nested(child, key))
    elif isinstance(obj, list):
        for child in obj:
            out.extend(_all_nested(child, key))
    return out


def _read_tail_text(path, max_bytes: int = _EVIDENCE_LOG_WINDOW) -> str:
    p = Path(path)
    try:
        size = p.stat().st_size
        with p.open("rb") as f:
            if size > max_bytes:
                f.seek(size - max_bytes)
            return f.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def candidate_marker_paths(text: str, receipt: Optional[dict], workdir=None):
    """收集候选「外发 marker」文件路径，按优先级去重。

    顺序：① 收据内嵌套 attemptMarker ② 文本里的 "attemptMarker" ③ --ledger+--marker-name
    ④ workdir/.runtime/send-ledger/*.json（按 mtime 新→旧，最多 8 个，覆盖不带 marker 路径的流）。
    """
    cands = []
    if isinstance(receipt, dict):
        cands.extend(_all_nested(receipt, "attemptMarker"))
    for m in _ATTEMPT_MARKER_RE.finditer(text or ""):
        cands.append(m.group(1))
    flags = {}
    for m in _LEDGER_FLAG_RE.finditer(text or ""):
        flags[m.group(1)] = m.group(2)
    if flags.get("ledger") and flags.get("marker-name"):
        cands.append(str(Path(flags["ledger"]) / flags["marker-name"]))
    if workdir:
        ledger_dir = Path(workdir) / ".runtime" / "send-ledger"
        try:
            if ledger_dir.is_dir():
                files = [p for p in ledger_dir.glob("*.json") if not p.name.startswith(".")]
                files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
                cands.extend(str(p) for p in files[:8])
        except OSError:
            pass
    seen, ordered = set(), []
    for c in cands:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)
    return ordered


def idempotent_evidence(text: str, receipt: Optional[dict], workdir=None) -> Optional[Dict]:
    """核实 legacy-marker-* 是否属「当日已验证外发」的良性幂等。只读，不写不删。

    返回 {"verified": bool, "marker": str, "state": ..., "sendAttempts": ...}；
    找不到任何可读 marker 时返回 None（调用方必须按未证实处理，不得静音）。
    """
    for raw in candidate_marker_paths(text, receipt, workdir):
        p = Path(raw)
        try:
            if not p.is_file():
                continue
            obj = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(obj, dict):
            continue
        state = obj.get("state")
        verified = (obj.get("verified") is True) or (state == "verified") or (obj.get("ok") is True)
        return {"verified": bool(verified), "marker": str(p), "state": state,
                "sendAttempts": obj.get("sendAttempts")}
    return None


def _idempotent_decision(text: str, receipt: Optional[dict], workdir, pattern: str):
    """幂等模式命中后的证据裁决，返回 (category, detail_suffix, signal_extra)。"""
    try:
        ev = idempotent_evidence(text, receipt, workdir)
    except Exception:  # noqa: BLE001  证据解析自身异常一律按「未证实」处理（fail-closed）
        ev = None
    if ev and ev.get("verified"):
        return ("SKIPPED_IDEMPOTENT",
                " [evidence-verified marker=%s state=%s]" % (ev["marker"], ev.get("state")),
                {"idempotent_evidence": str(ev["marker"])})
    if ev:
        return ("UNKNOWN",
                " [idempotent-skip-UNVERIFIED marker=%s state=%s sendAttempts=%s]"
                % (ev["marker"], ev.get("state"), ev.get("sendAttempts")),
                {"idempotent_unverified": True, "idempotent_evidence": str(ev["marker"])})
    return ("UNKNOWN",
            " [idempotent-skip-UNVERIFIED 未定位到外发 marker：拒绝静音，按真故障升级 %r]" % (pattern,),
            {"idempotent_unverified": True})


def classify_receipt(text: str, exit_code, timed_out: bool,
                     log_path=None, classify_fallback=None,
                     needs_login_patterns=None, recoverable_patterns=None,
                     workdir=None):
    """失败分类主入口：收据优先，文本兜底，语义与 classify() 保持一致。

    返回 (category, detail, signal)：
    - category ∈ SUCCESS / RECOVERABLE / NEEDS_LOGIN / UNKNOWN / SKIPPED_IDEMPOTENT
    - detail：人类可读；失败时必含可读故障码（验收判据 ③）
    - signal：{"kind","code","phase_last"} 供 record/告警/经验索引/P1-1 使用

    语义纪律：
    - exit=0 且未超时 → SUCCESS（不变）；
    - timed_out → RECOVERABLE（不变）；
    - 其余：先收据后文本。收据存在时**以收据为准**（文本关键词可能把
      dependency-drift 误判成 RECOVERABLE——实测见过）；无收据时退回原
      classify_fallback 行为。

    P0-1b（2026-10-06）唯一例外：`legacy-marker-*` 由「文本命中即 SKIPPED」改为
    **证据裁决**——必须读到当日 verified 外发 marker 才判 SKIPPED_IDEMPOTENT；
    证据缺失/非 verified ⇒ UNKNOWN（照常告警）。见 `_idempotent_decision`。
    """
    # 延迟导入避免循环依赖：pattern 列表由调用方（skill_runner）传入或用默认
    from skill_runner import (  # noqa: PLC0415
        NEEDS_LOGIN_PATTERNS, RECOVERABLE_PATTERNS, IDEMPOTENT_SKIP_PATTERNS)
    needs_login_patterns = needs_login_patterns or NEEDS_LOGIN_PATTERNS
    recoverable_patterns = recoverable_patterns or RECOVERABLE_PATTERNS

    signal: Dict = {}
    phase_last = None

    if exit_code == 0 and not timed_out:
        return "SUCCESS", "全部步骤 exit=0", signal
    if timed_out:
        return "RECOVERABLE", "执行超时（看门狗已终止进程组）", signal

    # ---- 收据优先 ----
    receipt = parse_top_receipt_log(log_path) if log_path else None
    if receipt is None:
        receipt = parse_top_receipt_text(text or "")
    sig = extract_signal(receipt)
    if receipt:
        phase_last = _phase_history_last(receipt)

    # 幂等证据检索用的原始文本：日志尾部优先（命令行 / attemptMarker 常只落在日志里）
    raw_for_evidence = text or ""
    if log_path:
        _tail = _read_tail_text(log_path)
        if _tail:
            raw_for_evidence = _tail + "\n" + raw_for_evidence

    # 幂等**模式**的搜索面：必须是顶层收据的完整 JSON 序列化（含被转义包裹的子进程
    # stdout/reason），而不是仅外层 reason —— 实测 taobao-flash 的 `legacy-marker-*`
    # 码只出现在 `stdout` 字符串里，外层 reason 只有 "Command failed: <命令>"。
    # 无收据时退回文本。
    idem_hay = text or ""
    if receipt is not None:
        try:
            idem_hay = json.dumps(receipt, ensure_ascii=False)
        except (TypeError, ValueError):
            idem_hay = text or ""

    if sig is not None:
        code = sig["code"]
        # 关键词匹配在「故障码 + reason 全文」上做，登录态优先于瞬态（与原序一致）
        reason_text = ""
        if receipt:
            r = receipt.get("reason")
            if isinstance(r, str):
                reason_text = r
        hay = " ".join([code, reason_text])
        kind_label = {
            "stage": "stage", "reason": "reason",
            "nested_stage": "nested-stage", "nested_reason": "nested-reason",
            "embedded_stage": "embedded-stage", "embedded_reason": "embedded-reason",
            "embedded_nested_stage": "embedded-nested-stage",
            "embedded_nested_reason": "embedded-nested-reason",
        }.get(sig["kind"], sig["kind"])
        detail = "%s=%s (receipt:%s)" % (kind_label, code, sig["kind"])
        signal = {"kind": sig["kind"], "code": code}
        if phase_last:
            signal["phase_last"] = phase_last
            detail += " phase_last=%s" % phase_last
        # P0-1b：幂等类不再凭文本直接静音，必须先核实「当日已 verified 外发」证据
        idem = _match_patterns(idem_hay, IDEMPOTENT_SKIP_PATTERNS)
        if idem:
            category, extra_detail, extra_signal = _idempotent_decision(
                raw_for_evidence, receipt, workdir, idem)
            detail += extra_detail
            signal.update(extra_signal)
        elif _match_patterns(hay, needs_login_patterns):
            category = "NEEDS_LOGIN"
        elif _match_patterns(hay, recoverable_patterns):
            category = "RECOVERABLE"
        else:
            category = "UNKNOWN"
        # E3b（2026-10-06 大同裁决）：认知层 retry_allowed 的 UNKNOWN 码升格为
        # RECOVERABLE，复用现有「重试预算 max_retries + cooldown」全套护栏。
        # 仅升 UNKNOWN——绝不覆盖 NEEDS_LOGIN / 幂等决策；never-silence 档在
        # code_policy 内恒 retry_allowed=False，机制上不可被白名单穿透。
        if category == "UNKNOWN" and code_policy(code)["retry_allowed"]:
            category = "RECOVERABLE"
            detail += " [policy-retry: 认知层白名单允许自动重试]"
        # P0-1c：认知层处置提示（只增诊断文本，不改分类、不静音）
        note = code_note(code)
        if note:
            detail += " [note: %s]" % note
        return category, detail, signal

    # ---- 文本兜底：Error: <code> ----
    text_code = extract_text_error(text or "")
    if text_code:
        detail = "error-code=%s (text)" % text_code
        signal = {"kind": "text", "code": text_code}
        if phase_last:
            signal["phase_last"] = phase_last
        idem = _match_patterns(idem_hay or text_code, IDEMPOTENT_SKIP_PATTERNS)
        if idem:
            category, extra_detail, extra_signal = _idempotent_decision(
                raw_for_evidence, receipt, workdir, idem)
            detail += extra_detail
            signal.update(extra_signal)
        elif _match_patterns(text_code, needs_login_patterns):
            category = "NEEDS_LOGIN"
        elif _match_patterns(text_code, recoverable_patterns):
            category = "RECOVERABLE"
        else:
            category = "UNKNOWN"
        # E3b：同上，text 分支同样仅升 UNKNOWN（retry_allowed 判定见上）
        if category == "UNKNOWN" and code_policy(text_code)["retry_allowed"]:
            category = "RECOVERABLE"
            detail += " [policy-retry: 认知层白名单允许自动重试]"
        note = code_note(text_code)
        if note:
            detail += " [note: %s]" % note
        return category, detail, signal

    # ---- 原逻辑兜底（无任何结构化信号）----
    if classify_fallback is not None:
        category, detail = classify_fallback(text, exit_code, timed_out)
        return category, ("无收据; " + detail), signal
    return "UNKNOWN", "exit=%r 未命中已知分类（无结构化收据）" % (exit_code,), signal


def explain(receipt: Optional[dict]) -> str:
    """把收据解析结果渲染成一行人类可读诊断（供看护代理/人肉排查）。"""
    if receipt is None:
        return "(无可解析收据)"
    sig = extract_signal(receipt)
    if not sig:
        keys = ",".join(list(receipt.keys())[:8])
        return "(收据无失败信号字段; keys=%s)" % keys
    phase = _phase_history_last(receipt)
    out = "%s=%s" % (sig["kind"], sig["code"])
    if phase:
        out += " phase_last=%s" % phase
    inner = receipt.get("workflowReceipt")
    if isinstance(inner, dict) and "ok" in inner:
        out += " workflowReceipt.ok=%s" % inner.get("ok")
    return out
