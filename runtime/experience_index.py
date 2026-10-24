#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""经验索引（P1-2 · 运行轨迹索引 + 老化 + 回答「过去 30 天怎么样」）。

来源：docs/architecture/20261003-任务机制自进化优化方案.md §4 P1-2。

设计：
- 每次真实运行（成功或失败）由 run_one 落一条摘要索引到
  `runtime/state/experience_index.jsonl`（skill/结果/耗时/故障码/日志路径）；
- `--query [skill] --days N`：P50/P95 耗时、成功率、Top 失败码、分时段失败率——
  验收判据：能回答「过去 30 天 daily-top10 平均耗时多少、哪种失败最常见」；
- 老化：>90 天的原始行先聚合进 `state/experience_monthly.json`（按月×skill×类别
  计数），再物理删除原始行（治"14 天即删=经验蒸发"）。

兼容 Python 3.9+；零第三方依赖。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

RUNTIME_DIR = Path(__file__).resolve().parent
STATE_DIR = RUNTIME_DIR / "state"
INDEX_FILE = STATE_DIR / "experience_index.jsonl"
MONTHLY_FILE = STATE_DIR / "experience_monthly.json"


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def record(rec: dict) -> Optional[dict]:
    """把一次 run_skill 的 record 写入索引。返回写入行（rec 无效时 None）。"""
    if not rec or not rec.get("skill"):
        return None
    signal = rec.get("fail_signal") or {}
    line = {
        "ts": rec.get("finished_at") or _now_iso(),
        "skill": rec.get("skill"),
        "status": rec.get("status"),
        "category": rec.get("category"),
        "attempts": rec.get("attempts"),
        "duration_seconds": rec.get("duration_seconds"),
        "code": signal.get("code"),
        "phase_last": signal.get("phase_last"),
        "log": (rec.get("logs") or [None])[-1],
    }
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with INDEX_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        return None
    return line


def _read_lines() -> List[dict]:
    if not INDEX_FILE.exists():
        return []
    out = []
    for line in INDEX_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _pctl(values: List[float], q: float) -> Optional[float]:
    """最近邻百分位（输入须已排序）。"""
    if not values:
        return None
    k = min(len(values) - 1, max(0, int(round(q * (len(values) - 1)))))
    return values[k]


