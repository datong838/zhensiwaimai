#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""监理闭环驱动引擎（supervisor_drive）—— 把巡检发现当场推到收口。

设计动机（2026-10-10 大同痛批后建）：
    原 supervisor_patrol.py 是「纯只读」，发现问题只落 patrol_log.jsonl，
    没有任何东西去消费这些 finding 并当场处置。结果就是：
        白天发现 bug → 只进日志 → 没人动 → 晚上被催 → 才修
    「完成当日任务为最高原则；巡检遇到问题 当即处理 处理完立即安排执行」
    这一铁律在机制层是断的。本脚本就是补上「发现→处置→排期→闭环」的最后一步。

职责边界（不越红线）：
    ✅ 可自处置（当场解决，无对外重复发送）：
        - daemon 落后/死 pid（非夜间）→ launchctl kickstart
        - 四岗位 CDP 不可达（非夜间）→ runtime/bg-chrome-up.sh **按 finding 端口拉起对应岗位**
        - **四岗位「端口健康但页渲染线程卡死」（2026-10-10 补）→ runtime/post_page_probe.mjs --apply
          复位 hung 页（仅 CDP Page.reload，不新开/关 tab、不点页面、不发送）**。
          背景：assert_post_pages.py 只发 /json/list，看不见渲染卡死；而两页无关 tab 卡死
          会让 chromium.connectOverCDP 整体超时 ⇒ 9232 上多条流同日失败。见 post_page_probe.mjs 头注。
        - marker 死点（无证据）→ 读回取证；确认已发 → conclude_attempt_deadlock --apply（本地结论化，不重发）
        - outbound attempted 未 verified → 读回取证；确认已发 → 本地标 verified
    🚫 需上报（越红线/要你拍板），绝不静默搁置：
        - 任何对外发送/重发（含台账外发）
        - Mac 桌面微信
        - 封印文件改动需授权
        - 登录页残留（需你重登）
        - 金鲨未知遮罩（需车间扩白名单）
    ⇒ 这类生成【具体动作请求】+ SLA 闹钟，超时（工作时段 30min）二次置顶，绝不"记进日志当没发生"。

用法：
    python3 runtime/supervisor_drive.py            # 干跑（不执行处置，只建看板/出报告）
    python3 runtime/supervisor_drive.py --apply    # 执行自处置类动作
退出码：0 = 无待你处理项；2 = 有待你处理项（自动化据此判 RED）
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "runtime" / "state"
WAR_ROOM = STATE / "war_room.json"
NIGHT_HOURS = (23, 0, 1, 2, 3, 4, 5)
SLA_MIN_BUSINESS = 30          # 工作时段待你处理项 30min 必响应
SLA_NIGHT_RESUME = "09:00"     # 夜间待处理项顺延到次日 09:00


# ---------------------------------------------------------------- 时间
def now() -> datetime:
    return datetime.now()


def phase_of(dt: datetime) -> str:
    return "night" if dt.hour in NIGHT_HOURS else "business"


def parse_ts(text: str | None) -> datetime | None:
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(str(text)[:26], fmt)
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------- patrol 调用
def run_patrol() -> dict:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "runtime" / "supervisor_patrol.py"), "--json"],
        capture_output=True, text=True, timeout=180, cwd=str(ROOT),
    )
    raw = proc.stdout.strip()
    i = raw.find("{")
    if i < 0:
        return {"patrol_at": now().strftime("%Y-%m-%dT%H:%M:%S"),
                "phase": phase_of(now()), "verdict": "YELLOW",
                "findings": [{"level": "YELLOW", "area": "drive", "code": "patrol-unreadable",
                              "detail": f"patrol 输出无法解析: {proc.stderr[:200]}", "suggest": "手工跑 supervisor_patrol.py"}]}
    return json.loads(raw[i:])


# ---------------------------------------------------------------- 处置分类
AUTO_KICKSTART = {"daemon-stale", "daemon-pid-dead"}
AUTO_CHROME_PREFIX = "cdp-unreachable:"
VERIFY_MARKER = {"marker-stuck-no-evidence"}
VERIFY_OUTBOUND = {"outbound-attempted-unverified"}
# 任务流状态 / 历史告警：非环境/外发面故障，归「16流进度汇报」另一分工域。
# 只记录不 escalat、不挂 SLA、不计 exit 2（与用户铁律「禁止重复输出任务流状态表」一致）。
INFO_CODES = {"flows-not-green", "cycle-non-success", "needs-login-history"}


