#!/usr/bin/env python3
"""Desktop-WeChat adapter preserving the merchant workflow's ledger and cursor."""
from __future__ import annotations

import json
import importlib.util
import re
import subprocess
import sys
import time
from pathlib import Path
from PIL import Image

import wechat_sender_executor as mobile

DESKTOP_SENDER = Path("/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts/desktop_sender.py")
DESKTOP_WECHAT = DESKTOP_SENDER.with_name("wechat_desktop.py")
DESKTOP_PREFLIGHT = DESKTOP_SENDER.with_name("desktop_preflight.py")
DEFAULT_CONTENTION_WAIT_SECONDS = 900.0
DEFAULT_CONTENTION_POLL_SECONDS = 5.0
MAC_CONTROL_PYTHON = Path("/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python")


def _load_desktop_control():
    spec = importlib.util.spec_from_file_location("merchant_wechat_desktop_control", DESKTOP_WECHAT)
    if spec is None or spec.loader is None:
        raise mobile.StopRun("desktop-control-load-failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _load_shared_preflight():
    spec = importlib.util.spec_from_file_location("merchant_wechat_shared_preflight", DESKTOP_PREFLIGHT)
    if spec is None or spec.loader is None:
        raise mobile.StopRun("desktop-preflight-load-failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_private_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _hard_gate(reason: str, send_attempts: int = 0) -> bool:
    """True means waiting/retrying could violate identity or idempotency."""
    if send_attempts:
        return True
    hard_fragments = (
        "blocked-login", "authorization", "already-attempted", "attempted-result",
        "payload-file", "message-contract", "collection-", "unsupported-group",
        "window-capture-failed", "window-capture-target-missing",
        "result-count:2", "result-count:3", "result-count:multiple",
        "header-count:multiple", "group-title-not-unique:2", "group-title-not-unique:3",
    )
    return any(fragment in reason for fragment in hard_fragments)


def _wait_before_send(operation, *, phase: str, output_dir: Path, wait_seconds: float,
                      poll_seconds: float) -> dict:
    """Retry transient desktop-WeChat interference only before a send attempt."""
    started = time.monotonic()
    events: list[dict] = []
    attempt = 0
    while True:
        attempt += 1
        try:
            receipt = operation()
        except subprocess.TimeoutExpired:
            receipt = {"ok": False, "reason": "desktop-wechat-operation-timeout", "sendAttempts": 0}
        except Exception as error:
            receipt = {"ok": False, "reason": str(error), "sendAttempts": 0}
        if receipt.get("ok") is True:
            waited_ms = sum(event["waitMs"] for event in events)
            result = receipt | {
                "contentionRetries": len(events),
                "contentionWaitMs": waited_ms,
                "contentionEvents": events,
            }
            _write_private_json(output_dir / "contention.json", result)
            return result
        reason = str(receipt.get("reason") or receipt.get("note") or "desktop-wechat-failed")
        send_attempts = int(receipt.get("sendAttempts") or 0)
        if receipt.get("hardGate") is True or _hard_gate(reason, send_attempts):
            result = receipt | {
                "contentionRetries": len(events),
                "contentionWaitMs": sum(event["waitMs"] for event in events),
                "contentionEvents": events,
            }
            _write_private_json(output_dir / "contention.json", result)
            return result
        elapsed = time.monotonic() - started
        if elapsed >= wait_seconds:
            result = receipt | {
                "ok": False,
                "reason": "desktop-wechat-contention-timeout:" + reason,
                "contentionRetries": len(events),
                "contentionWaitMs": sum(event["waitMs"] for event in events),
                "contentionEvents": events,
            }
            _write_private_json(output_dir / "contention.json", result)
            return result
        delay = min(poll_seconds, max(0.0, wait_seconds - elapsed))
        events.append({"phase": phase, "attempt": attempt, "reason": reason, "waitMs": round(delay * 1000)})
        _write_private_json(output_dir / "contention.json", {
            "ok": False, "phase": phase, "contentionRetries": len(events),
            "contentionWaitMs": sum(event["waitMs"] for event in events), "contentionEvents": events,
        })
        time.sleep(delay)


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
mains=[window for window in windows if value(window,AS.kAXTitleAttribute)=="微信"]
if len(mains)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-main-window-count","count":len(mains)}));raise SystemExit(0)
stack=[mains[0]];group_count=0;composer=[]
while stack:
 element=stack.pop();role=value(element,AS.kAXRoleAttribute);item=value(element,AS.kAXValueAttribute)
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
    return "".join(value.split()).replace("•", "·").replace("⋅", "·")


def _scroll_latest_messages() -> dict:
    """Scroll the unique WeChat message list to its latest position."""
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
mains=[window for window in windows if value(window,AS.kAXTitleAttribute)=="微信"]
if len(mains)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-main-window-count","count":len(mains)}));raise SystemExit(0)
stack=[mains[0]];lists=[]
while stack:
 element=stack.pop()
 if value(element,AS.kAXRoleAttribute)=="AXList" and value(element,AS.kAXTitleAttribute)=="消息":lists.append(element)
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
    if len(candidates) != 1:
        return {"ok": False, "bubbleCount": len(candidates), "matchedAnchorCount": len(anchors)}
    cluster = candidates[0]
    target = cluster[len(cluster) // 2][1]
    line_positions = {str(line): [hit.cx, hit.cy] for line, hit in cluster}
    return {
        "ok": True,
        "x": target.cx,
        "y": target.cy,
        "matchedLineIndexes": sorted({line for line, _ in cluster}),
        "matchedAnchorCount": len(cluster),
        "linePositions": line_positions,
    }


def _read_unique_payload_anchor(wd, shot: Path, group: str, text: str,
                                width: int, height: int, attempts: int = 3) -> dict:
    last = {"ok": False, "headerCount": 0, "bubbleCount": 0, "matchedAnchorCount": 0}
    for attempt in range(1, attempts + 1):
        hits = wd.ocr(shot)
        headers = wd.find_exact_headers(hits, group)
        anchor = _payload_bubble_anchor(hits, text, width, height)
        last = anchor | {"headerCount": len(headers), "ocrAttempts": attempt}
        if len(headers) == 1 and anchor.get("ok") is True:
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
            opened = wd.open_group(group, output_dir, exact=True)
            if opened.ok is not True:
                last_failure = {"reason": "desktop-reconcile-open-group:" + str(opened.note),
                                "recoveryCycle": cycle}
                time.sleep(1)
                continue
            for _ in range(4):
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
            observed = _read_unique_payload_anchor(wd, shot, group, item["text"], width, height)
            if observed.get("headerCount", 0) > 1:
                return {"ok": False, "reason": "desktop-reconcile-bubble-not-unique",
                        "headerCount": observed.get("headerCount"), "scrolls": scroll_receipts}
            if observed.get("headerCount") == 1 and observed.get("ok") is True:
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
    click_script = r'''import AppKit,ApplicationServices as AS,Quartz,sys,time,json
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
mains=[window for window in windows if value(window,AS.kAXTitleAttribute)=="微信"]
if len(mains)!=1:
 print(json.dumps({"ok":False,"reason":"wechat-main-window-count","count":len(mains)}));raise SystemExit(2)
apps[0].activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
AS.AXUIElementPerformAction(mains[0],AS.kAXRaiseAction);time.sleep(.25)
for event_type in (Quartz.kCGEventRightMouseDown,Quartz.kCGEventRightMouseUp):
 event=Quartz.CGEventCreateMouseEvent(None,event_type,(x,y),Quartz.kCGMouseButtonRight)
 Quartz.CGEventPost(Quartz.kCGHIDEventTap,event);time.sleep(.1)
print(json.dumps({"ok":True,"foreground":"com.tencent.xinWeChat"}))'''
    completed = subprocess.run([str(MAC_CONTROL_PYTHON), "-c", click_script, str(point_x), str(point_y)],
                               capture_output=True, text=True, timeout=8)
    if completed.returncode:
        return {"ok": False, "reason": "desktop-reconcile-context-menu-failed"}
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


def _reconcile_unknown(marker: Path, group: str, item: dict, output_dir: Path) -> dict:
    try:
        attempt = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "reason": "desktop-attempt-marker-invalid", "sendAttempts": 1}
    payloads = attempt.get("payloads") or []
    if not (
        attempt.get("state") == "unknown"
        and attempt.get("sendAttempts") == 1
        and attempt.get("stage") == "post_send_verify"
        and (
            attempt.get("reason") == "desktop-post-send-verification-unknown"
            or bool(attempt.get("postSendFailureReason"))
            or attempt.get("reason") == "desktop-chat-input-focus-failed"
        )
        and attempt.get("groupName") == group
        and len(payloads) == 1
        and payloads[0].get("sha256") == item.get("sha256")
        and payloads[0].get("text") == item.get("text")
    ):
        return {"ok": False, "reason": "desktop-attempt-not-reconcilable", "sendAttempts": 1}
    observation = _copy_exact_bubble(group, item, output_dir)
    if observation.get("ok") is not True:
        return {"ok": False, "reason": observation.get("reason", "desktop-bubble-copy-readback-failed"),
                "sendAttempts": 1, "reconcileObservation": observation}
    verified = attempt | {
        "ok": True, "verified": True, "state": "verified", "verifiedAt": time.time(),
        "verificationMethod": "desktop-bubble-copy-exact-two-frame", "reconciledWithoutSend": True,
        "reconcileObservation": observation, "copyReadback": observation,
        "physicalSendAttempts": 1, "sendAttempts": 1, "runtimeModelDecisions": 0,
        "merchantId": item["merchantId"], "messageSha256": item["sha256"],
    }
    _write_private_json(marker, verified)
    _write_private_json(output_dir / "reconcile.json", verified)
    _write_private_json(output_dir / "acceptance-receipt.json", verified)
    return verified


def _copy_verify_successful_send(marker: Path, group: str, item: dict,
                                 output_dir: Path, receipt: dict) -> dict:
    observation = _copy_exact_bubble(group, item, output_dir)
    if observation.get("ok") is not True:
        unknown = receipt | {
            "ok": False, "verified": False, "state": "unknown",
            "stage": "post_send_verify",
            "reason": "desktop-post-send-verification-unknown",
            "postSendFailureReason": observation.get("reason", "desktop-bubble-copy-readback-failed"),
            "copyReadback": observation, "physicalSendAttempts": 1,
            "sendAttempts": 1, "runtimeModelDecisions": 0,
        }
        _write_private_json(marker, unknown)
        _write_private_json(output_dir / "acceptance-receipt.json", unknown)
        return unknown
    verified = receipt | {
        "ok": True, "verified": True, "state": "verified",
        "verificationMethod": "desktop-bubble-copy-exact-two-frame",
        "copyReadback": observation, "physicalSendAttempts": 1,
        "sendAttempts": 1, "runtimeModelDecisions": 0,
        "merchantId": item["merchantId"], "messageSha256": item["sha256"],
    }
    _write_private_json(marker, verified)
    _write_private_json(output_dir / "acceptance-receipt.json", verified)
    return verified


def preflight(group: str, output_dir: Path, wait_seconds: float = DEFAULT_CONTENTION_WAIT_SECONDS,
              poll_seconds: float = DEFAULT_CONTENTION_POLL_SECONDS) -> dict:
    shared = _load_shared_preflight()
    def once() -> dict:
        return shared.run_exact_group_preflight(group, output_dir)

    receipt = _wait_before_send(once, phase="preflight", output_dir=output_dir,
                                wait_seconds=wait_seconds, poll_seconds=poll_seconds)
    if receipt.get("ok") is not True:
        raise mobile.StopRun(str(receipt.get("reason", "desktop-wechat-preflight-failed")))
    return receipt


def run(collection_path: Path, group: str, authorization: str, output_dir: Path,
        wait_seconds: float = DEFAULT_CONTENTION_WAIT_SECONDS,
        poll_seconds: float = DEFAULT_CONTENTION_POLL_SECONDS) -> dict:
    collection = mobile.load_collection(collection_path, group)
    mobile.audit_collection(collection)
    if group == mobile.TEST_GROUP and authorization != mobile.TEST_AUTHORIZATION:
        raise mobile.StopRun("test-standing-authorization-missing")
    history = []
    if mobile.HISTORY_FILE.exists():
        history = [json.loads(line) for line in mobile.HISTORY_FILE.read_text().splitlines()]
    sent_keys = {mobile.send_identity(group, row) for row in history if row.get("groupName") == group and row.get("verified") is True}
    messages = [row for row in collection["messages"] if mobile.send_identity(group, row) not in sent_keys]
    result = {"ok": False, "executor": "merchant-desktop-wechat-sender", "channel": "desktop", "sent": 0,
              "messageCount": len(messages), "historySkipped": len(collection["messages"]) - len(messages)}
    if not messages:
        return result | {"ok": True, "mode": "execute-noop"}
    for item in messages:
        item_dir = output_dir / item["merchantId"]
        marker = mobile.STATE_DIR / "send-attempts" / (mobile.send_identity(group, item) + ".json")
        if marker.exists():
            receipt = _reconcile_unknown(marker, group, item, item_dir)
            if receipt.get("verified") is not True:
                return result | {"reason": receipt.get("reason", "desktop-attempt-reconcile-failed"), "desktop": receipt}
            mobile.append_history_then_cursor(group, collection["businessDate"], item)
            result["sent"] += 1
            result["reconciled"] = result.get("reconciled", 0) + 1
            result["lastMerchantId"] = item["merchantId"]
            continue
        command = [sys.executable, str(DESKTOP_SENDER), "--group", group, "--payload-type", "text", "--item", item["text"],
                   "--authorization", authorization, "--ledger", str(mobile.STATE_DIR / "send-attempts"),
                   "--marker-name", mobile.send_identity(group, item) + ".json", "--output-dir", str(item_dir), "--execute"]
        def once() -> dict:
            completed = subprocess.run(command, capture_output=True, text=True)
            try:
                receipt = json.loads(completed.stdout.strip().splitlines()[-1])
            except (json.JSONDecodeError, IndexError):
                return {"ok": False, "reason": "desktop-send-invalid-receipt", "sendAttempts": 0}
            if completed.returncode or receipt.get("verified") is not True:
                return receipt | {"ok": False}
            return receipt
        receipt = _wait_before_send(once, phase="send-before-attempt", output_dir=item_dir,
                                    wait_seconds=wait_seconds, poll_seconds=poll_seconds)
        result.setdefault("contentionRetries", 0)
        result.setdefault("contentionWaitMs", 0)
        result["contentionRetries"] += int(receipt.get("contentionRetries") or 0)
        result["contentionWaitMs"] += int(receipt.get("contentionWaitMs") or 0)
        result.setdefault("contentionEvents", []).extend(receipt.get("contentionEvents") or [])
        if receipt.get("verified") is not True:
            if marker.exists() and receipt.get("reason") == "desktop-post-send-verification-unknown":
                receipt = _reconcile_unknown(marker, group, item, item_dir)
                if receipt.get("verified") is True:
                    result["reconciled"] = result.get("reconciled", 0) + 1
            if receipt.get("verified") is not True:
                return result | {"reason": receipt.get("reason", "desktop-send-failed"), "desktop": receipt}
        else:
            receipt = _copy_verify_successful_send(marker, group, item, item_dir, receipt)
            if receipt.get("verified") is not True:
                return result | {"reason": receipt.get("reason", "desktop-copy-readback-failed"), "desktop": receipt}
        mobile.append_history_then_cursor(group, collection["businessDate"], item)
        result["sent"] += 1
        result["lastMerchantId"] = item["merchantId"]
    return result | {"ok": True, "verified": True, "mode": "execute"}
