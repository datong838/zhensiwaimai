"""Extracted native text readback; no merchant contracts, state or cursors.
Source: daily-agent-new-merchants-to-wechat/scripts/desktop_wechat_sender.py.
Extraction preserves AX message-list pruning and unique-main-window raise.
"""
import json
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from PIL import Image

SHARED = Path('/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts')
DESKTOP_WECHAT = SHARED / 'wechat_desktop.py'
MAC_CONTROL_PYTHON = Path('/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python')

CONTEXT_MENU_SCRIPT = r'''import AppKit,ApplicationServices as AS,Quartz,sys,time,json
x,y=float(sys.argv[1]),float(sys.argv[2])
apps=AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.tencent.xinWeChat")
if len(apps)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-process-count","count":len(apps)}));raise SystemExit(2)
app=AS.AXUIElementCreateApplication(apps[0].processIdentifier())
def value(element,key):
 try:
  error,result=AS.AXUIElementCopyAttributeValue(element,key,None)
  return result if error==0 else None
 except Exception:return None
windows=value(app,AS.kAXWindowsAttribute) or []
def size(element):
 try:
  success,result=AS.AXValueGetValue(value(element,AS.kAXSizeAttribute),AS.kAXValueCGSizeType,None)
  return (float(result.width),float(result.height)) if success else None
 except Exception:return None
mains=[]
for window in windows:
 dimensions=size(window)
 if value(window,AS.kAXTitleAttribute)=="微信" and dimensions and dimensions[0]>=700 and dimensions[1]>=500:mains.append(window)
if len(mains)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-main-window-count","count":len(mains)}));raise SystemExit(2)
apps[0].activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
AS.AXUIElementPerformAction(mains[0],AS.kAXRaiseAction);time.sleep(.25)
for event_type in (Quartz.kCGEventRightMouseDown,Quartz.kCGEventRightMouseUp):
 event=Quartz.CGEventCreateMouseEvent(None,event_type,(x,y),Quartz.kCGMouseButtonRight)
 Quartz.CGEventPost(Quartz.kCGHIDEventTap,event);time.sleep(.1)
print(json.dumps({"ok":True,"foreground":"com.tencent.xinWeChat"}))'''

def _load_desktop_control():
    if str(SHARED) not in sys.path:
        sys.path.insert(0, str(SHARED))
    import wechat_desktop
    from desktop_headers import DesktopHeaders
    return DesktopHeaders(wechat_desktop)

def _ax_chat_state(group: str) -> dict:
    script = r'''import json,sys
import AppKit, ApplicationServices as AS
group=sys.argv[1]
apps=AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.tencent.xinWeChat")
if len(apps)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-process-count","count":len(apps)}));raise SystemExit(0)
app=AS.AXUIElementCreateApplication(apps[0].processIdentifier())
def value(element,key):
 try:
  error,result=AS.AXUIElementCopyAttributeValue(element,key,None)
  return result if error==0 else None
 except Exception:return None
windows=value(app,AS.kAXWindowsAttribute) or []
def size(element):
 try:
  success,result=AS.AXValueGetValue(value(element,AS.kAXSizeAttribute),AS.kAXValueCGSizeType,None)
  return (float(result.width),float(result.height)) if success else None
 except Exception:return None
mains=[]
for window in windows:
 dimensions=size(window)
 if value(window,AS.kAXTitleAttribute)=="微信" and dimensions and dimensions[0]>=700 and dimensions[1]>=500:mains.append(window)
if len(mains)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-main-window-count","count":len(mains)}));raise SystemExit(0)
stack=[mains[0]];group_count=0;composer=[]
while stack:
 element=stack.pop();role=value(element,AS.kAXRoleAttribute)
 # WeChat virtual message children can scroll the viewport when inspected.
 # This check needs only the header and composer, never message content.
 if role=="AXList" and value(element,AS.kAXTitleAttribute)=="消息":continue
 item=value(element,AS.kAXValueAttribute) if role in ("AXStaticText","AXTextArea") else None
 if role=="AXStaticText" and item==group:group_count+=1
 if role=="AXTextArea":
  raw_size=value(element,AS.kAXSizeAttribute)
  try:success,size=AS.AXValueGetValue(raw_size,AS.kAXValueCGSizeType,None)
  except Exception:success,size=False,None
  if success and size.width>400 and size.height>40:composer.append(item or "")
 stack.extend(value(element,AS.kAXChildrenAttribute) or [])
print(json.dumps({"ok":group_count==1 and composer==[""],
 "groupCount":group_count,"composerCount":len(composer),
 "composerEmpty":composer==[""]}))'''
    completed = subprocess.run([str(MAC_CONTROL_PYTHON), "-c", script, group], capture_output=True, text=True, timeout=8)
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "desktop-ax-receipt-invalid"}
    if completed.returncode:
        return result | {"ok": False, "reason": result.get("reason", "desktop-ax-read-failed")}
    return result