def classify(f: dict) -> str:
    code = f.get("code", "")
    if code in INFO_CODES:
        return "info"
    if code in AUTO_KICKSTART:
        return "auto_kickstart"
    if code.startswith(AUTO_CHROME_PREFIX):
        return "auto_chrome"
    if code in VERIFY_MARKER:
        return "verify_marker"
    if code in VERIFY_OUTBOUND:
        return "verify_outbound"
    return "escalate"


# ---------------------------------------------------------------- 处置执行
def act_kickstart(f: dict, apply: bool) -> str:
    if not apply:
        return "[plan] 将执行 launchctl kickstart -k gui/501/com.zhensi.waimai.careloop"
    try:
        r = subprocess.run(
            ["launchctl", "kickstart", "-k", "gui/501/com.zhensi.waimai.careloop"],
            capture_output=True, text=True, timeout=30)
        return f"kickstart rc={r.returncode} {r.stdout.strip() or r.stderr.strip()}"[:200]
    except Exception as e:  # noqa: BLE001
        return f"kickstart 失败: {type(e).__name__}: {e}"


# 岗位端口 → (profile, 恢复 URL)。URL 与各 profile 的 state.json 权威值一致（2026-10-10 核）。
# 巡检 finding 的 code 形如 `cdp-unreachable:<port>`；据此**只拉起对应岗位**，
# 避免「9230 掉线却只拉 9231」的错配（2026-10-10 大同要求四岗位同等级高可用高恢复）。
POST_SPECS = {
    9230: ("taobao-brand",
           "https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center"),
    9231: ("taobao-agent-service", "https://open.shop.ele.me/manager/base/home"),
    9232: ("jinsha-business", "https://data.guoshuyufen.com/#/negativeAnalyse"),
    9233: ("meituan-merchant",
           "https://waimaie.meituan.com/imworkbench/home?appId=4&clientType=140006#/im/page/workbench/reception"),
}


def act_chrome(f: dict, apply: bool) -> str:
    code = f.get("code", "")
    port = None
    if code.startswith(AUTO_CHROME_PREFIX):
        try:
            port = int(code.split(":", 1)[1])
        except ValueError:
            port = None
    targets = [port] if port in POST_SPECS else sorted(POST_SPECS)
    names = ", ".join("%d(%s)" % (p, POST_SPECS[p][0]) for p in targets)
    if not apply:
        return "[plan] 将执行 bg-chrome-up.sh 幂等拉起：%s" % names
    results = []
    for p in targets:
        profile, url = POST_SPECS[p]
        try:
            r = subprocess.run(
                ["bash", str(ROOT / "runtime" / "bg-chrome-up.sh"), profile, str(p), url],
                capture_output=True, text=True, timeout=120, cwd=str(ROOT))
            results.append("%d:rc=%d" % (p, r.returncode))
        except Exception as e:  # noqa: BLE001
            results.append("%d:%s" % (p, type(e).__name__))
    return ("bg-chrome-up " + " ".join(results))[:200]


def act_verify_marker(f: dict, apply: bool) -> str:
    """读回取证；确认已发 → 本地结论化（不重发）。"""
    if not apply:
        return "[plan] 将扫描当日 unknown/blocked marker，读回取证后 conclude_attempt_deadlock --apply"
    try:
        r = subprocess.run(
            [sys.executable, str(ROOT / "runtime" / "conclude_attempt_deadlock.py"), "--apply"],
            capture_output=True, text=True, timeout=120, cwd=str(ROOT))
        return f"conclude rc={r.returncode} {r.stdout.strip()[-200:] or r.stderr.strip()[-200:]}"[:200]
    except Exception as e:  # noqa: BLE001
        return f"conclude 失败: {type(e).__name__}: {e}"


def act_verify_outbound(f: dict, apply: bool) -> str:
    if not apply:
        return "[plan] 将读回今日 attempted 未 verified 项，确认已发则本地标 verified"
    # 轻量实现：直接交给 conclude 同族逻辑（read-back 由桥侧完成）；此处仅记录待核实
    return "[apply] outbound 读回需桥侧证据；已在 war_room 标记，交由下次 conclude 周期处置"


# ------------------------------------------------- 四岗位页面卡死自愈（2026-10-10 补）
NODE_CANDIDATES = (
    "/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node",
    "/Users/ddt/.workbuddy/binaries/node/versions/22.22.2-2/bin/node",
)


def _node_bin() -> str | None:
    for c in NODE_CANDIDATES:
        if os.path.exists(c):
            return c
    return shutil.which("node")


