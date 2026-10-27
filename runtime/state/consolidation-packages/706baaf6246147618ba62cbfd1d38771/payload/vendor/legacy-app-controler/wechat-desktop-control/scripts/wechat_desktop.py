#!/usr/bin/env python3
"""Mac 桌面微信控制：探测、打开群聊、定位并尝试下载最新视频。"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL_ROOT / "scripts"
ARTIFACTS = SKILL_ROOT / "artifacts"
WECHAT_BUNDLE = "com.tencent.xinWeChat"
WECHAT_CONTAINER = Path.home() / "Library/Containers/com.tencent.xinWeChat/Data"
VIDEO_CACHE = WECHAT_CONTAINER / "Documents/xwechat_files"
CONTROL_PYTHON = "/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python"
WECHAT_WINDOW_MAX_WIDTH = 1000
WECHAT_WINDOW_MAX_HEIGHT = 700
WECHAT_WINDOW_MIN_WIDTH = 900
WECHAT_WINDOW_MIN_HEIGHT = 560
WECHAT_WINDOW_MARGIN = 24
WECHAT_WINDOW_READBACK_TIMEOUT_SECONDS = 2.0
WECHAT_WINDOW_READBACK_POLL_SECONDS = 0.1


@dataclass
class OcrHit:
    cx: float
    cy: float
    w: float
    h: float
    confidence: float
    text: str


@dataclass
class Receipt:
    ok: bool
    action: str
    group: str | None = None
    header: str | None = None
    video_text: str | None = None
    output_path: str | None = None
    thumb_path: str | None = None
    note: str | None = None
    artifacts: list[str] | None = None


def run(cmd: list[str], *, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def run_preflight_control(cmd: list[str], *, timeout_code: str) -> subprocess.CompletedProcess[str]:
    """Bound a preflight helper process and retain the failed control stage."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(timeout_code) from error


def set_ax_messaging_timeout(ax, element, timeout_seconds: float = 5.0) -> None:
    """Prevent a wedged WeChat AX endpoint from blocking the desktop owner."""
    try:
        result = ax.AXUIElementSetMessagingTimeout(element, timeout_seconds)
    except Exception as error:
        raise RuntimeError("wechat-ax-timeout-configuration-failed") from error
    if result != ax.kAXErrorSuccess:
        raise RuntimeError("wechat-ax-timeout-configuration-failed")


def osascript(script: str) -> str:
    proc = run(["osascript", "-e", script])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def bounded_window_geometry(frame, visible) -> tuple[int, int, int, int]:
    """Return a usable, non-maximized WeChat window rectangle for this screen."""
    width = int(min(WECHAT_WINDOW_MAX_WIDTH, visible.size.width - 2 * WECHAT_WINDOW_MARGIN))
    height = int(min(WECHAT_WINDOW_MAX_HEIGHT, visible.size.height - 2 * WECHAT_WINDOW_MARGIN))
    if width < WECHAT_WINDOW_MIN_WIDTH or height < WECHAT_WINDOW_MIN_HEIGHT:
        raise RuntimeError("wechat-visible-screen-too-small")
    left = int(visible.origin.x + WECHAT_WINDOW_MARGIN)
    top = int(frame.size.height - visible.origin.y - visible.size.height + WECHAT_WINDOW_MARGIN)
    return left, top, width, height


def window_geometry_script(position: tuple[int, int], size: tuple[int, int]) -> str:
    """Set only the unique WeChat main window and return errors to the caller."""
    left, top = position
    width, height = size
    return f'''tell application "WeChat" to activate
delay 0.2
tell application "System Events" to tell process "WeChat"
set namedMains to {{}}
repeat with candidate in windows
set candidateWindow to contents of candidate
if (name of candidateWindow as text) is "微信" then set end of namedMains to candidateWindow
end repeat
if (count of namedMains) is not 1 then error "wechat-main-window-count-not-one"
set w to item 1 of namedMains
set position of w to {{{left}, {top}}}
set size of w to {{{width}, {height}}}
return "resize-requested"
end tell'''


def verify_window_size_readback(actual: tuple[int, int], expected: tuple[int, int]) -> None:
    if actual != expected:
        raise RuntimeError("wechat-main-window-size-readback-mismatch")


def wait_for_window_size_readback(read_size, expected: tuple[int, int], *,
                                  timeout_seconds: float = WECHAT_WINDOW_READBACK_TIMEOUT_SECONDS,
                                  poll_interval: float = WECHAT_WINDOW_READBACK_POLL_SECONDS) -> None:
    """Wait briefly for macOS/WeChat AX geometry to reflect the single resize request."""
    deadline = time.monotonic() + timeout_seconds
    actual = read_size()
    while actual != expected and time.monotonic() < deadline:
        time.sleep(min(poll_interval, max(0.0, deadline - time.monotonic())))
        actual = read_size()
    verify_window_size_readback(actual, expected)


def unique_wechat_application(applications):
    matches = [app for app in applications
               if app.bundleIdentifier() == WECHAT_BUNDLE]
    if len(matches) != 1:
        raise RuntimeError("wechat-process-count-not-one")
    if matches[0].isTerminated():
        raise RuntimeError("wechat-process-identity-mismatch")
    return matches[0]


# ---------------------------------------------------------------------------
# Accessibility (AX) helpers.
#
# The osascript / "System Events" route requires the macOS Automation
# (AppleEvents) TCC permission, which is NOT granted to every launch context
# (an unattended daemon or an embedded agent shell is denied with -10004).
# Accessibility (AX C API) and Screen Recording are granted independently and
# are already available in those contexts, so geometry, activation, focused
# text and the clipboard are all read/written through them instead.
# ---------------------------------------------------------------------------
def wechat_ax_application(ax):
    """AXUIElement for the unique running WeChat app."""
    import AppKit
    return ax.AXUIElementCreateApplication(
        unique_wechat_application(
            AppKit.NSWorkspace.sharedWorkspace().runningApplications()
        ).processIdentifier()
    )


def ax_attribute(ax, element, attribute, default=None):
    if element is None:
        return default
    set_ax_messaging_timeout(ax, element)
    error, value = ax.AXUIElementCopyAttributeValue(element, attribute, None)
    if error == getattr(ax, "kAXErrorCannotComplete", object()):
        raise RuntimeError("wechat-ax-read-timeout")
    return value if error == ax.kAXErrorSuccess else default


def ax_size(ax, element):
    raw = ax_attribute(ax, element, ax.kAXSizeAttribute)
    if raw is None:
        return None
    ok, value = ax.AXValueGetValue(raw, ax.kAXValueCGSizeType, None)
    return (float(value.width), float(value.height)) if ok else None


def ax_position(ax, element):
    raw = ax_attribute(ax, element, ax.kAXPositionAttribute)
    if raw is None:
        return None
    ok, value = ax.AXValueGetValue(raw, ax.kAXValueCGPointType, None)
    return (float(value.x), float(value.y)) if ok else None


def ax_windows(ax, app):
    windows = ax_attribute(ax, app, ax.kAXWindowsAttribute, []) or []
    for window in windows:
        set_ax_messaging_timeout(ax, window)
    return windows


