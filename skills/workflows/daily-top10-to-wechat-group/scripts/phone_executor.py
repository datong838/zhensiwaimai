#!/usr/bin/env python3
"""One-shot, fail-closed image delivery for the Zhensi WeChat pressure test."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import signal
import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps, ImageStat
import uiautomator2 as u2


SCRIPT_DIR = Path(__file__).resolve().parent
OCR_BIN = SCRIPT_DIR / "ocr_vision"
ADB = shutil.which("adb") or "/opt/homebrew/bin/adb"
AUTHORIZATION = "zhensi-feibing-neo-ai-main-wechat-top10-v1"
TARGET_GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"  # 2026-10-20 同步 runtime_guard 改运营群
REQUIRED_IMAGE_TEXT = ("门店", "营业额", "有效订单")


class StopRun(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, timeout: float = 10, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=True, text=text, timeout=timeout)


def adb(serial: str, *args: str, timeout: float = 10) -> str:
    return run([ADB, "-s", serial, *args], timeout=timeout).stdout.strip()


def physical_devices() -> list[dict[str, str]]:
    lines = run([ADB, "devices", "-l"]).stdout.splitlines()[1:]
    devices = []
    for line in lines:
        fields = line.split()
        if len(fields) < 2 or fields[1] != "device" or fields[0].startswith("emulator-"):
            continue
        serial = fields[0]
        model = re.search(r"\bmodel:([^ ]+)", line)
        devices.append({"serial": serial, "model": model.group(1) if model else "unknown"})
    return devices


def load_receipt(path: Path, *, for_training: bool = False, enforce_expiry: bool = True) -> tuple[dict, Path]:
    if not path.is_file():
        raise StopRun("desktop-receipt-missing")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("ok") is not True or receipt.get("executor") != "desktop":
        raise StopRun("desktop-receipt-invalid")
    expected_date = (datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)).isoformat()
    if receipt.get("dataDate") != expected_date:
        raise StopRun("desktop-receipt-stale-date")
    if not re.fullmatch(r"[a-f0-9-]{36}", str(receipt.get("runId", ""))):
        raise StopRun("desktop-run-id-missing")
    now_ms = time.time() * 1000
    if enforce_expiry and not for_training and (not 0 <= now_ms - receipt.get("startedAt", 0) < 180000 or not now_ms < receipt.get("deadlineAt", 0) <= receipt.get("startedAt", 0) + 180000):
        raise StopRun("desktop-receipt-expired")
    image = Path(str(receipt.get("file", ""))).resolve()
    if not image.is_file() or image.suffix.lower() != ".png":
        raise StopRun("desktop-image-missing")
    if int(receipt.get("width", 0)) < 1500:
        raise StopRun("desktop-image-too-small")
    with Image.open(image) as actual:
        if actual.width < 1500 or actual.size != (receipt.get("width"), receipt.get("height")):
            raise StopRun("desktop-image-geometry-mismatch")
    actual_hash = sha256_file(image)
    if actual_hash != receipt.get("sha256"):
        raise StopRun("desktop-image-hash-mismatch")
    if len(receipt.get("revenues", [])) != 10 or len(receipt.get("stores", [])) != 10:
        raise StopRun("desktop-top10-contract-failed")
    revenues = receipt["revenues"]
    if any(not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0 for v in revenues) or any(a < b for a, b in zip(revenues, revenues[1:])):
        raise StopRun("desktop-revenue-order-invalid")
    if receipt.get("page") != 1 or receipt.get("pageSize") != 10:
        raise StopRun("desktop-pagination-invalid")
    return receipt, image


def claim_send_once(desktop: dict, ledger: Path | None = None, *, authorized_repeat_id: str | None = None) -> Path:
    if authorized_repeat_id is not None and not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}', authorized_repeat_id):
        raise StopRun('invalid-authorized-repeat-id')
    ledger = ledger or SCRIPT_DIR.parent / ".runtime" / "send-ledger"
    ledger.mkdir(parents=True, exist_ok=True, mode=0o700)
    suffix = f'-repeat-{authorized_repeat_id}' if authorized_repeat_id else ''
    group_key = hashlib.sha256(TARGET_GROUP.encode("utf-8")).hexdigest()[:12]
    if authorized_repeat_id is None and any(ledger.glob(f"{desktop['dataDate']}-main-{group_key}*.json")):
        raise StopRun("send-already-attempted-for-data-date")
    marker = ledger / f"{desktop['dataDate']}-main-{group_key}{suffix}.json"
    try:
        with marker.open("x", encoding="utf-8") as stream:
            json.dump({"runId": desktop["runId"], "sha256": desktop["sha256"], "state": "attempted", "authorizedRepeatId": authorized_repeat_id}, stream)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        raise StopRun("send-already-attempted-for-data-date")
    return marker


def ocr_entries(image: Path) -> list[dict]:
    output = run([str(OCR_BIN), str(image), "zh-Hans"], timeout=15).stdout
    entries = []
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            cx, cy, width, height = (int(value) for value in parts[0].split(","))
            confidence = float(parts[1])
        except ValueError:
            continue
        entries.append({"x": cx, "y": cy, "w": width, "h": height, "confidence": confidence, "text": parts[2].strip()})
    return entries


def find_exact(entries: list[dict], text: str) -> list[dict]:
    normalized = text.replace(" ", "")
    if normalized == '原图':
        return [entry for entry in entries if re.fullmatch(r'[•·○●✓✔√]*原图',entry['text'].replace(' ',''))]
    return [entry for entry in entries if entry["text"].replace(" ", "") == normalized]


def normalize_group_title(value: str) -> str:
    return re.sub(r"A[lL]数字员工", "AI数字员工", re.sub(r"\s+", "", value.strip()))


def exact_group_title(value: str, group: str) -> bool:
    value=normalize_group_title(value)
    group=normalize_group_title(group)
    if not value.startswith(group):
        return False
    suffix=value[len(group):]
    return not suffix or (not suffix[0].isdigit() and not re.search(r'[\u3400-\u9fff]',suffix))


def group_search_candidates(entries: list[dict], group: str) -> list[dict]:
    section_names = {"最常使用", "群聊"}
    boundary_names = {"最常使用", "群聊", "创建新的群聊", "聊天记录", "联系人", "公众号"}
    boundaries = [entry for entry in entries if entry["text"] in boundary_names or "搜索网络结果" in entry["text"]]
    matches = []
    for heading in (entry for entry in entries if entry["text"] in section_names):
        lower = min((entry["y"] for entry in boundaries if entry["y"] > heading["y"]), default=float("inf"))
        matches.extend(entry for entry in entries if heading["y"] < entry["y"] < lower
                       and exact_group_title(entry["text"], group))
    unique = {(entry.get("x"), entry.get("y"), entry.get("text")): entry for entry in matches}
    return list(unique.values())


def group_title_matches(entries: list[dict], group: str) -> list[dict]:
    if any("搜索网络结果" in entry["text"] for entry in entries):
        return []
    return [entry for entry in entries if entry["y"] < 280
            and exact_group_title(entry["text"], group)]


def poll(fn, predicate, timeout: float, interval: float = 0.22):
    deadline = time.monotonic() + timeout
    latest = None
    while True:
        latest = fn()
        if predicate(latest):
            return latest
        if time.monotonic() >= deadline:
            return latest
        time.sleep(interval)


def is_main_wechat_foreground(current: dict, resumed: str) -> bool:
    """Require both the WeChat package and the main-space resumed task."""
    return current.get("package") == "com.tencent.mm" and bool(re.search(
        r"(?:mResumedActivity|topResumedActivity|ResumedActivity)[^\n]*\bu0\s+com\.tencent\.mm/",
        resumed,
    ))


def main_wechat_foreground_evidence(serial: str, device) -> dict:
    current = device.app_current()
    resumed = adb(serial, "shell", "dumpsys", "activity", "activities")
    return {"current": current, "resumed": resumed, "ok": is_main_wechat_foreground(current, resumed)}


def screenshot(device, directory: Path, name: str) -> Path:
    path = directory / f"{name}.png"
    device.screenshot(str(path))
    return path


def input_chinese(serial: str, device, text: str) -> str:
    if device.app_current().get("package") != "com.tencent.mm":
        raise StopRun("wechat-focus-lost-before-input")
    errors = []
    try:
        focused = device(focused=True)
        focused.set_text(text, timeout=1)
        return "focused-set-text"
    except Exception as error:
        errors.append(f"focused:{type(error).__name__}")
    try:
        device.set_clipboard(text, label="zhensi-group")
        if device.clipboard != text:
            raise RuntimeError("clipboard-roundtrip")
        device.jsonrpc.pasteClipboard()
        return "clipboard-paste"
    except Exception as error:
        errors.append(f"clipboard:{type(error).__name__}")
    raise StopRun(f"wechat-input-channels-failed:{','.join(errors)}")


def image_fingerprint(image: Image.Image) -> tuple[int, tuple[float, float, float]]:
    square = ImageOps.fit(image.convert("RGB"), (128, 128))
    gray = square.resize((9, 8)).convert("L")
    pixels = list(gray.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | int(pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    mean = tuple(ImageStat.Stat(square).mean)
    return bits, mean


def fingerprint_distance(left, right) -> float:
    hamming = (left[0] ^ right[0]).bit_count()
    color = sum(abs(a - b) for a, b in zip(left[1], right[1])) / (3 * 255)
    return hamming + color * 18


def gallery_candidates(screen: Image.Image) -> list[tuple[tuple[int, int, int, int], tuple[int, int]]]:
    width, height = screen.size
    top = round(height * 0.075)
    columns = 4
    cell = width // columns
    candidates = []
    visible_rows = max(1, (height - 220 - top) // cell)
    for row in range(visible_rows):
        for col in range(columns):
            x0, y0 = col * cell, top + row * cell
            box = (x0 + 4, y0 + 4, min(width, x0 + cell - 4), min(height, y0 + cell - 4))
            candidates.append((box, (min(width - 20, x0 + cell - 28), y0 + 70)))
    return candidates


def select_target_thumbnail(screen_path: Path, target_path: Path, *, prefer_newest_first: bool = False, diagnostics: dict | None = None) -> tuple[tuple[int, int], float, str]:
    with Image.open(target_path) as target, Image.open(screen_path) as screen:
        target_fp = image_fingerprint(target)
        scored = []
        candidates = gallery_candidates(screen)
        first_point = candidates[0][1]
        for box, check_point in candidates:
            scored.append((fingerprint_distance(target_fp, image_fingerprint(screen.crop(box))), check_point))
    scored.sort(key=lambda item: item[0])
    if diagnostics is not None:
        diagnostics.update(bestDistance=round(scored[0][0],3) if scored else None,
                           secondDistance=round(scored[1][0],3) if len(scored)>1 else None,
                           bestPoint=list(scored[0][1]) if scored else None,
                           screenshotSha256=sha256_file(screen_path))
    if not scored or scored[0][0] > 20:
        raise StopRun("target-thumbnail-not-confident")
    if len(scored) > 1 and scored[1][0] - scored[0][0] < 1.5:
        first = next(item for item in scored if item[1] == first_point)
        if prefer_newest_first and first[0] <= scored[0][0] + 1.5 and first[0] <= 20:
            return first[1], round(first[0], 3), "media-newest-top-left-equivalent"
        raise StopRun("target-thumbnail-ambiguous")
    return scored[0][1], round(scored[0][0], 3), "visual-unique"


def stable_target_thumbnail(device, work: Path, image: Path, receipt: dict):
    end=time.monotonic()+6
    previous=None
    receipt['thumbnailObservations']=[]
    while True:
        screen=screenshot(device,work,'gallery-candidate')
        observation={}
        try:
            selected=select_target_thumbnail(screen,image,prefer_newest_first=True,diagnostics=observation)
            observation['accepted']=True
        except StopRun as error:
            selected=None
            observation.update(accepted=False,reason=str(error))
        receipt['thumbnailObservations'].append(observation)
        if selected is not None and previous is not None and selected[0]==previous[0] and abs(selected[1]-previous[1])<=1.5:
            return selected
        previous=selected
        if time.monotonic()>=end:raise StopRun('target-thumbnail-not-stable-or-confident')
        time.sleep(.22)


def verify_media_newest(serial: str, remote_name: str) -> bool:
    output = adb(serial, "shell", "content", "query", "--uri", "content://media/external/images/media", timeout=15)
    lines = [line for line in output.splitlines() if "date_added=" in line]
    target = next((line for line in lines if f"_display_name={remote_name}," in line), None)
    if target is None:
        return False
    target_date = int(re.search(r"\bdate_added=(\d+)", target).group(1))
    newest = max(int(match.group(1)) for line in lines if (match := re.search(r"\bdate_added=(\d+)", line)))
    return target_date == newest


def locate_chat_target(screen_path: Path, target_path: Path) -> tuple[tuple[int, int], float]:
    with Image.open(target_path) as target, Image.open(screen_path) as screen:
        target_fp = image_fingerprint(target)
        target_ratio = target.height / target.width
        width, height = screen.size
        x1 = round(width * 0.852)
        scored = []
        for box_width in (round(width * ratio) for ratio in (0.43, 0.46, 0.50, 0.54)):
            box_height = round(box_width * target_ratio)
            x0 = x1 - box_width
            for y0 in range(round(height * 0.14), max(round(height * 0.90) - box_height, round(height * 0.14) + 1), max(24, round(height * 0.017))):
                box = (x0, y0, x1, y0 + box_height)
                scored.append((fingerprint_distance(target_fp, image_fingerprint(screen.crop(box))), box))
    scored.sort(key=lambda item: item[0])
    if not scored or scored[0][0] > 12:
        raise StopRun("sent-image-bubble-not-confident")
    score, box = scored[0]
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), round(score, 3)


def verify_large_image(screen_path: Path, target_path: Path) -> dict:
    """Verify the opened viewer image against the exact desktop artifact plus OCR structure."""
    with Image.open(target_path) as target, Image.open(screen_path) as screen:
        target_fp = image_fingerprint(target)
        display_height = round(screen.width * target.height / target.width)
        center_y = (screen.height - display_height) // 2
        scored = []
        for y0 in range(max(0, center_y - 100), min(screen.height - display_height, center_y + 100) + 1, 10):
            crop = screen.crop((0, y0, screen.width, y0 + display_height))
            scored.append((fingerprint_distance(target_fp, image_fingerprint(crop)), y0))
    distance, y0 = min(scored, default=(float("inf"), -1))
    entries = ocr_entries(screen_path)
    matched = [token for token in REQUIRED_IMAGE_TEXT if any(token in entry["text"] for entry in entries)]
    return {
        "ok": distance <= 6 and len(matched) >= 2,
        "distance": round(distance, 3),
        "matched": matched,
        "cropY": y0,
    }


def open_and_verify_sent_image(device, work: Path, image: Path, group: str, receipt: dict) -> dict:
    """Retry opening only on a freshly verified target chat; never retry sending."""
    deadline = time.monotonic() + 12
    attempts = 0
    previous_point = None
    settle_until = 0
    last = {'ok': False, 'page': 'unknown', 'distance': None, 'matched': []}
    events = receipt.setdefault('readbackEvents', [])
    while time.monotonic() < deadline:
        if device.app_current().get('package') != 'com.tencent.mm':
            raise StopRun('readback-wechat-not-foreground')
        screen = screenshot(device, work, 'sent-large-image')
        entries = ocr_entries(screen)
        in_chat = bool(group_title_matches(entries, group))
        page = 'target-chat' if in_chat else 'non-chat-unconfirmed'
        if last['page'] != page:
            events.append({'event': 'page', 'page': page})
        if not in_chat:
            previous_point = None
            last = verify_large_image(screen, image) | {'page': page}
            if last['ok']:
                receipt['viewerOpenAttempts'] = attempts
                return last
        else:
            last = {'ok': False, 'page': page, 'distance': None, 'matched': []}
            if attempts < 2 and time.monotonic() >= settle_until:
                try:
                    point, distance = locate_chat_target(screen, image)
                except StopRun:
                    previous_point = None
                else:
                    if point == previous_point and time.monotonic() < deadline:
                        # Coordinates belong to this screenshot, not the previous attempt.
                        if device.app_current().get('package') != 'com.tencent.mm':
                            raise StopRun('readback-wechat-not-foreground')
                        attempts += 1
                        receipt['viewerOpenAttempts'] = attempts
                        receipt['sentBubbleDistance'] = distance
                        events.append({'event': 'open', 'attempt': attempts, 'point': list(point),
                                       'distance': distance, 'screenshotSha256': sha256_file(screen)})
                        device.click(*point)
                        settle_until = time.monotonic() + 2
                        previous_point = None
                    else:
                        previous_point = point
        time.sleep(.22)
    receipt['viewerOpenAttempts'] = attempts
    receipt['readbackLastPage'] = last['page']
    receipt['largeImageDistance'] = last['distance']
    receipt['largeImageOcrFields'] = last['matched']
    if last['page'] == 'target-chat':
        raise StopRun('image-viewer-not-opened' if attempts else 'sent-image-bubble-not-stable')
    raise StopRun('viewer-page-or-content-not-verified')


def topbar_action_centers(image: Image.Image) -> list[tuple[int, int]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    x0, x1 = round(width * 0.72), width - 18
    y0, y1 = round(height * 0.034), round(height * 0.095)
    points = set()
    for y in range(y0, y1):
        for x in range(x0, x1):
            red, green, blue = rgb.getpixel((x, y))
            if max(red, green, blue) < 115:
                points.add((x, y))
    components = []
    while points:
        seed = points.pop()
        stack, xs, ys = [seed], [], []
        while stack:
            x, y = stack.pop()
            xs.append(x)
            ys.append(y)
            for nx in (x - 1, x, x + 1):
                for ny in (y - 1, y, y + 1):
                    if (nx, ny) in points:
                        points.remove((nx, ny))
                        stack.append((nx, ny))
        box = (min(xs), min(ys), max(xs), max(ys))
        box_width, box_height = box[2] - box[0] + 1, box[3] - box[1] + 1
        if len(xs) >= 120 and 20 <= box_width <= 75 and 20 <= box_height <= 75:
            components.append(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
    groups = []
    for center in sorted(components):
        if groups and abs(center[0] - groups[-1][-1][0]) < 38:
            groups[-1].append(center)
        else:
            groups.append([center])
    centers = [(round(sum(x for x, _ in group) / len(group)), round(sum(y for _, y in group) / len(group))) for group in groups]
    centers = [center for center in centers if center[0] > width * 0.78]
    if len(centers) < 2:
        raise StopRun(f"wechat-topbar-icon-count:{len(centers)}")
    search, plus = centers[-2], centers[-1]
    if not 60 <= plus[0] - search[0] <= 150:
        raise StopRun("wechat-topbar-icon-spacing-invalid")
    return [search, plus]


def green_mark_near(image_path: Path, entry: dict) -> bool:
    with Image.open(image_path) as image:
        x0 = max(0, entry["x"] - entry["w"] // 2 - 70)
        x1 = min(image.width, entry["x"] + entry["w"] // 2 + 20)
        y0 = max(0, entry["y"] - entry["h"])
        y1 = min(image.height, entry["y"] + entry["h"])
        pixels = image.convert("RGB").crop((x0, y0, x1, y1)).getdata()
        return sum(1 for red, green, blue in pixels if green > red + 22 and green > blue + 10 and green > 95) >= 12


def ensure_original_selected(device, work: Path) -> list[dict]:
    screen = screenshot(device, work, "gallery-original-state")
    entries = ocr_entries(screen)
    matches = find_exact(entries, "原图")
    if len(matches) != 1:
        raise StopRun(f"original-label-count:{len(matches)}")
    if not green_mark_near(screen, matches[0]):
        device.click(matches[0]["x"], matches[0]["y"])
    def scan():
        current = screenshot(device, work, "gallery-original-state")
        current_entries = ocr_entries(current)
        current_matches = find_exact(current_entries, "原图")
        return current_entries, bool(len(current_matches) == 1 and green_mark_near(current, current_matches[0]))
    verified = poll(scan, lambda value: value[1], 3)
    if not verified[1]:
        raise StopRun("original-selection-not-verified")
    return verified[0]


def stage(receipt: dict, name: str):
    started = time.monotonic()
    receipt["stage"] = name
    receipt["stageStartedMonotonic"] = started
    return lambda: receipt["stageMs"].__setitem__(name, round((time.monotonic() - started) * 1000))


def click_text(device, work: Path, name: str, text: str, timeout: float = 5) -> list[dict]:
    def scan():
        return ocr_entries(screenshot(device, work, name))
    entries = poll(scan, lambda values: bool(find_exact(values, text)), timeout)
    matches = find_exact(entries, text)
    if len(matches) != 1:
        raise StopRun(f"text-not-unique:{text}:{len(matches)}")
    device.click(matches[0]["x"], matches[0]["y"])
    return entries


def open_search_page(device, work: Path) -> None:
    entries = ocr_entries(screenshot(device, work, "wechat-home-actions"))
    if find_exact(entries, "发起群聊") or find_exact(entries, "添加朋友"):
        device.press("back")
        entries = poll(lambda: ocr_entries(screenshot(device, work, "wechat-home-actions")),
                       lambda values: not find_exact(values, "发起群聊"), 3)
    def scan_topbar():
        topbar = screenshot(device, work, "wechat-home-topbar")
        try:
            with Image.open(topbar) as image:
                return topbar_action_centers(image)
        except StopRun:
            return []
    centers = poll(scan_topbar, lambda values: len(values) == 2, 3)
    if len(centers) != 2:
        raise StopRun(f"wechat-topbar-icon-count:{len(centers)}")
    search, _ = centers
    device.click(*search)
    search_entries = poll(lambda: ocr_entries(screenshot(device, work, "wechat-search-page")),
                          lambda values: any("搜索" in entry["text"] for entry in values)
                          and not find_exact(values, "发起群聊"), 4)
    if not any("搜索" in entry["text"] for entry in search_entries) or find_exact(search_entries, "发起群聊"):
        raise StopRun("wechat-search-page-not-verified")


def ensure_wechat_home(device, work: Path) -> list[dict]:
    def is_home(entries):
        return all(find_exact(entries, label) for label in ("微信", "通讯录", "发现", "我"))
    entries = ocr_entries(screenshot(device, work, "wechat-home"))
    for attempt in range(6):
        if is_home(entries):
            return entries
        if attempt == 5:
            break
        device.press("back")
        entries = poll(lambda: ocr_entries(screenshot(device, work, "wechat-home")), is_home, 2)
    raise StopRun("wechat-home-not-recognized")


def run_executor(args) -> dict:
    started = time.monotonic()
    receipt = {"ok": False, "executor": "phone", "stageMs": {}, "sendAttempts": 0, "retryCount": 0}
    work = Path(tempfile.mkdtemp(prefix="zhensi-phone-"))
    original_ime = None
    result_file = None
    try:
        done = stage(receipt, "contract")
        training = bool(getattr(args, "train_phone", False))
        phone_only = bool(getattr(args, "phone_only_replay", False))
        if training and args.execute:
            raise StopRun("training-cannot-send")
        if phone_only and (training or not args.execute or getattr(args,'standing_authorization',None)!=AUTHORIZATION or not re.fullmatch(r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}',getattr(args,'authorized_repeat_id',None) or '')):
            raise StopRun('phone-replay-authorization-missing')
        desktop, image = load_receipt(Path(args.desktop_receipt), for_training=training or phone_only)
        result_file = (Path(tempfile.mkdtemp(prefix="zhensi-phone-training-" if training else "zhensi-phone-replay-")) if training or phone_only else Path(args.desktop_receipt).parent) / "phone_receipt.json"
        receipt["receiptFile"] = str(result_file)
        if training:
            receipt["mode"] = "training-preview-no-send"
        receipt["runId"] = desktop["runId"]
        receipt["dataDate"] = desktop["dataDate"]
        operation_deadline = time.time()+120 if phone_only else desktop['deadlineAt']/1000
        if phone_only:
            import uuid
            receipt.update(sourceDesktopRunId=desktop['runId'],phoneAttemptId=str(uuid.uuid4()),phoneOnlyReplay=True)
        def deadline_stop(signum, frame):
            raise StopRun("total-deadline-exceeded")
        signal.signal(signal.SIGALRM, deadline_stop)
        remaining = operation_deadline - time.time()
        if training:
            remaining = min(120, getattr(args, "training_deadline_at", time.time()*1000+120000) / 1000 - time.time())
        signal.setitimer(signal.ITIMER_REAL, max(0.001, remaining))
        if args.group != TARGET_GROUP or args.instance != "main":
            raise StopRun("target-contract-mismatch")
        if args.execute and args.standing_authorization != AUTHORIZATION:
            raise StopRun("standing-authorization-missing")
        devices = physical_devices()
        if args.serial:
            devices = [item for item in devices if item["serial"] == args.serial]
        if len(devices) != 1:
            raise StopRun(f"physical-device-count:{len(devices)}")
        serial = devices[0]["serial"]
        if "HLK" not in devices[0]["model"].upper():
            raise StopRun("unexpected-device-model")
        receipt.update({"group": args.group, "model": devices[0]["model"], "fileSha256": desktop["sha256"]})
        done()
        if not args.execute and not args.probe_locate_group and not training:
            receipt.update({"ok": True, "mode": "dry-run", "elapsedMs": round((time.monotonic() - started) * 1000)})
            return receipt

        device = u2.connect(serial)
        info = device.info
        if int(info.get("displayWidth", 0)) != 1080 or int(info.get("displayHeight", 0)) != 2340:
            raise StopRun("unverified-display-geometry")

        if args.execute or training:
            done = stage(receipt, "push")
            remote_name = f"{image.stem}-{desktop['sha256'][:12]}{image.suffix}"
            remote = f"/sdcard/Pictures/zhensi_reports/{remote_name}"
            receipt["remoteName"] = remote_name
            adb(serial, "shell", "mkdir", "-p", "/sdcard/Pictures/zhensi_reports")
            run([ADB, "-s", serial, "push", str(image), remote], timeout=20)
            adb(serial, "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d", f"file://{remote}")
            remote_hash = adb(serial, "shell", "sha256sum", remote).split()[0]
            if remote_hash != desktop["sha256"]:
                raise StopRun("device-image-hash-mismatch")
            media_newest = poll(lambda: verify_media_newest(serial, remote_name), bool, 4)
            if not media_newest:
                raise StopRun("device-media-newest-not-verified")
            receipt["mediaNewest"] = True
            done()

        done = stage(receipt, "open_main_wechat")
        initial = main_wechat_foreground_evidence(serial, device)
        already_main = initial["ok"]
        receipt['mainWechatAlreadyForeground'] = already_main
        if not already_main:
            adb(serial, "shell", "am", "start", "-n", "com.tencent.mm/.ui.LauncherUI")
            chooser = poll(lambda: device.app_current(), lambda value: "HwChooserActivity" in value.get("activity", ""), 2)
            if "HwChooserActivity" in chooser.get("activity", ""):
                main = device(description="微信")
                if not main.exists(timeout=2):
                    raise StopRun("main-wechat-chooser-not-found")
                main.click()
        foreground = poll(
            lambda: main_wechat_foreground_evidence(serial, device),
            lambda value: value["ok"],
            12,
        )
        if not foreground["ok"]:
            raise StopRun("wechat-not-foreground")
        processes = adb(serial, "shell", "ps", "-A", "-o", "USER,PID,NAME")
        if not re.search(r"^u0_a\d+\s+\d+\s+com\.tencent\.mm$", processes, re.MULTILINE):
            raise StopRun("main-wechat-process-not-verified")
        resumed = adb(serial, "shell", "dumpsys", "activity", "activities")
        if not is_main_wechat_foreground(device.app_current(), resumed):
            raise StopRun("main-wechat-foreground-task-not-verified")
        done()

        done = stage(receipt, "locate_group")
        ensure_wechat_home(device, work)
        open_search_page(device, work)
        original_ime = adb(serial, "shell", "settings", "get", "secure", "default_input_method")
        receipt["inputChannel"] = input_chinese(serial, device, args.group)
        entries = poll(lambda: ocr_entries(screenshot(device, work, "group-search")),
                       lambda values: bool(group_search_candidates(values, args.group)), 6)
        matches = group_search_candidates(entries, args.group)
        if len(matches) != 1:
            raise StopRun(f"group-result-count:{len(matches)}")
        device.click(matches[0]["x"], matches[0]["y"])
        title_entries = poll(lambda: ocr_entries(screenshot(device, work, "group-chat")),
                             lambda values: bool(group_title_matches(values, args.group)), 6)
        if len(group_title_matches(title_entries, args.group)) != 1:
            raise StopRun("group-title-not-verified")
        done()
        if args.probe_locate_group:
            receipt.update({"ok": True, "mode": "probe-locate-group", "groupTitleVerified": True,
                            "elapsedMs": round((time.monotonic() - started) * 1000)})
            return receipt

        done = stage(receipt, "select_original")
        device.click(1020, 2140)
        click_text(device, work, "plus-panel", "相册")
        gallery = poll(lambda: screenshot(device, work, "gallery"), lambda value: "原图" in "".join(e["text"] for e in ocr_entries(value)), 6)
        point, match_distance, selection_method = stable_target_thumbnail(device, work, image, receipt)
        receipt["thumbnailDistance"] = match_distance
        receipt["thumbnailSelection"] = selection_method
        receipt["galleryColumns"] = 4
        device.click(*point)
        final_entries = ensure_original_selected(device, work)
        final_entries = poll(lambda: ocr_entries(screenshot(device, work, "gallery-final")), lambda values: any(bool(re.fullmatch(r"发送[（(]1[）)]", e["text"].replace(" ", ""))) for e in values), 4)
        send_matches = [e for e in final_entries if bool(re.fullmatch(r"发送[（(]1[）)]", e["text"].replace(" ", "")))]
        if len(send_matches) != 1:
            raise StopRun("send-one-not-verified")
        preview_matches = [entry for entry in final_entries if bool(re.fullmatch(r"预览[（(]1[）)]", entry["text"].replace(" ", "")))]
        if len(preview_matches) != 1:
            raise StopRun("preview-one-not-verified")
        device.click(preview_matches[0]["x"], preview_matches[0]["y"])
        preview_entries = poll(lambda: ocr_entries(screenshot(device, work, "target-preview")),
                               lambda values: all(any(token in entry["text"] for entry in values) for token in REQUIRED_IMAGE_TEXT), 6)
        if not all(any(token in entry["text"] for entry in preview_entries) for token in REQUIRED_IMAGE_TEXT):
            raise StopRun("target-preview-content-not-verified")
        preview_match = verify_large_image(work / 'target-preview.png', image)
        originals = find_exact(preview_entries, '原图')
        if not preview_match['ok'] or len(originals) != 1 or not green_mark_near(work / 'target-preview.png', originals[0]):
            raise StopRun('preview-image-or-original-not-verified')
        receipt['previewDistance'] = preview_match['distance']
        send_matches = [entry for entry in preview_entries if re.fullmatch(r'发送[（(]1[）)]', entry['text'].replace(' ', ''))]
        if len(send_matches) != 1:
            raise StopRun("preview-send-button-not-verified")
        done()

        if training:
            receipt.update(ok=True, previewVerified=True)
            return receipt

        done = stage(receipt, "send_once")
        if time.time() >= operation_deadline:
            raise StopRun("total-deadline-exceeded-before-send")
        repeat_id = getattr(args, 'authorized_repeat_id', None)
        claim_send_once(desktop, authorized_repeat_id=repeat_id)
        if repeat_id: receipt['authorizedRepeatId'] = repeat_id
        receipt["sendAttempts"] = 1
        device.click(send_matches[0]["x"], send_matches[0]["y"])
        done()

        done = stage(receipt, "verify")
        sent_chat = poll(
            lambda: screenshot(device, work, "sent-chat"),
            lambda value: bool(group_title_matches(ocr_entries(value), args.group)),
            10,
        )
        sent_entries = ocr_entries(sent_chat)
        if not group_title_matches(sent_entries, args.group):
            raise StopRun("post-send-group-title-missing")
        enlarged = open_and_verify_sent_image(device, work, image, args.group, receipt)
        receipt["largeImageDistance"] = enlarged["distance"]
        receipt["largeImageOcrFields"] = enlarged["matched"]
        if not enlarged["ok"]:
            raise StopRun("large-image-content-not-verified")
        done()
        receipt.update({"ok": True, "mode": "execute", "verified": True, "elapsedMs": round((time.monotonic() - started) * 1000)})
        return receipt
    except Exception as error:
        receipt.update({"reason": str(error), "elapsedMs": round((time.monotonic() - started) * 1000)})
        return receipt
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        current_stage = receipt.get("stage")
        stage_started = receipt.pop("stageStartedMonotonic", None)
        if current_stage and stage_started is not None and current_stage not in receipt["stageMs"]:
            receipt["stageMs"][current_stage] = round((time.monotonic() - stage_started) * 1000)
        if original_ime:
            try:
                serial = locals().get("serial")
                if serial:
                    adb(serial, "shell", "ime", "set", original_ime)
            except Exception:
                pass
        receipt["elapsedMs"] = round((time.monotonic() - started) * 1000)
        if result_file:
            if not receipt.get('ok') and (work/'gallery-candidate.png').exists():
                private_dir=Path(tempfile.mkdtemp(prefix='zhensi-private-selection-'))
                diagnostic=private_dir/'gallery-candidate.png'
                shutil.copy2(work/'gallery-candidate.png',diagnostic);diagnostic.chmod(0o600)
                receipt['privateSelectionEvidence']=str(diagnostic)
            result_file.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
            result_file.chmod(0o600)
            # Retain only the target image viewer, never unrelated chat/home screens.
            for name in ("target-preview.png", "sent-large-image.png"):
                evidence = work / name
                if evidence.exists():
                    shutil.copyfile(evidence, result_file.parent / name)
        shutil.rmtree(work, ignore_errors=True)


def self_test() -> dict:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        image = root / "sample.png"
        Image.new("RGB", (1500, 900), "white").save(image)
        receipt_path = root / "receipt.json"
        receipt_path.write_text(json.dumps({
            "ok": True, "executor": "desktop", "file": str(image), "width": 1500, "height": 900,
            "runId": "11111111-1111-4111-8111-111111111111", "startedAt": time.time()*1000, "deadlineAt": time.time()*1000+179000,
            "dataDate": (datetime.now(ZoneInfo("Asia/Shanghai")).date()-timedelta(days=1)).isoformat(), "page": 1, "pageSize": 10,
            "sha256": sha256_file(image), "revenues": list(range(10, 0, -1)), "stores": [f"店{i}" for i in range(10)],
        }), encoding="utf-8")
        receipt, loaded = load_receipt(receipt_path)
        if loaded != image.resolve() or receipt["width"] != 1500:
            raise AssertionError("receipt self-test failed")
        main_resumed = "mResumedActivity: ActivityRecord{abc u0 com.tencent.mm/.ui.LauncherUI t1}"
        clone_resumed = "mResumedActivity: ActivityRecord{abc u128 com.tencent.mm/.ui.LauncherUI t1}"
        if not is_main_wechat_foreground({"package": "com.tencent.mm"}, main_resumed):
            raise AssertionError("main WeChat foreground self-test failed")
        if is_main_wechat_foreground({"package": "com.tencent.mm"}, clone_resumed):
            raise AssertionError("clone WeChat foreground self-test failed")
        left = image_fingerprint(Image.new("RGB", (64, 64), "white"))
        right = image_fingerprint(Image.new("RGB", (64, 64), "black"))
        if fingerprint_distance(left, left) != 0 or fingerprint_distance(left, right) <= 0:
            raise AssertionError("fingerprint self-test failed")
        if not exact_group_title("FEIBING NEO Al数字员工（18）", TARGET_GROUP):
            raise AssertionError("group OCR normalization self-test failed")
        canvas = Image.new("RGB", (1080, 2340), "white")
        draw = ImageDraw.Draw(canvas)
        draw.ellipse((875, 115, 920, 160), outline="black", width=7)
        draw.line((910, 150, 928, 168), fill="black", width=7)
        draw.line((1005, 120, 1005, 160), fill="black", width=7)
        draw.line((985, 140, 1025, 140), fill="black", width=7)
        centers = topbar_action_centers(canvas)
        if len(centers) != 2 or centers[0][0] >= centers[1][0]:
            raise AssertionError("topbar icon self-test failed")
        result_fixture = [{"x": 80, "y": 318, "text": "群聊"}, {"x": 360, "y": 461, "text": "FEIBING NEO Al数字员工（18）"},
                          {"x": 230, "y": 621, "text": "搜索网络结果"}, {"x": 230, "y": 735, "text": "FEIBING NEO AI数字员工"}]
        if len(group_search_candidates(result_fixture, TARGET_GROUP)) != 1:
            raise AssertionError("group result self-test failed")
        if len(group_search_candidates([{**entry, "text": "最常使用"} if entry["text"] == "群聊" else entry for entry in result_fixture], TARGET_GROUP)) != 1:
            raise AssertionError("frequent group result self-test failed")
        if len(group_title_matches([{"x": 300, "y": 160, "text": "FEIBING NEO AI数字员工（18）"}], TARGET_GROUP)) != 1:
            raise AssertionError("group title self-test failed")
        candidates = gallery_candidates(Image.new("RGB", (1080, 2340), "white"))
        if len(candidates) != 28 or candidates[0][1][0] != 242:
            raise AssertionError("four-column gallery self-test failed")
        target = Image.new("RGB", (1500, 1180), "white")
        target_draw = ImageDraw.Draw(target)
        target_draw.rectangle((100, 100, 1400, 1080), outline="black", width=16)
        target_draw.line((100, 400, 1400, 400), fill="black", width=12)
        target.save(image)
        viewer = Image.new("RGB", (1080, 2340), "black")
        fitted = target.resize((1080, round(1080 * 1180 / 1500)), Image.Resampling.LANCZOS)
        viewer.paste(fitted, (0, (2340 - fitted.height) // 2))
        display_height = fitted.height
        y0 = (viewer.height - display_height) // 2
        distance = fingerprint_distance(image_fingerprint(target), image_fingerprint(viewer.crop((0, y0, viewer.width, y0 + display_height))))
        if distance > 1:
            raise AssertionError("large-image visual fingerprint self-test failed")
    return {"ok": True, "tests": 11}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--desktop-receipt", default="/tmp/zhensi_top10/desktop_receipt.json")
    parser.add_argument("--group", default=TARGET_GROUP)
    parser.add_argument("--instance", default="main", choices=("main",))
    parser.add_argument("--serial")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--train-phone", action="store_true")
    parser.add_argument("--phone-only-replay", action="store_true")
    parser.add_argument("--authorized-repeat-id")
    parser.add_argument("--probe-locate-group", action="store_true")
    parser.add_argument("--standing-authorization")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    parsed = parse_args()
    result = self_test() if parsed.self_test else run_executor(parsed)
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    sys.exit(0 if result.get("ok") else 1)