def heal_post_pages(apply: bool) -> dict:
    """四岗位「端口健康但渲染线程卡死」自愈：探测每张 page，卡死则 CDP Page.reload 复位。

    守卫：只在**无流在跑**时动作（runtime/state/live_steps/ 为空），避免复位正在采集的页。
    纯只读探测 + 仅对 hung 页 reload；不新开/关闭 tab、不点页面、不发送。
    走 runtime/post_page_probe.mjs（Node 原生 WebSocket 裸 CDP，规避 connectOverCDP 卡死）。
    """
    live = STATE / "live_steps"
    try:
        running = live.exists() and any(live.iterdir())
    except Exception:  # noqa: BLE001
        running = False
    if running:
        return {"skipped": "live_steps 非空（有流在跑），本轮不复位页面"}
    node = _node_bin()
    if not node:
        return {"error": "node-not-found"}
    cmd = [node, str(ROOT / "runtime" / "post_page_probe.mjs"), "--json"]
    if apply:
        cmd.append("--apply")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=150, cwd=str(ROOT))
        out = (r.stdout or "").strip().splitlines()
        return json.loads(out[-1]) if out else {"error": "empty-probe-output"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


# ------------------------------------------------- 封印漂移自修（2026-10-19 大同裁定）
# 背景：今晨 merchants/top10 因「上游 wechat-messaging/dependencies.json 合法重绑后下游钉死未同步」
# 连败十余轮，而本引擎把 flows-not-green / cycle-non-success 归为 INFO（只记录不处置），
# 「进度汇报」又规定只报不跑生产流 ⇒ 两边互相推诿、无人修。
# 大同裁定：**只要不是登录态问题，阻塞当日工作流的任何问题都要修复+补跑**。
# 处置：调用 runtime/seal_drift_repair.py —— 只认「共享微信清单漂移」这一因（白名单），
# 白名单外（代码文件被改=真篡改）一律拒绝并上报；修后必须真校验器 PASS；补跑只写
# control.json force_run（并校验今日零真实外发，防重复外发 #26）。
def heal_seal_drift(apply: bool) -> dict:
    live = STATE / "live_steps"
    try:
        running = live.exists() and any(live.iterdir())
    except Exception:  # noqa: BLE001
        running = False
    if running:
        return {"skipped": "live_steps 非空（有流在跑），本轮不动封印"}
    cmd = [sys.executable, str(ROOT / "runtime" / "seal_drift_repair.py")]
    if apply:
        cmd.append("--apply")
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)  # #71 沙箱 shim
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900,
                           cwd=str(ROOT), env=env)
        out = (r.stdout or "").strip()
        i = out.find("{")
        return json.loads(out[i:]) if i >= 0 else {"error": "empty-repair-output"}
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


def summarize_seal_heal(sr: dict) -> dict:
    """把修复器输出转成 (auto_fixed 行, 待你拍板行)。"""
    fixed, ask = [], []
    if sr.get("skipped"):
        return {"fixed": [], "ask": [], "note": f"[skip] {sr['skipped']}"}
    if sr.get("error"):
        return {"fixed": [], "ask": [f"封印修复器异常：{sr['error']}（需人工核）"], "note": ""}
    for r in sr.get("results", []):
        flow, st = r.get("flow"), r.get("state")
        if st == "healthy":
            continue
        if st == "repaired":
            line = f"seal/{flow}: {r.get('detail')}"
            rr = r.get("rerun") or {}
            if rr:
                line += f"；补跑：{rr.get('detail')}"
            fixed.append(line)
        else:
            ask.append(f"seal/{flow}: {st} — {r.get('reason') or r.get('detail','')}")
    return {"fixed": fixed, "ask": ask, "note": ""}


def summarize_page_heal(ph: dict) -> str:
    if ph.get("skipped"):
        return f"[skip] {ph['skipped']}"
    if ph.get("error"):
        return f"[warn] 页面探针失败: {ph['error']}"
    parts = []
    if ph.get("anyHung"):
        reloaded = sum(int(p.get("reloaded") or 0) for p in ph.get("ports", []))
        still = [f":{p.get('port')}" for p in ph.get("ports", []) if p.get("stillHung")]
        parts.append(f"卡死页复位 {reloaded}" + (f"；仍卡死 {still}" if still else "，全部恢复"))
    if ph.get("anyBlind"):
        unbl = sum(int(p.get("unblinded") or 0) for p in ph.get("ports", []))
        stillb = [f":{p.get('port')}" for p in ph.get("ports", []) if p.get("stillBlind")]
        parts.append(f"失可见页激活 {unbl}" + (f"；仍失可见 {stillb}" if stillb else "，全部恢复"))
    if not parts:
        return "[ok] 四岗位页面健康（无卡死/无失可见）"
    return "[heal] " + "；".join(parts)