def ax_main_window(ax, app):
    """The unique WeChat main window: title 微信 and size >= 700x500."""
    named = []
    for window in ax_windows(ax, app):
        title = ax_attribute(ax, window, ax.kAXTitleAttribute)
        size = ax_size(ax, window)
        if title == "微信" and size is not None:
            named.append((window, size))
    mains = [(window, size) for window, size in named
             if size[0] >= 700 and size[1] >= 500]
    if len(mains) != 1:
        raise RuntimeError("wechat-main-window-count-not-one")
    return mains[0]


def ax_descendants(ax, root, *, limit: int = 6000):
    stack, seen = [root], 0
    while stack and seen < limit:
        element = stack.pop()
        seen += 1
        yield element
        stack.extend(ax_attribute(ax, element, ax.kAXChildrenAttribute, []) or [])


def activate_wechat() -> None:
    ensure_window_size()
    import ApplicationServices as AX
    import AppKit

    process = unique_wechat_application(
        AppKit.NSWorkspace.sharedWorkspace().runningApplications())
    activation_options = (
        AppKit.NSApplicationActivateAllWindows
        | AppKit.NSApplicationActivateIgnoringOtherApps
    )
    process.activateWithOptions_(activation_options)
    app = wechat_ax_application(AX)
    set_ax_messaging_timeout(AX, app)
    windows = ax_windows(AX, app)
    main, main_size = ax_main_window(AX, app)
    if main_size[0] < 700 or main_size[1] < 500:
        raise RuntimeError("wechat-main-window-too-small")
    for window in windows:
        if window is main:
            continue
        title = ax_attribute(AX, window, AX.kAXTitleAttribute)
        if title in ("微信", "微信 (窗口)", "图片和视频"):
            continue
        size = ax_size(AX, window)
        if size is not None and (size[0] > 500 or size[1] > 400):
            raise RuntimeError("wechat-unexpected-secondary-window")
    try:
        AX.AXUIElementSetAttributeValue(main, "AXMinimized", False)
    except Exception:
        pass
    try:
        AX.AXUIElementSetAttributeValue(main, AX.kAXFocusedAttribute, True)
    except Exception:
        pass
    raise_error = AX.AXUIElementPerformAction(main, AX.kAXRaiseAction)
    if raise_error != AX.kAXErrorSuccess:
        raise RuntimeError("wechat-main-window-raise-failed")
    time.sleep(0.6)
    for attempt in range(8):
        if (wechat_frontmost() and wechat_window_unobstructed()
                and wechat_menu_bar_frontmost()):
            time.sleep(0.2)
            return
        if attempt == 0:
            switched = run_preflight_control(
                ["osascript", "-e", 'tell application id "com.tencent.xinWeChat" to activate'],
                timeout_code="wechat-application-activation-timeout")
            if switched.returncode != 0:
                raise RuntimeError("wechat-application-activation-failed")
        process.activateWithOptions_(activation_options)
        if AX.AXUIElementPerformAction(main, AX.kAXRaiseAction) != AX.kAXErrorSuccess:
            raise RuntimeError("wechat-main-window-raise-failed")
        time.sleep(0.5)
    raise RuntimeError("wechat-window-obstructed")


def wechat_menu_bar_frontmost() -> bool:
    """Pixel ground truth that WeChat owns the visible Space and menu bar.

    CGWindowList z-order and NSWorkspace.frontmostApplication can both report
    WeChat while the display still shows the previous Space: activating an app
    whose window lives on another Space takes ~1s to composite. The menu bar
    is composited per active Space, so OCRing the top strip proves the Space
    actually switched. Requires a non-auto-hidden menu bar (current setup:
    26pt top inset).
    """
    import tempfile
    import AppKit
    screen = AppKit.NSScreen.mainScreen()
    width = int(screen.frame().size.width) if screen is not None else 1312
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "menubar.png"
        proc = run(["screencapture", "-x", "-R0,0,%d,30" % width, str(path)])
        if proc.returncode or not path.exists():
            return False
        ocr = run([str(SCRIPTS / "ocr_vision_bin"), str(path)])
        return "微信" in (ocr.stdout or "")


def window_occlusion_decision(window_infos, target_window_id: int, target_pid: int,
                              target_bounds: tuple[float, float, float, float]) -> str:
    """Classify the exact WeChat window against front-to-back on-screen windows."""
    try:
        left, top, width, height = (float(value) for value in target_bounds)
        target_id = int(target_window_id)
        owner_pid = int(target_pid)
    except (TypeError, ValueError):
        return "target-window-geometry-invalid"
    if width < 900 or height < 560:
        return "target-window-geometry-invalid"

    matches = [index for index, info in enumerate(window_infos or [])
               if str(info.get("kCGWindowNumber")) == str(target_id)
               and str(info.get("kCGWindowOwnerPID")) == str(owner_pid)]
    if not matches:
        return "target-window-not-onscreen"
    if len(matches) != 1:
        return "target-window-identity-not-unique"
    target_index = matches[0]
    target = window_infos[target_index]
    if not wechat_window_info_matches(target, owner_pid):
        return "target-window-identity-mismatch"
    bounds = target.get("kCGWindowBounds", {})
    try:
        if any(abs(float(bounds.get(key, 0)) - expected) > 2 for key, expected in
               (("X", left), ("Y", top), ("Width", width), ("Height", height))):
            return "target-window-geometry-mismatch"
    except (TypeError, ValueError):
        return "target-window-geometry-invalid"

    # CGWindowListCopyWindowInfo(OnScreenOnly) is front-to-back. Only windows
    # before this exact target can cover its screen-region fallback.
    for info in window_infos[:target_index]:
        try:
            if int(info.get("kCGWindowOwnerPID", -1)) == owner_pid:
                continue  # WeChat's own search/popover windows are part of its UI.
            if float(info.get("kCGWindowAlpha", 1.0)) <= 0.01:
                continue
            if int(info.get("kCGWindowLayer", 0)) != 0:
                # Keep the established system-layer exemption: Dock/menu-bar
                # backdrops can report full-screen bounds without covering app content.
                continue
            other = info.get("kCGWindowBounds", {})
            if not all(key in other for key in ("X", "Y", "Width", "Height")):
                return "window-occlusion-evidence-invalid"
            x, y = float(other.get("X", 0)), float(other.get("Y", 0))
            w, h = float(other.get("Width", 0)), float(other.get("Height", 0))
        except (TypeError, ValueError):
            return "window-occlusion-evidence-invalid"
        if not all(math.isfinite(value) for value in (x, y, w, h)) or w < 0 or h < 0:
            return "window-occlusion-evidence-invalid"
        if w == 0 or h == 0:
            continue
        if x < left + width and y < top + height and x + w > left and y + h > top:
            return "foreign-window-overlap"
    return "unobstructed"


def wechat_window_unobstructed(expected_window_id: int | None = None) -> bool:
    """True only when the exact WeChat chat window has no overlapping window above it."""
    import AppKit
    import Quartz
    left, top, width, height = window_bounds()
    process = unique_wechat_application(
        AppKit.NSWorkspace.sharedWorkspace().runningApplications()
    )
    wechat_pid = int(process.processIdentifier())
    target_id = expected_window_id or wechat_window_id()
    if not target_id:
        return False
    window_list = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID) or []
    return window_occlusion_decision(
        window_list, target_id, wechat_pid, (left, top, width, height)
    ) == "unobstructed"


