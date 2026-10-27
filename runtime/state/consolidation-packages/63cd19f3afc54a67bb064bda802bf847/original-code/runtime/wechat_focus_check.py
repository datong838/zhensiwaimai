#!/usr/bin/env python3
"""Bring WeChat to the foreground with the strong activation, then verify.

The skills call a monkey-patched fast `activate_wechat` that activates with
`NSApplicationActivateIgnoringOtherApps` only, raises the window and sleeps
0.3s without re-verifying.  The shared original instead asks for
`NSApplicationActivateAllWindows | NSApplicationActivateIgnoringOtherApps` and
polls `wechat_window_unobstructed() and wechat_menu_bar_frontmost()` for up to
4s, raising `wechat-window-obstructed` when we really are covered.

This helper runs the strong variant and reports the before/after state so a
desktop run can start from a verified foreground instead of a hopeful one.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

SHARED = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/legacy-app-controler/"
              "wechat-desktop-control/scripts")


def state(wd) -> dict:
    out = {}
    for key, reader in (("windowId", wd.wechat_window_id),
                        ("unobstructed", wd.wechat_window_unobstructed),
                        ("menuBarFrontmost", wd.wechat_menu_bar_frontmost),
                        ("frontmostApp", wd.wechat_frontmost)):
        try:
            out[key] = reader()
        except Exception as error:  # noqa: BLE001
            out[key] = "ERR:" + repr(error)
    return out


def main() -> int:
    if str(SHARED) not in sys.path:
        sys.path.insert(0, str(SHARED))
    import wechat_desktop as wd

    record = {"before": state(wd)}
    started = time.monotonic()
    try:
        wd.activate_wechat()
        record["activateError"] = None
    except Exception as error:  # noqa: BLE001
        record["activateError"] = repr(error)
    record["activateMs"] = round((time.monotonic() - started) * 1000)
    record["after"] = state(wd)
    print(json.dumps(record, ensure_ascii=False))
    return 0 if record["activateError"] is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