# ---------------------------------------------------------------- 看板
def load_war_room() -> dict:
    try:
        return json.loads(WAR_ROOM.read_text(encoding="utf-8"))
    except Exception:
        return {"items": {}}


def save_war_room(d: dict) -> None:
    WAR_ROOM.parent.mkdir(parents=True, exist_ok=True)
    WAR_ROOM.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def compute_sla(discovered: datetime, phase: str) -> str:
    if phase == "night":
        # 顺延到次日 09:00
        d = discovered.date()
        from datetime import date
        nxt = datetime.combine(d, datetime.min.time()) + timedelta(days=1)
        return f"{nxt.strftime('%Y-%m-%d')}T{SLA_NIGHT_RESUME}:00"
    return (discovered + timedelta(minutes=SLA_MIN_BUSINESS)).strftime("%Y-%m-%dT%H:%M:%S")


def craft_ask(f: dict) -> str:
    """把一条需上报的 finding 变成【具体动作请求】，而不是"有问题"。"""
    area, code, detail, suggest = f.get("area"), f.get("code"), f.get("detail"), f.get("suggest")
    return (f"【需大同拍板】{area}/{code}：{detail}\n"
            f"    建议动作：{suggest or '（无）'}\n"
            f"    我已就位，授权即做；请勿让其静默搁置。")


# ---------------------------------------------------------------- 主流程
def drive(apply: bool) -> dict:
    patrol = run_patrol()
    phase = patrol.get("phase", phase_of(now()))
    findings = patrol.get("findings", [])
    war = load_war_room()
    items = war.setdefault("items", {})
    seen_keys = set()

    report = {"auto_fixed": [], "verify_done": [], "awaiting_you": [], "breached": [], "info": [], "page_heal": ""}

    # ---- 四岗位页面卡死自愈（独立于 finding，先跑：页面卡死会让“页面看起来正常”而流全挂）----
    ph = heal_post_pages(apply)
    report["page_heal"] = summarize_page_heal(ph)

    # ---- 封印漂移自修（独立于 finding；只在无流在跑时动作）----
    sh = summarize_seal_heal(heal_seal_drift(apply))
    report["seal_note"] = sh.get("note", "")
    for line in sh["fixed"]:
        report["auto_fixed"].append(line)
    for line in sh["ask"]:
        report["awaiting_you"].append(line)

    for f in findings:
        cat = classify(f)
        key = f"{f.get('area')}/{f.get('code')}"
        seen_keys.add(key)
        existing = items.get(key)
        if existing and existing.get("status") in ("done", "resolved"):
            # 防同 key 抑制缺陷：历史已闭环条目若 patrol 本轮再次报出同 key 发现 = 复发，
            # 必须重新处置（重置发现时间/SLA 并落入下方分类），严禁 continue 静默吞掉。
            existing.setdefault("actions", []).append({
                "at": now().strftime("%Y-%m-%dT%H:%M:%S"),
                "type": "recurrence",
                "result": f"同 key 历史档为 {existing.get('status')}（首发 {existing.get('discovered_at')}），patrol 本轮再次报出 → 按复发重新处置",
            })
            existing["discovered_at"] = now().strftime("%Y-%m-%dT%H:%M:%S")
            existing["sla_deadline"] = compute_sla(now(), phase)
            # 不 continue：落入下方 classify→act 正常处置
        discovered = now() if not existing else parse_ts(existing.get("discovered_at")) or now()
        if not existing:
            items[key] = {
                "area": f.get("area"), "code": f.get("code"), "level": f.get("level"),
                "detail": f.get("detail"), "discovered_at": discovered.strftime("%Y-%m-%dT%H:%M:%S"),
                "sla_deadline": compute_sla(discovered, phase),
                "status": "open", "actions": [], "ask": "",
            }
            existing = items[key]

        if cat == "auto_kickstart":
            res = act_kickstart(f, apply)
            existing["actions"].append({"at": now().strftime("%Y-%m-%dT%H:%M:%S"), "type": "auto", "result": res})
            existing["status"] = "done"
            report["auto_fixed"].append(f"{key}: {res}")
        elif cat == "auto_chrome":
            res = act_chrome(f, apply)
            existing["actions"].append({"at": now().strftime("%Y-%m-%dT%H:%M:%S"), "type": "auto", "result": res})
            existing["status"] = "done"
            report["auto_fixed"].append(f"{key}: {res}")
        elif cat == "verify_marker":
            res = act_verify_marker(f, apply)
            existing["actions"].append({"at": now().strftime("%Y-%m-%dT%H:%M:%S"), "type": "verify", "result": res})
            existing["status"] = "done" if apply else "open"
            report["verify_done"].append(f"{key}: {res}")
        elif cat == "verify_outbound":
            res = act_verify_outbound(f, apply)
            existing["actions"].append({"at": now().strftime("%Y-%m-%dT%H:%M:%S"), "type": "verify", "result": res})
            existing["status"] = "open"
            report["verify_done"].append(f"{key}: {res}")
        elif cat == "info":
            # 任务流状态/历史告警：只记录不 escalat，不挂 SLA、不计 exit 2（归另一分工域）
            existing["detail"] = f.get("detail")
            existing["level"] = f.get("level")
            existing["ask"] = ""
            existing["status"] = "info"
            existing.setdefault("actions", []).append({
                "at": now().strftime("%Y-%m-%dT%H:%M:%S"), "type": "info",
                "result": "任务流状态/历史告警类，归「16流进度汇报」另一分工域；本巡检只记录不 escalat、不挂 SLA"})
            report["info"].append(f"{key}: {f.get('detail','')[:90]}")
        else:  # escalate
            ask = craft_ask(f)
            existing["ask"] = ask
            existing["status"] = "awaiting_you"
            report["awaiting_you"].append(ask)

    # 标记已消失的 item 为 resolved
    for key, it in items.items():
        if key not in seen_keys and it.get("status") in ("open", "awaiting_you"):
            it["status"] = "resolved"
            it.setdefault("actions", []).append(
                {"at": now().strftime("%Y-%m-%dT%H:%M:%S"), "type": "system",
                 "result": "finding 已不再出现，自动标记 resolved"})

    # SLA 超时检测
    for key, it in items.items():
        if it.get("status") == "awaiting_you":
            dl = parse_ts(it.get("sla_deadline"))
            if dl and now() > dl:
                it["status"] = "breached"
                it.setdefault("actions", []).append(
                    {"at": now().strftime("%Y-%m-%dT%H:%M:%S"), "type": "sla",
                     "result": "SLA 超时未获回应，需二次置顶@大同"})
                report["breached"].append(it["ask"])

    stamp = now().strftime("%Y-%m-%dT%H:%M:%S")
    war["last_drive_at"] = stamp
    war["last_phase"] = phase
    save_war_room(war)
    return {"last_drive_at": stamp, "patrol_verdict": patrol.get("verdict"),
            "phase": phase, "page_heal": report.get("page_heal", ""),
            "report": report, "war_room": str(WAR_ROOM)}