def wechat_running() -> bool:
    import AppKit
    apps = [a for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
            if a.bundleIdentifier() == WECHAT_BUNDLE]
    return len(apps) == 1 and not apps[0].isTerminated()


def screen_scale() -> float:
    import AppKit
    screen = AppKit.NSScreen.mainScreen()
    factor = float(screen.backingScaleFactor()) if screen is not None else 2.0
    return factor or 2.0


def to_points(x: float, y: float, scale: float) -> tuple[float, float]:
    if scale <= 1.0:
        return x, y
    return x / scale, y / scale


def click(x: float, y: float, *, activate: bool = True, scale: float | None = None) -> None:
    sc = scale or screen_scale()
    px, py = to_points(x, y, sc)
    bin_path = SCRIPTS / "cgevent_click_bin"
    if not bin_path.exists():
        raise FileNotFoundError(f"missing {bin_path}; run: swiftc -O -o cgevent_click_bin cgevent_click.swift")
    args = [str(bin_path)]
    if activate:
        args.append("--activate-wechat")
    args.extend([str(px), str(py)])
    proc = run(args)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())


def window_bounds() -> tuple[float, float, float, float]:
    """Unique borderless main-window rectangle via AX (no Automation prompt)."""
    import ApplicationServices as AX
    app = wechat_ax_application(AX)
    main, size = ax_main_window(AX, app)
    position = ax_position(AX, main)
    if position is None:
        raise RuntimeError("wechat-window-position-unavailable")
    return float(position[0]), float(position[1]), float(size[0]), float(size[1])


def click_local(x: float, y: float, *, activate: bool = True, scale: float | None = None) -> None:
    sc = scale or screen_scale(); left, top, _, _ = window_bounds()
    click(left + x / sc, top + y / sc, activate=activate, scale=1.0)


def wechat_window_info_matches(info: dict, process_id: int) -> bool:
    """Accept only a Quartz window owned by the unique WeChat process."""
    bounds = info.get("kCGWindowBounds", {})
    try:
        owner_pid = int(info.get("kCGWindowOwnerPID", -1))
        layer = int(info.get("kCGWindowLayer", -1))
        width = float(bounds.get("Width", 0))
        height = float(bounds.get("Height", 0))
    except (TypeError, ValueError):
        return False
    return (
        owner_pid == int(process_id)
        and info.get("kCGWindowOwnerName") in ("WeChat", "微信")
        and layer == 0
        and info.get("kCGWindowName") == "微信"
        and width >= 900
        and height >= 560
    )


def wechat_window_id() -> int | None:
    try:
        import AppKit
        import Quartz

        process = unique_wechat_application(
            AppKit.NSWorkspace.sharedWorkspace().runningApplications()
        )
        process_id = int(process.processIdentifier())
        options = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
        windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        matches = [window for window in windows
                   if wechat_window_info_matches(window, process_id)]
        if len(matches) != 1:
            return None
        return int(matches[0]["kCGWindowNumber"])
    except Exception:
        return None


def screenshot(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    activate_wechat()
    time.sleep(0.25)
    wid = wechat_window_id()
    if wid:
        proc = run(["screencapture", "-x", "-l", str(wid), str(path)])
    else:
        raise RuntimeError("wechat-window-capture-target-missing")
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or "screencapture failed")


def capture_image_stats(path: Path) -> dict:
    """Return geometry/content stats so a black placeholder cannot reach OCR."""
    script = r'''import json,sys
from PIL import Image,ImageStat
image=Image.open(sys.argv[1]).convert("RGB")
sample=image.copy();sample.thumbnail((64,64))
extrema=sample.getextrema();stddev=ImageStat.Stat(sample).stddev
variation=max((high-low) for low,high in extrema)
print(json.dumps({"width":image.width,"height":image.height,
 "variation":variation,"maxStddev":max(stddev)}))'''
    completed = run([CONTROL_PYTHON, "-c", script, str(path)])
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "capture-image-invalid")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("capture-image-stats-invalid") from error


def capture_image_valid(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        stats = capture_image_stats(path)
    except RuntimeError:
        return False
    return (
        stats.get("width", 0) >= 900
        and stats.get("height", 0) >= 560
        and stats.get("variation", 0) >= 8
        and stats.get("maxStddev", 0) >= 1
    )


def screenshot_main_region(path: Path) -> str:
    """Capture the unique main window and reject blank/obscured evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    wid = wechat_window_id()
    if not wid:
        raise RuntimeError("wechat-window-capture-target-missing")
    proc = run(["screencapture", "-x", "-o", "-l", str(wid), str(path)])
    if not proc.returncode and capture_image_valid(path):
        return "screencapture-window-id"
    # macOS can transiently refuse `screencapture -l` for an otherwise valid,
    # non-minimized window. Capture that same audited window id through Quartz;
    # unlike a screen-region fallback this never activates WeChat or captures a
    # foreground application that happens to cover it.
    script = r'''import json,sys
import AppKit,Quartz
wid=int(sys.argv[1]);out=sys.argv[2]
image=Quartz.CGWindowListCreateImage(
 Quartz.CGRectNull,Quartz.kCGWindowListOptionIncludingWindow,wid,
 Quartz.kCGWindowImageBoundsIgnoreFraming)
if image is None:raise RuntimeError("quartz-window-image-missing")
width=int(Quartz.CGImageGetWidth(image));height=int(Quartz.CGImageGetHeight(image))
if width<900 or height<560:raise RuntimeError("quartz-window-image-too-small")
bitmap=AppKit.NSBitmapImageRep.alloc().initWithCGImage_(image)
data=bitmap.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG,{})
if data is None or not data.writeToFile_atomically_(out,True):raise RuntimeError("quartz-window-png-write-failed")
print(json.dumps({"width":width,"height":height}))'''
    fallback = run([CONTROL_PYTHON, "-c", script, str(wid), str(path)])
    primary = proc.stderr.strip() or "screencapture-window-id-invalid"
    secondary = fallback.stderr.strip() or "quartz-window-capture-invalid"
    try:
        geometry = json.loads(fallback.stdout)
    except json.JSONDecodeError as error:
        geometry = {}
        secondary = "quartz-receipt-invalid"
    if (
        not fallback.returncode
        and geometry.get("width", 0) >= 900
        and geometry.get("height", 0) >= 560
        and capture_image_valid(path)
    ):
        return "quartz-window-id"

    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass

    # Final fallback: capture the exact main-window rectangle from the screen.
    # This WeChat build refuses per-window capture (`screencapture -l` errors,
    # Quartz returns a black frame) even with Screen Recording granted, so the
    # borderless window rectangle is the only sound evidence source. A region
    # capture is correct only while WeChat owns the foreground — otherwise
    # another app could cover the window and the evidence would be wrong — so
    # it is hard-gated on the foreground identity and still has to pass the
    # same blank/size checks.
    try:
        if not wechat_window_unobstructed(expected_window_id=wid) or not wechat_menu_bar_frontmost():
            activate_wechat()
        if wechat_window_unobstructed(expected_window_id=wid) and wechat_menu_bar_frontmost():
            left, top, width, height = window_bounds()
            region = f"{int(left)},{int(top)},{int(width)},{int(height)}"
            region_proc = run(["screencapture", "-x", "-R" + region, str(path)])
            if not region_proc.returncode and capture_image_valid(path):
                if (wechat_window_unobstructed(expected_window_id=wid)
                        and wechat_menu_bar_frontmost()):
                    return "screencapture-region-frontmost"
    except RuntimeError:
        pass
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    raise RuntimeError(f"wechat-window-capture-failed:{primary}:{secondary}")


def screenshot_search_region(path: Path) -> None:
    """Capture the composited main-window rectangle including search popovers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    activate_wechat()
    time.sleep(0.15)
    target_window_id = wechat_window_id()
    if (not target_window_id
            or not wechat_frontmost()
            or not wechat_window_unobstructed(expected_window_id=target_window_id)
            or not wechat_menu_bar_frontmost()):
        raise RuntimeError("wechat-search-region-contended")
    left, top, width, height = window_bounds()
    region = f"{int(left)},{int(top)},{int(width)},{int(height)}"
    proc = run(["screencapture", "-x", "-R" + region, str(path)])
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "wechat-search-region-capture-failed")
    if (not wechat_frontmost()
            or not wechat_window_unobstructed(expected_window_id=target_window_id)
            or not wechat_menu_bar_frontmost()):
        path.unlink(missing_ok=True)
        raise RuntimeError("wechat-search-region-contended")


