#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""断点续跑只读规划器（P1-1 · 先只读试点）。

来源：docs/architecture/20261003-任务机制自进化优化方案.md §4 P1-1。

铁律：本工具**只读**——只回答"如果续跑，该从哪个阶段继续、预计省多少"，
绝不执行任何流水线、不写任何执行状态。真正执行续跑（W5 后续）必须另行
大同授权 + 测试群验证（与防重账本/去重上传语义强耦合）。

用法：
  python3 runtime/resume_planner.py --skill daily-taobao-download-to-jinsha
  python3 runtime/resume_planner.py --skill <name> --days 7   # 回看窗口
  python3 runtime/resume_planner.py --skill <name> --json     # 机器可读输出

输出（文本模式）：
  - 最后失败时间 / 失败 stage / reason
  - 已完成阶段（phaseHistory 末项）
  - 建议续跑起点（末项之后的下一阶段——由 skill 的 phase 序列推断）
  - 预计可节省耗时（stageMs 中已完成阶段的累计）
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

RUNTIME_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME_DIR))
import receipt as rc  # noqa: E402

HISTORY_DIR = RUNTIME_DIR / "run_history"


def find_last_failure(skill: str, days: int = 7) -> Optional[dict]:
    """在回看窗口内找该 skill 最新一次 FAILED record（含其日志路径）。"""
    cutoff = (datetime.now() - timedelta(days=days)).date()
    candidates = []
    for day_dir in sorted(HISTORY_DIR.iterdir(), reverse=True):
        if not day_dir.is_dir():
            continue
        try:
            day = datetime.strptime(day_dir.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if day < cutoff:
            break
        for rec_path in sorted(day_dir.glob("%s--*--record.json" % skill), reverse=True):
            try:
                rec = json.loads(rec_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if rec.get("status") == "FAILED":
                candidates.append(rec)
        if candidates:
            break  # 只看最近一个有失败记录的日子即可
    if not candidates:
        return None
    rec = candidates[0]
    rec.setdefault("logs", [])
    return rec


def build_plan(rec: dict) -> Optional[dict]:
    """从失败 record 构造只读续跑计划。无可解析收据时返回 None。"""
    logs = rec.get("logs") or []
    log = logs[-1] if logs else None
    receipt = rc.parse_top_receipt_log(log) if log else None
    if receipt is None:
        return None
    sig = rc.extract_signal(receipt)
    phase_last = rc._phase_history_last(receipt)  # noqa: SLF001  同仓内复用
    # stageMs：已完成各阶段的耗时（收据任意层级找 dict 形态的 stageMs）
    stage_ms = _find_stage_ms(receipt) or {}
    plan = {
        "skill": rec.get("skill"),
        "failed_at": rec.get("finished_at"),
        "failed_stage": (sig or {}).get("code"),
        "failed_kind": (sig or {}).get("kind"),
        "completed_through": phase_last,
        "stage_ms": stage_ms,
        "log": log,
    }
    plan["elapsed_completed_seconds"] = round(
        sum(v for v in stage_ms.values() if isinstance(v, (int, float))) / 1000.0, 1)
    return plan


def _find_stage_ms(obj):
    if isinstance(obj, dict):
        sm = obj.get("stageMs")
        if isinstance(sm, dict) and sm:
            return sm
        for child in obj.values():
            found = _find_stage_ms(child)
            if found:
                return found
    elif isinstance(obj, list):
        for child in obj:
            found = _find_stage_ms(child)
            if found:
                return found
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="P1-1 断点续跑只读规划器")
    ap.add_argument("--skill", required=True, help="流水线名")
    ap.add_argument("--days", type=int, default=7, help="回看窗口天数（默认 7）")
    ap.add_argument("--json", action="store_true", help="输出机器可读 JSON")
    args = ap.parse_args()

    rec = find_last_failure(args.skill, args.days)
    if rec is None:
        print("(近 %d 天无 FAILED record：%s)" % (args.days, args.skill))
        return 0
    plan = build_plan(rec)
    if args.json:
        print(json.dumps({"record": {k: rec.get(k) for k in
                                     ("skill", "finished_at", "category", "detail")},
                          "plan": plan}, ensure_ascii=False, indent=1))
        return 0
    print("=== P1-1 只读续跑计划（不执行任何动作）===")
    print("  流水线    : %s" % rec.get("skill"))
    print("  失败时间  : %s" % rec.get("finished_at"))
    print("  失败分类  : %s / %s" % (rec.get("category"), rec.get("detail")))
    if plan is None:
        print("  (末条日志无可解析收据——无法给出续跑起点)")
        return 0
    print("  失败阶段  : %s（来源 %s）" % (plan["failed_stage"], plan["failed_kind"]))
    print("  已完成至  : %s" % plan["completed_through"])
    if plan["stage_ms"]:
        print("  各阶段耗时: %s" % json.dumps(plan["stage_ms"], ensure_ascii=False))
    print("  若续跑可省: ~%ss（已完成阶段的累计耗时）" % plan["elapsed_completed_seconds"])
    print("  ⚠️ 真正执行续跑需大同授权 + 测试群验证（防重账本耦合），本工具不执行。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
