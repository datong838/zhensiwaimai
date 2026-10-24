#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外卖运营统一调度薄包裹层 · skill_runner（Phase 1 · runtime/）

设计铁律（docs/architecture/系统架构加固方案-参考三独立系统.md §10）：
- 零碰 skill 内部逻辑：本层只按 manifest 以命令行方式包裹各 skill 现有入口。
- 安全门零改动：EXTERNAL_EFFECT fail-closed / 防重账本 / 逐字授权 / ActionResult 收据
  全在各 skill executor 内部，本层不感知、不绕过。
- 看护模型：一键启动（run_all.py）+ 代理（WorkBuddy）逐流程看护，非自治 cron。
- 失败分类：SUCCESS / RECOVERABLE（预算内自动重试）/ NEEDS_LOGIN（@人告警）/ UNKNOWN（升级）。

本模块同时是库（被 run_all.py 调用）与自测载体（--selftest 由 run_all.py 驱动）。
兼容 Python 3.9+。
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import signal
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

RUNTIME_DIR = Path(__file__).resolve().parent
REPO_ROOT = RUNTIME_DIR.parent
DEFAULT_MANIFEST = RUNTIME_DIR / "skills_manifest.json"
DEFAULT_HISTORY = RUNTIME_DIR / "run_history"
LOCK_PATH = RUNTIME_DIR / ".runner.lock"
STATE_DIR = RUNTIME_DIR / "state"
LAST_SUCCESS_FILE = STATE_DIR / "last_success.json"
# 各 skill 的「本轮独立输出目录」根（{run_dir} 占位 → <root>/<skill>/<ts>）
RUN_DIR_ROOT = STATE_DIR / "runs"

# ---- 本机回环/内网直连豁免（2026-09-30 确立） ----
# 为什么必须有：WorkBuddy/CI 沙箱会把 HTTP_PROXY/HTTPS_PROXY 注入子进程环境，
# 而 playwright-core 的自带 httpRequest() 会调用 getProxyForUrl() 读取这些变量
# （实测 playwright-core 1.62.1 lib/coreBundle.js:8394 `function httpRequest`）。
# 于是 chromium.connectOverCDP('http://127.0.0.1:9230') 的 DevTools 发现请求被
# 送到沙箱代理，代理对未白名单的 DevTools 端口一律回 404，特征报错为：
#   browserType.connectOverCDP: Unexpected status 404 when connecting to
#   http://127.0.0.1:9230/json/version/.  This does not look like a DevTools server
# 而同一时刻 `curl http://127.0.0.1:9230/json/version` 是 200 —— 端口本身健康，
# 纯粹是「代理劫持回环请求」。同一个 9232 恰好被代理放行，所以问题表现为
# 「时好时坏、按端口挑食」，极难定位。
# 修法：调度层在 spawn 时为每个 skill 子进程补 NO_PROXY/no_proxy，把本机回环
# 与局域网内网段排除在代理之外；其余出网流量仍走代理，语义不变。
# 覆盖 127.0.0.1 / localhost / ::1（CDP、金鲨本地 App）+ 192.168.*（Windows
# 微信驱动 192.168.110.184:8731 等内网服务）。
NO_PROXY_REQUIRED = ("127.0.0.1", "localhost", "::1", "192.168.0.0/16")


def merge_no_proxy(existing: Optional[str]) -> str:
    """把必需的回环/内网直连条目并入既有 NO_PROXY，去重保序。

    既有值为 '*' 时直接沿用（全豁免语义），不画蛇添足。
    """
    current = str(existing or "").strip()
    if current == "*":
        return current
    parts: List[str] = [p.strip() for p in current.split(",") if p.strip()]
    for item in NO_PROXY_REQUIRED:
        if item not in parts:
            parts.append(item)
    return ",".join(parts)


def local_network_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """返回应注入子进程的 NO_PROXY/no_proxy 覆盖（大小写双写，兼容各家实现）。"""
    base = env if env is not None else os.environ
    merged = merge_no_proxy(base.get("NO_PROXY") or base.get("no_proxy"))
    return {"NO_PROXY": merged, "no_proxy": merged}