def wechat_frontmost() -> bool:
    try:
        import AppKit
        app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    except Exception:
        return False
    return app is not None and app.bundleIdentifier() == WECHAT_BUNDLE


def wechat_ax_state() -> dict:
    """Read WeChat's main-window text geometry through Accessibility only."""
    script = r'''import json
import AppKit,ApplicationServices as AX
apps=[a for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
 if a.bundleIdentifier()=="com.tencent.xinWeChat"]
if len(apps)!=1:raise RuntimeError("wechat-process-count-not-one")
app=AX.AXUIElementCreateApplication(apps[0].processIdentifier())
def attr(element,name,default=None):
 AX.AXUIElementSetMessagingTimeout(element,5.0)
 error,value=AX.AXUIElementCopyAttributeValue(element,name,None)
 if error==getattr(AX,"kAXErrorCannotComplete",None):raise RuntimeError("wechat-ax-read-timeout")
 return value if error==0 else default
windows=attr(app,AX.kAXWindowsAttribute,[]) or []
def pair(value,kind):
 ok,result=AX.AXValueGetValue(value,kind,None)
 if not ok:return None
 return [float(result.x),float(result.y)] if kind==AX.kAXValueCGPointType else [float(result.width),float(result.height)]
main=[]
for candidate in windows:
 if attr(candidate,AX.kAXTitleAttribute,"")!="微信":continue
 candidate_size=pair(attr(candidate,AX.kAXSizeAttribute),AX.kAXValueCGSizeType)
 if candidate_size and candidate_size[0]>=700 and candidate_size[1]>=500:main.append(candidate)
if len(main)!=1:raise RuntimeError("wechat-main-window-count-not-one")
window=main[0]
position=pair(attr(window,AX.kAXPositionAttribute),AX.kAXValueCGPointType)
size=pair(attr(window,AX.kAXSizeAttribute),AX.kAXValueCGSizeType)
items=[];stack=[window];seen=0
while stack and seen<6000:
 element=stack.pop();seen+=1
 role=attr(element,AX.kAXRoleAttribute,"")
 # Header/session geometry must not materialize virtual message children:
 # doing so can move the chat viewport after a verified bubble screenshot.
 if role=="AXList" and attr(element,AX.kAXTitleAttribute,"")=="消息":continue
 if role=="AXStaticText":
  value=attr(element,AX.kAXValueAttribute,"") or attr(element,AX.kAXTitleAttribute,"")
  pos=pair(attr(element,AX.kAXPositionAttribute),AX.kAXValueCGPointType)
  dimensions=pair(attr(element,AX.kAXSizeAttribute),AX.kAXValueCGSizeType)
  if value and pos and dimensions:
   items.append({"text":str(value),"x":pos[0],"y":pos[1],"width":dimensions[0],"height":dimensions[1]})
 stack.extend(attr(element,AX.kAXChildrenAttribute,[]) or [])
print(json.dumps({"window":{"x":position[0],"y":position[1],"width":size[0],"height":size[1]},"texts":items},ensure_ascii=False))'''
    completed = run_preflight_control([CONTROL_PYTHON, "-c", script],
                                      timeout_code="wechat-ax-read-timeout")
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "wechat-ax-read-failed")
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("wechat-ax-receipt-invalid") from error


def open_group_exact_ax_visible(group_name: str) -> Receipt | None:
    """Open one exact visible chat-list row and verify its AX header."""
    state = wechat_ax_state()
    window = state["window"]
    texts = state.get("texts", [])

    def is_header(item: dict) -> bool:
        return (
            item["x"] > window["x"] + 280
            and item["y"] < window["y"] + 100
            and exact_group_text(item["text"], group_name)
        )

    def unique_headers(items: list[dict]) -> list[dict]:
        unique: dict[tuple[int, int, int], dict] = {}
        for item in items:
            key = (round(item["x"]), round(item["y"]), round(item["height"]))
            previous = unique.get(key)
            if previous is None or len(item["text"]) < len(previous["text"]):
                unique[key] = item
        return list(unique.values())

    headers = unique_headers([item for item in texts if is_header(item)])
    if len(headers) == 1:
        return Receipt(ok=True, action="open-group", group=group_name,
                       header=headers[0]["text"], note="ax-current-header")
    if len(headers) > 1:
        return Receipt(ok=False, action="open-group", group=group_name,
                       note="ax-exact-header-count:multiple")

    rows = []
    for item in texts:
        first_line = item["text"].splitlines()[0].strip()
        if (
            window["x"] + 50 <= item["x"] <= window["x"] + 330
            and 40 <= item["height"] <= 100
            and item["width"] >= 150
            and exact_group_text(first_line, group_name)
        ):
            rows.append(item)
    if not rows:
        return None
    if len(rows) > 1:
        return Receipt(ok=False, action="open-group", group=group_name,
                       note=f"ax-exact-row-count:{len(rows)}")

    # Activating the application alone can leave its chat window behind another
    # window. Raise the verified main window, then discard the old coordinates.
    activate_wechat()
    refreshed = wechat_ax_state()
    window = refreshed["window"]
    rows = [item for item in refreshed.get("texts", [])
            if window["x"] + 50 <= item["x"] <= window["x"] + 330
            and 40 <= item["height"] <= 100 and item["width"] >= 150
            and exact_group_text(item["text"].splitlines()[0].strip(), group_name)]
    if len(rows) != 1:
        return Receipt(ok=False, action="open-group", group=group_name,
                       note=f"ax-exact-row-count:{len(rows)}")
    row = rows[0]
    click(row["x"] + row["width"] / 2, row["y"] + row["height"] / 2,
          activate=True, scale=1.0)
    for _ in range(3):
        time.sleep(0.4)
        verified = wechat_ax_state()
        verified_window = verified["window"]
        verified_headers = unique_headers([
            item for item in verified.get("texts", [])
            if item["x"] > verified_window["x"] + 280
            and item["y"] < verified_window["y"] + 100
            and exact_group_text(item["text"], group_name)
        ])
        if len(verified_headers) == 1:
            return Receipt(ok=True, action="open-group", group=group_name,
                           header=verified_headers[0]["text"], note="ax-visible-exact-row")
    return Receipt(ok=False, action="open-group", group=group_name,
                   note="ax-exact-header-count:0")


