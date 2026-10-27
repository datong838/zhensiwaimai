#!/usr/bin/env python3
"""Deterministic, receipt-backed sender for an already logged-in Mac WeChat."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image, ImageChops

import wechat_desktop as wd
import desktop_preflight as shared_preflight
from wechat_interaction_lock import InteractionLockTimeout, WeChatInteractionLock


class StopRun(RuntimeError):
    pass


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def payload_identity(group: str, kind: str, items: list[str]) -> tuple[str, list[dict]]:
    payloads = []
    for item in items:
        if kind == "text":
            payloads.append({"text": item, "sha256": sha256_bytes(item.encode("utf-8"))})
        else:
            path = Path(item).expanduser().resolve()
            if not path.is_file():
                raise StopRun(f"payload-file-missing:{path}")
            payloads.append({
                "path": str(path), "name": path.name, "size": path.stat().st_size,
                "sha256": sha256_bytes(path.read_bytes()),
            })
    canonical = json.dumps({"group": group, "kind": kind, "payloads": payloads}, ensure_ascii=False, sort_keys=True)
    return sha256_bytes(canonical.encode("utf-8")), payloads


def exact_group(value: str, expected: str) -> bool:
    return wd.exact_group_text(value, expected)


def file_preview_prefix(name: str) -> str:
    return Path(name).stem.split("_", 1)[0]


def set_text_clipboard(value: str) -> None:
    # pbcopy replaces the pasteboard with plain text. AppleScript's
    # `set the clipboard` may preserve stale file flavors from an earlier
    # file-send workflow, causing WeChat to paste attachments instead.
    proc = subprocess.run(["/usr/bin/pbcopy"], input=value, text=True, capture_output=True)
    if proc.returncode:
        raise StopRun("text-clipboard-failed")


def focused_text_value() -> str:
    script = '''tell application "System Events"
tell process "WeChat"
set fe to value of attribute "AXFocusedUIElement"
if role of fe is not "AXTextArea" then return "__NOT_TEXT_AREA__"
return value of fe
end tell
end tell'''
    proc = subprocess.run(["osascript", "-e", script], text=True, capture_output=True)
    if proc.returncode:
        raise StopRun("desktop-text-input-readback-failed")
    return proc.stdout.rstrip("\n")


def set_focused_text(value: str) -> None:
    script = '''on run argv
tell application "System Events"
tell process "WeChat"
set fe to value of attribute "AXFocusedUIElement"
if role of fe is not "AXTextArea" then error "not text area"
set value of fe to item 1 of argv
end tell
end tell
end run'''
    proc = subprocess.run(["/usr/bin/osascript", "-", value], input=script, text=True, capture_output=True)
    if proc.returncode:
        raise StopRun("desktop-text-input-write-failed")


def focus_chat_input() -> None:
    script = '''tell application "System Events" to tell process "WeChat"
set mains to (every window whose name is "微信")
if (count of mains) is not 1 then error "wechat-main-window-count-not-one"
set xs to entire contents of item 1 of mains
set candidates to {}
repeat with e in xs
try
set s to size of e
if role of e is "AXTextArea" and item 1 of s > 400 and item 2 of s > 40 then set end of candidates to e
end try
end repeat
if count of candidates is not 1 then error "wechat-chat-input-count-not-one"
set target to item 1 of candidates
set value of attribute "AXFocused" of target to true
set fe to value of attribute "AXFocusedUIElement"
set fs to size of fe
if role of fe is not "AXTextArea" or item 1 of fs <= 400 or item 2 of fs <= 40 then error "wechat-chat-input-focus-readback-failed"
return "ok"
end tell'''
    proc = subprocess.run(["osascript", "-e", script], text=True, capture_output=True)
    if proc.returncode or proc.stdout.strip() != "ok":
        raise StopRun("desktop-chat-input-focus-failed")


def chat_input_empty() -> bool:
    for attempt in range(2):
        try:
            focus_chat_input()
            time.sleep(.1)
            if focused_text_value() == "":
                return True
        except StopRun:
            if attempt == 1:
                raise
        time.sleep(.15)
    return False


def normalize_empty_composer() -> bool:
    value = focused_text_value()
    if value == "":
        return True
    if value.strip() != "":
        return False
    set_focused_text("")
    time.sleep(.1)
    return focused_text_value() == ""


def set_file_clipboard(paths: list[str]) -> None:
    from AppKit import NSPasteboard
    from Foundation import NSURL

    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    urls = [NSURL.fileURLWithPath_(str(Path(value).resolve())) for value in paths]
    if not pasteboard.writeObjects_(urls):
        raise StopRun("file-clipboard-failed")
    items = list(pasteboard.pasteboardItems() or [])
    if len(items) != len(paths) or any("public.file-url" not in list(item.types()) for item in items):
        raise StopRun("file-clipboard-type-readback-failed")


def set_png_clipboard(path: str) -> None:
    script = """on run argv
