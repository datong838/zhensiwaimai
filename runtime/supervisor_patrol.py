#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""监理督查巡检（只读，绝不下场执行生产动作）。

用途：作为「常驻督查」的眼睛，周期性巡检各任务流与岗位环境，主动产出
      异常清单（findings），供监理定性/上报。**不做任何写操作、不跑流程、
      不发消息、不发图。**

用法：
    python3 runtime/supervisor_patrol.py            # 人读摘要
    python3 runtime/supervisor_patrol.py --json     # 机读 JSON

退出码：0 = 无异常；2 = 存在 RED 项（需上报）

设计口径（2026-10-08 定）：
- 夜间（23:00-06:00）Windows 主机被休眠是**预期状态**，网络/浏览器类检查
  降级为「不告警」，避免噪音；本地文件类检查（daemon/流收口/告警）照跑。
- 浏览器探活**必须枚举全部 page**（教训：残留任意一个 /login 页就会让流程
  整轮 fail-closed，只看首个页会误判）。
- 对外发送**只看回执**：`attempted` 不等于「没发过」。
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "runtime" / "state"
LOCAL_STATE = ROOT / ".local" / "state"
# node 候选（沙箱里 `node` 常不在 PATH，托管 runtime 路径会变，故按存在性择优）
NODE_CANDIDATES = [
    "/Users/ddt/.workbuddy/binaries/node/versions/22.22.2-2/bin/node",
    "/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
    "/usr/local/bin/node",
    "/opt/homebrew/bin/node",
]

# 岗位 Chrome（2026-10-08 成形）
CHROME_PORTS = {
    9230: "taobao-brand",
    9231: "taobao-agent-service",
    9232: "jinsha-business",
    9233: "meituan-im",
}

DAEMON_STALE_MIN = 45          # daemon 周期落后超过该值 => RED（夜间另算）
NIGHT_HOURS = (23, 0, 1, 2, 3, 4, 5)

# These historical filenames are live report-format inputs, not disposable history.
# The customer roster remains mutable business data; fixed formats bind Git c310f639.
BUSINESS_ASSETS = {
    "data/reports/jinsha/客户表最新.xlsx": None,
    "data/reports/jinsha/美团全部_2026-08-25至2026-08-25.xlsx":
        "80f79cbcf4a269ace4ade1715a4f7f15d73dbef627d74a3931de8448387f3177",
    "data/reports/jinsha/淘宝闪购_模版2026-08-24至2026-08-24.xlsx":
        "00cf7c170349e739b61e59e9aadb35922df51adcf3109a65ca6978d4e4016da4",
}


# ---------------------------------------------------------------- helpers
def now() -> datetime:
    return datetime.now()


def parse_ts(value) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text[:26], fmt)
        except ValueError:
            continue
    return None


