#!/usr/bin/env python3
"""WeChat foreground evidence probe for the care agent.

The shared desktop locator refuses a composited region capture with
`wechat-search-region-contended` when any of three things is true:

  1. the exact WeChat main window cannot be identified (`wechat_window_id()`),
  2. another window overlaps it (`wechat_window_unobstructed()`), or
  3. WeChat does not own the menu bar of the active Space
     (`wechat_menu_bar_frontmost()`).

Skill receipts only ever say "contended", so the care agent cannot tell which
condition failed or why.  Observed live: 12 consecutive attempts each failing
in ~600ms, i.e. the fast `activate_wechat()` returns and the very next strict
check fails deterministically.

This probe records, once per skill invocation, the three conditions plus the
raw menu-bar OCR text — both BEFORE and AFTER calling the same
`activate_wechat()` every skill calls.  The before/after pair separates
"activation does not work from this context" from "something steals the
foreground back immediately", which no existing artifact can distinguish.

`--read-only` skips the activation step.  Output is appended as JSONL and is
never allowed to raise into a skill run.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SHARED = Path(
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/"
    "wechat-desktop-control/scripts"
)
DEFAULT_OUT = Path(__file__).resolve().parent / "state" / "wechat_foreground_probe.jsonl"


def menu_bar_evidence() -> dict:
    """OCR the menu-bar strip the locator uses as its frontmost proof."""
    import AppKit

    screen = AppKit.NSScreen.mainScreen()
    width = int(screen.frame().size.width) if screen is not None else 1312
    with tempfile.TemporaryDirectory() as directory:
        image = Path(directory) / "menubar.png"
        capture = subprocess.run(
            ["/usr/sbin/screencapture", "-x", "-R0,0,%d,30" % width, str(image)],
            capture_output=True, text=True,
        )
        if capture.returncode or not image.exists():
            return {"captureReturncode": capture.returncode,
                    "captureError": (capture.stderr or "").strip()[:200],
                    "text": None}
        ocr = subprocess.run(
            [str(SHARED / "ocr_vision_bin"), str(image)],
            capture_output=True, text=True,
        )
        return {"captureReturncode": 0,
                "imageBytes": image.stat().st_size,
                "ocrReturncode": ocr.returncode,
                "text": (ocr.stdout or "").strip()[:400],
                "ocrError": (ocr.stderr or "").strip()[:200]}


def snapshot(wd) -> dict:
    """Read-only readings the locator's contention check is built from."""
    out: dict = {}
    for key, reader in (("windowId", wd.wechat_window_id),
                        ("bounds", wd.window_bounds),
                        ("unobstructed", wd.wechat_window_unobstructed),
                        ("menuBarFrontmost", wd.wechat_menu_bar_frontmost),
                        ("frontmostApp", wd.wechat_frontmost)):
        try:
            out[key] = reader()
        except Exception as error:  # noqa: BLE001
            out[key] = "ERR:" + repr(error)
    try:
        out["menuBar"] = menu_bar_evidence()
    except Exception as error:  # noqa: BLE001
        out["menuBar"] = "ERR:" + repr(error)
    try:
        out["pixels"] = pixel_identity(out.get("bounds"))
    except Exception as error:  # noqa: BLE001
        out["pixels"] = "ERR:" + repr(error)
    out["contended"] = not (out.get("windowId")
                            and out.get("unobstructed") is True
                            and out.get("menuBarFrontmost") is True)
    return out


# Positive evidence must be **WeChat-exclusive**.  A hit on a generic word such
# as "搜索" or "聊天" is worthless because most apps draw one -- WorkBuddy's own
# sidebar and Chrome both render "搜索", which produced a false `verified` while
# bringing this up.  Keep only strings no other app on this host draws, and pair
# them with the foreign-draw check below.
WECHAT_MARKERS = ("通讯录", "文件传输助手", "订阅号", "服务通知", "微信团队",
                  "折叠的群聊", "搜一搜", "看一看", "视频号", "朋友圈")
# 注意不要收裸「微信」：本项目的 Chrome 标签页里就有「微信小店 / 微信支付」，
# 一点就会让别的应用蒙混过关（实测踩过一次）。

# Any of these proves the rectangle is showing somebody else's UI.  Observed
# live: the Meituan merchant console and WorkBuddy's own frame both sit inside
# the WeChat window rectangle and win the compositor.
FOREIGN_MARKERS = ("美团", "商家", "订单", "商品", "顾客", "财务", "经营",
                   "WorkBuddy", "新聊天", "资料库", "自动化", "专家", "助理")


