#!/usr/bin/env python3
"""Mac 桌面微信控制：探测、打开群聊、定位并尝试下载最新视频。"""
from __future__ import annotations

import argparse
import json
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


def osascript(script: str) -> str:
    proc = run(["osascript", "-e", script])
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())
    return proc.stdout.strip()


def activate_wechat() -> None:
    script = '''tell application "WeChat" to activate
delay 0.2
tell application "System Events" to tell process "WeChat"
set mains to (every window whose name is "微信")
if (count of mains) is not 1 then error "wechat-main-window-count-not-one"
set w to item 1 of mains
set mainSize to size of w
if (item 1 of mainSize) < 700 or (item 2 of mainSize) < 500 then error "wechat-main-window-too-small"
repeat with candidate in windows
if candidate is not w then
set candidateName to name of candidate as text
if candidateName is not "微信" and candidateName is not "微信 (窗口)" and candidateName is not "图片和视频" then
set candidateSize to size of candidate
if (item 1 of candidateSize) > 500 or (item 2 of candidateSize) > 400 then error "wechat-unexpected-secondary-window"
end if
end if
end repeat
try
set value of attribute "AXMinimized" of w to false
end try
set frontmost to true
try
perform action "AXRaise" of w
end try
end tell'''
    proc = run(["osascript", "-e", script])
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "wechat-window-activation-failed")
    time.sleep(0.6)


def wechat_running() -> bool:
    out = osascript(
        'tell application "System Events" to return exists process "WeChat"'
    )
    return out.lower() == "true"


def screen_scale() -> float:
    proc = run(
        [
            "osascript",
            "-e",
            'tell application "Finder" to get image scale of desktop',
        ]
    )
    try:
        return float(proc.stdout.strip())
    except ValueError:
        return 2.0


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
    raw = osascript('''tell application "System Events" to tell process "WeChat"
set mains to (every window whose name is "微信")
if (count of mains) is not 1 then error "wechat-main-window-count-not-one"
set w to item 1 of mains
set p to position of w
set s to size of w
return (item 1 of p as text) & "," & (item 2 of p as text) & "," & (item 1 of s as text) & "," & (item 2 of s as text)
end tell''')
    return tuple(float(value) for value in raw.split(","))


def click_local(x: float, y: float, *, activate: bool = True, scale: float | None = None) -> None:
    sc = scale or screen_scale(); left, top, _, _ = window_bounds()
    click(left + x / sc, top + y / sc, activate=activate, scale=1.0)


def wechat_window_id() -> int | None:
    script = """import Quartz
opts=Quartz.kCGWindowListOptionAll|Quartz.kCGWindowListExcludeDesktopElements
wins=[]
for w in Quartz.CGWindowListCopyWindowInfo(opts,Quartz.kCGNullWindowID):
    bounds=w.get('kCGWindowBounds',{})
    if w.get('kCGWindowOwnerName') in ('WeChat','微信') and w.get('kCGWindowLayer',0)==0 and w.get('kCGWindowName')=='微信' and bounds.get('Width',0)>=900 and bounds.get('Height',0)>=560:
        wins.append(w)
print(int(wins[0]['kCGWindowNumber']) if len(wins)==1 else 0)
"""
    try:
        wid = int(run([CONTROL_PYTHON, "-c", script]).stdout.strip())
        return wid if wid > 0 else None
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
    raise RuntimeError(f"wechat-window-capture-failed:{primary}:{secondary}")


def screenshot_search_region(path: Path) -> None:
    """Capture the composited main-window rectangle including search popovers."""
    path.parent.mkdir(parents=True, exist_ok=True)
    activate_wechat()
    time.sleep(0.15)
    if not wechat_frontmost():
        raise RuntimeError("wechat-search-region-contended")
    left, top, width, height = window_bounds()
    region = f"{int(left)},{int(top)},{int(width)},{int(height)}"
    proc = run(["screencapture", "-x", "-R" + region, str(path)])
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or "wechat-search-region-capture-failed")
    if not wechat_frontmost():
        path.unlink(missing_ok=True)
        raise RuntimeError("wechat-search-region-contended")