def read_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def cdp_pages(port: int, timeout: float = 3.0):
    """枚举该端口全部 page（含 /login 页）。返回 (pages, error)。"""
    url = f"http://127.0.0.1:{port}/json/list"
    req = urllib.request.Request(url, headers={"Host": "localhost"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return [t for t in data if t.get("type") == "page"], None
    except Exception as exc:  # noqa: BLE001
        return [], f"{type(exc).__name__}: {exc}"


def login_page_urls(port: int, pages: list[dict]) -> tuple[list[str], list[str]]:
    """Return business login candidates and ignored unrelated /login pages.

    9233 can contain WorkBuddy helper tabs. Those tabs are not Meituan session
    evidence and must never trigger a Meituan-login RED.
    """
    urls = [p.get("url", "") or "" for p in pages]
    if port != 9233:
        return [url for url in urls if "/login" in url], []
    matched: list[str] = []
    ignored: list[str] = []
    for url in urls:
        lowered = url.lower()
        has_auth_marker = "/login" in lowered or "nopermission" in lowered
        if not has_auth_marker:
            continue
        host = (urlsplit(url).hostname or "").lower()
        if host == "meituan.com" or host.endswith(".meituan.com") or host.endswith(".dianping.com"):
            matched.append(url)
        elif "/login" in lowered:
            ignored.append(url)
    return matched, ignored


def finding(level: str, area: str, code: str, detail: str, suggest: str = "") -> dict:
    return {"level": level, "area": area, "code": code,
            "detail": detail, "suggest": suggest}


# ---------------------------------------------------------------- checks
def check_business_assets(phase: str) -> tuple[dict, list]:
    """Check local live inputs in daytime and at night without reading cell values."""
    snapshot, findings = {"files": []}, []
    for relative, expected in BUSINESS_ASSETS.items():
        file = ROOT / relative
        item = {"path": relative, "status": "invalid"}
        try:
            if not file.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError("path-outside-repository")
            if not file.is_file():
                raise ValueError("required-file-missing-or-not-file")
            content = file.read_bytes()
            if not content:
                raise ValueError("required-file-empty")
            digest = hashlib.sha256(content).hexdigest()
            item.update(size=len(content), sha256=digest)
            if expected and digest != expected:
                raise ValueError("fixed-template-digest-mismatch")
            with zipfile.ZipFile(file) as archive:
                if not {"[Content_Types].xml", "xl/workbook.xml"}.issubset(archive.namelist()):
                    raise ValueError("xlsx-required-parts-missing")
                if archive.testzip() is not None:
                    raise ValueError("xlsx-crc-invalid")
            item["status"] = "valid"
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as error:
            item["reason"] = str(error)
            findings.append(finding("RED", "business-assets", "required-input-invalid",
                                    f"{relative}: {error}",
                                    "原制表入口必需资料；先按原件核验恢复，不能用旧日报替代当日数据"))
        snapshot["files"].append(item)
    return snapshot, findings


def check_daemon(phase: str) -> tuple[dict, list]:
    out: list = []
    snap: dict = {}
    d = read_json(STATE / "daemon.json") or {}
    snap["daemon"] = d
    pid = d.get("pid")
    alive = None
    if isinstance(pid, int):
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
    snap["daemon_pid_alive"] = alive

    last = parse_ts(d.get("last_cycle_at"))
    nxt = parse_ts(d.get("next_cycle_at"))
    if last is None:
        out.append(finding("RED", "daemon", "daemon-state-missing",
                           "daemon.json 无 last_cycle_at",
                           "确认 LaunchAgent com.zhensi.waimai.careloop 是否加载"))
    else:
        lag = (now() - last).total_seconds() / 60.0
        snap["daemon_lag_min"] = round(lag, 1)
        if lag > DAEMON_STALE_MIN:
            lvl = "INFO" if (phase == "night" and also_asleep(d)) else "RED"
            out.append(finding(lvl, "daemon", "daemon-stale",
                               f"daemon 落后 {lag:.0f} 分钟（阈值 {DAEMON_STALE_MIN}）",
                               "夜间/主机休眠属预期；日间须 kickstart -k gui/501/com.zhensi.waimai.careloop"))
    if alive is False:
        out.append(finding("RED", "daemon", "daemon-pid-dead",
                           f"daemon pid={pid} 不存在（状态文件残留）",
                           "launchctl kickstart -k gui/501/com.zhensi.waimai.careloop"))
    snap["next_cycle_at"] = d.get("next_cycle_at")
    return snap, out


def also_asleep(daemon_state: dict) -> bool:
    """粗略判断是否处于夜间休眠窗口（用于降级告警）。"""
    return now().hour in NIGHT_HOURS


def check_flows() -> tuple[dict, list]:
    """各流当日收口（复用 daily_progress.py，只读）。"""
    out: list = []
    snap: dict = {}
    script = ROOT / "runtime" / "daily_progress.py"
    try:
        proc = subprocess.run([sys.executable, str(script), "--json"],
                              capture_output=True, text=True, timeout=120, cwd=str(ROOT))
        data = json.loads(proc.stdout)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}, [
            finding("YELLOW", "flows", "progress-unreadable",
                    f"daily_progress.py 无法解析：{exc}", "手工核对 last_success.json")]
    snap["all_green"] = data.get("all_green")
    snap["date"] = data.get("date")
    pending = None
    if isinstance(data.get("rows"), list):
        pending = [row for row in data['rows'] if isinstance(row, dict)
                   and row.get('done') is not True and row.get('superseded') is not True]
    for key in ("pending", "unfinished", "not_done", "records"):
        if pending is not None:
            break
        val = data.get(key)
        if isinstance(val, list):
            pending = val
            break
    if pending is None:
        if not data.get('all_green'):
            return {**snap, 'pending_count': None, 'pending': []}, [
                finding('YELLOW', 'flows', 'progress-schema-unrecognized',
                        '当日未全绿，但进度源缺少可识别任务清单', '核对daily_progress输出格式')]
        pending = []
    snap["pending_count"] = len(pending)
    snap["pending"] = [
        {"name": p.get("name") or p.get("skill"), "reason": (p.get("reason") or "")[:120]}
        for p in pending if isinstance(p, dict)
    ]
    if not data.get("all_green"):
        names = ", ".join(sorted({str(p.get("name") or p.get("skill")) for p in pending if isinstance(p, dict)})) or "?"
        out.append(finding("YELLOW", "flows", "flows-not-green",
                           f"当日未全绿，未完成 {len(pending)} 条：{names[:200]}",
                           "逐条定性（是否在 cadence 内、是否已排下一档），真故障才上报车间"))
    return snap, out


def check_last_cycle() -> tuple[dict, list]:
    out: list = []
    d = read_json(STATE / "last_cycle.json") or {}
    snap = {"all_green": d.get("all_green"), "checked_at": d.get("checked_at") or d.get("cycle_at")}
    skills = d.get("skills") or {}
    bad = {k: v.get("category") for k, v in skills.items() if v.get("category") != "SUCCESS"}
    snap["non_success"] = bad
    if bad:
        out.append(finding("YELLOW", "flows", "cycle-non-success",
                           f"守护最近周期非 SUCCESS：{json.dumps(bad, ensure_ascii=False)[:200]}",
                           "看对应 run 的 step1.log 定失败码，别按报错文案直接猜修"))
    return snap, out


def check_chrome(phase: str) -> tuple[dict, list]:
    out: list = []
    snap: dict = {"ports": {}}
    for port, name in CHROME_PORTS.items():
        pages, err = cdp_pages(port)
        login, ignored_login = login_page_urls(port, pages)
        entry = {"name": name, "page_count": len(pages),
                 "login_pages": len(login), "error": err,
                 "urls": [(p.get("url") or "")[:100] for p in pages[:6]]}
        if port == 9233:
            entry["ignored_non_business_login_pages"] = len(ignored_login)
        snap["ports"][str(port)] = entry
        if err:
            lvl = "INFO" if phase == "night" else "YELLOW"
            out.append(finding(lvl, "chrome", f"cdp-unreachable:{port}",
                               f"{name}(:{port}) CDP 不可达：{err}",
                               "夜间预期；日间用 runtime/bg-chrome-up.sh 幂等拉起"))
            continue
        if login:
            out.append(finding("RED", "chrome", f"login-page-present:{port}",
                               f"{name}(:{port}) 存在 {len(login)} 个业务域登录/无权限页 "
                               f"（流程扫全量 page，会整轮 fail-closed）",
                               "让大同重登后**关掉登录页**；下次遇 *-login-expired 先枚举全部 page 再叫人"))
        biz: dict = {}
        for p in pages:
            url0 = (p.get("url") or "").split("#")[0]
            if not url0 or "console.ctyun" in url0 or "chromewebdata" in url0:
                continue
            biz[url0] = biz.get(url0, 0) + 1
        dup = {k: v for k, v in biz.items() if v > 1}
        if dup:
            out.append(finding("YELLOW", "chrome", f"duplicate-page:{port}",
                               f"{name}(:{port}) 同域存在多页（尚未判定归属）："
                               f"{json.dumps({k[:70]: v for k, v in dup.items()}, ensure_ascii=False)[:200]}",
                               "先核对原流程回执、当前监听PID/启动时刻及精确页面归属；同域多页不构成清理许可，禁止清window.name或批量关页；岗位忙则跳过。"))
    return snap, out


def check_outbound(phase: str) -> tuple[dict, list]:
    """今日对外发送回执（attempted 不等于没发过）。"""
    out: list = []
    snap: dict = {"by_type": {}, "attempted_unverified": []}
    today = now().strftime("%Y-%m-%d")
    patterns = [str(LOCAL_STATE / "*attempts" / "*.json"),
                str(LOCAL_STATE / "*attempts" / "*.jsonl")]
    seen: set[str] = set()
    for pat in patterns:
        for path in glob.glob(pat):
            if path in seen:
                continue
            seen.add(path)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                continue
            if mtime.strftime("%Y-%m-%d") != today:
                continue
            d = read_json(Path(path))
            if not isinstance(d, dict):
                continue
            ptype = d.get("payloadType") or "unknown"
            state = str(d.get("state") or ("verified" if d.get("verified") else "unknown"))
            snap["by_type"].setdefault(ptype, {})
            snap["by_type"][ptype][state] = snap["by_type"][ptype].get(state, 0) + 1
            if state == "attempted" and not d.get("verified"):
                names = [p.get("name") for p in (d.get("payloads") or []) if isinstance(p, dict)]
                snap["attempted_unverified"].append(
                    {"dir": Path(path).parent.name, "at": mtime.strftime("%H:%M:%S"),
                     "payloadType": ptype, "payloads": names,
                     "group": d.get("groupName")})
    if snap["attempted_unverified"] and phase != "night":
        for item in snap["attempted_unverified"]:
            out.append(finding("YELLOW", "send", "outbound-attempted-unverified",
                               f"{item['at']} {item['dir'][:32]} 发出{len(item['payloads'])}个"
                               f"{item['payloadType']}但未 verified（{','.join(str(x) for x in item['payloads'][:2])}）",
                               "attempted≠没发过；重跑前先对账，否则会重复外发（10-08 已发生）"))
    return snap, out


def check_popup(phase: str) -> tuple[dict, list]:
    """金鲨公告弹窗白名单覆盖率（F11-4 兜底）。

    执行器 closeKnownJinshaPopup 只认 hasText:'新功能上线'，遇到别的文案会**静默放过**
    （既不计 pitfalls 也不抛错）。本项只读检查 9232 是否存在「未命中白名单」的可见
    .upload 遮罩，让「站点改文案」在当天被发现，而不是等上传失败后绕路定性。
    """
    out: list = []
    snap: dict = {"checked": False, "port": 9232, "overlays": 0, "unknown": [], "skipped": None}
    probe = ROOT / "runtime" / "jinsha_popup_probe.mjs"
    node = (os.environ.get("SUPERVISOR_NODE")
            or shutil.which("node")
            or next((p for p in NODE_CANDIDATES if os.path.exists(p)), None))
    if not probe.exists() or not node:
        snap["skipped"] = "缺少 probe 脚本或 node 运行时"
        return snap, out
    try:
        proc = subprocess.run([node, str(probe), "--json"], timeout=25,
                              capture_output=True, text=True, check=False)
        raw = (proc.stdout or "").strip()
        i = raw.find("{")
        data = json.loads(raw[i:]) if i >= 0 else {}
    except Exception as exc:  # noqa: BLE001
        snap["skipped"] = f"probe 失败：{type(exc).__name__}: {exc}"
        if phase != "night":
            out.append(finding("INFO", "popup", "probe-unavailable",
                               snap["skipped"], "检查 node 与 runtime/jinsha_popup_probe.mjs 是否在位"))
        return snap, out
    snap["checked"] = True
    hits = data.get("hits") or []
    snap["overlays"] = len(hits)
    snap["unknown"] = [{"cls": h.get("cls"), "text": (h.get("text") or "")[:80]}
                       for h in hits if not h.get("known")]
    if snap["unknown"] and phase != "night":
        first = snap["unknown"][0]
        out.append(finding("RED", "popup", "jinsha-overlay-unknown-text",
                           f"9232 存在 {len(snap['unknown'])} 个未命中白名单的 .upload 遮罩"
                           f"（如「{first['text'] or '(空)'}」）— 执行器会静默放过，后续上传/切 tab 会报无关错",
                           "按 F11-4 缺陷单处理：先人工确认是否为非业务遮罩，"
                           "再交车间扩白名单（监理勿自行关弹窗）"))
    return snap, out


def _transport_sent_evidence(marker: dict) -> bool:
    """传输层显式确认发出（与桥 10-09 判据一致：transport.data.sent / transport.sent 为 true）。"""
    for it in (marker.get("commonReceipt") or {}).get("items") or []:
        tr = it.get("transport") or {}
        if tr.get("sent") is True or (tr.get("data") or {}).get("sent") is True:
            return True
    return False


def check_marker_deadlocks(phase: str) -> tuple[dict, list]:
    """未收口 marker（unknown/blocked）按「传输层发出证据」分类（10-09 疆麦尔教训）。

    桥已改为「unknown+传输确认发出→按已送达复用不卡流」，但当日残留的卡点 marker
    仍须监理当场定性：有证据→事实结论化（禁重发）；无证据→读回取证，禁盲 resume
    （防重复外发，10-08 事故）。只扫当日 mtime，历史不翻（历史告警≠当前故障）。
    """
    out: list = []
    snap: dict = {"scanned": 0, "stuck": []}
    today = now().strftime("%Y-%m-%d")
    patterns = [str(ROOT / "state" / "*" / "send-attempts" / "*.json"),
                str(LOCAL_STATE / "*attempts" / "*.json")]
    seen: set[str] = set()
    for pat in patterns:
        for path in glob.glob(pat):
            if path in seen:
                continue
            seen.add(path)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(path))
            except OSError:
                continue
            if mtime.strftime("%Y-%m-%d") != today:
                continue
            d = read_json(Path(path))
            if not isinstance(d, dict) or d.get("state") not in ("unknown", "blocked"):
                continue
            snap["scanned"] += 1
            sent = _transport_sent_evidence(d)
            item = {"dir": Path(path).parent.name, "at": mtime.strftime("%H:%M:%S"),
                    "state": d.get("state"), "sentEvidence": sent,
                    "group": d.get("groupName"), "reason": (d.get("reason") or "")[:80]}
            snap["stuck"].append(item)
            if sent:
                out.append(finding("YELLOW", "marker", "unknown-marker-sent-evidence",
                                   f"{item['at']} {item['dir'][:40]} marker state=unknown "
                                   f"但传输层已确认发出（{item['group'] or '?'}）",
                                   "桥已按已送达复用不卡流（10-09 修复）；若该流当日仍停滞，"
                                   "当场事实结论化（conclude_attempt_deadlock --apply，禁重发）"))
            else:
                out.append(finding("YELLOW", "marker", "marker-stuck-no-evidence",
                                   f"{item['at']} {item['dir'][:40]} marker state={item['state']} "
                                   f"无发出证据（{item['group'] or '?'} {item['reason']}）",
                                   "先读回取证定性；禁盲 resume/重跑（防重复外发，10-08 事故）"))
    return snap, out