set pngData to (read (POSIX file (item 1 of argv)) as «class PNGf»)
set the clipboard to pngData
end run
"""
    proc = subprocess.run(["osascript", "-", path], input=script, text=True, capture_output=True)
    if proc.returncode:
        raise StopRun("png-clipboard-failed")


def key(code: str) -> None:
    binary = Path(__file__).with_name("cgevent_key_bin")
    if not binary.is_file():
        raise StopRun("cgevent-key-binary-missing")
    proc = subprocess.run([str(binary), code], text=True, capture_output=True)
    if proc.returncode:
        raise StopRun(f"key-{code}-failed")


def press_send_button() -> None:
    script = '''tell application "System Events" to tell process "WeChat"
set frontmost to true
set mains to (every window whose name is "微信")
if (count of mains) is not 1 then error "wechat-main-window-count-not-one"
set xs to entire contents of item 1 of mains
set candidates to {}
repeat with e in xs
try
if role of e is "AXButton" and title of e is "发送" and enabled of e is true then set end of candidates to e
end try
end repeat
if count of candidates is not 1 then error "wechat-send-button-count-not-one"
set target to item 1 of candidates
set p to position of target
set s to size of target
return ((item 1 of p) + ((item 1 of s) / 2) as text) & "," & ((item 2 of p) + ((item 2 of s) / 2) as text)
end tell'''
    proc = subprocess.run(["osascript", "-e", script], text=True, capture_output=True)
    if proc.returncode:
        raise StopRun("desktop-send-button-press-failed")
    try:
        x, y = (float(value) for value in proc.stdout.strip().split(","))
    except (ValueError, TypeError):
        raise StopRun("desktop-send-button-position-invalid")
    # Activation and click must stay in the same CGEvent helper invocation.
    # A separate AX `frontmost` request can lose the race to another process
    # before the physical click is posted.
    wd.click(x, y, activate=True, scale=1.0)


def image_size(path: Path) -> tuple[int, int]:
    proc = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)], text=True, capture_output=True)
    width = re.search(r"pixelWidth: (\d+)", proc.stdout)
    height = re.search(r"pixelHeight: (\d+)", proc.stdout)
    if not width or not height:
        raise StopRun("window-screenshot-size-missing")
    return int(width.group(1)), int(height.group(1))


def changed_pixels(left: Path, right: Path, crop: tuple[int, int, int, int]) -> int:
    with Image.open(left).convert("RGB") as a, Image.open(right).convert("RGB") as b:
        if a.size != b.size:
            raise StopRun("desktop-evidence-geometry-mismatch")
        diff = ImageChops.difference(a.crop(crop), b.crop(crop))
        return sum(1 for pixel in diff.getdata() if max(pixel) > 8)


def verify_group(path: Path, group: str) -> None:
    matches = wd.find_exact_headers(wd.ocr(path), group)
    if len(matches) != 1:
        raise StopRun(f"desktop-group-title-not-unique:{len(matches)}")


def claim(ledger: Path, identity: str, receipt: dict, marker_name: str | None = None) -> Path:
    ledger.mkdir(parents=True, exist_ok=True, mode=0o700)
    marker = ledger / (marker_name or f"{identity}.json")
    try:
        with marker.open("x", encoding="utf-8") as stream:
            os.chmod(marker, 0o600)
            json.dump(receipt | {"state": "attempted", "attemptedAt": time.time()}, stream, ensure_ascii=False)
            stream.flush(); os.fsync(stream.fileno())
    except FileExistsError as exc:
        raise StopRun("desktop-send-already-attempted") from exc
    return marker


def atomic_write(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(temporary, 0o600); os.replace(temporary, path)


SEND_STAGE_ORDER = (
    "resource_wait", "locate_group", "verify_target_and_input",
    "prepare_payload", "claim_and_send", "post_send_verify",
)
SEND_STAGE_LABELS = {
    "resource_wait": "微信交互资源等待",
    "locate_group": "精确定位目标群",
    "verify_target_and_input": "复核目标群与输入框",
    "prepare_payload": "准备并复核发送载荷",
    "claim_and_send": "领取防重账本并单次发送",
    "post_send_verify": "发送后双帧复核",
}


def finalize_send_review(result: dict) -> None:
    stage_ms = result.setdefault("stageMs", {})
    order = {stage: index for index, stage in enumerate(SEND_STAGE_ORDER)}
    rows = []
    for index, (stage, elapsed_ms) in enumerate(sorted(stage_ms.items(), key=lambda item: (order.get(item[0], 999), item[0]))):
        if not isinstance(elapsed_ms, int) or elapsed_ms < 0:
            raise StopRun(f"send-review-stage-time-invalid:{stage}")
        pitfalls = []
        if result.get("ok") is not True and result.get("stage") == stage and result.get("reason"):
            pitfalls.append({"code": "send-failure", "reason": result["reason"]})
        rows.append({
            "item": index + 1,
            "stage": stage,
            "label": SEND_STAGE_LABELS.get(stage, stage),
            "elapsedMs": elapsed_ms,
            "status": "failed" if pitfalls else "completed",
            "pitfalls": pitfalls,
        })
    result["sendReview"] = rows
    result["reviewSummary"] = {
        "totalElapsedMs": result.get("elapsedMs", 0),
        "itemCount": len(rows),
        "pitfallCount": sum(len(row["pitfalls"]) for row in rows),
        "result": "success" if result.get("ok") is True else "failed",
    }


def _send_locked(args: argparse.Namespace) -> dict:
    started = time.monotonic()
    t = started
    out = Path(args.output_dir).resolve(); out.mkdir(parents=True, exist_ok=True, mode=0o700)
    result = {"ok": False, "executor": "wechat-desktop-sender", "channel": "desktop", "groupName": args.group,
              "payloadType": args.payload_type, "sendAttempts": 0, "runtimeModelDecisions": 0,
              "stage": "preflight", "stageMs": {}}
    marker = None
    try:
        identity, payloads = payload_identity(args.group, args.payload_type, args.item)
        result.update(payloadIdentity=identity, payloads=payloads)
        if not args.execute:
            result.update(ok=True, mode="dry-run")
            return result
        if not args.authorization:
            raise StopRun("standing-authorization-missing")
        result["stage"] = "locate_group"
        t = time.monotonic(); opened = shared_preflight.run_exact_group_preflight(
            args.group, out, locator=wd, acquire_lock=False)
        result["stageMs"]["locate_group"] = round((time.monotonic() - t) * 1000)
        result["groupPreflight"] = opened
        if opened.get("ok") is not True:
            raise StopRun(f"desktop-open-group:{opened.get('reason') or opened.get('note')}")
        result["stage"] = "verify_target_and_input"
        t = time.monotonic()
        before = out / "before-send.png"; wd.screenshot_main_region(before); verify_group(before, args.group)
        width, height = image_size(before)
        # AX can read an obscured main window, but WeChat will not grant focus to
        # its composer while the application is backgrounded.  Activation is
        # delayed until a non-empty authorized payload is ready, keeping the
        # read-only group preflight fully background-safe.
        wd.activate_wechat()
        focus_chat_input(); time.sleep(.3)
        if not normalize_empty_composer():
            raise StopRun("desktop-chat-input-not-empty")
        result["stageMs"]["verify_target_and_input"] = round((time.monotonic() - t) * 1000)
        result["stage"] = "prepare_payload"
        t = time.monotonic()
        if args.payload_type == "text":
            set_text_clipboard("")
            for write_attempt in range(3):
                if write_attempt:
                    set_focused_text(""); time.sleep(.2)
                    focus_chat_input(); time.sleep(.2)
                set_focused_text(args.item[0])
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    time.sleep(.2)
                    if focused_text_value() == args.item[0]:
                        result["textInputVerified"] = True
                        result["textWriteAttempts"] = write_attempt + 1
                        break
                if result.get("textInputVerified"):
                    break
            if result.get("textInputVerified") is not True:
                raise StopRun("desktop-text-input-readback-mismatch")
            result["clipboardClearedBeforeTextWrite"] = True
        elif args.payload_type == "image" and len(payloads) == 1 and Path(payloads[0]["path"]).suffix.lower() == ".png":
            set_png_clipboard(payloads[0]["path"])
            key("paste"); time.sleep(.8)
        else:
            set_file_clipboard([p["path"] for p in payloads]); key("paste"); time.sleep(.8)
        prepared = out / "prepared.png"; wd.screenshot_main_region(prepared); verify_group(prepared, args.group)
        # WeChat 4.x image bubbles can extend below 74% of the window. Keep the
        # input evidence in the actual bottom composer band so a newly sent
        # bubble is not mistaken for a retained preview.
        input_crop = (int(width * .28), int(height * .82), width, height)
        chat_crop = (int(width * .28), int(height * .08), width, int(height * .82))
        prepared_delta = changed_pixels(before, prepared, input_crop)
        result["preparedInputChangedPixels"] = prepared_delta
        result["stageMs"]["prepare_payload"] = round((time.monotonic() - t) * 1000)
        if args.payload_type == "image" and prepared_delta < 10000:
            raise StopRun("desktop-image-preview-not-prepared")
        if args.payload_type == "file":
            prepared_visible = "".join(
                h.text for h in wd.ocr(prepared)
                if h.cx > width * .28 and h.cy > height * .70
            )
            prepared_value = focused_text_value()
            result["preparedFileObjectCount"] = prepared_value.count("\ufffc")
            result["preparedFilePrefixesVerified"] = all(file_preview_prefix(p["name"]) in prepared_visible for p in payloads)
            if prepared_delta < 10000 or prepared_value != "\ufffc" * len(payloads) or result["preparedFilePrefixesVerified"] is not True:
                raise StopRun("desktop-file-preview-not-prepared")
        result["stage"] = "claim_and_send"
        t = time.monotonic()
        marker = claim(Path(args.ledger).expanduser().resolve(), identity, result, args.marker_name)
        result["attemptMarker"] = str(marker); result["sendAttempts"] = 1
        press_send_button()
        result["stageMs"]["claim_and_send"] = round((time.monotonic() - t) * 1000)
        result["stage"] = "post_send_verify"
        t = time.monotonic()
        signatures = []
        for index in range(2):
            time.sleep(1.2)
            shot = out / f"after-send-{index + 1}.png"; wd.screenshot_main_region(shot); verify_group(shot, args.group)
            hits = wd.ocr(shot)
            visible = "".join(
                h.text for h in hits
                if h.cx > width * .28 and 260 < h.cy < height * .82
            )
            input_cleared = chat_input_empty()
            result.setdefault("postSendInputCleared", []).append(input_cleared)
            if args.payload_type == "text":
                probes = [line.strip() for line in args.item[0].splitlines() if line.strip()]
                ok = (
                    input_cleared
                    and bool(probes)
                    and sum(probe in visible for probe in probes) >= max(1, len(probes) - 1)
                )
            elif args.payload_type == "file":
                ok = input_cleared and all(file_preview_prefix(p["name"]) in visible for p in payloads)
            else:
                body_delta = changed_pixels(before, shot, chat_crop)
                input_delta = changed_pixels(before, shot, input_crop)
                result.setdefault("postSendEvidence", []).append({"chatChangedPixels": body_delta, "inputChangedPixels": input_delta})
                ok = (
                    body_delta >= 10000
                    and input_cleared
                    and input_delta < max(7500, int(prepared_delta * .65))
                )
            signatures.append(ok)
        result["stageMs"]["post_send_verify"] = round((time.monotonic() - t) * 1000)
        if signatures != [True, True]:
            raise StopRun("desktop-post-send-verification-unknown")
        verified = result | {"ok": True, "verified": True, "state": "verified", "verifiedAt": time.time()}
        atomic_write(marker, verified)
        result.update(ok=True, verified=True, state="verified", stage="completed")
    except Exception as exc:
        active_stage = result.get("stage")
        if active_stage not in (None, "preflight", "completed") and active_stage not in result["stageMs"]:
            result["stageMs"][active_stage] = round((time.monotonic() - t) * 1000)
        if marker is not None:
            result["postSendFailureReason"] = str(exc)
            result["reason"] = "desktop-post-send-verification-unknown"
            result["state"] = "unknown"
            atomic_write(marker, result)
        else:
            result["reason"] = str(exc)
    finally:
        result["elapsedMs"] = round((time.monotonic() - started) * 1000)
        finalize_send_review(result)
        if marker is not None:
            atomic_write(marker, result)
        atomic_write(out / "receipt.json", result)
    return result


def send(args: argparse.Namespace) -> dict:
    lease = WeChatInteractionLock(f"sender:{os.getpid()}:{time.time_ns()}")
    try:
        lease.acquire()
    except InteractionLockTimeout as error:
        result = {
            "ok": False, "verified": False, "executor": "wechat-desktop-sender",
            "channel": "desktop", "groupName": args.group, "payloadType": args.payload_type,
            "stage": "resource_wait", "reason": str(error), "sendAttempts": 0,
            "runtimeModelDecisions": 0, "interactionLock": lease.receipt(),
        }
        result["stageMs"] = {"resource_wait": int(result["interactionLock"].get("waitMs") or 0)}
        result["elapsedMs"] = result["stageMs"]["resource_wait"]
        finalize_send_review(result)
        out = Path(args.output_dir).resolve(); out.mkdir(parents=True, exist_ok=True, mode=0o700)
        atomic_write(out / "receipt.json", result)
        return result
    try:
        result = _send_locked(args)
    finally:
        lease.release()
    result["interactionLock"] = lease.receipt()
    atomic_write(Path(args.output_dir).resolve() / "receipt.json", result)
    return result


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument("--group", required=True); p.add_argument("--payload-type", choices=("text", "image", "file"), required=True)
    p.add_argument("--item", action="append", required=True); p.add_argument("--authorization")
    p.add_argument("--ledger", required=True); p.add_argument("--output-dir", required=True); p.add_argument("--execute", action="store_true")
    p.add_argument("--marker-name")
    return p


if __name__ == "__main__":
    receipt = send(parser().parse_args()); print(json.dumps(receipt, ensure_ascii=False)); sys.exit(0 if receipt.get("ok") else 1)