def wechat_frontmost() -> bool:
    try:
        bundle = osascript(
            'tell application "System Events" to get bundle identifier of first application process whose frontmost is true'
        )
    except RuntimeError:
        return False
    return bundle == WECHAT_BUNDLE


def wechat_ax_state() -> dict:
    """Read WeChat's main-window text geometry through Accessibility only."""
    script = r'''import json
import AppKit,ApplicationServices as AX
apps=[a for a in AppKit.NSWorkspace.sharedWorkspace().runningApplications()
 if a.bundleIdentifier()=="com.tencent.xinWeChat"]
if len(apps)!=1:raise RuntimeError("wechat-process-count-not-one")
app=AX.AXUIElementCreateApplication(apps[0].processIdentifier())
def attr(element,name,default=None):
 error,value=AX.AXUIElementCopyAttributeValue(element,name,None)
 return value if error==0 else default
windows=attr(app,AX.kAXWindowsAttribute,[]) or []
main=[w for w in windows if attr(w,AX.kAXTitleAttribute,"")=="微信"]
if len(main)!=1:raise RuntimeError("wechat-main-window-count-not-one")
def pair(value,kind):
 ok,result=AX.AXValueGetValue(value,kind,None)
 if not ok:return None
 return [float(result.x),float(result.y)] if kind==AX.kAXValueCGPointType else [float(result.width),float(result.height)]
window=main[0]
position=pair(attr(window,AX.kAXPositionAttribute),AX.kAXValueCGPointType)
size=pair(attr(window,AX.kAXSizeAttribute),AX.kAXValueCGSizeType)
items=[];stack=[window];seen=0
while stack and seen<6000:
 element=stack.pop();seen+=1
 role=attr(element,AX.kAXRoleAttribute,"")
 if role=="AXStaticText":
  value=attr(element,AX.kAXValueAttribute,"") or attr(element,AX.kAXTitleAttribute,"")
  pos=pair(attr(element,AX.kAXPositionAttribute),AX.kAXValueCGPointType)
  dimensions=pair(attr(element,AX.kAXSizeAttribute),AX.kAXValueCGSizeType)
  if value and pos and dimensions:
   items.append({"text":str(value),"x":pos[0],"y":pos[1],"width":dimensions[0],"height":dimensions[1]})
 stack.extend(attr(element,AX.kAXChildrenAttribute,[]) or [])
print(json.dumps({"window":{"x":position[0],"y":position[1],"width":size[0],"height":size[1]},"texts":items},ensure_ascii=False))'''
    completed = run([CONTROL_PYTHON, "-c", script])
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
    return bool(re.fullmatch(re.escape(expected) + r"(?:[（(]\d+[）)])?", value))


def find_exact_group_rows(hits: list[OcrHit], group_name: str) -> list[OcrHit]:
    # Search result section labels are UI copy and may change.  Treat the
    # left result pane as the contract instead: the query echoed in the top
    # search input is excluded by the top band, while chat content is excluded
    # by the pane boundary.  The caller still requires exactly one complete
    # name and verifies the opened chat header before any send.
    return [
        h for h in hits
        if h.cx < 700 and h.cy >= 120 and exact_group_text(h.text, group_name)
    ]


def find_search_query_echoes(hits: list[OcrHit], group_name: str) -> list[OcrHit]:
    expected = normalize_group_text(group_name)
    return [
        h for h in hits
        if h.cx < 700 and h.cy < 120 and expected in normalize_group_text(h.text)
    ]


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
    return any(value in joined for value in ("请重新登录", "进入微信", "切换账号", "仅传输文件"))


