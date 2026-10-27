#!/usr/bin/env python3
"""外发契约拒发告警探测器（只读）。

背景（2026-10-05 实证）：wechat-messaging 桥在 prepare() 阶段拒绝外发时，
step 日志顶层只留 `{"ok":false,"reason":"Command failed: <命令>"}`，真正的拒绝原因
（如 `workflow-ledger-mismatch` / `workflow-...-path-mismatch`）被包在子进程的
stdout 里，外面套了一层。结果是：
  * `verified=false` 且 `sendAttempts=null` ⇒ **消息从未发出**；
  * 但进度表只显示「失败 / 未知原因」，连续多次也无人察觉。

本脚本把这一层剥开，把「契约拒发」变成一等告警信号。只读，不修改任何状态。

用法：
    python runtime/alert_send_rejections.py [YYYY-MM-DD]
退出码：0 = 无告警；1 = 存在告警（供守护/自动化判定）。
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_HISTORY = ROOT / "runtime" / "run_history"

# 桥/契约层的真实拒绝 reason（区别于网络抖动、页面未就绪等瞬时原因）
# 子进程的 stdout 被包了两层：外层 JSON 的 stderr/stdout 字段里又嵌了一层 JSON，
# 真实文本形如  ...\\\"reason\\\": \\\"legacy-marker-binding-mismatch\\\"...
# 故键名与值两侧都要能吞掉任意数量的反斜杠。
CONTRACT_REASON = re.compile(r'\\*"(?:reason|code)\\*"\s*[:=]\s*\\*"([a-z][a-z0-9-]{3,})')
# "verified": false / "verified":false（含子进程 stdout 里的转义形式）
VERIFIED_FALSE = re.compile(r'verified\\*"?\s*:\s*false')
SEND_ATTEMPTS_NULL = re.compile(r'sendAttempts\\*"?\s*:\s*(null|None)')
NEEDS_TICKET_THRESHOLD = 3


def _skill_of(path: Path) -> str:
    name = path.name
    # <flow>--<yyyymmdd>-<hhmmss>--a1--s4.log
    return name.split("--")[0]


def scan(day: str) -> dict:
    directory = RUN_HISTORY / day
    findings: list[dict] = []
    if not directory.is_dir():
        return {"day": day, "ok": True, "alerts": [], "note": "run_history 目录不存在"}

    for log in sorted(directory.glob("*.log")):
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        # 只认「verified=false 且 sendAttempts=null」= 从未外发；
        # 单有 verified=false 可能是回读未通过但确实发过，另行处理。
        if not (VERIFIED_FALSE.search(text) and SEND_ATTEMPTS_NULL.search(text)):
            continue
        candidates = [r for r in CONTRACT_REASON.findall(text) if "-" in r]
        preferred = [r for r in candidates if r.startswith(
            ("workflow-", "contract-", "payload-", "ledger-", "legacy-", "marker-"))]
        reason = (preferred or candidates or ["unknown"])[-1]
        findings.append({
            "log": log.name,
            "skill": _skill_of(log),
            "step": (log.name.rsplit("--", 1)[-1].replace(".log", "") or "?"),
            "reason": reason,
            "neverSent": bool(SEND_ATTEMPTS_NULL.search(text)),
        })

    by_reason: dict[str, list[dict]] = defaultdict(list)
    for item in findings:
        by_reason[item["reason"]].append(item)

    alerts = []
    # P0-1b（2026-10-06）：`legacy-marker-*` 是**二义码**——既可能是「当日已外发后重算被拒」
    # 的良性幂等，也可能是「marker 绑陈旧/占位载荷、从未发出」的真故障。本探测器无上下文
    # 无法自证，故不再一律免单：保留可见性 + 提示必须核实当日 verified 外发证据。
    for reason, items in by_reason.items():
        skills = Counter(i["skill"] for i in items)
        idempotent = reason.startswith("legacy-marker-")
        alerts.append({
            "reason": reason,
            "count": len(items),
            "skills": dict(skills),
            "neverSent": all(i["neverSent"] for i in items),
            "idempotentSkip": idempotent,
            "needsVerification": idempotent,
            "needsTicket": (not idempotent) and len(items) >= NEEDS_TICKET_THRESHOLD,
            "latest": items[-1]["log"],
        })
    alerts.sort(key=lambda a: a["count"], reverse=True)

    return {
        "day": day,
        "ok": not alerts,
        "scanCount": len(list(directory.glob("*.log"))),
        "alerts": alerts,
    }


def main(argv: list[str]) -> int:
    day = argv[1] if len(argv) > 1 else date.today().isoformat()
    result = scan(day)
    if "--json" in argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    if not result["alerts"]:
        print("✅ 无外发契约拒发告警（%s，扫 %s 个日志）" % (day, result.get("scanCount", 0)))
        return 0
    print("🚨 外发契约拒发告警 · %s（扫 %s 个日志）" % (day, result.get("scanCount", 0)))
    print("| reason | 次数 | 涉及流 | 从未外发 | 建议 |")
    print("|---|---|---|---|---|")
    for alert in result["alerts"]:
        print("| `%s` | %d | %s | %s | %s |" % (
            alert["reason"], alert["count"],
            ", ".join("%s x%d" % (k, v) for k, v in alert["skills"].items()),
            "是" if alert["neverSent"] else "否",
            "**开单/人工介入**" if alert["needsTicket"]
            else ("幂等候选·须核实当日 verified 外发证据" if alert.get("idempotentSkip") else "观察"),
        ))
    print()
    print("说明：`verified=false` 且 `sendAttempts=null` 表示消息从未发出，业务侧步骤可能全绿，"
          "不能按「网络抖动」处理。`legacy-marker-*` 是二义码——既可能是同日幂等保护，也可能是"
          "真故障；P0-1b（2026-10-06 起）运行时必须读到当日 verified 外发 marker 才判"
          "SKIPPED_IDEMPOTENT，否则按真故障（UNKNOWN）告警。")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