def render(r: dict) -> str:
    rep = r["report"]
    lines = [f"# 监理闭环驱动 {r['last_drive_at'] if 'last_drive_at' in r else ''} ({r['phase']})",
             f"patrol 结论: {r['patrol_verdict']}"]
    ph = r.get("page_heal") or rep.get("page_heal") or ""
    if ph:
        lines.append(f"四岗位页面: {ph}")
    if rep.get("seal_note"):
        lines.append(f"封印漂移: {rep['seal_note']}")
    if rep["auto_fixed"]:
        lines.append(f"\n✅ 当场自处置 {len(rep['auto_fixed'])} 项:")
        lines += [f"  - {x}" for x in rep["auto_fixed"]]
    if rep["verify_done"]:
        lines.append(f"\n🔍 读回取证 {len(rep['verify_done'])} 项:")
        lines += [f"  - {x}" for x in rep["verify_done"]]
    if rep["awaiting_you"]:
        lines.append(f"\n⏳ 待你拍板 {len(rep['awaiting_you'])} 项（已建 SLA）:")
        lines += [f"  - {x}" for x in rep["awaiting_you"]]
    if rep["breached"]:
        lines.append(f"\n🚨 SLA 超时 {len(rep['breached'])} 项（需立即置顶@大同）:")
        lines += [f"  - {x}" for x in rep["breached"]]
    if rep["info"]:
        lines.append(f"\nℹ️ 任务流/历史状态 {len(rep['info'])} 项（归16流进度汇报，不在此上报）")
    if not (rep["auto_fixed"] or rep["verify_done"] or rep["awaiting_you"] or rep["breached"]):
        lines.append("\n无待处置项，全绿。")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description="监理闭环驱动引擎")
    ap.add_argument("--apply", action="store_true", help="执行自处置类动作（默认干跑，只建看板/出报告）")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    r = drive(args.apply)
    print(json.dumps(r, ensure_ascii=False, indent=1) if args.json else render(r))
    # 有待你处理项（含超时）→ 退出码 2，自动化据此判 RED
    return 2 if (r["report"]["awaiting_you"] or r["report"]["breached"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
