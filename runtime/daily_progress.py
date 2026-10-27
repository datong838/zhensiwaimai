#!/usr/bin/env python3
"""当日任务流进度表（只读，唯一真相源）。

设计目的（2026-10-02 大同要求：监工每小时展示当日 10+ 条任务流进度并跟未完成）：
  * 只认**当天**的真实成功（时间戳必须落在今天），昨天的成功一律不算 —— 与 run_all._cadence_gate 同一口径。
  * 未到点 = 「待跑」，绝不能显示成已完成。
  * 每条都给出可下钻的证据路径，方便跟未完成。

用法：
    python3 runtime/daily_progress.py            # 打印 markdown 进度表
    python3 runtime/daily_progress.py --json     # 机器可读
"""
from __future__ import annotations

import fixed_schedule
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "runtime" / "skills_manifest.json"
STATE = ROOT / "runtime" / "state"
# 注意：run_history 在 runtime/ 下，不是 runtime/state/ 下（写错会导致全天记录读不到 → 全部误判"无外发"）
RUN_HISTORY = ROOT / "runtime" / "run_history"


def _load(p: Path, default):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return default


# 真实外发证据标记（**只收正向证据**：出现即代表确实对外交付过）。
# 注意：不能用 sendAttempts / messageCount —— 失败回执里也有这些字段，会造成假阳性
# （13:00 档那次 wechat-send-failed 的日志里就有 sendAttempts，实际一张都没发出去）。
# 注意：比对前会把文本里的 ": " 统一成 ":"，所以这里的标记一律写成**无空格**形式。
DELIVER_MARKERS = (
    "windows-readback",           # 回读锚点（text-anchor / file-card 等）；注：此标记名虽旧称"桌面微信回读"，实际指 Windows 网关回读，Mac 桌面微信已于 2026-09-30 停用
    '"verified":true',
    '"sent":true',
    '"stage":"verified"',         # jinsha 验收回执的终态
    '"status":"verified"',        # 新店开业/品牌等流的回读终态
    "verificationLevel",          # 回读锚点等级（windows-readback-* 的伴生字段）
)
EXTRA_EVIDENCE_GLOBS = {
    # 金鲨日报：发送+回读的终态写在 exam-receipt.json（"stage": "verified"）
    "daily-jinsha-reports-to-business-wechat":
        [".local/runs/jinsha-business-production/{YYYYMMDD}/*/exam-receipt.json"],
    # 新店开业：日级发送台账（含 verified/state/sendAttempts）
    "daily-new-stores-opening-to-wechat":
        ["skills/workflows/daily-new-stores-opening-to-wechat/.runtime/"
         "new-stores-send-ledger/{YYYY-MM-DD}-*.json"],
    # 淘宝新增商家：每次运行的 workflow.json（wechat.ok/sent/messageCount/verified）
    "daily-agent-new-merchants-to-wechat":
        ["runtime/state/runs/daily-agent-new-merchants-to-wechat/"
         "{YYYYMMDD}-*/output/workflow.json"],
    # 淘宝闪购门店经营任务完成率：由 --deliver-run 补发入群，events marker 双 verified
    "daily-store-task-completion-ops-to-wechat":
        ["skills/workflows/daily-store-task-completion-ops-to-wechat/.runtime/"
         "taskrate/events/{YYYY-MM-DD}-taobao-store-task-detail.json",
         "skills/workflows/daily-store-task-completion-ops-to-wechat/.runtime/"
         "taskrate/events/{YYYY-MM-DD}-taobao-store-task-stats.json"],
}
# run_history 之外也扫 daemon 为每步留的自包含日志（部分流的外发证据只落在这里）
RUNS_DIR = ROOT / "runtime" / "state" / "runs"


def _has_delivery_evidence(name: str, day: str, ts: str | None = None) -> bool:
    """扫该流**当天全部**逐步日志，判断当天是否真的对外交付过。

    扫全天而非只扫最后一次：像 hourly 的 agent-new-merchants，某次可能 0 发送，
    但当天早些时候确实发过 —— 老板要看的是"今天有没有发出去"。
    """
    files = _evidence_files(name, day)
    for p in sorted(files):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        # JSON 可能是 "verified": true（带空格）也可能是 "verified":true，统一去空格再比对
        if any(mk in txt.replace(": ", ":") for mk in DELIVER_MARKERS):
            return True
    return False