def ensure_window_size() -> None:
    from AppKit import NSScreen

    screen = NSScreen.mainScreen()
    frame = screen.frame()
    visible = screen.visibleFrame()
    left = int(visible.origin.x + 24)
    top = int(frame.size.height - visible.origin.y - visible.size.height + 24)
    width = int(min(1200, visible.size.width - 48))
    height = int(min(820, visible.size.height - 48))
    if width < 900 or height < 560:
        raise RuntimeError("wechat-visible-screen-too-small")
    script = f"""
tell application "WeChat" to activate
delay 0.2
tell application "System Events"
  tell process "WeChat"
    set frontmost to true
    set mains to (every window whose name is "微信")
    if (count of mains) is not 1 then error "wechat-main-window-count-not-one"
    set w to item 1 of mains
    try
      set position of w to {{{left}, {top}}}
      set size of w to {{{width}, {height}}}
    end try
  end tell
end tell
"""
    run(["osascript", "-e", script])
    time.sleep(0.5)


def search_and_open_group(group_name: str, hits: list[OcrHit], *, scale: float = 2.0) -> bool:
    search = next((h for h in hits if "搜索" in h.text and h.cx < 900), None)
    if not search:
        return False
    click_local(search.cx, search.cy, activate=True, scale=scale)
    time.sleep(0.3)
    run(["osascript", "-e", f'set the clipboard to "{group_name}"'])
    run(["osascript", "-e", 'tell application "System Events" to keystroke "v" using command down'])
    time.sleep(1.2)
    return True


def set_clipboard_text(value: str) -> None:
    script = "on run argv\nset the clipboard to item 1 of argv\nend run\n"
    proc = subprocess.run(["osascript", "-", value], input=script, text=True, capture_output=True)
    if proc.returncode:
        raise RuntimeError("wechat-search-clipboard-failed")


def post_key(action: str) -> None:
    binary = SCRIPTS / "cgevent_key_bin"
    proc = run([str(binary), action]) if binary.is_file() else None
    if proc is None or proc.returncode:
        raise RuntimeError(f"wechat-key-{action}-failed")


def open_group_exact(group_name: str, artifacts: Path, shot: Path, hits: list[OcrHit], scale: float) -> Receipt:
    headers = find_exact_headers(hits, group_name)
    if len(headers) == 1:
        return Receipt(ok=True, action="open-group", group=group_name, header=headers[0].text, artifacts=[str(shot)])
    if len(headers) > 1:
        return Receipt(ok=False, action="open-group", group=group_name, note="exact-group-header-count:multiple", artifacts=[str(shot)])

    # An interrupted or contended run can leave a valid search result panel
    # already open.  Consume its unique full-name result before touching the
    # search control; toggling the search control here would hide that result.
    ready_rows = find_exact_group_rows(hits, group_name)
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
    set_clipboard_text(group_name)
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
        rows = find_exact_group_rows(search_hits, group_name)
        if len(rows) > 1:
            return Receipt(ok=False, action="open-group", group=group_name, note=f"exact-group-result-count:{len(rows)}", artifacts=[str(shot), str(focus_shot), str(search_shot)])
        if len(rows) == 1:
            selected = rows[0]
            break
        if attempt == 0:
            query_echoes = find_search_query_echoes(search_hits, group_name)
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
            return Receipt(ok=True, action="open-group", group=group_name, header=headers[0].text, artifacts=[str(shot), str(focus_shot), str(search_shot), str(after)])
    return Receipt(ok=False, action="open-group", group=group_name, note=f"exact-group-header-count:{len(headers)}", artifacts=[str(shot), str(focus_shot), str(search_shot), str(after)])


def open_group(group_name: str, artifacts: Path, *, exact: bool = False) -> Receipt:
    if not wechat_running():
        return Receipt(ok=False, action="open-group", group=group_name, note="WeChat 未运行")

    if exact:
        # The common preflight fast path is AX-only.  When the target chat is
        # already current (or its exact row is visible), do not resize, move,
        # screenshot or repeatedly foreground the user's WeChat window.
        ax_receipt = open_group_exact_ax_visible(group_name)
        if ax_receipt is not None:
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
        return open_group_exact(group_name, artifacts, shot, hits, scale)
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
            elems = int(
                osascript(
                    'tell application "System Events" to tell process "WeChat" '
                    "to count of (entire contents of front window)"
                )
            )
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
