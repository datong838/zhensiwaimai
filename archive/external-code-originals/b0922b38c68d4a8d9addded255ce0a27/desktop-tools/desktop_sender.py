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

# This is an existence signal, not a readability/clarity score. Keep it
# relative to the composer crop so window scale and renderer differences do
# not reject a clearly visible preview.
MIN_IMAGE_PREVIEW_PIXELS = 3000
MIN_IMAGE_PREVIEW_RATIO = 0.0015


class StopRun(RuntimeError):
    pass


def _ax_module():
    import ApplicationServices as AX
    return AX


def _ax_set(element, attribute, value) -> int:
    return _ax_module().AXUIElementSetAttributeValue(element, attribute, value)


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


def file_preview_size(size: int) -> str:
    if size < 1024:
        return f"{size}B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f}K"
    return f"{size / (1024 * 1024):.1f}M"


def file_preview_visible(name: str, size: int, visible: str) -> bool:
    prefix = file_preview_prefix(name)
    if prefix in visible:
        return True
    stem, suffix = Path(name).stem, Path(name).suffix
    # WeChat shortens long attachment names in the composer and message bubble.
    # Accept only a strong paired anchor plus the exact displayed size; never a
    # lone prefix or suffix.  The source file remains hash-bound by the receipt.
    return len(stem) >= 8 and stem[:6] in visible and f"{stem[-2:]}{suffix}" in visible and file_preview_size(size) in visible