# 显式 noop 回执（2026-10-05）：**全部**标记同现才成立，且都是"无事可做"的结构化回执，
# 不是"该发没发"。命中即 "已完成·无待发内容"，替代长期假"外发待核"。
# 比对前统一 ": "→":" 并 lower()。
NOOP_MARKER_SETS = (
    ('"skipped":true', 'no-candidate-records'),   # 差评申诉：当日无候选记录（itemCount=0）——2026-10-22 前的旧判据，保留以读历史日志
    ('"skipped":true', 'report-has-no-data-rows'),# 差评申诉：汇总表 0 行（2026-10-22 新判据，0 条/空表不外发）
    ('"hits":0', '"unresolved":0'),               # 新店开业识别：命中 0、无未决
    ('"targetcount":0', '"shops":[]'),            # 活动缺项巡检：目标店铺 0 家
)


def _evidence_files(name: str, day: str) -> list:
    files: list = []
    d = RUN_HISTORY / day
    if d.is_dir():
        files += [p for p in d.glob("%s--*" % name) if not p.name.endswith("record.json")]
    rd = RUNS_DIR / name
    if rd.is_dir():
        stamp = day.replace("-", "")
        files += [p for p in rd.rglob("step*.log") if p.parent.name.startswith(stamp)]
    # 个别流的外发回执落在自己的产物目录，不在 step 日志里
    for pat in EXTRA_EVIDENCE_GLOBS.get(name, []):
        files += list(ROOT.glob(pat.replace("{YYYYMMDD}", day.replace("-", ""))
                                   .replace("{YYYY-MM-DD}", day)))
    return files


def _has_noop_evidence(name: str, day: str) -> bool:
    """当天日志里是否存在显式"无事可做"回执（no-candidate / 命中 0 / 目标 0）。"""
    for p in sorted(_evidence_files(name, day)):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore").replace(": ", ":").lower()
        except Exception:
            continue
        if any(all(mk in txt for mk in marker_set) for marker_set in NOOP_MARKER_SETS):
            return True
    return False


def _latest_record(name: str, day: str):
    """取该 skill 当天最新的 record.json。"""
    d = RUN_HISTORY / day
    if not d.is_dir():
        return None
    cands = sorted(d.glob("%s--*--record.json" % name))
    if not cands:
        return None
    p = cands[-1]
    rec = _load(p, None)
    if rec is None:
        return None
    # 从文件名取时间戳：<name>--<YYYYMMDD-HHMMSS>--aN--sN
    rec["_has_delivery_evidence"] = _has_delivery_evidence(name, day)
    return rec


