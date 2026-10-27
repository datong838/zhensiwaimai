#!/usr/bin/env python3
"""只读盘点实体手机微信缓存中的 MP4 候选，不判断、不发布、不覆盖原文件。"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def adb(serial: str, *args: str, binary: bool = False) -> str | bytes:
    p = subprocess.run(["adb", "-s", serial, *args], text=not binary,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if p.returncode:
        raise RuntimeError(f"adb failed ({p.returncode}): {p.stderr.strip()}")
    return p.stdout


def probe_duration(path: Path) -> float | None:
    data = path.read_bytes()
    def walk(start: int, end: int) -> float | None:
        pos = start
        while pos + 8 <= end:
            size = int.from_bytes(data[pos:pos + 4], "big")
            typ = data[pos + 4:pos + 8]
            if size == 0:
                size = end - pos
            header = 16 if size == 1 else 8
            if size < header or pos + size > end:
                return None
            if typ == b"mvhd":
                body = pos + header
                version = data[body]
                if version == 0 and body + 20 <= len(data):
                    timescale = int.from_bytes(data[body + 12:body + 16], "big")
                    duration = int.from_bytes(data[body + 16:body + 20], "big")
                elif version == 1 and body + 32 <= len(data):
                    timescale = int.from_bytes(data[body + 20:body + 24], "big")
                    duration = int.from_bytes(data[body + 24:body + 32], "big")
                else:
                    return None
                return round(duration / timescale, 3) if timescale else None
            if typ in (b"moov", b"trak", b"mdia", b"minf", b"stbl"):
                found = walk(pos + header, pos + size)
                if found is not None:
                    return found
            pos += size
        return None
    return walk(0, len(data))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(serial: str, root: str, run_dir: Path) -> dict:
    raw = adb(serial, "shell", "find", root, "-type", "f")
    paths = [x.strip() for x in raw.splitlines() if x.strip()]
    items = []
    scratch = run_dir / "cache-probe"
    scratch.mkdir(parents=True, exist_ok=True)
    for remote in paths:
        # 只读取头部判断 MP4，不把整机缓存复制下来。
        head = adb(serial, "exec-out", "dd", f"if={remote}", "bs=1", "count=16", binary=True)
        if b"ftyp" not in head:
            continue
        item = {"remote": remote, "signature": head[:16].hex(), "candidate": True}
        # 仅拉取 MP4 签名文件到本轮临时盘点目录，绝不写回手机。
        local = scratch / (hashlib.sha256(remote.encode()).hexdigest()[:16] + ".mp4")
        p = subprocess.run(["adb", "-s", serial, "pull", remote, str(local)],
                           text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
        if p.returncode:
            item["pullError"] = p.stderr.strip() or p.stdout.strip()
        else:
            item.update({"localProbe": str(local), "bytes": local.stat().st_size,
                         "sha256": sha256(local), "durationSeconds": probe_duration(local)})
        items.append(item)
    return {"serial": serial, "root": root, "createdAt": datetime.now(timezone.utc).isoformat(),
            "runtimeModelDecisions": 0, "items": items}


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--serial", required=True)
    p.add_argument("--run-dir", required=True)
    p.add_argument("--root", default="/sdcard/Android/data/com.tencent.mm")
    args = p.parse_args()
    run_dir = Path(args.run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    result = inventory(args.serial, args.root, run_dir)
    out = run_dir / "cache-inventory.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"ok": True, "inventory": str(out), "count": len(result["items"])}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