def _control_text(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).split()).replace("•", "·").replace("⋅", "·")

def _scroll_latest_messages() -> dict:
    """Scroll the unique WeChat message list to its latest position."""
    # App activation alone does not raise the chat window above other windows.
    # Reuse the shared unique-main-window gate before posting scroll events.
    _load_desktop_control().activate_wechat()
    script = r'''import json,time
import AppKit, ApplicationServices as AS, Quartz
apps=AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_("com.tencent.xinWeChat")
if len(apps)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-process-count","count":len(apps)}));raise SystemExit(0)
apps[0].activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
app=AS.AXUIElementCreateApplication(apps[0].processIdentifier())
def value(element,key):
 try:
  error,result=AS.AXUIElementCopyAttributeValue(element,key,None)
  return result if error==0 else None
 except Exception:return None
def pair(raw,kind):
 try:
  success,result=AS.AXValueGetValue(raw,kind,None)
  if not success:return None
  return (float(result.x),float(result.y)) if kind==AS.kAXValueCGPointType else (float(result.width),float(result.height))
 except Exception:return None
windows=value(app,AS.kAXWindowsAttribute) or []
mains=[]
for window in windows:
 dimensions=pair(value(window,AS.kAXSizeAttribute),AS.kAXValueCGSizeType)
 if value(window,AS.kAXTitleAttribute)=="微信" and dimensions and dimensions[0]>=700 and dimensions[1]>=500:mains.append(window)
if len(mains)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-main-window-count","count":len(mains)}));raise SystemExit(0)
stack=[mains[0]];lists=[]
while stack:
 element=stack.pop()
 if value(element,AS.kAXRoleAttribute)=="AXList" and value(element,AS.kAXTitleAttribute)=="消息":
  lists.append(element);continue
 stack.extend(value(element,AS.kAXChildrenAttribute) or [])
if len(lists)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-message-list-count","count":len(lists)}));raise SystemExit(0)
position=pair(value(lists[0],AS.kAXPositionAttribute),AS.kAXValueCGPointType)
size=pair(value(lists[0],AS.kAXSizeAttribute),AS.kAXValueCGSizeType)
if not position or not size or size[0]<400 or size[1]<250:
 print(json.dumps({"ok":False,"reason":"wechat-message-list-bounds-invalid"}));raise SystemExit(0)
x=position[0]+size[0]/2;y=position[1]+size[1]/2
move=Quartz.CGEventCreateMouseEvent(None,Quartz.kCGEventMouseMoved,(x,y),Quartz.kCGMouseButtonLeft)
Quartz.CGEventPost(Quartz.kCGHIDEventTap,move)
for _ in range(12):
 event=Quartz.CGEventCreateScrollWheelEvent(None,Quartz.kCGScrollEventUnitLine,1,-10)
 Quartz.CGEventPost(Quartz.kCGHIDEventTap,event);time.sleep(.05)
print(json.dumps({"ok":True,"messageList":{"x":position[0],"y":position[1],"width":size[0],"height":size[1]},"scrollEvents":12}))'''
    completed = subprocess.run([str(MAC_CONTROL_PYTHON), "-c", script], capture_output=True, text=True, timeout=10)
    try:
        receipt = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "reason": "wechat-message-scroll-receipt-invalid"}
    if completed.returncode or receipt.get("ok") is not True:
        return receipt | {"ok": False, "reason": receipt.get("reason", "wechat-message-scroll-failed")}
    time.sleep(.8)
    return receipt

