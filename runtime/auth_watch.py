#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""P3-3 授权续期 + 到期告警（治诊断根因5）· runtime/auth_watch.py

设计铁律（已核实 executor-lock.json 的 scope 字段）：
- 重封（reseal）只在「本轮真实非空商家发送通过」时由 skill 内部 executor_integrity 原子完成，
  **绝不由本看护进程代劳**——否则会放宽 UNSEALED_ACCEPTANCE 安全门。
- 因此本模块**只做只读扫描 + 到期告警**，不写、不改任何锁/策略文件。安全门零改动。

扫哪些文件：REPO_ROOT/skills 下递归找 `executor-lock.json` 与 `runtime-policy.json`，
抽取所有 `expiresAt` 字段（兼容 ISO 字符串 与 Unix epoch 整数两种格式），
对「距到期 ≤ 阈值(默认24h)」的项写告警事件（抄 n8n Error Workflow 的"失败/异常触发告警流"语义）。

去重：state/auth_watch_state.json 记录每个 (文件::子路径) 上次告警时间，24h 内不重复告警，避免每周期刷屏。

用法（由 run_all 调用，也可独立）：
  python3 auth_watch.py [--root <skills根>] [--state <state目录>] [--threshold 24]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

AUTH_FILE_NAMES = ("executor-lock.json", "runtime-policy.json")
THRESHOLD_HOURS_DEFAULT = 24
SEEN_PATH_DEFAULT_NAME = "auth_watch_state.json"


def _parse_expiry(value):
    """兼容 ISO 字符串 与 Unix epoch（int/float/数字字符串）。返回 epoch 秒或 None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(value, str):
        s = value.strip()
        # ISO 8601（含 +08:00）
        try:
            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            pass
        # 纯数字 epoch 字符串
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _extract_expiries(obj, path: str = "", out: list = None) -> list:
    """递归抽取所有 `expiresAt` 键 → (json子路径, epoch秒)。

    2026-10-21 修正（治每日假告警）：`lastUnsealedAcceptance` 是**历史审计快照**
    （上一次未封板验收的存证），不是活动门禁——同文件存在当前的
    `unsealedAcceptance`（活动验收窗口）时，历史快照已被取代，过期属预期。
    盲扫它导致每天刷「已过期需人工重封」假警报（cnt=15 实证）。
    """
    if out is None:
        out = []
    if isinstance(obj, dict):
        has_current = "unsealedAcceptance" in obj
        sealed = obj.get("status") == "SEALED"
        for k, v in obj.items():
            if k == "expiresAt":
                ts = _parse_expiry(v)
                if ts is not None:
                    out.append((path, ts))
            elif sealed and k in {"unsealedAcceptance", "lastUnsealedAcceptance"}:
                continue  # SEALED 运行门不消费这两段历史验收窗口。
            elif k == "lastUnsealedAcceptance" and has_current:
                continue  # 历史快照：被当前 unsealedAcceptance 取代，跳过
            else:
                _extract_expiries(v, path + "/" + k, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _extract_expiries(v, path + "[%d]" % i, out)
    return out


def scan_files(root: Path) -> list:
    """递归扫描 root 下目标文件名，返回 [{file, subpath, expires_at}]。"""
    items = []
    for name in AUTH_FILE_NAMES:
        for p in root.rglob(name):
            try:
                obj = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for subpath, ts in _extract_expiries(obj):
                items.append({"file": str(p), "subpath": subpath, "expires_at": ts})
    return items


def run_auth_watch(root: Path, state_dir: Path, threshold_hours: float = THRESHOLD_HOURS_DEFAULT) -> list:
    """扫描授权到期。返回待告警列表 [{key, status, detail}]；24h 内同键去重。

    注意：只产生告警事件，不修改任何锁/策略文件（安全门零改动）。
    """
    items = scan_files(root)
    now = time.time()
    state_dir.mkdir(parents=True, exist_ok=True)
    seen_path = state_dir / SEEN_PATH_DEFAULT_NAME
    seen: dict = {}
    if seen_path.exists():
        try:
            seen = json.loads(seen_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            seen = {}

    alerts = []
    for it in items:
        remain_h = (it["expires_at"] - now) / 3600.0
        if remain_h > threshold_hours:
            continue
        key = "%s::%s" % (it["file"], it["subpath"])
        status = "AUTH_EXPIRED" if remain_h <= 0 else "AUTH_EXPIRING"
        last = seen.get(key)
        if last is not None and (now - float(last) <= 24 * 3600):
            continue  # 24h 内已告警，去重
        detail = "%s %s 将于 %.1fh 后到期 (epoch %.0f)" % (
            it["file"], it["subpath"], remain_h, it["expires_at"])
        if status == "AUTH_EXPIRED":
            detail = "%s 已过期 %.1fh (epoch %.0f)，需人工重封/续期" % (
                it["file"], -remain_h, it["expires_at"])
        alerts.append({"key": key, "status": status, "detail": detail})
        seen[key] = now

    seen_path.write_text(json.dumps(seen, indent=2), encoding="utf-8")
    return alerts


def main() -> int:
    ap = argparse.ArgumentParser(description="P3-3 授权到期只读扫描+告警")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parent.parent / "skills"))
    ap.add_argument("--state", default=str(Path(__file__).resolve().parent / "state"))
    ap.add_argument("--threshold", type=float, default=THRESHOLD_HOURS_DEFAULT)
    args = ap.parse_args()

    alerts = run_auth_watch(Path(args.root), Path(args.state), args.threshold)
    if not alerts:
        print("[ok] 无即将到期/已过期的授权（阈值 %.0fh 内）。" % args.threshold)
        return 0
    for a in alerts:
        print("[auth-alert] %s :: %s" % (a["status"], a["detail"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
