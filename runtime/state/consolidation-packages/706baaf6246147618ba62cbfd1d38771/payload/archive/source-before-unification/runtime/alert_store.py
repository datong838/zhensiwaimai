#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""告警聚合与老化（P0-3 · 让信号浮出来）。

来源：docs/architecture/20261003-任务机制自进化优化方案.md §4 P0-3。

设计：
- 原始告警流 `state/alerts.jsonl` **原样保留**（append-only，审计底线不动）；
- 新增聚合视图 `state/alerts_summary.json`：按 (skill, category, code) 聚合，
  同一故障只占一行，带 first/last/count/consecutive/持续时长；
- 成功即治愈：skill SUCCESS 后其 open 条目标记 resolved_at（老化窗口后归档）；
- 归档：`state/alerts_archive.jsonl`（解决后保留统计摘要，不物理删除历史）；
- `--rebuild`：用 P0-1 收据解析器把**全部历史原始告警**（含 434 条
  "exit=1 未命中已知分类"）重建为可读聚合——历史噪音一次性变成可分诊的诊断流。

兼容 Python 3.9+；零第三方依赖。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

RUNTIME_DIR = Path(__file__).resolve().parent
STATE_DIR = RUNTIME_DIR / "state"
ALERTS_RAW = STATE_DIR / "alerts.jsonl"
ALERTS_SUMMARY = STATE_DIR / "alerts_summary.json"
ALERTS_ARCHIVE = STATE_DIR / "alerts_archive.jsonl"

# detail 中结构化故障码的形态（与 receipt.classify_receipt 输出一致）：
#   stage=xxx (receipt:stage) / reason=xxx (receipt:reason) /
#   nested-reason=xxx (receipt:nested_reason) / error-code=xxx (text)
_CODE_RE = re.compile(r"\b(stage|reason|nested-stage|nested-reason|error-code)=([^\s(]+)")
_LEGACY_RE = re.compile(r"exit=(\S+) 未命中已知分类")
_COMMAND_FAILED_RE = re.compile(r"--workflow-id\s+([^\s]+)")
_MAX_CODE_LEN = 96


def normalize_code(code: Optional[str]) -> str:
    """聚合键稳定性归一（不改原始告警与收据语义）。

    reason 类码偶尔是整条命令行（bridge 子进程把命令塞进收据 reason），
    直接做键会让同源故障裂成多行。归一规则：
    - `Command failed: ... --workflow-id X ...` → `command-failed:<X>`
    - 其余超长码 → `long-reason-<sha1前8>`（同文聚合、异文不撞）
    """
    code = (code or "").strip()
    if not code:
        return "uncoded"
    if code.lower().startswith("command failed:"):
        m = _COMMAND_FAILED_RE.search(code)
        return "command-failed:" + (m.group(1) if m else "unknown")
    if len(code) > _MAX_CODE_LEN:
        digest = hashlib.sha1(code.encode("utf-8")).hexdigest()[:8]
        return "long-reason-" + digest
    return code


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _atomic_write_json(path: Path, data) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def code_from_detail(detail: str) -> str:
    """从 detail 提取故障码；无结构化码时归并为 legacy-exit。"""
    d = detail or ""
    m = _CODE_RE.search(d)
    if m:
        return m.group(2)
    m = _LEGACY_RE.search(d)
    if m:
        return "legacy-exit-%s" % m.group(1)
    return "uncoded"


