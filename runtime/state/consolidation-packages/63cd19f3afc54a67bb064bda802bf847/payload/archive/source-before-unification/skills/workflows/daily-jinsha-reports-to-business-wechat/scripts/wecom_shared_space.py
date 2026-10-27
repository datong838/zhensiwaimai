#!/usr/bin/env python3
"""Deterministic WeCom WeDrive shared-space preflight and two-file import."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import Quartz
from AppKit import NSWorkspace

BUNDLE = "com.tencent.WeWorkMac"
APP_NAME = "企业微信"
OCR = Path("/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts/ocr_vision_bin")


class StopRun(RuntimeError):
    pass


@dataclass(frozen=True)
class Hit:
    x: float
    y: float
    w: float
    h: float
    confidence: float
    text: str


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("．", ".")


def canonical_document_name(value: str) -> str:
    """Normalize only punctuation OCR is known to vary; keep every word/date."""
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", compact(value)).casefold()


def document_names(files: list[Path]) -> list[str]:
    # WeCom converts local XLSX files to intelligent spreadsheets and removes
    # the extension from the document title.
    return [file.stem for file in files]


def parse_ocr(raw: str) -> list[Hit]:
    hits: list[Hit] = []
    for line in raw.splitlines():
        if line.count("\t") < 2:
            continue
        box, confidence, text = line.split("\t", 2)
        try:
            x, y, w, h = (float(value) for value in box.split(","))
            hits.append(Hit(x, y, w, h, float(confidence), text.strip()))
        except ValueError:
            continue
    return hits


def exact_count(hits: list[Hit], value: str) -> int:
    expected = compact(value)
    return sum(compact(hit.text) == expected for hit in hits)


def classify_space(hits: list[Hit], space: str, filenames: list[str]) -> dict:
    text = compact("\n".join(hit.text for hit in hits))
    canonical_text = canonical_document_name(text)
    markers = {name: name in text for name in ("文档", "微盘", "共享空间")}
    space_count = exact_count(hits, space)
    contained_space_count = sum(canonical_document_name(space) in canonical_document_name(hit.text) for hit in hits)
    present = [name for name in filenames if canonical_document_name(name) in canonical_text]
    return {
        # Vision regularly merges the selected left-row bullet with the title.
        # Require two standalone exact titles plus the third contained title;
        # never weaken the full space-name comparison itself.
        "isSpaceWindow": all(markers.values()) and space_count >= 2 and contained_space_count >= 3,
        "markers": markers,
        "spaceExactCount": space_count,
        "spaceEvidenceCount": contained_space_count,
        "present": present,
        "fileState": "complete" if len(present) == len(filenames) else ("partial" if present else "absent"),
    }


def running_pid() -> int:
    apps = [app for app in NSWorkspace.sharedWorkspace().runningApplications() if app.bundleIdentifier() == BUNDLE]
    if len(apps) != 1:
        raise StopRun("wecom-not-running" if not apps else "wecom-process-ambiguous")
    return int(apps[0].processIdentifier())


def windows(pid: int) -> list[dict]:
    options = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
    result = []
    for value in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID):
        bounds = value.get("kCGWindowBounds", {})
        if (int(value.get("kCGWindowOwnerPID", -1)) == pid and int(value.get("kCGWindowLayer", 1)) == 0
                and float(bounds.get("Width", 0)) >= 700 and float(bounds.get("Height", 0)) >= 500):
            result.append({
                "id": int(value["kCGWindowNumber"]),
                "name": str(value.get("kCGWindowName") or ""),
                "bounds": {key: float(bounds.get(key, 0)) for key in ("X", "Y", "Width", "Height")},
            })
    return result


def identity_windows(pid: int) -> list[dict]:
    options = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
    result = []
    for value in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID):
        bounds = value.get("kCGWindowBounds", {})
        if (int(value.get("kCGWindowOwnerPID", -1)) == pid and int(value.get("kCGWindowLayer", 1)) == 0
                and float(bounds.get("Width", 0)) >= 400 and float(bounds.get("Height", 0)) >= 300):
            result.append({"id": int(value["kCGWindowNumber"]), "bounds": {key: float(bounds.get(key, 0)) for key in ("X", "Y", "Width", "Height")}})
    return result


def popup_windows(pid: int) -> list[dict]:
    options = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
    result = []
    for value in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID):
        bounds = value.get("kCGWindowBounds", {})
        if (int(value.get("kCGWindowOwnerPID", -1)) == pid and int(value.get("kCGWindowLayer", 0)) > 0
                and float(bounds.get("Width", 0)) >= 200 and float(bounds.get("Height", 0)) >= 100):
            result.append({"id": int(value["kCGWindowNumber"]), "bounds": {key: float(bounds.get(key, 0)) for key in ("X", "Y", "Width", "Height")}})
    return result


def owner_windows(owner: str, *, min_width: int, min_height: int) -> list[dict]:
    options = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
    result = []
    for value in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID):
        bounds = value.get("kCGWindowBounds", {})
        if (str(value.get("kCGWindowOwnerName") or "") == owner and int(value.get("kCGWindowLayer", 1)) == 0
                and float(bounds.get("Width", 0)) >= min_width and float(bounds.get("Height", 0)) >= min_height):
            result.append({"id": int(value["kCGWindowNumber"]), "bounds": {key: float(bounds.get(key, 0)) for key in ("X", "Y", "Width", "Height")}})
    return result


def all_visible_windows(*, min_width: int = 350, min_height: int = 180) -> list[dict]:
    options = Quartz.kCGWindowListOptionAll | Quartz.kCGWindowListExcludeDesktopElements
    result = []
    for value in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID):
        bounds = value.get("kCGWindowBounds", {})
        if (int(value.get("kCGWindowLayer", 1)) >= 0 and float(bounds.get("Width", 0)) >= min_width
                and float(bounds.get("Height", 0)) >= min_height):
            result.append({"id": int(value["kCGWindowNumber"]), "owner": str(value.get("kCGWindowOwnerName") or ""),
                           "bounds": {key: float(bounds.get(key, 0)) for key in ("X", "Y", "Width", "Height")}})
    return result


def capture(window_id: int, destination: Path) -> list[Hit]:
    destination.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(["screencapture", "-x", "-o", "-l", str(window_id), str(destination)], capture_output=True, text=True)
    if proc.returncode or not destination.is_file():
        raise StopRun("wecom-window-capture-failed")
    proc = subprocess.run([str(OCR), str(destination)], capture_output=True, text=True)
    if proc.returncode:
        raise StopRun("wecom-window-ocr-failed")
    return parse_ocr(proc.stdout)


def image_size(path: Path) -> tuple[int, int]:
    proc = subprocess.run(["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(path)], capture_output=True, text=True)
    values = [int(value) for value in re.findall(r"(?:pixelWidth|pixelHeight):\s*(\d+)", proc.stdout)]
    if len(values) != 2:
        raise StopRun("wecom-capture-size-unreadable")
    return values[0], values[1]


def scan_space(space: str, filenames: list[str], artifacts: Path, sequence: str) -> list[tuple[dict, list[Hit], dict, Path]]:
    pid = running_pid()
    found = []
    for window in windows(pid):
        screenshot = artifacts / f"{sequence}-window-{window['id']}.png"
        hits = capture(window["id"], screenshot)
        state = classify_space(hits, space, filenames)
        if state["isSpaceWindow"]:
            found.append((window, hits, state, screenshot))
    return found


def login_state(pid: int, artifacts: Path) -> str:
    bodies = []
    for window in windows(pid):
        shot = artifacts / f"login-state-window-{window['id']}.png"
        hits = capture(window["id"], shot)
        bodies.append(compact("\n".join(hit.text for hit in hits)))
    body = "\n".join(bodies)
    if any(value in body for value in ("扫码登录", "手机号登录", "登录企业微信")) and "文档" not in body:
        return "logged-out"
    return "available"


def locate(space: str, filenames: list[str], artifacts: Path, sequence: str) -> tuple[dict, list[Hit], dict, Path]:
    found = scan_space(space, filenames, artifacts, sequence)
    if len(found) != 1:
        raise StopRun("wecom-shared-space-window-not-found" if not found else "wecom-shared-space-window-ambiguous")
    return found[0]


def documents_all_tabs(hits: list[Hit]) -> list[Hit]:
    return [hit for hit in hits
            if all(word in compact(hit.text) for word in ("与我相关", "智能文档", "智能表格", "全部"))
            and hit.y < 260]


def wait_for_documents_page(window: dict, artifacts: Path) -> tuple[list[Hit], Path]:
    """Wait for the exact documents toolbar instead of assuming a 1s switch."""
    deadline = time.monotonic() + 5.0
    attempt = 0
    last_hits: list[Hit] = []
    last_shot = artifacts / "navigation-documents.png"
    while time.monotonic() < deadline:
        attempt += 1
        time.sleep(.5)
        last_shot = artifacts / f"navigation-documents-{attempt}.png"
        last_hits = capture(window["id"], last_shot)
        if len(documents_all_tabs(last_hits)) == 1:
            return last_hits, last_shot
    raise StopRun("wecom-documents-page-not-ready")


def open_space(space: str, filenames: list[str], artifacts: Path) -> tuple[dict, list[Hit], dict, Path]:
    found = scan_space(space, filenames, artifacts, "initial")
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        raise StopRun("wecom-shared-space-window-ambiguous")
    pid = running_pid()
    if login_state(pid, artifacts) == "logged-out":
        raise StopRun("wecom-not-logged-in")
    document_entries = []
    for window in windows(pid):
        shot = artifacts / f"navigation-window-{window['id']}.png"
        hits = capture(window["id"], shot)
        matches = [hit for hit in hits if compact(hit.text) == "文档" and hit.x < 240 and hit.y < 1000]
        if len(matches) == 1:
            document_entries.append((window, hits, shot, matches[0]))
    if len(document_entries) != 1:
        raise StopRun("wecom-document-entry-not-unique")
    window, _, shot, document = document_entries[0]
    key(53)
    time.sleep(.2)
    raise_window(window)
    click_hit(window, shot, document)
    hits, after = wait_for_documents_page(window, artifacts)
    candidates = [hit for hit in hits if compact(space) in compact(hit.text) and hit.x < 900 and hit.y > 250]
    if not candidates:
        all_tabs = documents_all_tabs(hits)
        if len(all_tabs) != 1:
            raise StopRun("wecom-documents-all-tab-not-unique")
        click_hit(window, after, all_tabs[0], fraction_x=.93)
        time.sleep(.8)
        after = artifacts / "navigation-all.png"
        hits = capture(window["id"], after)
        candidates = [hit for hit in hits if compact(space) in compact(hit.text) and hit.x < 900 and hit.y > 250]
    if candidates:
        if len(candidates) != 1:
            raise StopRun("wecom-shared-space-entry-ambiguous")
        click_hit(window, after, candidates[0])
        time.sleep(.8)
    else:
        raise StopRun("wecom-shared-space-entry-not-found")
    return locate(space, filenames, artifacts, "opened")


def raise_window(window: dict) -> None:
    width = int(window["bounds"]["Width"])
    height = int(window["bounds"]["Height"])
    script = f'''tell application "System Events" to tell process "{APP_NAME}"
set candidates to every window
set matched to {{}}
repeat with w in candidates
set s to size of w
if (item 1 of s) is {width} and (item 2 of s) is {height} then set end of matched to w
end repeat
if (count of matched) is not 1 then error "wecom-window-bounds-not-unique"
set frontmost to true
try
perform action "AXRaise" of item 1 of matched
end try
end tell'''
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if proc.returncode:
        raise StopRun("wecom-window-raise-failed")
    time.sleep(0.35)


def click_point(x: float, y: float) -> None:
    for event_type in (Quartz.kCGEventLeftMouseDown, Quartz.kCGEventLeftMouseUp):
        event = Quartz.CGEventCreateMouseEvent(None, event_type, (x, y), Quartz.kCGMouseButtonLeft)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(0.04)


def click_hit(window: dict, screenshot: Path, hit: Hit, *, fraction_x: float = .5) -> None:
    pixel_width, pixel_height = image_size(screenshot)
    bounds = window["bounds"]
    scale_x, scale_y = pixel_width / bounds["Width"], pixel_height / bounds["Height"]
    left_px = hit.x - hit.w / 2
    click_point(bounds["X"] + (left_px + hit.w * fraction_x) / scale_x, bounds["Y"] + hit.y / scale_y)


def unique_hit(hits: list[Hit], predicate, error: str) -> Hit:
    matches = [hit for hit in hits if predicate(hit)]
    if len(matches) != 1:
        raise StopRun(error)
    return matches[0]


def key(code: int, flags: int = 0) -> None:
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(source, code, down)
        Quartz.CGEventSetFlags(event, flags)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(.05)


def type_unicode(value: str) -> None:
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    # CGEvent unicode payloads are bounded. Chunking also preserves underscores
    # that high-level synthetic typing can otherwise drop.
    for offset in range(0, len(value), 16):
        chunk = value[offset:offset + 16]
        event = Quartz.CGEventCreateKeyboardEvent(source, 0, True)
        Quartz.CGEventKeyboardSetUnicodeString(event, len(chunk), chunk)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        event = Quartz.CGEventCreateKeyboardEvent(source, 0, False)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        time.sleep(.02)


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        temp = Path(handle.name)
    os.replace(temp, path)


def verify_identity(window: dict, screenshot: Path, hits: list[Hit], enterprise: str, artifacts: Path) -> Path:
    # The profile popup truncates the organization label. Use it only as the
    # deterministic entry, then require the full name and certification state.
    visible_prefix = compact(enterprise)[:-3]
    key(53)
    time.sleep(.2)
    raise_window(window)
    bounds = window["bounds"]
    click_point(bounds["X"] + 30, bounds["Y"] + 42)
    time.sleep(.6)
    popup = artifacts / "enterprise-profile-entry.png"
    popup_hits = capture(window["id"], popup)
    body = compact("\n".join(hit.text for hit in popup_hits))
    if visible_prefix not in body:
        raise StopRun("wecom-enterprise-identity-mismatch")
    entry = unique_hit(popup_hits, lambda h: visible_prefix in compact(h.text), "wecom-enterprise-entry-not-unique")
    click_hit(window, popup, entry)
    matches = []
    for attempt in range(1, 9):
        time.sleep(.75)
        pid = running_pid()
        matches = []
        for candidate in identity_windows(pid):
            shot = artifacts / f"enterprise-detail-{attempt}-{candidate['id']}.png"
            current = capture(candidate["id"], shot)
            texts = [compact(hit.text) for hit in current]
            if exact_count(current, enterprise) >= 1 and any("已认证" in value for value in texts):
                matches.append(shot)
        if len(matches) == 1:
            break
    key(53)
    if len(matches) != 1:
        raise StopRun("wecom-enterprise-detail-not-exact" if not matches else "wecom-enterprise-detail-ambiguous")
    return matches[0]


def make_staging(files: list[Path], root: Path) -> Path:
    staging = root / "upload-staging"
    staging.mkdir(parents=True, exist_ok=True)
    for file in files:
        destination = staging / file.name
        if destination.exists():
            if destination.is_symlink() or sha256(destination) != sha256(file):
                raise StopRun("wecom-upload-staging-conflict")
        else:
            shutil.copy2(file.resolve(), destination)
    return staging


def open_panel_state() -> tuple[str, bool]:
    """Read the protected macOS open panel through AX, never screenshot OCR."""
    script = f'''tell application "System Events"
tell process "{APP_NAME}"
set matches to every window whose name is "{APP_NAME}"
if (count of matches) is not 1 then error "wecom-main-window-not-unique"
set w to item 1 of matches
if (count of sheets of w) is not 1 then error "wecom-open-sheet-not-unique"
set s to first sheet of w
if (count of sheets of s) is not 0 then error "wecom-go-to-sheet-still-open"
set locationButtons to every pop up button of s whose name is "位置："
set openButtons to every button of s whose name is "打开"
if (count of locationButtons) is not 1 or (count of openButtons) is not 1 then error "wecom-open-panel-controls-not-unique"
return (value of item 1 of locationButtons as text) & linefeed & (enabled of item 1 of openButtons as text)
end tell
end tell'''
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    values = [value.strip() for value in proc.stdout.splitlines() if value.strip()]
    if proc.returncode or len(values) != 2 or values[1] not in ("true", "false"):
        raise StopRun("wecom-open-panel-structure-unreadable")
    return values[0], values[1] == "true"


def wait_for_open_panel_location(expected: str) -> tuple[str, bool]:
    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        time.sleep(.25)
        try:
            state = open_panel_state()
        except StopRun:
            continue
        if compact(state[0]) == compact(expected):
            return state
    raise StopRun("wecom-open-panel-navigation-not-confirmed")


def main_window_sheet_count() -> int:
    script = f'''tell application "System Events"
tell process "{APP_NAME}"
set matches to every window whose name is "{APP_NAME}"
if (count of matches) is not 1 then error "wecom-main-window-not-unique"
return count of sheets of item 1 of matches
end tell
end tell'''
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    value = proc.stdout.strip()
    if proc.returncode or not value.isdigit():
        raise StopRun("wecom-sheet-count-unreadable")
    return int(value)


def close_pre_attempt_panels(artifacts: Path) -> None:
    """Clear only modal sheets left by a pre-attempt failure."""
    for _ in range(4):
        if main_window_sheet_count() == 0:
            return
        pid = running_pid()
        candidates = [window for window in windows(pid) if window["name"] == APP_NAME]
        if len(candidates) != 1:
            raise StopRun("wecom-main-window-not-unique")
        raise_window(candidates[0])
        key(53)
        time.sleep(.45)
    if main_window_sheet_count() != 0:
        raise StopRun("wecom-stale-open-panel-not-closed")


def read_marker(marker: Path) -> dict:
    try:
        value = json.loads(marker.read_text())
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def confirm_marker(marker: Path, files: list[Path], frames: list[str], *, recovered: bool) -> dict:
    previous = read_marker(marker)
    value = {
        **previous,
        "state": "confirmed",
        "confirmedAt": previous.get("confirmedAt", time.time()),
        "files": [file.name for file in files],
        "documentNames": document_names(files),
        "uploadAttempts": int(previous.get("uploadAttempts", 0)),
        "recovered": bool(previous.get("recovered", False) or recovered),
        "lastVerifiedAt": time.time(),
        "verifiedFrames": frames,
    }
    atomic_json(marker, value)
    return value


def privacy_gate_visible(artifacts: Path) -> bool:
    # Only inspect known macOS consent surfaces. Never OCR unrelated apps.
    allowed_owners = {"SecurityAgent", "CoreServicesUIAgent", "UserNotificationCenter", "Open and Save Panel Service"}
    for candidate in all_visible_windows():
        if candidate["owner"] not in allowed_owners:
            continue
        shot = artifacts / f"privacy-scan-{candidate['id']}.png"
        try:
            hits = capture(candidate["id"], shot)
        except StopRun:
            continue
        body = compact("\n".join(hit.text for hit in hits))
        if "想访问其他App的数据" in body or "想要访问其他App的数据" in body:
            return True
    return False


def import_two(window: dict, hits: list[Hit], screenshot: Path, files: list[Path], marker: Path, artifacts: Path) -> None:
    key(53)
    time.sleep(.2)
    raise_window(window)
    import_hit = unique_hit(hits, lambda h: "导入" in compact(h.text) and h.y < 140 and h.x > 900, "wecom-import-entry-not-unique")
    # Vision may merge several toolbar items; derive Import's position from its
    # character offset instead of using a fixed desktop coordinate.
    toolbar = compact(import_hit.text)
    offset = toolbar.index("导入")
    fraction = (offset + 1) / max(1, len(toolbar))
    click_hit(window, screenshot, import_hit, fraction_x=fraction)
    time.sleep(.55)
    menu_matches = []
    for candidate in popup_windows(running_pid()):
        menu_shot = artifacts / f"import-menu-{candidate['id']}.png"
        menu_hits = capture(candidate["id"], menu_shot)
        local = [hit for hit in menu_hits if compact(hit.text).endswith("导入本地文件")]
        if len(local) == 1:
            menu_matches.append((candidate, menu_shot, local[0]))
    if len(menu_matches) != 1:
        raise StopRun("wecom-import-local-file-not-unique")
    menu_window, menu_shot, local = menu_matches[0]
    click_hit(menu_window, menu_shot, local)
    time.sleep(.8)
    staging = make_staging(files, artifacts)
    panels = owner_windows("Open and Save Panel Service", min_width=600, min_height=350)
    if len(panels) != 1:
        if privacy_gate_visible(artifacts):
            raise StopRun("wecom-macos-open-panel-privacy-gate")
        raise StopRun("wecom-open-panel-not-unique")
    panel = panels[0]
    bounds = panel["bounds"]
    click_point(bounds["X"] + bounds["Width"] * .58, bounds["Y"] + bounds["Height"] * .45)
    time.sleep(.2)
    key(5, Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift)
    time.sleep(.35)
    key(0, Quartz.kCGEventFlagMaskCommand)
    time.sleep(.1)
    type_unicode(str(staging))
    key(36)
    wait_for_open_panel_location(staging.name)
    expected_entries = sorted(file.name for file in files)
    actual_entries = sorted(value.name for value in staging.iterdir())
    if actual_entries != expected_entries:
        raise StopRun("wecom-upload-staging-not-exact")
    location, _ = open_panel_state()
    if compact(location) != compact(staging.name):
        raise StopRun("wecom-open-panel-location-mismatch")
    key(0, Quartz.kCGEventFlagMaskCommand)
    time.sleep(.25)
    selected_location, open_enabled = open_panel_state()
    if compact(selected_location) != compact(staging.name) or not open_enabled:
        raise StopRun("wecom-open-panel-selection-not-confirmed")
    atomic_json(marker, {"state": "attempted", "attemptedAt": time.time(), "files": [file.name for file in files],
                         "documentNames": document_names(files), "uploadAttempts": 1})
    key(36)


def click_text_in_window(window: dict, artifacts: Path, sequence: str, predicate, error: str, *, fraction_x: float = .5) -> tuple[list[Hit], Path]:
    shot = artifacts / f"{sequence}-window-{window['id']}.png"
    hits = capture(window["id"], shot)
    hit = unique_hit(hits, predicate, error)
    click_hit(window, shot, hit, fraction_x=fraction_x)
    return hits, shot


def find_wecom_surface(artifacts: Path, sequence: str, predicate, error: str) -> tuple[dict, list[Hit], Path]:
    matches = []
    pid = running_pid()
    candidates = identity_windows(pid) + popup_windows(pid)
    seen = set()
    for candidate in candidates:
        if candidate["id"] in seen:
            continue
        seen.add(candidate["id"])
        shot = artifacts / f"{sequence}-window-{candidate['id']}.png"
        hits = capture(candidate["id"], shot)
        if predicate(hits):
            matches.append((candidate, hits, shot))
    if len(matches) != 1:
        raise StopRun(error if not matches else f"{error}-ambiguous")
    return matches[0]


def open_related_documents(window: dict, artifacts: Path) -> tuple[dict, list[Hit], Path]:
    key(53)
    raise_window(window)
    shot = artifacts / "related-entry.png"
    hits = capture(window["id"], shot)
    merged = unique_hit(hits, lambda h: "与我相关" in compact(h.text) and "智能表格" in compact(h.text)
                        and h.y < 300, "wecom-related-tab-not-unique")
    toolbar = compact(merged.text)
    offset = toolbar.index("与我相关")
    click_hit(window, shot, merged, fraction_x=(offset + 2) / max(1, len(toolbar)))
    time.sleep(.8)
    updated = artifacts / "related-documents.png"
    return window, capture(window["id"], updated), updated


def wait_for_import_complete(names: list[str], artifacts: Path) -> None:
    expected = [canonical_document_name(name) for name in names]
    for attempt in range(1, 21):
        time.sleep(.6)
        pid = running_pid()
        for candidate in identity_windows(pid) + popup_windows(pid):
            shot = artifacts / f"import-result-{attempt}-{candidate['id']}.png"
            try:
                hits = capture(candidate["id"], shot)
            except StopRun:
                continue
            body = canonical_document_name("\n".join(hit.text for hit in hits))
            raw = compact("\n".join(hit.text for hit in hits))
            if all(name in body for name in expected) and ("导入完成" in raw or raw.count("已完成") >= 2):
                return
    raise StopRun("wecom-import-conversion-outcome-unknown")


def move_document_to_space(main_window: dict, document_name: str, space: str, artifacts: Path, index: int) -> None:
    main_window, hits, shot = open_related_documents(main_window, artifacts)
    expected = canonical_document_name(document_name)
    item = unique_hit(hits, lambda h: expected in canonical_document_name(h.text), "wecom-imported-document-not-unique")
    click_hit(main_window, shot, item)
    time.sleep(.9)
    doc_window, _, _ = find_wecom_surface(
        artifacts, f"move-{index}-document",
        lambda values: any(expected in canonical_document_name(hit.text) for hit in values)
        and not classify_space(values, space, [document_name])["isSpaceWindow"],
        "wecom-imported-document-window-not-found",
    )
    raise_window(doc_window)
    # The overflow button is a window-relative chrome control. It is used only
    # after the exact document title has uniquely bound this window.
    bounds = doc_window["bounds"]
    click_point(bounds["X"] + bounds["Width"] - 28, bounds["Y"] + 68)
    time.sleep(.45)
    menu_window, menu_hits, menu_shot = find_wecom_surface(
        artifacts, f"move-{index}-menu",
        lambda values: any(compact(hit.text).startswith("移动到") for hit in values),
        "wecom-move-menu-not-found",
    )
    move = unique_hit(menu_hits, lambda h: compact(h.text).startswith("移动到"), "wecom-move-menu-entry-not-unique")
    click_hit(menu_window, menu_shot, move)
    time.sleep(.6)
    dialog, dialog_hits, dialog_shot = find_wecom_surface(
        artifacts, f"move-{index}-dialog",
        lambda values: exact_count(values, space) == 1 and any("移动至此" in compact(hit.text) for hit in values),
        "wecom-move-dialog-not-found",
    )
    destination = unique_hit(dialog_hits, lambda h: compact(h.text) == compact(space), "wecom-move-target-not-unique")
    click_hit(dialog, dialog_shot, destination)
    time.sleep(.25)
    refreshed = artifacts / f"move-{index}-dialog-selected.png"
    refreshed_hits = capture(dialog["id"], refreshed)
    button = unique_hit(refreshed_hits, lambda h: "移动至此" in compact(h.text), "wecom-move-confirm-not-unique")
    click_hit(dialog, refreshed, button)
    for attempt in range(1, 11):
        time.sleep(.45)
        try:
            _, toast_hits, _ = find_wecom_surface(
                artifacts, f"move-{index}-result-{attempt}",
                lambda values: any("已移动文档" in compact(hit.text) for hit in values),
                "wecom-move-result-not-found",
            )
            if any("已移动文档" in compact(hit.text) for hit in toast_hits):
                key(13, Quartz.kCGEventFlagMaskCommand)
                time.sleep(.35)
                return
        except StopRun:
            continue
    raise StopRun("wecom-move-outcome-unknown")


def move_imported_documents(window: dict, names: list[str], space: str, artifacts: Path) -> None:
    for index, name in enumerate(names, 1):
        move_document_to_space(window, name, space, artifacts, index)


def verify_two_frames(space: str, names: list[str], artifacts: Path, prefix: str) -> list[str]:
    frames = []
    for index in (1, 2):
        _, _, current, shot = locate(space, names, artifacts, f"{prefix}-{index}")
        if current["fileState"] != "complete":
            raise StopRun("wecom-target-readback-not-complete")
        frames.append(str(shot))
        time.sleep(.8)
    return frames


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: argparse.Namespace) -> dict:
    started = time.time()
    nodes: list[dict] = []
    args._nodes = nodes

    def step(name: str, action):
        node_started = time.time()
        try:
            value = action()
            nodes.append({"name": name, "elapsedMs": round((time.time() - node_started) * 1000),
                          "ok": True, "llmIntervention": False})
            return value
        except Exception:
            nodes.append({"name": name, "elapsedMs": round((time.time() - node_started) * 1000),
                          "ok": False, "llmIntervention": False})
            raise

    artifacts = Path(args.artifacts).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    files = [Path(value).resolve() for value in args.file]
    if len(files) != 2 or len({file.name for file in files}) != 2:
        raise StopRun("wecom-requires-two-unique-files")
    for file in files:
        if not file.is_file() or file.suffix.lower() != ".xlsx" or file.stat().st_size <= 0:
            raise StopRun("wecom-invalid-upload-file")
    names = document_names(files)
    marker = Path(args.attempt_marker).resolve()
    marker_value = read_marker(marker)
    if not marker.exists():
        step("stale-open-panel-cleanup", lambda: close_pre_attempt_panels(artifacts))
    window, hits, state, screenshot = step("target-space-locate", lambda: open_space(args.space, names, artifacts))
    identity = step("enterprise-identity", lambda: verify_identity(window, screenshot, hits, args.enterprise, artifacts))
    base = {"ok": True, "channel": "wecom", "targetType": "wedrive-shared-space", "targetName": args.space,
            "enterprise": args.enterprise, "fileState": state["fileState"], "present": state["present"],
            "windowId": window["id"], "spaceExactCount": state["spaceExactCount"],
            "spaceEvidenceCount": state["spaceEvidenceCount"], "uploadAttempts": 0,
            "artifacts": [str(screenshot), str(identity)], "nodes": nodes, "runtimeModelDecisions": 0}
    if state["fileState"] == "partial":
        if (args.mode != "upload" or marker_value.get("state") != "attempted"
                or int(marker_value.get("uploadAttempts", 0)) != 1):
            raise StopRun("wecom-partial-file-history")
        missing = [name for name in names if name not in state["present"]]
        step("move-missing-document", lambda: move_imported_documents(window, missing, args.space, artifacts))
        window, hits, state, screenshot = step("target-space-return", lambda: open_space(args.space, names, artifacts))
        frames = step("target-dual-frame-readback", lambda: verify_two_frames(args.space, names, artifacts, "verify-partial-recovered"))
        confirmed = step("delivery-receipt-commit", lambda: confirm_marker(marker, files, frames, recovered=True))
        return {**base, "fileState": "complete", "present": names, "confirmed": True, "uploadAttempts": 0,
                "historicalUploadAttempts": confirmed["uploadAttempts"], "recovered": True,
                "files": [{"name": file.name, "documentName": file.stem, "size": file.stat().st_size, "sha256": sha256(file)} for file in files],
                "artifacts": base["artifacts"] + frames, "elapsedMs": round((time.time() - started) * 1000)}
    if args.mode == "preflight":
        return {**base, "elapsedMs": round((time.time() - started) * 1000)}
    if state["fileState"] == "complete":
        frames = step("target-dual-frame-readback", lambda: verify_two_frames(args.space, names, artifacts, "verify-existing"))
        marker_value = step("delivery-receipt-commit", lambda: confirm_marker(
            marker, files, frames, recovered=read_marker(marker).get("state") == "attempted"))
        return {**base, "confirmed": True, "files": [{"name": file.name, "documentName": file.stem, "size": file.stat().st_size, "sha256": sha256(file)} for file in files],
                "uploadAttempts": 0, "historicalUploadAttempts": marker_value["uploadAttempts"],
                "artifacts": base["artifacts"] + frames, "elapsedMs": round((time.time() - started) * 1000)}
    if marker.exists():
        if args.mode != "upload" or marker_value.get("state") != "attempted" or int(marker_value.get("uploadAttempts", 0)) != 1:
            raise StopRun("wecom-attempted-outcome-unknown")
        step("move-imported-documents", lambda: move_imported_documents(window, names, args.space, artifacts))
        window, hits, state, screenshot = step("target-space-return", lambda: open_space(args.space, names, artifacts))
        frames = step("target-dual-frame-readback", lambda: verify_two_frames(args.space, names, artifacts, "verify-recovered"))
        confirmed = step("delivery-receipt-commit", lambda: confirm_marker(marker, files, frames, recovered=True))
        return {**base, "fileState": "complete", "present": names, "confirmed": True, "uploadAttempts": 0,
                "historicalUploadAttempts": confirmed["uploadAttempts"], "recovered": True,
                "files": [{"name": file.name, "documentName": file.stem, "size": file.stat().st_size, "sha256": sha256(file)} for file in files],
                "artifacts": base["artifacts"] + frames, "elapsedMs": round((time.time() - started) * 1000)}
    if args.mode == "verify":
        raise StopRun("wecom-confirmed-files-not-visible")
    step("import-two-files", lambda: import_two(window, hits, screenshot, files, marker, artifacts))
    step("wait-import-conversion", lambda: wait_for_import_complete(names, artifacts))
    step("move-imported-documents", lambda: move_imported_documents(window, names, args.space, artifacts))
    window, hits, state, screenshot = step("target-space-return", lambda: open_space(args.space, names, artifacts))
    frames = step("target-dual-frame-readback", lambda: verify_two_frames(args.space, names, artifacts, "verify-upload"))
    step("delivery-receipt-commit", lambda: confirm_marker(marker, files, frames, recovered=False))
    return {**base, "fileState": "complete", "present": names, "confirmed": True, "uploadAttempts": 1,
            "files": [{"name": file.name, "documentName": file.stem, "size": file.stat().st_size, "sha256": sha256(file)} for file in files],
            "artifacts": base["artifacts"] + frames, "elapsedMs": round((time.time() - started) * 1000)}


def main() -> int:
    if os.environ.get("JINSHA_WORKFLOW_INTERNAL") != "business-workflow-executor-v1":
        print(json.dumps({"ok": False, "reason": "direct-stage-invocation-forbidden"}, ensure_ascii=False))
        return 1
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preflight", "upload", "verify"), required=True)
    parser.add_argument("--enterprise", required=True)
    parser.add_argument("--space", required=True)
    parser.add_argument("--file", action="append", required=True)
    parser.add_argument("--attempt-marker", required=True)
    parser.add_argument("--artifacts", required=True)
    args = parser.parse_args()
    try:
        result = run(args)
    except Exception as error:
        marker_value = read_marker(Path(args.attempt_marker).resolve())
        result = {"ok": False, "channel": "wecom", "targetType": "wedrive-shared-space", "targetName": args.space,
                  "reason": str(error), "attemptedState": marker_value.get("state"),
                  "uploadAttempts": int(marker_value.get("uploadAttempts", 0)), "nodes": getattr(args, "_nodes", []),
                  "runtimeModelDecisions": 0}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