def prior_zero_attempt_prepared_matches(out: Path, identity: str, group: str, payloads: list[dict]) -> bool:
    try:
        prior = json.loads((out / "receipt.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    keys = ("name", "size", "sha256")
    return (
        prior.get("groupName") == group
        and prior.get("payloadIdentity") == identity
        and prior.get("sendAttempts") == 0
        and prior.get("reason") == "desktop-file-preview-not-prepared"
        and prior.get("uncommittedPreviewCleanup") == "failed"
        and len(prior.get("payloads") or []) == len(payloads)
        and all(all(left.get(key) == right.get(key) for key in keys)
                for left, right in zip(prior.get("payloads") or [], payloads))
    )


def set_text_clipboard(value: str) -> None:
    # pbcopy replaces the pasteboard with plain text. AppleScript's
    # `set the clipboard` may preserve stale file flavors from an earlier
    # file-send workflow, causing WeChat to paste attachments instead.
    proc = subprocess.run(["/usr/bin/pbcopy"], input=value, text=True, capture_output=True)
    if proc.returncode:
        raise StopRun("text-clipboard-failed")


def focused_text_value() -> str:
    # Accessibility (AX) instead of "System Events": the AX C API does not
    # require the macOS Automation permission, which an unattended daemon or an
    # embedded agent shell is denied (-10004).
    import ApplicationServices as AX
    app = wd.wechat_ax_application(AX)
    focused = wd.ax_attribute(AX, app, AX.kAXFocusedUIElementAttribute)
    if focused is None:
        raise StopRun("desktop-text-input-readback-failed")
    if wd.ax_attribute(AX, focused, AX.kAXRoleAttribute, "") != "AXTextArea":
        return "__NOT_TEXT_AREA__"
    value = wd.ax_attribute(AX, focused, AX.kAXValueAttribute, "")
    return "" if value is None else str(value)


def set_focused_text(value: str) -> None:
    import ApplicationServices as AX
    app = wd.wechat_ax_application(AX)
    focused = wd.ax_attribute(AX, app, AX.kAXFocusedUIElementAttribute)
    role = wd.ax_attribute(AX, focused, AX.kAXRoleAttribute, "") if focused is not None else ""
    if focused is None or role != "AXTextArea":
        error = StopRun("desktop-text-input-write-failed")
        error.diagnostics = {"reason": "focused-element-not-text-area"}
        raise error
    ax_error = _ax_set(focused, AX.kAXValueAttribute, value)
    if ax_error != AX.kAXErrorSuccess:
        # AX may apply the value and still report a transient error while
        # unwinding. Only native, exact readback can distinguish that from a
        # failed/partial write; never infer success from the screenshot.
        try:
            if focused_text_value() == value:
                return
        except StopRun:
            pass
        error = StopRun("desktop-text-input-write-failed")
        error.diagnostics = {"axError": ax_error}
        raise error


def _focused_text_area_candidates(ax):
    """Unique composer text area (AXTextArea > 400x40) inside the main window."""
    app = wd.wechat_ax_application(ax)
    main, _ = wd.ax_main_window(ax, app)
    candidates = []
    for element in wd.ax_descendants(ax, main):
        if wd.ax_attribute(ax, element, ax.kAXRoleAttribute, "") != "AXTextArea":
            continue
        size = wd.ax_size(ax, element)
        if size and size[0] > 400 and size[1] > 40:
            candidates.append(element)
    return app, candidates


def focus_chat_input() -> None:
    import ApplicationServices as AX
    try:
        app, candidates = _focused_text_area_candidates(AX)
    except RuntimeError as error:
        raise StopRun("desktop-chat-input-focus-failed") from error
    if len(candidates) != 1:
        raise StopRun("desktop-chat-input-focus-failed")
    target = candidates[0]
    _ax_set(target, AX.kAXFocusedAttribute, True)
    focused = wd.ax_attribute(AX, app, AX.kAXFocusedUIElementAttribute)
    role = wd.ax_attribute(AX, focused, AX.kAXRoleAttribute, "") if focused is not None else ""
    size = wd.ax_size(AX, focused) if focused is not None else None
    if role != "AXTextArea" or not size or size[0] <= 400 or size[1] <= 40:
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
    from AppKit import NSData, NSPasteboard, NSPasteboardTypePNG
    data = NSData.dataWithContentsOfFile_(str(Path(path).resolve()))
    if data is None:
        raise StopRun("png-clipboard-failed")
    pasteboard = NSPasteboard.generalPasteboard()
    pasteboard.clearContents()
    if not pasteboard.setData_forType_(data, NSPasteboardTypePNG):
        raise StopRun("png-clipboard-failed")


def cancel_uncommitted_preview(result: dict) -> None:
    """Cancel a pasted-but-unattempted preview so failed runs leave no draft."""
    try:
        key("Escape")
        time.sleep(.2)
        result["uncommittedPreviewCleanup"] = "attempted"
        result["uncommittedPreviewCleared"] = chat_input_empty()
    except Exception as exc:
        result["uncommittedPreviewCleanup"] = "failed"
        result["uncommittedPreviewCleanupReason"] = str(exc)


def key(code: str) -> None:
    binary = Path(__file__).with_name("cgevent_key_bin")
    if not binary.is_file():
        raise StopRun("cgevent-key-binary-missing")
    proc = subprocess.run([str(binary), code], text=True, capture_output=True)
    if proc.returncode:
        raise StopRun(f"key-{code}-failed")


def _enabled_send_buttons(ax):
    """Enabled 发送 AXButtons inside the unique WeChat main window."""
    app = wd.wechat_ax_application(ax)
    main, _ = wd.ax_main_window(ax, app)
    buttons = []
    for element in wd.ax_descendants(ax, main):
        if wd.ax_attribute(ax, element, ax.kAXRoleAttribute, "") != "AXButton":
            continue
        if wd.ax_attribute(ax, element, ax.kAXTitleAttribute, "") != "发送":
            continue
        if wd.ax_attribute(ax, element, ax.kAXEnabledAttribute, False):
            buttons.append(element)
    return buttons


def press_send_button() -> None:
    import ApplicationServices as AX
    try:
        candidates = _enabled_send_buttons(AX)
    except RuntimeError as error:
        raise StopRun("desktop-send-button-press-failed") from error
    if len(candidates) != 1:
        raise StopRun("desktop-send-button-press-failed")
    target = candidates[0]
    position = wd.ax_position(AX, target)
    size = wd.ax_size(AX, target)
    if position is None or size is None:
        raise StopRun("desktop-send-button-position-invalid")
    x = position[0] + size[0] / 2
    y = position[1] + size[1] / 2
    # Activation and click must stay in the same CGEvent helper invocation.
    # A separate AX `frontmost` request can lose the race to another process
    # before the physical click is posted.
    wd.click(x, y, activate=True, scale=1.0)


def enabled_send_button_count() -> int:
    import ApplicationServices as AX
    try:
        return len(_enabled_send_buttons(AX))
    except RuntimeError as error:
        if "wechat-main-window-count-not-one" in str(error):
            return -1
        raise StopRun("desktop-send-button-readback-failed") from error


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


def verify_group(path: Path, group: str, opened: dict | None = None) -> None:
    matches = wd.find_exact_headers(wd.ocr(path), group)
    if len(matches) == 1:
        return
    section_proof = (len(matches) == 0 and opened is not None
                     and opened.get("note") == "exact-group-section-text-row"
                     and opened.get("group") == group
                     and wd.exact_group_text(opened.get("header") or "", group))
    if section_proof and wd.ax_confirms_raw_group_header(group):
        return
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
    preview_pasted = False
    existing_prepared_file = False
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
        before = out / "before-send.png"; wd.screenshot_main_region(before); verify_group(before, args.group, opened)
        width, height = image_size(before)
        # AX can read an obscured main window, but WeChat will not grant focus to
        # its composer while the application is backgrounded.  Activation is
        # delayed until a non-empty authorized payload is ready, keeping the
        # read-only group preflight fully background-safe.
        wd.activate_wechat()
        focus_chat_input(); time.sleep(.3)
        current_value = focused_text_value() if args.payload_type == "file" else ""
        if args.payload_type == "file" and current_value == "\ufffc" * len(payloads) and prior_zero_attempt_prepared_matches(out, identity, args.group, payloads):
            current_visible = "".join(
                h.text for h in wd.ocr(before)
                if h.cx > width * .28 and h.cy > height * .70
            )
            existing_prepared_file = (
                all(file_preview_visible(p["name"], p["size"], current_visible) for p in payloads)
                and enabled_send_button_count() == 1
            )
            if existing_prepared_file:
                result["existingPreparedFileVerified"] = True
                result["existingPreparedFileRecovery"] = "same-event-zero-send"
        if not existing_prepared_file and not normalize_empty_composer():
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
            key("paste"); preview_pasted = True; time.sleep(.8)
        elif not existing_prepared_file:
            set_file_clipboard([p["path"] for p in payloads]); key("paste"); preview_pasted = True; time.sleep(.8)
        prepared = out / "prepared.png"; wd.screenshot_main_region(prepared); verify_group(prepared, args.group, opened)
        # WeChat 4.x image bubbles can extend below 74% of the window. Keep the
        # input evidence in the actual bottom composer band so a newly sent
        # bubble is not mistaken for a retained preview.
        input_crop = (int(width * .28), int(height * .82), width, height)
        chat_crop = (int(width * .28), int(height * .08), width, int(height * .82))
        prepared_delta = changed_pixels(before, prepared, input_crop)
        result["preparedInputChangedPixels"] = prepared_delta
        input_area = max(1, (input_crop[2] - input_crop[0]) * (input_crop[3] - input_crop[1]))
        result["preparedInputChangedRatio"] = round(prepared_delta / input_area, 6)
        result["stageMs"]["prepare_payload"] = round((time.monotonic() - t) * 1000)
        preview_evidence_ok = existing_prepared_file or (
            prepared_delta >= MIN_IMAGE_PREVIEW_PIXELS
            and prepared_delta / input_area >= MIN_IMAGE_PREVIEW_RATIO
        )
        if args.payload_type == "image" and not preview_evidence_ok:
            raise StopRun("desktop-image-preview-not-prepared")
        if args.payload_type == "file":
            prepared_visible = "".join(
                h.text for h in wd.ocr(prepared)
                if h.cx > width * .28 and h.cy > height * .70
            )
            prepared_value = focused_text_value()
            result["preparedFileObjectCount"] = prepared_value.count("\ufffc")
            result["preparedFilePrefixesVerified"] = all(file_preview_visible(p["name"], p["size"], prepared_visible) for p in payloads)
            if not preview_evidence_ok or prepared_value != "\ufffc" * len(payloads) or result["preparedFilePrefixesVerified"] is not True:
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
            shot = out / f"after-send-{index + 1}.png"; wd.screenshot_main_region(shot); verify_group(shot, args.group, opened)
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
                ok = input_cleared and all(file_preview_visible(p["name"], p["size"], visible) for p in payloads)
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
        diagnostics = getattr(exc, "diagnostics", None)
        if diagnostics:
            result["textInputWriteDiagnostics"] = diagnostics
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
        if marker is None and preview_pasted:
            cancel_uncommitted_preview(result)
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