def pixel_identity(bounds) -> dict:
    """Capture the exact window rectangle and look for WeChat-only UI markers.

    `wechat_menu_bar_frontmost()` only proves which app is ACTIVE: the menu bar
    belongs to the active app even when its window sits on another Space and is
    nowhere on screen.  `wechat_window_unobstructed()` can likewise disagree
    with the compositor.  Both being true therefore does NOT mean the rectangle
    contains WeChat, and the locator will happily OCR whatever else is there
    and then report a downstream `search-control-count:0`.  Reading the pixels
    is the only way to tell those two situations apart.
    """
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        return {"captured": False, "error": "bounds-unavailable"}
    left, top, width, height = (int(value) for value in bounds)
    if width <= 0 or height <= 0:
        return {"captured": False, "error": "bounds-invalid"}
    region = "%d,%d,%d,%d" % (left, top, width, height)
    with tempfile.TemporaryDirectory() as directory:
        shot = Path(directory) / "region.png"
        capture = subprocess.run(
            ["/usr/sbin/screencapture", "-x", "-R" + region, str(shot)],
            capture_output=True, text=True)
        if capture.returncode or not shot.exists():
            return {"captured": False, "region": region,
                    "error": (capture.stderr or "").strip()[:200]}
        ocr = subprocess.run([str(SHARED / "ocr_vision_bin"), str(shot)],
                             capture_output=True, text=True)
    text = " ".join((ocr.stdout or "").split())
    hits = [marker for marker in WECHAT_MARKERS if marker in text]
    strangers = [marker for marker in FOREIGN_MARKERS if marker in text]
    # A foreign draw means the rectangle is NOT showing WeChat, however many
    # WeChat-shaped words happen to be in there.
    return {"captured": True, "region": region, "hits": hits,
            "foreignHits": strangers,
            "verified": bool(hits) and not strangers, "textPreview": text[:200]}


def diagnose(row: dict) -> tuple:
    """Name the ONE condition the locator collapses into "contended".

    The locator raises a single `wechat-search-region-contended` for a missing
    window id, a foreign overlap AND a failed menu-bar capture, so a receipt
    cannot distinguish them.  The most important distinction is that a failing
    `screencapture` is not contention at all: no amount of waiting or retrying
    can clear it, and the real cause is that this process tree holds no Screen
    Recording grant (proved by A/B: the same interpreter spawned from an
    interactive shell captures fine).  Retrying it starves the daemon cycle.
    """
    menubar = row.get("menuBar")
    if isinstance(menubar, dict) and menubar.get("captureReturncode"):
        return True, ("screen-recording-unavailable: screencapture rc=%s (%s) — "
                      "this process tree has no Screen Recording grant, so every "
                      "desktop skill reports contended; grant it before retrying"
                      % (menubar.get("captureReturncode"),
                         menubar.get("captureError")))
    if not row.get("windowId"):
        return False, "wechat-window-id-unavailable (window names need Screen Recording)"
    if row.get("unobstructed") is not True:
        owners = [b.get("owner") for b in (row.get("blockers") or []) if isinstance(b, dict)]
        return False, "foreign-window-overlap: " + (", ".join(str(o) for o in owners) or "unknown")
    if row.get("menuBarFrontmost") is not True:
        return False, "wechat-does-not-own-menubar"
    pixels = row.get("pixels")
    if isinstance(pixels, dict) and pixels.get("captured") and not pixels.get("verified"):
        return False, ("wechat-window-not-on-this-space: every API check says "
                       "frontmost+unobstructed, but the window rectangle holds no "
                       "WeChat-only UI marker (foreign draw: %s) — it captured another "
                       "app's pixels, so OCR finds no search box: %s"
                       % (", ".join(pixels.get("foreignHits") or []) or "none",
                          pixels.get("textPreview")))
    return False, "ok"


def probe(skill: str | None = None, *, activate: bool = True) -> dict:
    if str(SHARED) not in sys.path:
        sys.path.insert(0, str(SHARED))
    record: dict = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "skill": skill,
                    "python": sys.version.split()[0],
                    "activated": bool(activate)}
    try:
        import wechat_desktop as wd
    except Exception as error:  # noqa: BLE001
        record["loadError"] = repr(error)
        return record
    record["before"] = snapshot(wd)
    if activate:
        started = time.monotonic()
        try:
            wd.activate_wechat()
            record["activateError"] = None
        except Exception as error:  # noqa: BLE001
            record["activateError"] = repr(error)
        record["activateMs"] = round((time.monotonic() - started) * 1000)
        time.sleep(0.5)
        record["after"] = snapshot(wd)
    # Top-level fields keep the first-cycle schema readable for the care agent.
    record.update({k: v for k, v in record["before"].items()})
    if "after" in record:
        record["contendedAfterActivate"] = record["after"]["contended"]
    record["captureUnavailable"], record["diagnosis"] = diagnose(record["before"])
    return record


def append(record: dict, out: Path = DEFAULT_OUT) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("skill", nargs="?")
    parser.add_argument("--read-only", action="store_true",
                        help="skip the activate_wechat() step")
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args()
    try:
        record = probe(args.skill, activate=not args.read_only)
    except Exception as error:  # noqa: BLE001
        record = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                  "skill": args.skill, "probeError": repr(error)}
    try:
        append(record, Path(args.out))
    except Exception:  # noqa: BLE001
        pass
    print(json.dumps(record, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