def check_alerts(phase: str) -> tuple[dict, list]:
    out: list = []
    snap: dict = {"today_total": 0, "by_category": {}}
    today = now().strftime("%Y-%m-%d")
    path = STATE / "alerts.jsonl"
    if not path.exists():
        return snap, out
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:  # noqa: BLE001
        return snap, out
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:  # noqa: BLE001
            continue
        if str(rec.get("ts", ""))[:10] != today:
            continue
        snap["today_total"] += 1
        cat = rec.get("category") or "?"
        snap["by_category"][cat] = snap["by_category"].get(cat, 0) + 1
    if snap["by_category"].get("NEEDS_LOGIN"):
        # 历史事实 ≠ 当前故障：当前是否真掉登录由 check_chrome 的 /login 页判定。
        out.append(finding("INFO", "alert", "needs-login-history",
                           f"今日有 {snap['by_category']['NEEDS_LOGIN']} 条登录类告警记录"
                           f"（历史；当前登录态看岗位检查）",
                           "残留 /login 页才是 RED；10-08 教训：告警发了没人接=堵 9 小时，直推大同并挂等待器"))
    return snap, out


# ---------------------------------------------------------------- main
def phase_of(dt: datetime) -> str:
    return "night" if dt.hour in NIGHT_HOURS else "business"