def ocr(path: Path) -> list[OcrHit]:
    bin_path = SCRIPTS / "ocr_vision_bin"
    if not bin_path.exists():
        raise FileNotFoundError(f"missing {bin_path}")
    proc = run([str(bin_path), str(path)])
    hits: list[OcrHit] = []
    for line in proc.stdout.splitlines():
        if "\t" not in line:
            continue
        box, conf, text = line.split("\t", 2)
        cx_s, cy_s, w_s, h_s = box.split(",")
        hits.append(
            OcrHit(
                cx=float(cx_s),
                cy=float(cy_s),
                w=float(w_s),
                h=float(h_s),
                confidence=float(conf),
                text=text.strip(),
            )
        )
    return hits


def find_group_row(hits: list[OcrHit], group_name: str) -> OcrHit | None:
    key = group_name[:8]
    candidates = [
        h
        for h in hits
        if key in h.text and h.cx < 700 and ("置顶" in h.text or "视频" in h.text or "：" in h.text or len(h.text) < 40)
    ]
    if not candidates:
        candidates = [h for h in hits if key in h.text and h.cx < 700]
    if not candidates:
        return None
    return max(candidates, key=lambda h: h.cy)


def find_header(hits: list[OcrHit], group_name: str) -> OcrHit | None:
    key = group_name[:6]
    rows = [h for h in hits if key in h.text and h.cx > 850 and h.cy < 280]
    return rows[0] if rows else None


def normalize_group_text(value: str) -> str:
    return re.sub(r"A[lL]数字员工", "AI数字员工", re.sub(r"\s+", "", value.strip()))


def exact_group_text(value: str, expected: str) -> bool:
    value = normalize_group_text(value)
    expected = normalize_group_text(expected)
    if re.fullmatch(re.escape(expected) + r"(?:[（(]\d+[）)])?", value):
        return True
    # Money-bag glyphs are frequently OCR'd as ®/菌/⑧. Keep the stable
    # Chinese decorative phrase and member count exact while ignoring only
    # those bounded glyph slots.
    marker = "💰发财精英荟💰"
    if marker in expected:
        core = expected.split(marker, 1)[0]
        tail = value[len(core):] if value.startswith(core) else ""
        if tail:
            return bool(re.fullmatch(
                r"[^\u4e00-\u9fff]{0,3}发财精英荟[^\u4e00-\u9fff]{0,3}"
                r"(?:[（(]\d+[）)])?[^\u4e00-\u9fff]{0,3}", tail
            ))
    return False


def decorated_group_result_text(value: str, expected: str) -> bool:
    value = normalize_group_text(value)
    expected = normalize_group_text(expected)
    if not value.startswith(expected):
        return False
    suffix = value[len(expected):]
    return bool(re.fullmatch(r"(?:…+\.*|\.{3,})[QqO0④]?", suffix))


def find_exact_group_rows(hits: list[OcrHit], group_name: str) -> list[OcrHit]:
    # Current WeChat can place a real group suggestion above “聊天记录”, while
    # repeating the query under “搜索网络结果”. Use section boundaries rather
    # than a fixed y cutoff so the query echo cannot be clicked as a chat row.
    excluded_headings = [
        h for h in hits
        if h.cx < 700 and h.text.strip() in ("聊天记录", "搜索网络结果")
    ]

    def in_excluded_section(hit: OcrHit) -> bool:
        preceding = [heading for heading in excluded_headings if heading.cy < hit.cy]
        section_excluded = bool(preceding) and max(
            preceding, key=lambda heading: heading.cy
        ).text.strip() in (
            "聊天记录", "搜索网络结果"
        )
        # The populated search input is also echoed in the top band. Its
        # center is below the clipped top suggestion row in the calibrated
        # WeChat layout; keep only the <40px top suggestion before any section.
        query_echo = not preceding and 40 <= hit.cy < 120
        return section_excluded or query_echo

    exact = [
        h for h in hits
        if h.cx < 700 and exact_group_text(h.text, group_name)
        and not in_excluded_section(h)
    ]
    group_headings = [h for h in hits if h.cx < 700 and h.text.strip() in ("群聊", "最常使用")]
    history_headings = [h for h in hits if h.cx < 700 and h.text.strip() == "聊天记录"]
    decorated = []
    for heading in group_headings:
        stop = min((h.cy for h in history_headings if h.cy > heading.cy), default=float("inf"))
        decorated.extend(h for h in hits if h.cx < 700 and heading.cy < h.cy < stop
                         and decorated_group_result_text(h.text, group_name))
    unique = []
    for item in exact + decorated:
        if item not in unique:
            unique.append(item)
    return unique


def find_search_query_echoes(hits: list[OcrHit], group_name: str) -> list[OcrHit]:
    expected = normalize_group_text(group_name)
    return [
        h for h in hits
        if h.cx < 700 and h.cy < 120 and expected in normalize_group_text(h.text)
    ]


def find_unique_core_group_rows(hits: list[OcrHit], group_name: str, search_name: str) -> list[OcrHit]:
    if normalize_group_text(search_name) == normalize_group_text(group_name):
        return find_exact_group_rows(hits, group_name)
    expected = normalize_group_text(search_name)
    group_headings = [h for h in hits if h.cx < 700 and h.text.strip() in ("群聊", "最常使用")]
    history_headings = [h for h in hits if h.cx < 700 and h.text.strip() == "聊天记录"]
    candidates = []
    for heading in group_headings:
        stop = min((h.cy for h in history_headings if h.cy > heading.cy), default=float("inf"))
        candidates.extend(h for h in hits if h.cx < 700 and heading.cy < h.cy < stop
                          and core_group_result_text(h.text, search_name))
    unique = []
    for item in candidates:
        if not any(abs(item.cx-old.cx)<2 and abs(item.cy-old.cy)<2 for old in unique):
            unique.append(item)
    return unique


def core_group_result_text(value: str, expected: str) -> bool:
    value = normalize_group_text(value)
    expected = normalize_group_text(expected)
    # OCR may prepend a tiny avatar/icon fragment (for example ``1``) to the
    # first Chinese character. Ignore only up to three non-Chinese chars;
    # the opened chat header is still required to match the complete title.
    if expected and re.match(r"[\u4e00-\u9fff]", expected):
        value = re.sub(r"^[^\u4e00-\u9fff]{1,3}", "", value)
    if value.startswith(expected):
        return True
    truncated = re.match(r"^(.*?)(?:…+|⋯+|\.{3,})", value)
    if not truncated:
        return False
    prefix = truncated.group(1)
    return len(prefix) >= 12 and expected.startswith(prefix)


def ax_confirms_raw_group_header(group_name: str) -> bool:
    """Read only: preserve the real group identity when OCR changes a plus glyph."""
    state = wechat_ax_state()
    window = state["window"]
    pattern = re.escape(group_name) + r"(?:[（(]\d+[）)])?"
    positions = {
        (round(item["x"]), round(item["y"]), round(item["height"]))
        for item in state.get("texts", [])
        if item["x"] > window["x"] + 280
        and window["y"] <= item["y"] < window["y"] + 100
        and re.fullmatch(pattern, item["text"].strip())
    }
    return len(positions) == 1


