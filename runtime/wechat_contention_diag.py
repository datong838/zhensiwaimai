#!/usr/bin/env python3
"""Separate the possible causes of `wechat-search-region-contended`.

`wechat_desktop.screenshot_search_region()` refuses to capture when ANY of
three conditions is false:

  1. `wechat_window_id()` returns nothing,
  2. `wechat_window_unobstructed()` is false (a foreign window covers it), or
  3. `wechat_menu_bar_frontmost()` is false (WeChat does not own the Space).

Skill receipts only ever report the merged string, so the care agent cannot
tell a real obstruction from a failed Space switch.

Crucially the skill path does NOT call the shared `wechat_desktop.activate_wechat`
(which polls up to 4s).  `DesktopAdapter.__init__` monkey-patches it with the
fast `desktop_input.activate_wechat`, which activates with
`NSApplicationActivateIgnoringOtherApps` **only** (no
`NSApplicationActivateAllWindows`), raises the window, sleeps 0.3s and never
re-verifies.  This probe exercises that *patched* entry point — the one every
skill actually calls — then samples for 3s.

Interpretation:
  * contended -> unaffected within ~1s (menu bar)  = timing race: a bounded
    re-verify wait is the correct fix.
  * contended -> unaffected for the whole 3s with a named foreign `blockers`
    entry = a real obstruction; waiting can never help.
  * contended -> unaffected for the whole 3s with no blockers = the fast
    activation itself fails to switch the Space (missing AllWindows).

Strictly read-only apart from raising the WeChat window.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SHARED = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/legacy-app-controler/"
              "wechat-desktop-control/scripts")
MESSAGING = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/"
                 "skills/wechat-messaging/scripts")


def blockers(bounds) -> list:
    """Foreign on-screen windows overlapping the WeChat rectangle, front-to-back."""
    import Quartz

    left, top, width, height = bounds
    out = []
    try:
        info = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
    except Exception as error:  # noqa: BLE001
        return [{"error": repr(error)}]
    for entry in info:
        try:
            if entry.get("kCGWindowOwnerName") == "微信":
                continue
            if float(entry.get("kCGWindowAlpha", 1.0)) <= 0.01:
                continue
            if int(entry.get("kCGWindowLayer", 0)) != 0:
                continue
            box = entry.get("kCGWindowBounds", {})
            x, y = float(box.get("X", 0)), float(box.get("Y", 0))
            w, h = float(box.get("Width", 0)), float(box.get("Height", 0))
        except (TypeError, ValueError):
            continue
        if w <= 0 or h <= 0:
            continue
        if x < left + width and y < top + height and x + w > left and y + h > top:
            out.append({"owner": entry.get("kCGWindowOwnerName"),
                        "title": entry.get("kCGWindowName"),
                        "bounds": [x, y, w, h]})
    return out


def sample(wd) -> dict:
    row: dict = {}
    for key, reader in (("windowId", wd.wechat_window_id),
                        ("unobstructed", wd.wechat_window_unobstructed),
                        ("menuBarFrontmost", wd.wechat_menu_bar_frontmost),
                        ("frontmostApp", wd.wechat_frontmost)):
        try:
            row[key] = reader()
        except Exception as error:  # noqa: BLE001
            row[key] = "ERR:" + repr(error)
    try:
        row["blockers"] = blockers(wd.window_bounds())
    except Exception as error:  # noqa: BLE001
        row["blockers"] = ["ERR:" + repr(error)]
    row["contended"] = not (row.get("windowId")
                            and row.get("unobstructed") is True
                            and row.get("menuBarFrontmost") is True)
    return row


def pump(wd, seconds: float, step: float = 0.25) -> list:
    rows, deadline, started = [], time.monotonic() + seconds, time.monotonic()
    while time.monotonic() < deadline:
        row = sample(wd)
        row["ms"] = round((time.monotonic() - started) * 1000)
        rows.append(row)
        time.sleep(step)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=3.0)
    args = parser.parse_args()
    for path in (str(MESSAGING), str(SHARED)):
        if path not in sys.path:
            sys.path.insert(0, path)

    record: dict = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "python": sys.version.split()[0]}
    try:
        import desktop_adapter
        import wechat_desktop
        wd = desktop_adapter.DesktopAdapter().wd
    except Exception as error:  # noqa: BLE001
        record["loadError"] = repr(error)
        print(json.dumps(record, ensure_ascii=False, indent=1))
        return 0

    # Proof we are measuring the patched entry point, not the shared original.
    record["activateSource"] = getattr(wechat_desktop.activate_wechat,
                                       "__module__", "?")
    record["baseline"] = pump(wd, 0.75)
    started = time.monotonic()
    try:
        wd.activate_wechat()
        record["activateError"] = None
    except Exception as error:  # noqa: BLE001
        record["activateError"] = repr(error)
    record["activateMs"] = round((time.monotonic() - started) * 1000)
    record["afterActivate"] = pump(wd, args.seconds)
    record["recoveredMs"] = next(
        (row["ms"] for row in record["afterActivate"] if not row["contended"]), None)
    print(json.dumps(record, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