# ---- 分类常量 ----
CAT_SUCCESS = "SUCCESS"
CAT_RECOVERABLE = "RECOVERABLE"      # 瞬态：预算内自动重试
CAT_NEEDS_LOGIN = "NEEDS_LOGIN"      # 登录态失效：@人告警，等人工恢复
CAT_UNKNOWN = "UNKNOWN"              # 真故障：升级，附日志
CAT_SKIPPED = "SKIPPED_IDEMPOTENT"   # 幂等保护：已核实「当日已 verified 外发」，重算内容被桥拒绝（非故障）

NEXT_ACTION = {
    CAT_SUCCESS: "无需动作",
    CAT_RECOVERABLE: "重试预算耗尽：看护代理读日志决定再等冷却重跑或跳过",
    CAT_NEEDS_LOGIN: "人工恢复登录态（扫码/重登）后由看护代理重跑",
    CAT_UNKNOWN: "看护代理读日志定位根因后升级处理",
    CAT_SKIPPED: "当日外发标记幂等保护触发（已核实当日 verified 外发证据）：不重发、不计失败、不告警",
}

# 分类关键词（小写匹配；NEEDS_LOGIN 优先级高于 RECOVERABLE）
NEEDS_LOGIN_PATTERNS = [
    "needs_login", "not logged in", "login required", "please log in",
    "login expired", "qr code", "scan qr", "未登录", "请登录", "扫码",
    "二维码", "登录态", "登录失效", "登录过期", "重新登录",
]
# 幂等保护（2026-10-05）：优先级最高——桥 check_old() 的同日标记拒发是
# 防重复外发的设计行为，不是故障。典型场景：top10 payload 是每次截图 sha
# 都不同的图片，当日 verified 外发后重跑必被拒（跨 3 天累计 30+ 次假 FAILED）。
IDEMPOTENT_SKIP_PATTERNS = [
    "legacy-marker-binding-mismatch",
    "legacy-marker-type-mismatch",
]
RECOVERABLE_PATTERNS = [
    "timed out", "timeout", "etimedout", "econnrefused", "econnreset",
    "econnaborted", "enotfound", "epipe", "socket hang up", "net::err",
    "device offline", "adb:", "connection refused", "connection reset",
    "temporarily", "transient", "超时", "连接失败", "连接超时", "暂时",
    "临时失败", "服务不可用",
]

LOG_TAIL_CHARS = 4000


# ---------------------------------------------------------------- 数据结构

@dataclass
class StepResult:
    argv: List[str]
    cwd: str
    exit_code: Optional[int]
    timed_out: bool
    duration_seconds: float
    log_path: str
    stdout_tail: str = ""
    stderr_tail: str = ""


# ---------------------------------------------------------------- 失败分类

def classify(text: str, exit_code: Optional[int], timed_out: bool) -> Tuple[str, str]:
    """按 输出文本 + 退出码 + 是否超时 归类。"""
    if exit_code == 0 and not timed_out:
        return CAT_SUCCESS, "全部步骤 exit=0"
    if timed_out:
        return CAT_RECOVERABLE, "执行超时（看门狗已终止进程组）"
    low = (text or "").lower()
    for p in IDEMPOTENT_SKIP_PATTERNS:
        if p in low:
            # P0-1b（2026-10-06）：裸 classify() 没有日志/文件系统上下文，无法核实
            # 「当日已 verified 外发」，因此**不得静音**。带证据的裁决在
            # receipt._idempotent_decision() 完成；此处按真故障升级（fail-closed）。
            return CAT_UNKNOWN, "幂等跳过待核证（无上下文，拒绝静音）: %r" % p
    for p in NEEDS_LOGIN_PATTERNS:
        if p in low:
            return CAT_NEEDS_LOGIN, "命中登录态特征: %r" % p
    for p in RECOVERABLE_PATTERNS:
        if p in low:
            return CAT_RECOVERABLE, "命中瞬态特征: %r" % p
    return CAT_UNKNOWN, "exit=%r 未命中已知分类" % exit_code