def find_exact_headers(hits: list[OcrHit], group_name: str) -> list[OcrHit]:
    # The chat pane moves horizontally with the normalized WeChat window width.
    # Derive its left edge from the current OCR canvas instead of assuming the
    # old wide-window x>700 layout. The top-band requirement excludes matching
    # text in search results and message history.
    right_edge = max((h.cx + h.w / 2 for h in hits), default=0)
    content_left = max(300.0, right_edge * 0.27)
    top_hits = [
        h for h in hits
        if h.cx > content_left and h.cy < 120
    ]
    exact = [h for h in top_hits if exact_group_text(h.text, group_name)]
    if "+" not in group_name and "＋" not in group_name:
        return exact
    # Vision can merge the small icon after the member count into a single '>'.
    # Only that observed suffix is removed; AX must still prove the raw identity.
    visual = [h for h in top_hits if exact_group_text(
        re.sub(r"([（(]\d+[)）])\s*>\s*$", r"\1", h.text).replace("＋", "+"),
        group_name.replace("＋", "+"))]
    if visual == exact:
        return exact
    # Count all visual candidates before consulting AX; never collapse two titles.
    if len(visual) != 1:
        return visual
    return visual if ax_confirms_raw_group_header(group_name) else []


def find_search_controls(hits: list[OcrHit]) -> list[OcrHit]:
    controls = []
    for hit in hits:
        compact = re.sub(r"\s+", "", hit.text)
        prefix = compact[:-2] if compact.endswith("搜索") else ""
        if hit.cx < 700 and hit.cy < 220 and compact.endswith("搜索") and len(prefix) <= 2 and not re.search(r"[\u3400-\u9fff]", prefix):
            controls.append(hit)
    return controls


def chat_panel_visible(hits: list[OcrHit]) -> bool:
    markers = ("视频号", "时间海", "吃过", "鱼杂", "发送", "聊天记录")
    return any(any(m in h.text for m in markers) and h.cx > 750 for h in hits)


def find_latest_video(hits: list[OcrHit]) -> OcrHit | None:
    patterns = ("视频号", "[视频号]", "［视频号］", "[视频]", "［视频］")
    rows = [
        h
        for h in hits
        if any(p in h.text for p in patterns) and h.cx > 750 and "：" in h.text
    ]
    if rows:
        return max(rows, key=lambda h: h.cy)
    rows = [h for h in hits if any(p in h.text for p in patterns) and h.cx > 750]
    if rows:
        return max(rows, key=lambda h: h.cy)
    title = next(
        (
            h
            for h in hits
            if ("鱼杂" in h.text or "吃过" in h.text) and h.cx > 750 and h.cy > 400
        ),
        None,
    )
    if title:
        return title
    sender = [h for h in hits if h.text == "时间海" and h.cx > 750 and h.cy > 400]
    return sender[0] if sender else None


def login_blocked(hits: list[OcrHit]) -> bool:
    joined = "".join(hit.text for hit in hits)
    # “仅传输文件” is ordinary conversation text as well as a historical
    # file-transfer UI label.  OCR frames used for group search can include
    # the right-side conversation, so treating it as a login signal makes a
    # logged-in client fail closed before it can locate the target group.
    # Keep only text that explicitly requires a login/account action.
    return any(value in joined for value in ("请重新登录", "进入微信", "切换账号"))


def ensure_window_size() -> None:
    import ApplicationServices as AX
    import AppKit

    screen = AppKit.NSScreen.mainScreen()
    frame = screen.frame()
    visible = screen.visibleFrame()
    left, top, width, height = bounded_window_geometry(frame, visible)
    process = unique_wechat_application(
        AppKit.NSWorkspace.sharedWorkspace().runningApplications())
    app = AX.AXUIElementCreateApplication(process.processIdentifier())
    set_ax_messaging_timeout(AX, app)
    error, windows = AX.AXUIElementCopyAttributeValue(app, AX.kAXWindowsAttribute, None)
    if error != AX.kAXErrorSuccess:
        if error == getattr(AX, "kAXErrorCannotComplete", object()):
            raise RuntimeError("wechat-ax-read-timeout:window-list")
        raise RuntimeError("wechat-window-list-unavailable")
    for candidate in windows or []:
        set_ax_messaging_timeout(AX, candidate)
    named = [window for window in (windows or [])
             if AX.AXUIElementCopyAttributeValue(window, AX.kAXTitleAttribute, None)
             == (AX.kAXErrorSuccess, "微信")]
    if len(named) != 1:
        # Preserve an already usable unique main window without resizing it.
        usable = []
        for window in windows or []:
            title_error, title = AX.AXUIElementCopyAttributeValue(window, AX.kAXTitleAttribute, None)
            size_error, raw_size = AX.AXUIElementCopyAttributeValue(window, AX.kAXSizeAttribute, None)
            if title_error != AX.kAXErrorSuccess or title != "微信" or size_error != AX.kAXErrorSuccess:
                continue
            ok, current = AX.AXValueGetValue(raw_size, AX.kAXValueCGSizeType, None)
            if ok and current.width >= 700 and current.height >= 500:
                usable.append(window)
        if len(usable) == 1:
            return
        raise RuntimeError("wechat-main-window-count-not-one")
    window = named[0]
    size_error, raw_size = AX.AXUIElementCopyAttributeValue(window, AX.kAXSizeAttribute, None)
    if size_error != AX.kAXErrorSuccess or raw_size is None:
        raise RuntimeError("wechat-window-size-unavailable")
    ok, current = AX.AXValueGetValue(raw_size, AX.kAXValueCGSizeType, None)
    if not ok:
        raise RuntimeError("wechat-window-size-unavailable")
    if current.width >= 700 and current.height >= 500:
        return
    expected_size = (width, height)
    # Resize/position through AX (no Automation prompt). window_geometry_script
    # is retained above as the reference contract of the rectangle applied.
    from Quartz import CGPointMake, CGSizeMake
    position_value = AX.AXValueCreate(AX.kAXValueCGPointType,
                                      CGPointMake(float(left), float(top)))
    size_value = AX.AXValueCreate(AX.kAXValueCGSizeType,
                                  CGSizeMake(float(width), float(height)))
    position_error = AX.AXUIElementSetAttributeValue(
        window, AX.kAXPositionAttribute, position_value)
    size_error = AX.AXUIElementSetAttributeValue(
        window, AX.kAXSizeAttribute, size_value)
    if position_error != AX.kAXErrorSuccess or size_error != AX.kAXErrorSuccess:
        raise RuntimeError("wechat-main-window-size-update-failed")
    def read_window_size() -> tuple[int, int]:
        size_error, verified_size = AX.AXUIElementCopyAttributeValue(window, AX.kAXSizeAttribute, None)
        if size_error != AX.kAXErrorSuccess or verified_size is None:
            raise RuntimeError("wechat-window-size-readback-unavailable")
        ok, actual = AX.AXValueGetValue(verified_size, AX.kAXValueCGSizeType, None)
        if not ok:
            raise RuntimeError("wechat-window-size-readback-unavailable")
        return round(actual.width), round(actual.height)

    wait_for_window_size_readback(read_window_size, expected_size)