def build(now: dt.datetime | None = None) -> dict:
    from business_coverage import read_daily_coverage
    from business_delivery_facts import read_fact
    now = now or dt.datetime.now()
    day = now.strftime("%Y-%m-%d")
    m = _load(MANIFEST, {})
    skills = {s["name"]: s for s in m.get("skills", [])}
    last_success = _load(STATE / "last_success.json", {})
    failure_watch = _load(STATE / "failure_watch.json", {})
    last_cycle = _load(STATE / "last_cycle.json", {})

    rows = []
    for s in m.get("skills", []):
        if s.get("dev_state") != "active" or not s.get("enabled", True):
            continue
        name = s["name"]
        earliest = s.get("earliest_hour", 0)
        earliest_min = s.get("earliest_minute", 0)
        threshold = earliest * 60 + earliest_min  # 与 run_all._cadence_gate 同口径（含分钟）
        ls = last_success.get(name)
        ls_dt = None
        if ls:
            try:
                ls_dt = dt.datetime.fromisoformat(ls)
            except ValueError:
                ls_dt = None
        # 只认当天 + 时段门槛（凌晨成功不得顶当日排班档）——与 _cadence_gate 同口径
        done = bool(ls_dt and ls_dt.date() == now.date()
                    and (not earliest or ls_dt.hour * 60 + ls_dt.minute >= threshold))
        due = now.hour * 60 + now.minute >= threshold
        if 'schedule_times' in s:
            _, slot_reason = fixed_schedule.gate(s, now, ls)
            done = slot_reason == 'done_today'
            due = slot_reason != 'not_due'
        fw = failure_watch.get(name, {})
        rec = _latest_record(name, day)
        superseded = fixed_schedule.customer_slot_superseded(name, now)
        coverage = read_daily_coverage(name, day, ROOT)
        accepted_delivery = read_fact(name, now)
        if due and coverage and not coverage['complete']:
            done = False
            state, mark = '未完成·门店未覆盖', '❌'
            reason = coverage['reason']
        elif accepted_delivery:
            done = True
            state, mark = '已完成·业务送达已核对', '✅'
            reason = '原送达证据与独立业务验收已核对'
        elif superseded:
            state, mark = '历史档·不补跑', '⏭️'
            reason = '保留历史记录；当前最新客服档承担全量值班'
        elif fixed_schedule.customer_duty_user_accepted(name, now):
            done = True
            state, mark = '用户确认完成·本次未发送', '✅'
            reason = '用户确认今天客服完成；保留原发送异常，不再补跑'
        elif done:
            ev = bool(rec and rec.get("_has_delivery_evidence"))
            if ev:
                # 真外发证据在案
                state, mark = "已完成·已外发", "✅"
                reason = "当日成功 %s" % (ls_dt.strftime("%H:%M:%S") if ls_dt else "")
            elif _has_noop_evidence(name, day):
                # 业务回执显式 noop（无候选/命中0/目标0）——无事可发，不是漏发
                state, mark = "已完成·无待发内容", "✅"
                reason = "当日成功 %s；业务回执显式 noop（无候选/命中0），无需外发" % (
                    ls_dt.strftime("%H:%M:%S") if ls_dt else "")
            else:
                state, mark = "已完成·外发待核", "✅"
                reason = "当日成功 %s；日志未见外发回执（以群回读为准）" % (
                    ls_dt.strftime("%H:%M:%S") if ls_dt else "")
        elif not due:
            state, mark = "待跑（未到 %02d:%02d）" % (earliest, earliest_min), "⏳"
            reason = "排班未到点"
        else:
            fails = fw.get("consecutive_failures", 0)
            state, mark = ("未完成·失败 x%d" % fails) if fails else "未完成（本日尚无成功）", "❌"
            reason = fw.get("last_category") or (rec or {}).get("detail") or "无当日成功记录"
        rows.append({
            "order": s.get("order", 99),
            "name": name,
            "ledger_name": s.get("ledger_name", name),
            "schedule": s.get("schedule", ""),
            "earliest_hour": earliest,
            "target_group": s.get("target_group", ""),
            "done": done,
            "superseded": superseded,
            "due": due,
            "mark": mark,
            "state": state,
            "reason": reason,
            "last_success": "" if (not superseded and fixed_schedule.customer_duty_user_accepted(name, now)) else (ls or ""),
            "consecutive_failures": fw.get("consecutive_failures", 0),
            "last_cycle_status": (last_cycle.get("skills", {}).get(name) or {}).get("status", ""),
            "record": rec,
        })
    rows.sort(key=lambda r: (r["order"], r["earliest_hour"], r["name"]))
    total = sum(1 for r in rows if not r["superseded"])
    done_n = sum(1 for r in rows if r["done"] and not r["superseded"])
    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "date": day,
        "total_active": total,
        "done": done_n,
        "all_green": done_n == total,
        "rows": rows,
    }


def render_md(d: dict) -> str:
    out = []
    out.append("## 臻肆外卖当日任务流进度 · %s（%s）" % (d["date"], d["generated_at"][11:16]))
    out.append("")
    out.append("**%d / %d 已完成** · %s" % (
        d["done"], d["total_active"], "全绿 ✅" if d["all_green"] else "未全绿 ❌（只认当天真实成功）"))
    out.append("")
    out.append("| # | 状态 | 工作流 | 排班 | 当日成功时间 | 说明 |")
    out.append("|---|---|---|---|---|---|")
    for i, r in enumerate(d["rows"], 1):
        out.append("| %d | %s %s | %s | %s | %s | %s |" % (
            i, r["mark"], r["state"], r["ledger_name"], r["schedule"],
            (r["last_success"][11:19] if r["done"] and r["last_success"] else "—"),
            r["reason"]))
    pend = [r for r in d["rows"] if not r["done"] and not r.get("superseded")]
    out.append("")
    if not pend:
        out.append("### 未完成：无（当日全部完成）")
    else:
        out.append("### 未完成跟进（%d 条）" % len(pend))
        for r in pend:
            out.append("- **%s**（%s）：%s" % (r["ledger_name"], r["schedule"], r["reason"]))
            if r["record"]:
                rec = r["record"]
                out.append("  - 最近记录 `%s` status=%s category=%s detail=%s" % (
                    rec.get("finished_at", ""), rec.get("status"), rec.get("category"),
                    rec.get("detail")))
            out.append("  - 下钻：`runtime/run_history/%s/%s--*--record.json`"
                       % (d["date"], r["name"]))
    return "\n".join(out)


def main() -> int:
    d = build()
    if "--json" in sys.argv:
        print(json.dumps(d, ensure_ascii=False, indent=1, default=str))
    else:
        print(render_md(d))
    return 0 if d["all_green"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