def _load_summary() -> Dict[str, dict]:
    if ALERTS_SUMMARY.exists():
        try:
            return json.loads(ALERTS_SUMMARY.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
    return {}


def _entry_key(skill: str, category: str, code: str) -> str:
    return "%s|%s|%s" % (skill, category, code)


def record_alert(skill: str, category: str, detail: str,
                 log_path: Optional[str] = None, code: Optional[str] = None,
                 ts: Optional[str] = None) -> dict:
    """登记一条告警到聚合视图（原始流由调用方照旧 append）。返回聚合条目。"""
    ts = ts or _now_iso()
    code = normalize_code(code or code_from_detail(detail))
    key = _entry_key(skill, category, code)
    data = _load_summary()
    entry = data.get(key) or {
        "skill": skill, "category": category, "code": code,
        "first_ts": ts, "count": 0, "consecutive": 0,
        "resolved_at": None,
    }
    entry["last_ts"] = ts
    entry["count"] = entry.get("count", 0) + 1
    entry["consecutive"] = entry.get("consecutive", 0) + 1
    entry["last_detail"] = detail
    entry["last_log"] = log_path
    if entry.get("resolved_at"):
        # 治愈后复发：重开一轮，保留历史累计
        entry["recurred_at"] = ts
        entry["consecutive"] = 1
    entry["resolved_at"] = None
    data[key] = entry
    _atomic_write_json(ALERTS_SUMMARY, data)
    return entry


def mark_skill_resolved(skill: str, ts: Optional[str] = None) -> int:
    """skill SUCCESS 后把它的 open 条目标记已解决。返回解决条数。"""
    ts = ts or _now_iso()
    data = _load_summary()
    n = 0
    for key, entry in data.items():
        if entry.get("skill") == skill and not entry.get("resolved_at"):
            entry["resolved_at"] = ts
            entry["resolved_consecutive"] = entry.get("consecutive", 0)
            entry["consecutive"] = 0
            n += 1
    if n:
        _atomic_write_json(ALERTS_SUMMARY, data)
    return n


def age_alerts(now: Optional[datetime] = None, resolved_days: int = 7) -> int:
    """老化：resolved 且 last_ts 早于 N 天的条目归档到 alerts_archive.jsonl。返回归档数。"""
    now = now or datetime.now()
    data = _load_summary()
    if not data:
        return 0
    keep: Dict[str, dict] = {}
    archived: list = []
    cutoff = time.time() - resolved_days * 86400
    for key, entry in data.items():
        resolved = entry.get("resolved_at")
        last = entry.get("last_ts") or ""
        try:
            last_t = datetime.fromisoformat(last).timestamp() if last else 0
        except ValueError:
            last_t = 0
        if resolved and last_t and last_t < cutoff:
            entry["archived_at"] = _now_iso()
            archived.append(entry)
        else:
            keep[key] = entry
    if not archived:
        return 0
    with ALERTS_ARCHIVE.open("a", encoding="utf-8") as f:
        for entry in archived:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    _atomic_write_json(ALERTS_SUMMARY, keep)
    return len(archived)


def load_summary() -> Dict[str, dict]:
    return _load_summary()


def open_issues() -> list:
    """未解决条目，按 consecutive（强度）降序——看护一眼看出哪条最久未解决。"""
    items = [e for e in _load_summary().values() if not e.get("resolved_at")]
    items.sort(key=lambda e: (-(e.get("consecutive") or 0), e.get("first_ts") or ""))
    return items


# ---------------------------------------------------------------- 历史重建

def rebuild_from_raw(alerts_path: Optional[Path] = None) -> dict:
    """把全部历史原始告警重建为可读聚合（一次性，幂等覆盖）。

    对每条历史告警：
    1. code 先取自 detail 的结构化码；
    2. 若是 legacy "exit=N 未命中已知分类" 且带 log 路径 → 用 P0-1 收据解析器
       读日志提取真实故障码（这正是 434 条历史噪音的可读化路径）；
    3. resolved 判定：该 skill 在告警之后有过成功（last_success.json）→ resolved。
    """
    try:
        sys.path.insert(0, str(RUNTIME_DIR))
        import receipt as _receipt  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        _receipt = None
    try:
        import skill_runner as _sr  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        _sr = None

    alerts_path = alerts_path or ALERTS_RAW
    data: Dict[str, dict] = {}
    n = 0
    readable = 0
    if not alerts_path.exists():
        _atomic_write_json(ALERTS_SUMMARY, data)
        return {"total": 0, "readable": 0, "skills": 0}
    last_success = {}
    if _sr is not None:
        try:
            last_success = json.loads(_sr.LAST_SUCCESS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            last_success = {}
    for line in alerts_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            evt = json.loads(line)
        except ValueError:
            continue
        n += 1
        skill = evt.get("skill") or "?"
        category = evt.get("category") or "?"
        detail = evt.get("detail") or ""
        ts = evt.get("ts") or ""
        log = evt.get("log")
        code = code_from_detail(detail)
        if code.startswith(("legacy-exit", "uncoded")) and log and _receipt is not None:
            rcpt = _receipt.parse_top_receipt_log(log)
            sig = _receipt.extract_signal(rcpt) if rcpt else None
            if sig:
                code = sig["code"]
                readable += 1
            else:
                # 文本兜底：Node 崩溃栈（无 JSON，仅 `Error: <code>`）——实测 50 条
                try:
                    log_text = Path(log).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    log_text = ""
                text_code = _receipt.extract_text_error(log_text)
                if text_code:
                    code = text_code
                    readable += 1
        key = _entry_key(skill, category, code)
        entry = data.get(key) or {
            "skill": skill, "category": category, "code": code,
            "first_ts": ts, "count": 0, "consecutive": 0,
            "resolved_at": None,
        }
        if ts and (not entry.get("last_ts") or ts >= entry["last_ts"]):
            entry["last_ts"] = ts
            entry["last_detail"] = detail
            entry["last_log"] = log
        entry["count"] = entry.get("count", 0) + 1
        entry["consecutive"] = entry.get("consecutive", 0) + 1
        data[key] = entry
    # resolved 判定：skill 在最后一条告警之后仍有成功 → 已解决
    for key, entry in data.items():
        ls = last_success.get(entry.get("skill") or "")
        lt = entry.get("last_ts") or ""
        if ls and lt:
            try:
                if datetime.fromisoformat(ls) >= datetime.fromisoformat(lt):
                    entry["resolved_at"] = ls
                    entry["resolved_consecutive"] = entry["consecutive"]
                    entry["consecutive"] = 0
            except ValueError:
                pass
    _atomic_write_json(ALERTS_SUMMARY, data)
    return {"total": n, "readable": readable,
            "keys": len(data), "skills": len({e.get("skill") for e in data.values()})}


# ---------------------------------------------------------------- CLI

def _cmd_show() -> int:
    items = open_issues()
    print("=== 未解决告警聚合（%d 条键）===" % len(items))
    for e in items:
        span = ""
        try:
            hours = (datetime.fromisoformat(e["last_ts"]) -
                     datetime.fromisoformat(e["first_ts"])).total_seconds() / 3600
            span = " 持续%.1fh" % hours
        except (ValueError, KeyError):
            pass
        print("  [%s] %s | %s | x%d%s | %s" % (
            e.get("category"), e.get("skill"), e.get("code"),
            e.get("consecutive") or 0, span, (e.get("last_detail") or "")[:100]))
        if e.get("last_log"):
            print("        log: %s" % e["last_log"])
    total = sum(e.get("count", 0) for e in _load_summary().values())
    print("\n(聚合键 %d 个，累计告警 %d 条；明细流 %s)" % (
        len(_load_summary()), total, ALERTS_RAW))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="P0-3 告警聚合与老化")
    ap.add_argument("--show", action="store_true", help="打印未解决聚合视图")
    ap.add_argument("--rebuild", action="store_true",
                    help="从 alerts.jsonl 全量重建聚合（含历史 UNKNOWN 可读化）")
    ap.add_argument("--age", action="store_true", help="执行一次老化归档")
    args = ap.parse_args()
    if args.rebuild:
        stat = rebuild_from_raw()
        print("[ok] 重建完成：%r" % stat)
        return 0 if stat.get("total") else 1
    if args.age:
        n = age_alerts()
        print("[ok] 归档 %d 条已解决旧告警" % n)
        return 0
    return _cmd_show()


if __name__ == "__main__":
    sys.exit(main())