def search_and_open_group(group_name: str, hits: list[OcrHit], *, scale: float = 2.0) -> bool:
    search = next((h for h in hits if "搜索" in h.text and h.cx < 900), None)
    if not search:
        return False
    click_local(search.cx, search.cy, activate=True, scale=scale)
    time.sleep(0.3)
    set_clipboard_text(group_name)
    post_key("paste")
    time.sleep(1.2)
    return True


def set_clipboard_text(value: str) -> None:
    from AppKit import NSPasteboard, NSPasteboardTypeString
    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    if not pasteboard.setString_forType_(value, NSPasteboardTypeString):
        raise RuntimeError("wechat-search-clipboard-failed")


def post_key(action: str) -> None:
    binary = SCRIPTS / "cgevent_key_bin"
    proc = run([str(binary), action]) if binary.is_file() else None
    if proc is None or proc.returncode:
        raise RuntimeError(f"wechat-key-{action}-failed")


def open_group_exact(group_name: str, artifacts: Path, shot: Path, hits: list[OcrHit], scale: float, search_name: str | None = None) -> Receipt:
    search_name = search_name or group_name
    headers = find_exact_headers(hits, group_name)
    force_core_search = normalize_group_text(search_name) != normalize_group_text(group_name)
    if len(headers) == 1 and not force_core_search:
        return Receipt(ok=True, action="open-group", group=group_name, header=headers[0].text, artifacts=[str(shot)])
    if len(headers) > 1 and not force_core_search:
        return Receipt(ok=False, action="open-group", group=group_name, note="exact-group-header-count:multiple", artifacts=[str(shot)])

    # An interrupted or contended run can leave a valid search result panel
    # already open.  Consume its unique full-name result before touching the
    # search control; toggling the search control here would hide that result.
    ready_rows = find_unique_core_group_rows(hits, group_name, search_name)
    if len(ready_rows) > 1:
        return Receipt(ok=False, action="open-group", group=group_name, note=f"exact-group-result-count:{len(ready_rows)}", artifacts=[str(shot)])
    if len(ready_rows) == 1:
        click_local(ready_rows[0].cx, ready_rows[0].cy, activate=False, scale=scale)
        after_ready = artifacts / "open_group_exact_after_ready.png"
        ready_headers: list[OcrHit] = []
        for _ in range(3):
            time.sleep(0.6)
            screenshot_main_region(after_ready)
            ready_hits = ocr(after_ready)
            ready_headers = find_exact_headers(ready_hits, group_name)
            if len(ready_headers) == 1:
                return Receipt(ok=True, action="open-group", group=group_name, header=ready_headers[0].text, note="existing-exact-result", artifacts=[str(shot), str(after_ready)])
        return Receipt(ok=False, action="open-group", group=group_name, note=f"exact-group-header-count:{len(ready_headers)}", artifacts=[str(shot), str(after_ready)])

    searches = find_search_controls(hits)
    if len(searches) != 1:
        # No usable exact result was visible.  Only now close a stale search
        # overlay and obtain a clean base frame for a new exact search.
        post_key("escape")
        time.sleep(0.2)
        reset_shot = artifacts / "open_group_exact_reset.png"
        screenshot_main_region(reset_shot)
        hits = ocr(reset_shot)
        searches = find_search_controls(hits)
        if len(searches) != 1:
            return Receipt(ok=False, action="open-group", group=group_name, note=f"search-control-count:{len(searches)}", artifacts=[str(shot), str(reset_shot)])
    click_local(searches[0].cx, searches[0].cy, activate=True, scale=scale)
    time.sleep(0.25)
    focus_shot = artifacts / "open_group_exact_focus.png"
    screenshot_main_region(focus_shot)
    focus_hits = ocr(focus_shot)
    focus_searches = find_search_controls(focus_hits)
    if len(focus_searches) != 1:
        return Receipt(ok=False, action="open-group", group=group_name, note=f"search-focus-control-count:{len(focus_searches)}", artifacts=[str(shot), str(focus_shot)])
    click_local(focus_searches[0].cx, focus_searches[0].cy, activate=False, scale=scale)
    time.sleep(0.15)
    set_clipboard_text(search_name)
    post_key("select-all")
    post_key("paste")

    search_shot = artifacts / "open_group_exact_search.png"
    selected = None
    for attempt in range(3):
        time.sleep(0.6)
        screenshot_search_region(search_shot)
        search_hits = ocr(search_shot)
        if login_blocked(search_hits):
            return Receipt(ok=False, action="open-group", group=group_name, note="blocked-login", artifacts=[str(shot), str(focus_shot), str(search_shot)])
        rows = find_unique_core_group_rows(search_hits, group_name, search_name)
        if len(rows) > 1:
            return Receipt(ok=False, action="open-group", group=group_name, note=f"exact-group-result-count:{len(rows)}", artifacts=[str(shot), str(focus_shot), str(search_shot)])
        if len(rows) == 1:
            selected = rows[0]
            break
        if attempt == 0:
            query_echoes = find_search_query_echoes(search_hits, search_name)
            if len(query_echoes) == 1:
                # The text is present but WeChat has not expanded its results.
                # One click on the populated input opens the panel; never do
                # this when a valid result row is already visible.
                click_local(query_echoes[0].cx, query_echoes[0].cy, activate=False, scale=scale)
    if selected is None:
        return Receipt(ok=False, action="open-group", group=group_name, note="exact-group-result-count:0", artifacts=[str(shot), str(focus_shot), str(search_shot)])
    click_local(selected.cx, selected.cy, activate=False, scale=scale)

    after = artifacts / "open_group_exact_after.png"
    for _ in range(3):
        time.sleep(0.6)
        screenshot_main_region(after)
        after_hits = ocr(after)
        headers = find_exact_headers(after_hits, group_name)
        if len(headers) == 1:
            note = "unique-core-search-and-exact-header" if normalize_group_text(search_name) != normalize_group_text(group_name) else ("exact-group-section-text-row" if decorated_group_result_text(selected.text, group_name) else None)
            return Receipt(ok=True, action="open-group", group=group_name, header=headers[0].text, note=note, artifacts=[str(shot), str(focus_shot), str(search_shot), str(after)])
    return Receipt(ok=False, action="open-group", group=group_name, note=f"exact-group-header-count:{len(headers)}", artifacts=[str(shot), str(focus_shot), str(search_shot), str(after)])