# P0-1（2026-10-03）：结构化收据驱动的失败分类。receipt 模块缺失时自动退回
# 上面的 classify()，库文件缺失不致瘫痪调度层。
try:  # noqa: SIM105
    import receipt as _receipt  # type: ignore
except ImportError:  # pragma: no cover
    _receipt = None


def classify_with_receipt(text: str, exit_code: Optional[int], timed_out: bool,
                          log_path: Optional[str] = None,
                          workdir: Optional[str] = None) -> Tuple[str, str, Dict]:
    """P0-1 主入口：收据优先、文本兜底，语义与 classify() 一致。

    返回 (category, detail, signal)。signal 含 kind/code/phase_last，供
    record.json、告警聚合（P0-3）与经验索引（P1-2）使用。

    P0-1b：`workdir` 用于定位该工作流的 send-ledger（幂等证据），使
    `legacy-marker-*` 能区分「当日已 verified 外发（良性）」与「从未发出（真故障）」。
    """
    if _receipt is None:
        category, detail = classify(text, exit_code, timed_out)
        return category, detail, {}
    return _receipt.classify_receipt(
        text, exit_code, timed_out, log_path=log_path, classify_fallback=classify,
        workdir=workdir)


# ---------------------------------------------------------------- 全局锁

class RunnerLock:
    """fcntl.flock 非阻塞互斥：防止两个 run_all 实例并行操作同一批真机资源。"""

    def __init__(self, path: Path = LOCK_PATH) -> None:
        self.path = Path(path)
        self._fh = None

    def acquire(self) -> bool:
        self._fh = open(self.path, "w")
        try:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self._fh.close()
            self._fh = None
            return False

    def release(self) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


# ---------------------------------------------------------------- 步骤执行

