#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A2a · `attempted` 死结体检器（**纯只读**）

背景（详见 docs/solutions/20261006-A2方案-attempted死结检测与根治.md）：
桥对已存在 marker 只有四条出口，其中 `attempted` 且**无收据**（sendAttempts=null）⇒
`existing-attempt-reconcile-only`：**既不发也不前进**。中继丢响应事故会造出这种 marker，
一旦出现，该游标后的条目全被挡（2026-10-06 旨寿司实证，人工方案 A 解开）。

本工具只做一件事：**把这种死结扫出来并报告**，让看护 1 小时内发现，而不是靠人撞见。

纪律
----
* 纯只读：只读 marker JSON 与文件 mtime；不写任何文件、不改任何 marker、不发送。
* **排除证据旁文件**（文件名含 `evidence` 的 sidecar 不是 marker，扫进来是误报）。
* 需要真 marker 形状（至少含 bridgeVersion/groupName/payloadType/payloads/items 之一）。
* `--selftest` hermetic：临时目录造真/假 marker，正负对照。
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent   # repo root
sys.path.insert(0, str(ROOT / "runtime"))

MARKER_KEYS = ("bridgeVersion", "groupName", "payloadType", "payloads", "items", "itemId")
EVIDENCE_HINTS = ("evidence", "unknown-evidence", "-evidence-", "reconcile-only")


def looks_like_marker(obj) -> bool:
    return isinstance(obj, dict) and any(k in obj for k in MARKER_KEYS)


def is_evidence_sidecar(path: Path, obj) -> bool:
    """证据旁文件不是 marker：文件名含探索性关键词即排除（宁漏不误报）。"""
    name = path.name.lower()
    return any(h in name for h in EVIDENCE_HINTS)


def is_deadlock(obj) -> bool:
    """死结特征：state=attempted 且无收据（sendAttempts 为 None 或 0）。"""
    if not isinstance(obj, dict):
        return False
    return obj.get("state") == "attempted" and obj.get("sendAttempts") in (None, 0)


def discover_marker_dirs(roots: List[Path]) -> List[Path]:
    """找出所有 marker/账本目录（名字含 attempts / markers）。深度限 1~3 层，避免全树遍历。"""
    out = []
    for r in roots:
        if not r.exists():
            continue
        for pat in ("*attempts*", "*/*attempts*", "*/*/*attempts*"):
            for p in r.glob(pat):
                if p.is_dir():
                    out.append(p)
    return sorted(set(out))


def scan(roots: List[Path], now: float | None = None) -> List[Dict]:
    """返回死结清单（每条含 path/group/age_hours）。"""
    now = now if now is not None else time.time()
    found: List[Dict] = []
    for d in discover_marker_dirs(roots):
        for f in sorted(d.glob("*.json")):
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not looks_like_marker(obj) or is_evidence_sidecar(f, obj):
                continue
            if not is_deadlock(obj):
                continue
            try:
                age_h = round((now - f.stat().st_mtime) / 3600.0, 1)
            except OSError:
                age_h = -1.0
            found.append({
                "path": str(f),
                "group": str(obj.get("groupName") or ""),
                "payloadType": str(obj.get("payloadType") or ""),
                "state": obj.get("state"),
                "sendAttempts": obj.get("sendAttempts"),
                "age_hours": age_h,
            })
    return found


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="A2a attempted 死结体检（只读）")
    ap.add_argument("--root", action="append", default=None,
                    help="额外扫描根（默认 state/ 与 .local/state/）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    roots = [Path(p) if Path(p).is_absolute() else ROOT / p
             for p in (args.root or ["state", ".local/state"])]
    found = scan(roots)

    print("attempt-deadlock-scan: roots=%s n=%d" % (",".join(str(r) for r in roots), len(found)))
    for it in found:
        print("  [DEADLOCK] %s" % it["path"])
        print("      group=%s type=%s state=%s attempts=%s age=%sh"
              % (it["group"][:30], it["payloadType"], it["state"], it["sendAttempts"], it["age_hours"]))
    if found:
        print("  建议：先跑 `python runtime/conclude_attempt_deadlock.py --scan` 做**只读读回取证**"
              "（会给出逐例唯一授权串与 --apply 命令）；")
        print("        A2b-② 会在 `--apply --authorize <token>` 下把 marker 结论化为 verified"
              "（等价人工方案 A，但证据由机器采集）。")
        print("        **不要盲目重发、不要手工删 marker**；读不到证据就只报告。")
        print("attempt-deadlock-scan: FOUND %d" % len(found))
        return 1
    print("attempt-deadlock-scan: CLEAN")
    return 0


# ---------------------------------------------------------------- hermetic 自测

def _selftest() -> int:
    ok = True

    def chk(name, cond):
        nonlocal ok
        print("  [%s] %s" % ("OK" if cond else "FAIL", name))
        ok = ok and cond

    with tempfile.TemporaryDirectory() as td:
        root = Path(td) / "state"
        d = root / "flow.send-attempts"
        d.mkdir(parents=True)

        # 正例：真死结（attempted + 无收据）
        (d / "aaa.json").write_text(json.dumps({
            "bridgeVersion": 1, "state": "attempted", "sendAttempts": None,
            "groupName": "G", "payloadType": "file"}), encoding="utf-8")
        # 负例1：已 verified
        (d / "bbb.json").write_text(json.dumps({
            "bridgeVersion": 1, "state": "verified", "sendAttempts": 1, "groupName": "G"}),
            encoding="utf-8")
        # 负例2：attempted 但已有收据（sendAttempts>0）⇒ 可 reconcile，不是死结
        (d / "ccc.json").write_text(json.dumps({
            "bridgeVersion": 1, "state": "attempted", "sendAttempts": 2, "groupName": "G"}),
            encoding="utf-8")
        # 负例3：blocked 且零尝试（安全出口）
        (d / "ddd.json").write_text(json.dumps({
            "bridgeVersion": 1, "state": "blocked", "sendAttempts": 0, "groupName": "G"}),
            encoding="utf-8")
        # 负例4：证据旁文件（文件名含 evidence）⇒ 不算死结
        (d / "eee.unknown-evidence-20260910-2219.json").write_text(json.dumps({
            "bridgeVersion": 1, "state": "attempted", "sendAttempts": 0, "groupName": "G"}),
            encoding="utf-8")
        # 负例5：非 marker 形状
        (d / "fff.json").write_text(json.dumps({"hello": "world"}), encoding="utf-8")

        res = scan([root])
        paths = [Path(r["path"]).name for r in res]
        chk("只扫出真死结（其余 5 个负例全排除）", paths == ["aaa.json"])
        chk("字段解析正确", res and res[0]["state"] == "attempted" and res[0]["sendAttempts"] is None)

        # 负例6：空目录 ⇒ 干净
        empty = Path(td) / "emptystate"
        (empty / "x.send-attempts").mkdir(parents=True)
        chk("空目录 ⇒ CLEAN", scan([empty]) == [])

    print("attempt-deadlock-scan-selftest: %s" % ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
