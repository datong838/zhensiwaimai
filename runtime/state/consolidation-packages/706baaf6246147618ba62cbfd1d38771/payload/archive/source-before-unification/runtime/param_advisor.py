#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""参数自适应建议器（P2-1 · DSPy 式「把运行参数当可优化对象」——只建议、绝不写回）。

来源：docs/architecture/20261003-任务机制自进化优化方案.md §4 P2-1。

红线（方案原文）：**只建议、不自动写**。参数自适应若自动改写 manifest，等于让系统
自己改生产配置。本工具只读 manifest + 经验索引，产出「当前值 / 建议值 / 依据」
三列对照表（markdown + json），**采纳与否由大同人审决定**。

用法：
  python3 runtime/param_advisor.py --report          # 生成建议表
  python3 runtime/param_advisor.py --days 14         # 改评估窗口
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

RUNTIME_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME_DIR))
import experience_index as xi  # noqa: E402

REPO_ROOT = RUNTIME_DIR.parent
MANIFEST = RUNTIME_DIR / "skills_manifest.json"
OUT_DIR = REPO_ROOT / "work"
OUT_MD = OUT_DIR / "参数建议-%s.md"
OUT_JSON = RUNTIME_DIR / "state" / "param_suggestions.json"


def _suggest_timeout(p95: Optional[float], current: int) -> Optional[int]:
    """超时预算建议：P95 的 2 倍再向上取整到分钟，下限 300s。无数据返回 None。"""
    if not p95 or p95 <= 0:
        return None
    suggested = max(300, int(math.ceil(p95 * 2 / 60.0)) * 60)
    if abs(suggested - current) < 60:  # 差距 <1 分钟视为无需调整
        return None
    return suggested


def build_suggestions(days: int = 30) -> Dict[str, dict]:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    stats = xi.query(None, days)
    out: Dict[str, dict] = {}
    for s in manifest.get("skills", []):
        name = s.get("name")
        if not name or not s.get("enabled"):
            continue
        cur_timeout = int(s.get("timeout_seconds", 1800))
        cur_retries = int(s.get("max_retries", 2))
        cur_cadence = s.get("cadence_hours", 24)
        b = stats.get(name)
        sug_timeout = None
        basis = None
        retry_reuse = None
        if b and b["n"]:
            p95 = b["p95_seconds"]
            sug_timeout = _suggest_timeout(p95, cur_timeout)
            basis = "近%d天 n=%d P95=%ss max=%ss 失败%d" % (
                days, b["n"], p95, b["max_seconds"], b["fail"])
            retry_reuse = round(b["fail"] / b["n"], 3)
        out[name] = {
            "timeout_current": cur_timeout,
            "timeout_suggested": sug_timeout,
            "max_retries_current": cur_retries,
            "cadence_hours": cur_cadence,
            "n": b["n"] if b else 0,
            "ok_rate": b["ok_rate"] if b else None,
            "p95_seconds": b["p95_seconds"] if b else None,
            "basis": basis,
        }
    return out


def write_report(days: int = 30) -> Path:
    suggestions = build_suggestions(days)
    date_str = datetime.now().strftime("%Y-%m-%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    md_path = OUT_DIR / ("参数建议-%s.md" % date_str)
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(timespec="seconds"),
         "days": days, "suggestions": suggestions},
        ensure_ascii=False, indent=1), encoding="utf-8")
    lines = [
        "# 参数自适应建议表（P2-1 · 只建议不自动写）",
        "",
        "> 生成时间：%s ｜ 评估窗口：近 %d 天经验索引" % (
            datetime.now().isoformat(timespec="seconds"), days),
        "> **红线**：本表由机器生成，任何写回 manifest 的动作必须大同人审后手动执行。",
        "",
        "| 流水线 | 超时当前 | 超时建议 | 依据（近%d天） | 成功率 |" % days,
        "|---|---|---|---|---|",
    ]
    for name, s in sorted(suggestions.items()):
        sug = s["timeout_suggested"]
        lines.append("| %s | %ss | %s | %s | %s |" % (
            name, s["timeout_current"],
            ("**%ss**" % sug) if sug else "—（维持）",
            s["basis"] or "（窗口内无运行数据）",
            s["ok_rate"] if s["ok_rate"] is not None else "—"))
    lines += ["", "## 采纳方式", "",
              "1. 大同逐行人审上表；",
              "2. 确认采纳的行由监理（或人）改 `runtime/skills_manifest.json` 对应字段；",
              "3. 改完 `launchctl kickstart -k gui/$(id -u)/com.zhensi.waimai.careloop` 重启生效。",
              ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path


def main() -> int:
    ap = argparse.ArgumentParser(description="P2-1 参数建议（只建议不写回）")
    ap.add_argument("--report", action="store_true", help="生成建议表")
    ap.add_argument("--days", type=int, default=30, help="评估窗口（默认 30 天）")
    args = ap.parse_args()
    if args.report:
        path = write_report(args.days)
        print("[ok] 参数建议表已生成：%s（同时落 %s）" % (path, OUT_JSON))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