def _payload_bubble_anchor(hits, text: str, width: int, height: int) -> dict:
    lines = [_control_text(line) for line in text.splitlines() if _control_text(line)]
    content_left = max(300.0, width * .28)
    anchors = [
        (line_index, hit) for line_index, line in enumerate(lines) for hit in hits
        if _control_text(hit.text) == line
        and hit.cx > content_left and height * .18 < hit.cy < height * .80
    ]
    clusters: list[list[tuple[int, object]]] = []
    for entry in sorted(anchors, key=lambda pair: pair[1].cy):
        if not clusters or entry[1].cy - clusters[-1][-1][1].cy > max(90.0, height * .08):
            clusters.append([entry])
        else:
            clusters[-1].append(entry)
    candidates = [cluster for cluster in clusters if len({line for line, _ in cluster}) >= 1]
    if not candidates:
        return {"ok": False, "bubbleCount": len(candidates), "matchedAnchorCount": len(anchors)}
    # Explicitly authorized repeat tests can contain identical old messages.
    # Select the lowest candidate; the caller MUST prove new outgoing pixels
    # against before/after frames and exact native-copy text before committing.
    cluster = candidates[-1]
    target = cluster[len(cluster) // 2][1]
    line_positions = {str(line): [hit.cx, hit.cy] for line, hit in cluster}
    return {
        "ok": True,
        "candidateCount": len(candidates),
        "x": target.cx,
        "y": target.cy,
        "matchedLineIndexes": sorted({line for line, _ in cluster}),
        "matchedAnchorCount": len(cluster),
        "linePositions": line_positions,
    }

def _read_unique_payload_anchor(wd, shot: Path, group: str, text: str,
                                width: int, height: int, attempts: int = 3,
                                ax_header_confirmed: bool = False) -> dict:
    last = {"ok": False, "headerCount": 0, "bubbleCount": 0, "matchedAnchorCount": 0}
    for attempt in range(1, attempts + 1):
        hits = wd.ocr(shot)
        headers = wd.find_exact_headers(hits, group)
        anchor = _payload_bubble_anchor(hits, text, width, height)
        last = anchor | {"headerCount": len(headers), "ocrAttempts": attempt,
                         "headerVerifiedByAX": ax_header_confirmed}
        if len(headers) > 1:
            return last
        if (len(headers) == 1 or ax_header_confirmed) and anchor.get("ok") is True:
            return last
        if attempt < attempts:
            time.sleep(.15)
    return last

def _copy_exact_bubble(group: str, item: dict, output_dir: Path) -> dict:
    wd = _load_desktop_control()
    positions = []
    frame_anchors = []
    scroll_receipts = []
    for index in range(2):
        anchor = None
        last_failure = {"reason": "desktop-reconcile-bubble-not-unique"}
        for cycle in range(1, 4):
            # Sending leaves the verified group open.  Reuse it when native AX
            # confirms the exact group and empty composer; only an unverified
            # state may use the existing exact-open recovery path.
            current = _ax_chat_state(group)
            opened = None if current.get("ok") is True else (wd.open_group(group, output_dir, exact=True) if index == 0 else None)
            if opened is not None and opened.ok is not True:
                last_failure = {"reason": "desktop-reconcile-open-group:" + str(opened.note),
                                "recoveryCycle": cycle}
                time.sleep(1)
                continue
            for _ in range(4 if index == 0 else 0):
                scroll = _scroll_latest_messages()
                scroll_receipts.append(scroll | {"frame": index + 1, "recoveryCycle": cycle})
                if scroll.get("ok") is not True:
                    return {"ok": False, "reason": scroll.get("reason", "desktop-reconcile-scroll-failed"),
                            "scrolls": scroll_receipts}
            state = _ax_chat_state(group)
            if state.get("ok") is not True:
                if state.get("composerCount") == 1 and state.get("composerEmpty") is False:
                    return state | {"ok": False, "reason": "desktop-reconcile-chat-state-invalid"}
                last_failure = state | {"reason": "desktop-reconcile-chat-state-contended",
                                        "recoveryCycle": cycle}
                time.sleep(1)
                continue
            shot = output_dir / f"reconcile-bubble-{index + 1}.png"
            wd.screenshot_main_region(shot)
            with Image.open(shot) as image:
                width, height = image.size
            observed = _read_unique_payload_anchor(
                wd, shot, group, item["text"], width, height, ax_header_confirmed=True)
            if observed.get("headerCount", 0) > 1:
                return {"ok": False, "reason": "desktop-reconcile-bubble-not-unique",
                        "headerCount": observed.get("headerCount"), "scrolls": scroll_receipts}
            if observed.get("headerVerifiedByAX") is True and observed.get("ok") is True:
                anchor = observed | {"recoveryCycle": cycle}
                break
            last_failure = observed | {"reason": "desktop-reconcile-bubble-not-unique",
                                       "recoveryCycle": cycle}
            time.sleep(1)
        if anchor is None:
            return {"ok": False, **last_failure, "scrolls": scroll_receipts}
        frame_anchors.append(anchor)
    common = sorted(set(frame_anchors[0]["linePositions"]) & set(frame_anchors[1]["linePositions"]),
                    key=lambda key: len(item["text"].splitlines()[int(key)]), reverse=True)
    stable_line = None
    for key in common:
        first = frame_anchors[0]["linePositions"][key]
        second = frame_anchors[1]["linePositions"][key]
        if abs(first[0] - second[0]) <= 6 and abs(first[1] - second[1]) <= 6:
            positions = [tuple(first), tuple(second)]
            stable_line = int(key)
            break
    if stable_line is None:
        return {"ok": False, "reason": "desktop-reconcile-bubble-not-stable",
                "frameAnchors": frame_anchors, "scrolls": scroll_receipts}
    marker = "desktop-reconcile-" + str(time.time_ns())
    subprocess.run(["/usr/bin/pbcopy"], input=marker, text=True, check=True)
    left, top, _, _ = wd.window_bounds(); scale = wd.screen_scale()
    point_x = left + positions[-1][0] / scale; point_y = top + positions[-1][1] / scale
    completed = subprocess.run([str(MAC_CONTROL_PYTHON), "-c", CONTEXT_MENU_SCRIPT, str(point_x), str(point_y)],
                               capture_output=True, text=True, timeout=8)
    if completed.returncode:
        return {"ok": False, "reason": "desktop-reconcile-context-menu-failed",
                "contextMenuError": (completed.stderr or completed.stdout).strip()[-500:]}
    time.sleep(.6)
    menu_shot = output_dir / "reconcile-context-menu.png"
    captured = subprocess.run(["/usr/sbin/screencapture", "-x", str(menu_shot)], capture_output=True, text=True)
    if captured.returncode:
        return {"ok": False, "reason": "desktop-reconcile-menu-capture-failed"}
    copy_hits = [hit for hit in wd.ocr(menu_shot) if hit.text.strip() == "复制"]
    if len(copy_hits) != 1:
        subprocess.run([str(DESKTOP_WECHAT.parent / "cgevent_key_bin"), "escape"], capture_output=True, text=True)
        return {"ok": False, "reason": "desktop-reconcile-copy-menu-not-unique", "copyMenuCount": len(copy_hits)}
    wd.click(copy_hits[0].cx, copy_hits[0].cy, activate=False, scale=scale)
    time.sleep(.3)
    copied = subprocess.run(["/usr/bin/pbpaste"], capture_output=True, text=True, timeout=5)
    if copied.returncode or copied.stdout != item["text"] or copied.stdout == marker:
        return {"ok": False, "reason": "desktop-reconcile-copied-text-mismatch"}
    return {"ok": True, "bubblePositions": positions, "copyMenuCount": 1,
            "composerEmpty": True, "copiedTextSha256": item["sha256"],
            "scrolls": scroll_receipts, "frameAnchors": frame_anchors, "stableLineIndex": stable_line}