def open_group(group_name: str, artifacts: Path, *, exact: bool = False, search_name: str | None = None) -> Receipt:
    if not wechat_running():
        return Receipt(ok=False, action="open-group", group=group_name, note="WeChat 未运行")

    if exact and not search_name:
        # The common preflight fast path is AX-only.  When the target chat is
        # already current (or its exact row is visible), do not resize, move,
        # screenshot or repeatedly foreground the user's WeChat window.
        ax_receipt = open_group_exact_ax_visible(group_name)
        if ax_receipt is not None and ax_receipt.ok:
            return ax_receipt
        # A uniquely matched AX row may have been clicked while the title is
        # still transiently absent (for example, WeChat did not switch from a
        # virtualized/folded row). Continue only this precise zero-header case
        # through the existing exact screenshot/search contract. Ambiguous AX
        # identities and every other failure remain fail-closed.
        if ax_receipt is not None and ax_receipt.note != "ax-exact-header-count:0":
            return ax_receipt
    ensure_window_size()
    scale = screen_scale()
    shot = artifacts / "open_group.png"
    # Action coordinates must come from the borderless window region. A
    # `screencapture -l` image includes Retina shadow margins, so feeding its
    # OCR coordinates to click_local deterministically offsets the click.
    if exact:
        screenshot_search_region(shot)
    else:
        screenshot_main_region(shot)
    hits = ocr(shot)
    if login_blocked(hits):
        return Receipt(ok=False, action="open-group", group=group_name, note="blocked-login", artifacts=[str(shot)])
    if exact:
        return open_group_exact(group_name, artifacts, shot, hits, scale, search_name)
    header = find_header(hits, group_name)
    if header and chat_panel_visible(hits):
        return Receipt(
            ok=True,
            action="open-group",
            group=group_name,
            header=header.text,
            artifacts=[str(shot)],
        )

    row = find_group_row(hits, group_name)

    if row:
        click_local(row.cx, row.cy, activate=True, scale=scale)
    else:
        if not search_and_open_group(group_name, hits, scale=scale):
            return Receipt(
                ok=False,
                action="open-group",
                group=group_name,
                note="OCR 未找到群聊列表项且搜索框不可用",
                artifacts=[str(shot)],
            )
        time.sleep(0.5)
    shot2 = artifacts / "open_group_after.png"
    for attempt in range(3):
        time.sleep(0.9)
        screenshot(shot2)
        hits2 = ocr(shot2)
        if login_blocked(hits2):
            return Receipt(ok=False, action="open-group", group=group_name, note="blocked-login", artifacts=[str(shot), str(shot2)])
        if chat_panel_visible(hits2):
            break
        row_retry = find_group_row(hits2, group_name)
        if row_retry:
            click_local(row_retry.cx, row_retry.cy, activate=False, scale=scale)
        elif attempt == 0 and not row:
            search_and_open_group(group_name, hits2, scale=scale)

    hits2 = ocr(shot2)
    header = find_header(hits2, group_name)
    panel_ok = chat_panel_visible(hits2)
    ok = header is not None and panel_ok
    return Receipt(
        ok=ok,
        action="open-group",
        group=group_name,
        header=header.text if header else None,
        note=None
        if ok
        else ("聊天区未加载（仅侧边栏可见）" if not panel_ok else "点击后未在标题栏看到群名"),
        artifacts=[str(shot), str(shot2)],
    )


def newest_mp4_since(since_epoch: float) -> Path | None:
    if not VIDEO_CACHE.exists():
        return None
    best: Path | None = None
    best_mtime = since_epoch
    for path in VIDEO_CACHE.rglob("*.mp4"):
        if path.name.endswith("_raw.mp4"):
            continue
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= best_mtime:
            best_mtime = mtime
            best = path
    return best


def find_thumb_for_today(prefix: str | None = None) -> Path | None:
    today = datetime.now().strftime("%Y-%m")
    base = VIDEO_CACHE
    if not base.exists():
        return None
    paths = list(base.rglob(f"msg/video/{today}/*_thumb.jpg"))
    if prefix:
        paths = [p for p in paths if prefix in p.name]
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def download_latest_video(group_name: str, output_dir: Path) -> Receipt:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = ARTIFACTS / f"download_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)

    opened = open_group(group_name, run_dir)
    if not opened.ok:
        return opened

    shot = run_dir / "video_scan.png"
    screenshot(shot)
    hits = ocr(shot)
    video = find_latest_video(hits)
    if not video:
        return Receipt(
            ok=False,
            action="download-latest-video",
            group=group_name,
            header=opened.header,
            note="未在聊天区 OCR 到视频/视频号消息",
            artifacts=opened.artifacts,
        )

    since = time.time()
    scale = screen_scale()
    # 点击视频卡片并尝试播放，促使微信拉取缓存
    click_local(video.cx, video.cy, activate=True, scale=scale)
    time.sleep(0.8)
    click_local(video.cx, min(video.cy + 80, 980), activate=False, scale=scale)
    time.sleep(0.8)
    click_local(video.cx, min(video.cy + 120, 1000), activate=False, scale=scale)

    mp4: Path | None = None
    for _ in range(20):
        mp4 = newest_mp4_since(since - 1)
        if mp4 and mp4.stat().st_mtime >= since - 1:
            break
        time.sleep(1.5)

    thumb = find_thumb_for_today()
    out_mp4 = output_dir / f"{ts}_latest.mp4"
    out_thumb = output_dir / f"{ts}_latest_thumb.jpg"
    copied_mp4: str | None = None
    copied_thumb: str | None = None

    if mp4 and mp4.stat().st_mtime >= since - 2:
        shutil.copy2(mp4, out_mp4)
        copied_mp4 = str(out_mp4)

    if thumb:
        shutil.copy2(thumb, out_thumb)
        copied_thumb = str(out_thumb)

    is_channels = any(
        k in video.text
        for k in ("视频号", "［视频号］", "[视频号]", "时间海：", "时间海:", "鱼杂", "吃过")
    )
    if copied_mp4:
        note = "已从微信缓存复制 mp4"
        ok = True
    elif is_channels:
        note = (
            "最新消息为视频号卡片；Mac 微信未暴露右键另存为，"
            "播放后也未写入 msg/video/*.mp4。已保存缩略图，"
            "完整 mp4 需手动转发到文件传输助手或在手机端保存。"
        )
        ok = bool(copied_thumb)
    else:
        note = "未找到新 mp4；请确认消息为原生视频文件而非链接卡片"
        ok = False

    return Receipt(
        ok=ok,
        action="download-latest-video",
        group=group_name,
        header=opened.header,
        video_text=video.text,
        output_path=copied_mp4,
        thumb_path=copied_thumb,
        note=note,
        artifacts=(opened.artifacts or []) + [str(shot)],
    )


def probe() -> Receipt:
    running = wechat_running()
    elems = 0
    if running:
        try:
            elems = 1 if wechat_window_id() else -1
        except Exception:
            elems = -1
    return Receipt(
        ok=running,
        action="probe",
        note=f"running={running} ax_elems={elems}",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Mac 桌面微信控制")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("probe", help="检查 WeChat 是否运行")

    og = sub.add_parser("open-group", help="打开指定群聊")
    og.add_argument("--name", required=True)
    og.add_argument("--exact", action="store_true")

    dl = sub.add_parser("download-latest-video", help="打开群并尝试下载最新视频")
    dl.add_argument("--group", required=True)
    dl.add_argument("--output", default=str(ARTIFACTS / "downloads"))

    return p


def main() -> int:
    args = build_parser().parse_args()
    if args.cmd == "probe":
        receipt = probe()
    elif args.cmd == "open-group":
        receipt = open_group(args.name, ARTIFACTS / "runs", exact=args.exact)
    elif args.cmd == "download-latest-video":
        receipt = download_latest_video(args.group, Path(args.output))
    else:
        return 2

    print(json.dumps(asdict(receipt), ensure_ascii=False, indent=2))
    return 0 if receipt.ok else 1


if __name__ == "__main__":
    sys.exit(main())
