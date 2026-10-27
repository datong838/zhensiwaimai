#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""失败自动分诊（P2-2 · 杜绝「告警没人跟、靠记忆」）。

来源：docs/architecture/20261003-任务机制自进化优化方案.md §4 P2-2。

规则：UNKNOWN（或 NEEDS_LOGIN）且**连败 >= 3** 的 (skill, code) 组合，自动开一条
待办进 `runtime/state/dev_backlog.jsonl`（按组合去重，只增不改不自动关——
关闭由人处理），并生成 `work/失败分诊-<date>.md` 报告（open 待办 + 证据链）。

调用方：daemon 每周期末尾自动跑一次（run_all.daemon_cycle），也可手动 CLI。
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

RUNTIME_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(RUNTIME_DIR))

REPO_ROOT = RUNTIME_DIR.parent
BACKLOG_FILE = RUNTIME_DIR / "state" / "dev_backlog.jsonl"
REPORT_DIR = REPO_ROOT / "work"
THRESHOLD = 3


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_backlog() -> Dict[str, dict]:
    items: Dict[str, dict] = {}
    if BACKLOG_FILE.exists():
        for line in BACKLOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except ValueError:
                continue
            items[item.get("key") or ""] = item  # 同键后者覆盖（保留最新状态字段）
    return items


def _append_backlog(item: dict) -> None:
    BACKLOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with BACKLOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(item, ensure_ascii=False) + "\n")


def run_triage(repo_root: Path = REPO_ROOT, threshold: int = THRESHOLD) -> List[dict]:
    """扫描聚合告警 + 失败计数，把连败>=threshold 的组合开成待办。返回本轮新增。"""
    try:
        import alert_store  # noqa: PLC0415
    except ImportError:  # pragma: no cover
        return []
    backlog = _load_backlog()
    added = []
    # 数据源1：P0-3 聚合视图中未解决且 consecutive 达标的条目
    for entry in alert_store.open_issues():
        if (entry.get("consecutive") or 0) < threshold:
            continue
        key = "%s|%s|%s" % (entry.get("skill"), entry.get("category"), entry.get("code"))
        if key in backlog and backlog[key].get("status") == "open":
            continue
        item = {
            "key": key,
            "opened_at": _now_iso(),
            "status": "open",
            "skill": entry.get("skill"),
            "category": entry.get("category"),
            "code": entry.get("code"),
            "consecutive": entry.get("consecutive"),
            "first_ts": entry.get("first_ts"),
            "last_ts": entry.get("last_ts"),
            "evidence_log": entry.get("last_log"),
            "last_detail": entry.get("last_detail"),
            "source": "alert_summary",
        }
        _append_backlog(item)
        backlog[key] = item
        added.append(item)
    # 数据源2：failure_watch 连败计数（无聚合码时兜底）
    try:
        fw = json.loads((RUNTIME_DIR / "state" / "failure_watch.json")
                        .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        fw = {}
    for skill, e in fw.items():
        consecutive = e.get("consecutive_failures") or 0
        if consecutive < threshold:
            continue
        code = "failure-watch:%s" % (e.get("last_category") or "?")
        key = "%s|FAILURE_WATCH|%s" % (skill, code)
        if key in backlog and backlog[key].get("status") == "open":
            continue
        item = {
            "key": key, "opened_at": _now_iso(), "status": "open",
            "skill": skill, "category": "FAILURE_WATCH", "code": code,
            "consecutive": consecutive, "last_ts": e.get("last_failure_at"),
            "evidence_log": None, "last_detail": None, "source": "failure_watch",
        }
        _append_backlog(item)
        backlog[key] = item
        added.append(item)
    return added


def write_report() -> Path:
    """把 open 待办渲染成 markdown 报告（供大同/监理每天扫一眼）。"""
    backlog = [v for v in _load_backlog().values() if v.get("status") == "open"]
    backlog.sort(key=lambda x: -(x.get("consecutive") or 0))
    date_str = datetime.now().strftime("%Y-%m-%d")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / ("失败分诊-%s.md" % date_str)
    lines = [
        "# 失败分诊清单（P2-2 自动生成）",
        "",
        "> 生成时间：%s ｜ open 待办 %d 条 ｜ 待办账本：%s" % (
            _now_iso(), len(backlog), BACKLOG_FILE),
        "> 规则：UNKNOWN/NEEDS_LOGIN 且连败 ≥%d 自动开单；**关闭待办必须人工处理**。" % THRESHOLD,
        "",
    ]
    if not backlog:
        lines.append("（当前无 open 待办）")
    else:
        lines += ["| 连败 | 流水线 | 故障码 | 首次 | 最近 | 证据日志 |", "|---|---|---|---|---|---|"]
        for it in backlog:
            lines.append("| x%d | %s | `%s` | %s | %s | %s |" % (
                it.get("consecutive") or 0, it.get("skill"), it.get("code"),
                it.get("first_ts") or "—", it.get("last_ts") or "—",
                it.get("evidence_log") or "—"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="P2-2 失败自动分诊")
    ap.add_argument("--run", action="store_true", help="执行一轮分诊并生成报告")
    ap.add_argument("--report", action="store_true", help="仅重新渲染报告")
    ap.add_argument("--threshold", type=int, default=THRESHOLD, help="连败开单阈值")
    args = ap.parse_args()
    if args.run:
        added = run_triage(threshold=args.threshold)
        print("[ok] 本轮新增待办 %d 条" % len(added))
        for it in added:
            print("  + [%s] %s x%d (%s)" % (it.get("category"), it.get("skill"),
                                            it.get("consecutive"), it.get("code")))
    path = write_report()
    print("[ok] 分诊报告：%s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