def _killpg(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return


def _killpg_force(proc: subprocess.Popen) -> None:
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        return


# --------------------------------------------------------- 步骤进程的遗骸登记
#
# 每一步都用 start_new_session=True 跑在自己的会话里：好处是超时能整组杀掉，
# 代价是 **daemon 死掉时它们不会跟着死** —— 被 launchd 收养后继续跑、继续驱动
# 共享的微信界面，而没人再看它的日志。这正是「占着微信却不工作」的真实形态：
# daemon 已被杀、技能还活着的孤儿，它会一直重复激活微信直到自己超时。
#
# 所以每步出生时登记 <pgid>.json、正常结束时注销；daemon 启动时（此刻独占全局
# 锁，收割任何遗留进程都是安全的）清理上一轮的遗骸，收到 SIGTERM 时立刻收割
# 正在跑的步骤，而不是等整个周期跑完。
LIVE_STEPS_DIR = STATE_DIR / "live_steps"


def _pgid_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    return True


def _register_step(proc: subprocess.Popen, argv: List[str]) -> Optional[Path]:
    try:
        LIVE_STEPS_DIR.mkdir(parents=True, exist_ok=True)
        record = LIVE_STEPS_DIR / ("%d.json" % os.getpgid(proc.pid))
        record.write_text(json.dumps({
            "pgid": os.getpgid(proc.pid), "pid": proc.pid, "argv": list(argv),
            "at": datetime.now().isoformat(timespec="seconds"),
        }, ensure_ascii=False), encoding="utf-8")
        return record
    except OSError:
        return None


def _unregister_step(record: Optional[Path]) -> None:
    if record is None:
        return
    try:
        record.unlink()
    except OSError:
        pass


def kill_live_steps(reason: str = "", grace: float = 5.0) -> List[dict]:
    """SIGTERM→(grace)→SIGKILL 收割所有已登记的步骤进程组，并清空登记。"""
    records = sorted(LIVE_STEPS_DIR.glob("*.json")) if LIVE_STEPS_DIR.exists() else []
    victims: List[Tuple[int, dict]] = []
    for record in records:
        try:
            data = json.loads(record.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        pgid = data.get("pgid")
        if isinstance(pgid, int) and _pgid_alive(pgid):
            victims.append((pgid, data))
        _unregister_step(record)
    for pgid, _ in victims:
        try:
            os.killpg(pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    if victims and grace > 0:
        deadline = time.time() + grace
        while time.time() < deadline and any(_pgid_alive(p) for p, _ in victims):
            time.sleep(0.25)
    for pgid, _ in victims:
        if _pgid_alive(pgid):
            try:
                os.killpg(pgid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
    for pgid, data in victims:
        print("[reap%s] 终止遗留步骤进程组 pgid=%s argv=%s" % (
            (":" + reason) if reason else "", pgid,
            " ".join(data.get("argv") or [])[:160]))
    return [{"pgid": pgid, "argv": data.get("argv")} for pgid, data in victims]


def reap_stale_steps() -> List[dict]:
    """daemon 启动时收割上一轮遗留的步骤进程（崩溃 / SIGKILL 之后的孤儿）。"""
    return kill_live_steps("startup")


def _tail_of(path: Path, limit: int = LOG_TAIL_CHARS) -> str:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return data[-limit:]


def run_step(argv: List[str], cwd: Path, timeout_seconds: int, log_path: Path,
             env: Optional[Dict[str, str]] = None) -> StepResult:
    """执行单步：进程组隔离 + 全局看门狗（SIGTERM→10s→SIGKILL）+ 日志落盘。"""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # 始终显式构造 env：既支持调用方覆盖，也强制注入本机回环/内网直连豁免，
    # 否则沙箱代理会劫持 CDP 发现请求（详见 NO_PROXY_REQUIRED 注释）。
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    full_env.update(local_network_env(full_env))
    start = time.time()
    timed_out = False
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            argv, cwd=str(cwd), stdout=log, stderr=subprocess.STDOUT,
            start_new_session=True, env=full_env,
        )
        record = _register_step(proc, argv)
        try:
            proc.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            _killpg(proc)
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                _killpg_force(proc)
                proc.wait()
        finally:
            _unregister_step(record)
    duration = round(time.time() - start, 2)
    tail = _tail_of(log_path)
    return StepResult(
        argv=list(argv), cwd=str(cwd), exit_code=proc.returncode,
        timed_out=timed_out, duration_seconds=duration,
        log_path=str(log_path), stdout_tail=tail, stderr_tail="",
    )


# ---------------------------------------------------------------- Skill 级执行

def run_skill(entry: Dict, history_dir: Optional[Path] = None,
              max_retries: Optional[int] = None, timeout_override: Optional[int] = None,
              cooldown: Optional[int] = None,
              env: Optional[Dict[str, str]] = None,
              interpreters: Optional[Dict[str, str]] = None,
              run_source: str = "daemon") -> Dict:
    """按 manifest 条目执行一个 skill：逐步执行 + 失败分类 + RECOVERABLE 预算内重试。

    重试语义：总尝试次数 <= 1 + max_retries；仅 RECOVERABLE 重试；
    NEEDS_LOGIN / UNKNOWN 不重试（交看护代理处理）。
    超时语义：per-step 看门狗（每步独立 timeout_seconds 预算）。

    run_source（2026-10-20 SRE 首轮成功率口径）：本 run 的触发来源，
    "daemon"（自动调度）| "manual"（manual_run_once / 人工直跑），随 record
    落盘为 triggered_by 字段。旧 record 无此字段按 daemon 处理（历史多数如此）。
    """
    name = entry["name"]
    history_dir = Path(history_dir) if history_dir else DEFAULT_HISTORY
    retries = entry.get("max_retries", 2) if max_retries is None else max_retries
    timeout = entry.get("timeout_seconds", 1800) if timeout_override is None else timeout_override
    cool = entry.get("cooldown_seconds", 300) if cooldown is None else cooldown
    cwd = REPO_ROOT / entry.get("cwd", ".")
    steps = entry["steps"]

    started_at = datetime.now().isoformat(timespec="seconds")
    t0 = time.time()
    attempts = 0
    all_logs = []
    category, detail = CAT_UNKNOWN, "未执行"
    fail_signal: Dict[str, str] = {}

    while True:
        attempts += 1
        ts = time.strftime("%Y%m%d-%H%M%S")
        day_dir = history_dir / time.strftime("%Y-%m-%d")
        day_dir.mkdir(parents=True, exist_ok=True)

        # 本轮独立输出目录：供需要「本次独立输出目录」参数的 skill 使用（{run_dir} 占位）
        run_dir = RUN_DIR_ROOT / name / ts
        run_dir.mkdir(parents=True, exist_ok=True)
        ctx = {"run_dir": str(run_dir), "date": time.strftime("%Y-%m-%d"), "ts": ts}

        step_results: List[StepResult] = []
        failed = False
        combined_tail: List[str] = []
        for i, step in enumerate(steps, 1):
            slog = day_dir / ("%s--%s--a%d--s%d.log" % (name, ts, attempts, i))
            resolved = [resolve_token(a, interpreters, ctx) for a in step.get("argv", [])]
            sr = run_step(resolved, cwd, timeout, slog, env=env)
            step_results.append(sr)
            all_logs.append(str(slog))
            combined_tail.append(sr.stdout_tail or "")
            # 诊断自包含：把本步日志同步落一份到 {run_dir}/stepN.log。
            # 否则 skill 早期崩溃时 run_dir 是空目录，看护只能靠猜 —— 实测代价：
            # 3 条流水线 exit=1 却查不到原因，静默失败 2 天才被发现。
            try:
                shutil.copyfile(slog, run_dir / ("step%d.log" % i))
            except OSError:
                pass
            if sr.exit_code != 0 or sr.timed_out:
                failed = True
                break

        if not failed:
            category, detail = CAT_SUCCESS, "全部 %d 步 exit=0" % len(steps)
            break
        last = step_results[-1]
        # P0-1：收据优先分类——detail 必含可读故障码（stage/reason/error-code）
        # P0-1b：传 workdir 以便对 legacy-marker-* 做「当日 verified 外发」证据裁决
        category, detail, fail_signal = classify_with_receipt(
            "\n".join(combined_tail), last.exit_code, last.timed_out, last.log_path,
            workdir=str(cwd))
        if category != CAT_RECOVERABLE or attempts > retries:
            break
        if cool > 0:
            time.sleep(cool)

    if category == CAT_SUCCESS:
        status = "SUCCESS"
    elif category == CAT_SKIPPED:
        status = "SKIPPED"  # 幂等跳过：已核实「当日已 verified 外发」，非失败（P0-1b）
    else:
        status = "FAILED"
    record = {
        "skill": name,
        "ledger_name": entry.get("ledger_name", name),
        "schedule": entry.get("schedule", ""),
        "dev_state": entry.get("dev_state", ""),
        "status": status,
        "category": category,
        "detail": detail,
        "next_action": NEXT_ACTION[category],
        "attempts": attempts,
        "max_retries": retries,
        "duration_seconds": round(time.time() - t0, 2),
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "triggered_by": run_source,
        "logs": all_logs,
    }
    # P0-1/P1-2：结构化故障信号随 record 落盘（供告警聚合、经验索引、P1-1 续跑规划）
    if fail_signal:
        record["fail_signal"] = fail_signal
    rec_path = day_dir / ("%s--%s--record.json" % (name, ts))
    rec_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    record["record_path"] = str(rec_path)
    return record


# ---------------------------------------------------------------- 历史修剪

def prune_history(history_dir: Optional[Path] = None, keep_days: int = 14) -> int:
    """删除 run_history 中 mtime 超过 keep_days 的日志/记录，返回删除数。治 runs 堆积。"""
    history_dir = Path(history_dir) if history_dir else DEFAULT_HISTORY
    if not history_dir.exists():
        return 0
    cutoff = time.time() - keep_days * 86400
    removed = 0
    for p in history_dir.rglob("*"):
        if p.is_file() and p.stat().st_mtime < cutoff:
            p.unlink()
            removed += 1
    for d in sorted(history_dir.rglob("*"), reverse=True):
        if d.is_dir() and not any(d.iterdir()):
            d.rmdir()
    return removed


# ---------------------------------------------------------------- Manifest

def load_manifest(path: Optional[Path] = None) -> Dict:
    path = Path(path) if path else DEFAULT_MANIFEST
    data = json.loads(path.read_text(encoding="utf-8"))
    skills = data.get("skills", [])
    if not skills:
        raise ValueError("manifest 无 skills 条目: %s" % path)
    for s in skills:
        if "name" not in s or "steps" not in s:
            raise ValueError("manifest 条目缺 name/steps: %r" % (s.get("name"),))
        cwd = REPO_ROOT / s.get("cwd", ".")
        if not cwd.exists():
            raise ValueError("skill %s 的 cwd 不存在: %s" % (s["name"], cwd))
    return data


# ---------------------------------------------------------------- interpreters 解析

def resolve_interpreters(data: Dict, env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """合并 manifest 顶层 interpreters + ZENSI_* env 覆盖，返回 {node/python/python3: 真实路径}。"""
    env = env or dict(os.environ)
    overrides = data.get("interpreter_env_overrides", {})
    out: Dict[str, str] = {}
    for key, default in data.get("interpreters", {}).items():
        env_key = overrides.get(key)
        out[key] = env.get(env_key, default) if env_key else default
    return out


def resolve_token(tok: str, interpreters: Optional[Dict[str, str]],
                  ctx: Optional[Dict[str, str]] = None) -> str:
    """argv 占位 → 真实值。

    {node}/{python}/{python3} → 解释器路径；
    {run_dir} → 本轮独立输出目录（skill 需要「本次独立输出目录」类参数时使用）；
    {date}/{ts} → 当日日期 / 本轮时间戳。
    占位符既可整 token 使用，也可内嵌在参数中（如 "{run_dir}/output"）。非占位原样返回。
    """
    if tok.startswith("{") and tok.endswith("}") and len(tok) > 2:
        inner = tok[1:-1]
        if interpreters and inner in interpreters:
            return interpreters[inner]
        if ctx and inner in ctx:
            return ctx[inner]
    if interpreters or ctx:
        def _sub(match) -> str:
            key = match.group(1)
            if interpreters and key in interpreters:
                return interpreters[key]
            if ctx and key in ctx:
                return ctx[key]
            return match.group(0)
        return re.sub(r"\{(\w+)\}", _sub, tok)
    return tok


# ---------------------------------------------------------------- 当日汇总

def summarize_today(history_dir: Optional[Path] = None, day: Optional[str] = None) -> Dict[str, Dict]:
    """读 run_history/<day>/ 下各 skill 最新 record.json，返回 {skill: record}（供台账/看护用）。"""
    history_dir = Path(history_dir) if history_dir else DEFAULT_HISTORY
    day = day or time.strftime("%Y-%m-%d")
    day_dir = history_dir / day
    if not day_dir.exists():
        return {}
    result: Dict[str, Dict] = {}
    for p in sorted(day_dir.glob("*--record.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        sk = rec.get("skill")
        if sk and (sk not in result or rec.get("finished_at", "") >= result[sk].get("finished_at", "")):
            result[sk] = rec
    return result


# ---------------------------------------------------------------- 持久成功状态（跨天 cadence 依赖）

def _ensure_state_dir() -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR


def update_last_success(name: str, iso: Optional[str] = None) -> None:
    """记录某 skill 最近一次成功时间（ISO）。cadence 门控与台账"任意一轮成功=是"共用。"""
    _ensure_state_dir()
    iso = iso or datetime.now().isoformat(timespec="seconds")
    data: Dict[str, str] = {}
    if LAST_SUCCESS_FILE.exists():
        try:
            data = json.loads(LAST_SUCCESS_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    data[name] = iso
    LAST_SUCCESS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def get_last_success(name: str) -> Optional[str]:
    if not LAST_SUCCESS_FILE.exists():
        return None
    try:
        data = json.loads(LAST_SUCCESS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data.get(name)