def query(skill: Optional[str] = None, days: int = 30) -> Dict[str, dict]:
    """按 skill 聚合最近 N 天：次数/成功率/P50/P95/最大耗时/Top失败码/分时段失败。"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    per: Dict[str, dict] = {}
    for line in _read_lines():
        if line.get("ts", "") < cutoff:
            continue
        sk = line.get("skill") or "?"
        if skill and sk != skill:
            continue
        bucket = per.setdefault(sk, {
            "n": 0, "ok": 0, "fail": 0, "durations": [],
            "failures": {}, "hour_fail": {},
        })
        bucket["n"] += 1
        if line.get("status") == "SUCCESS":
            bucket["ok"] += 1
        else:
            bucket["fail"] += 1
            code = line.get("code") or line.get("category") or "uncoded"
            bucket["failures"][code] = bucket["failures"].get(code, 0) + 1
            hour = (line.get("ts") or "")[11:13]
            if hour:
                bucket["hour_fail"][hour] = bucket["hour_fail"].get(hour, 0) + 1
        d = line.get("duration_seconds")
        if isinstance(d, (int, float)) and d > 0:
            bucket["durations"].append(round(float(d), 1))
    out: Dict[str, dict] = {}
    for sk, b in per.items():
        durs = sorted(b["durations"])
        top_fail = sorted(b["failures"].items(), key=lambda x: -x[1])[:5]
        out[sk] = {
            "n": b["n"],
            "ok": b["ok"],
            "fail": b["fail"],
            "ok_rate": round(b["ok"] / b["n"], 3) if b["n"] else None,
            "p50_seconds": _pctl(durs, 0.50),
            "p95_seconds": _pctl(durs, 0.95),
            "max_seconds": durs[-1] if durs else None,
            "top_failures": top_fail,
            "hour_fail": dict(sorted(b["hour_fail"].items())),
        }
    return out


def prune(keep_days: int = 90) -> int:
    """>keep_days 的行先按 (月, skill, status, code) 聚合进 monthly，再物理删除。"""
    lines = _read_lines()
    if not lines:
        return 0
    cutoff = (datetime.now() - timedelta(days=keep_days)).isoformat(timespec="seconds")
    old = [l for l in lines if l.get("ts", "") < cutoff]
    keep = [l for l in lines if l.get("ts", "") >= cutoff]
    if not old:
        return 0
    monthly: Dict[str, dict] = {}
    if MONTHLY_FILE.exists():
        try:
            monthly = json.loads(MONTHLY_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            monthly = {}
    for l in old:
        month = (l.get("ts") or "")[:7]
        sk = l.get("skill") or "?"
        code = l.get("code") or l.get("category") or "uncoded"
        key = "%s|%s" % (month, sk)
        bucket = monthly.setdefault(key, {"month": month, "skill": sk, "n": 0,
                                          "ok": 0, "fail": 0, "failures": {},
                                          "dur_sum": 0.0})
        bucket["n"] += 1
        if l.get("status") == "SUCCESS":
            bucket["ok"] += 1
        else:
            bucket["fail"] += 1
            bucket["failures"][code] = bucket["failures"].get(code, 0) + 1
        d = l.get("duration_seconds")
        if isinstance(d, (int, float)):
            bucket["dur_sum"] = round(bucket["dur_sum"] + float(d), 1)
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = MONTHLY_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(monthly, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(MONTHLY_FILE)
    tmp_idx = INDEX_FILE.with_suffix(".tmp")
    with tmp_idx.open("w", encoding="utf-8") as f:
        for l in keep:
            f.write(json.dumps(l, ensure_ascii=False) + "\n")
    tmp_idx.replace(INDEX_FILE)
    return len(old)


def backfill(history_dir: Optional[Path] = None) -> int:
    """从 run_history/<day>/<skill>--<ts>--record.json 回填索引（跳过已有 ts+skill 行）。

    存量 record 早于 P0-1、没有 fail_signal：回填时用收据解析器从其末条日志
    提取真实故障码，让历史经验即刻可查。
    """
    history_dir = history_dir or RUNTIME_DIR / "run_history"
    existing = {(l.get("skill"), l.get("ts")) for l in _read_lines()}
    n = 0
    for rec_path in sorted(history_dir.glob("*/*--record.json")):
        try:
            rec = json.loads(rec_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        key = (rec.get("skill"), rec.get("finished_at"))
        if key in existing:
            continue
        if not rec.get("fail_signal") and rec.get("status") != "SUCCESS":
            try:
                sys.path.insert(0, str(RUNTIME_DIR))
                import receipt as _receipt  # noqa: PLC0415
                log = (rec.get("logs") or [None])[-1]
                rcpt = _receipt.parse_top_receipt_log(log) if log else None
                sig = _receipt.extract_signal(rcpt) if rcpt else None
                if sig:
                    rec["fail_signal"] = {"kind": sig["kind"], "code": sig["code"]}
            except Exception:  # noqa: BLE001  回填增强失败不影响主流程
                pass
        if record(rec):
            existing.add(key)
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description="P1-2 经验索引")
    ap.add_argument("--query", metavar="SKILL", nargs="?", const="ALL",
                    help="查询（无参=全部 skill）")
    ap.add_argument("--days", type=int, default=30, help="查询窗口天数（默认 30）")
    ap.add_argument("--prune", action="store_true", help="老化：>90 天聚合后删除")
    ap.add_argument("--backfill", action="store_true",
                    help="从 run_history 存量 record.json 回填索引")
    args = ap.parse_args()
    if args.backfill:
        n = backfill()
        print("[ok] 回填 %d 条经验索引" % n)
        return 0
    if args.prune:
        n = prune()
        print("[ok] 已聚合并删除 %d 条 >90 天索引行" % n)
        return 0
    if args.query:
        sk = None if args.query == "ALL" else args.query
        result = query(sk, args.days)
        if not result:
            print("(窗口内无索引数据)")
            return 0
        for sk_name, b in sorted(result.items()):
            print("=== %s（近 %d 天，n=%d）===" % (sk_name, args.days, b["n"]))
            print("  成功率 %s（成功 %d / 失败 %d）" % (
                b["ok_rate"], b["ok"], b["fail"]))
            print("  耗时 P50=%ss P95=%ss max=%ss" % (
                b["p50_seconds"], b["p95_seconds"], b["max_seconds"]))
            print("  Top失败码: %s" % (b["top_failures"] or "无"))
            if b["hour_fail"]:
                print("  失败分时: %s" % b["hour_fail"])
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