def patrol() -> dict:
    p = phase_of(now())
    findings: list = []
    snap: dict = {}
    for fn in (check_business_assets, check_daemon, check_flows, check_last_cycle, check_chrome,
               check_outbound, check_marker_deadlocks, check_popup, check_alerts):
        try:
            sub, items = fn(p) if fn.__code__.co_argcount else fn()
        except Exception as exc:  # noqa: BLE001
            items = [finding("YELLOW", "patrol", "check-crashed",
                             f"{fn.__name__} 异常：{type(exc).__name__}: {exc}")]
            sub = {}
        snap[fn.__name__] = sub
        findings.extend(items)
    order = {"RED": 0, "YELLOW": 1, "INFO": 2}
    findings.sort(key=lambda f: order.get(f["level"], 3))
    levels = {f["level"] for f in findings}
    verdict = "RED" if "RED" in levels else ("YELLOW" if "YELLOW" in levels else "GREEN")
    return {"patrol_at": now().strftime("%Y-%m-%dT%H:%M:%S"),
            "phase": p, "verdict": verdict, "findings": findings, "snapshot": snap}


def render_md(r: dict) -> str:
    lines = [f"# 监理督查 {r['patrol_at']} ({r['phase']}) — {r['verdict']}"]
    if not r["findings"]:
        lines.append("无异常。")
    for f in r["findings"]:
        lines.append(f"- [{f['level']}] {f['area']}/{f['code']}: {f['detail']}")
        if f["suggest"]:
            lines.append(f"    → {f['suggest']}")
    fl = r["snapshot"].get("check_flows", {})
    if fl.get("pending"):
        lines.append(f"\n未完成 {fl.get('pending_count')} 条:")
        for p in fl["pending"]:
            lines.append(f"  - {p['name']}: {p['reason']}")
    ch = r["snapshot"].get("check_chrome", {}).get("ports", {})
    if ch:
        lines.append("\n岗位:")
        for port, e in ch.items():
            flag = "LOGIN!" if e.get("login_pages") else ("ok" if not e.get("error") else "err")
            lines.append(f"  - :{port} {e.get('name')} [{flag}] pages={e.get('page_count')} {e.get('error') or ''}")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="监理督查巡检（只读）")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-log", action="store_true",
                    help="不追加 patrol_log.jsonl（手工排查时用，避免污染留痕）")
    args = ap.parse_args()
    r = patrol()
    if not args.no_log and r["verdict"] in ("YELLOW", "RED"):
        # 留痕：异常轮次自动落一行，保证 patrol_log.jsonl 不因「没人手填」而空缺
        try:
            log = STATE / "patrol_log.jsonl"
            log.parent.mkdir(parents=True, exist_ok=True)
            summary = "; ".join(f"[{f['level']}] {f['area']}/{f['code']}: {f['detail']}"
                                for f in r["findings"])
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": r["patrol_at"], "verdict": r["verdict"],
                                     "summary": summary}, ensure_ascii=False) + "\n")
        except Exception as exc:  # 留痕失败不得掩盖巡检结论
            print(f"(patrol_log 写入失败: {exc})", file=sys.stderr)
    print(json.dumps(r, ensure_ascii=False, indent=1) if args.json else render_md(r))
    return 2 if r["verdict"] == "RED" else 0


if __name__ == "__main__":
    raise SystemExit(main())
