#!/usr/bin/env python3
"""selftest.py — 跑 browser_precise_ops 全部子模块自检（离线、纯 stdlib）。

用法：python shared/browser_precise_ops/selftest.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import content_guard  # noqa: E402
import pacing  # noqa: E402
import status_protocol  # noqa: E402
import verify  # noqa: E402


def main() -> int:
    results = {}
    for mod in (status_protocol, verify, pacing, content_guard):
        try:
            results[mod.__name__] = mod.self_test()
        except Exception as e:  # noqa: BLE001
            results[mod.__name__] = {"ok": False, "error": repr(e)}
    ok = all(r.get("ok") for r in results.values())
    print(json.dumps({"ok": ok, "modules": results}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
