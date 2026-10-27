#!/usr/bin/env python3
"""One-shot, hash-bound delivery of two Jinsha XLSX reports to main WeChat."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import uiautomator2 as u2
from resume_flow import next_action, retryable, retry_delay, validate_binding


BUILD_RECEIPT = Path("/tmp/zhensi_jinsha_reports/build_receipt.json")
SEND_RECEIPT = Path("/tmp/zhensi_jinsha_reports/wechat_send_receipt.json")
PHONE_EXECUTOR = Path(__file__).resolve().parents[2] / "workflows/daily-top10-to-wechat-group/scripts/phone_executor.py"
MERCHANT_SENDER = Path(__file__).resolve().parents[2] / "workflows/daily-agent-new-merchants-to-wechat/scripts/wechat_sender_executor.py"
TARGET_GROUP = "臻肆测试群"
AUTHORIZATION = "zhensi-test-main-wechat-jinsha-files-v1"
DEVICE_ID_SHA256 = "f2724cf436e9590a92d0668176b1ea2b12531d451ccc2f82e08f6935e6713156"
DELIVERY_LEDGER = Path(__file__).resolve().parents[3] / ".local/state/jinsha-report-send.json"


class StopRun(RuntimeError):
    pass


def verify_physical_identity(helpers, serial):
    identity = helpers.adb(serial, "shell", "getprop", "ro.serialno").strip()
    model = helpers.adb(serial, "shell", "getprop", "ro.product.model").strip()
    if hashlib.sha256(identity.encode()).hexdigest() != DEVICE_ID_SHA256 or model != "HLK-AL00":
        raise StopRun("physical-device-identity-mismatch")
    return {"identityHash": DEVICE_ID_SHA256[:12], "model": model}


def select_verified_device(helpers):
    """USB and wireless may expose the same physical device twice."""
    devices = helpers.physical_devices()
    if not devices:
        raise StopRun("physical-device-not-connected")
    verified = []
    for item in devices:
        identity = verify_physical_identity(helpers, item["serial"])
        verified.append((item, identity))
    # Every candidate must be the authorized physical device, not just its model.
    verified.sort(key=lambda pair: (":" in pair[0]["serial"], pair[0]["serial"]))
    item, identity = verified[0]
    return item["serial"], {**identity, "transport": "wireless" if ":" in item["serial"] else "usb",
                            "verifiedEndpoints": len(verified)}


def load_module(name: str, file: Path):
    spec = importlib.util.spec_from_file_location(name, file)
    if spec is None or spec.loader is None:
        raise StopRun(f"module-load-failed:{name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256_file(file: Path) -> str:
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(file: Path, payload: dict) -> None:
    file.parent.mkdir(parents=True, exist_ok=True)
    temporary = file.with_name(f".{file.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, file)


def load_build_receipt(file: Path) -> tuple[dict, list[dict]]:
    receipt = json.loads(file.read_text(encoding="utf-8"))
    if receipt.get("ok") is not True or receipt.get("executor") != "build-reports":
        raise StopRun("build-receipt-invalid")
    files = []
    for platform in ("meituan", "taobao"):
        item = receipt.get("files", {}).get(platform, {})
        local = Path(str(item.get("file", ""))).resolve()
        if not local.is_file() or local.suffix.lower() != ".xlsx":
            raise StopRun(f"output-missing:{platform}")
        actual = sha256_file(local)
        if actual != item.get("sha256"):
            raise StopRun(f"output-hash-mismatch:{platform}")
        files.append({"platform": platform, "file": local, "name": local.name,
                      "size": local.stat().st_size, "sha256": actual})
    if len({item["name"] for item in files}) != 2:
        raise StopRun("output-name-not-unique")
    return receipt, files


def exact(entries: list[dict], label: str) -> list[dict]:
    wanted = re.sub(r"\s+", "", label)
    return [item for item in entries if re.sub(r"\s+", "", item["text"]) == wanted]


def screenshot_entries(device, helpers, work: Path, name: str) -> tuple[Path, list[dict]]:
    shot = helpers.screenshot(device, work, name)
    return shot, helpers.ocr_entries(shot)


def open_file_panel(device, helpers, work: Path) -> dict:
    width, height = device.window_size()
    shot, entries = screenshot_entries(device, helpers, work, "plus-panel-1")
    # 恢复已展开面板时不再次点加号把它关闭。
    panel_labels = sum(bool(exact(entries, x)) for x in ("相册", "拍摄", "位置", "红包", "文件", "音乐"))
    if panel_labels < 2:
        device.click(width - 58, height - 198)
        shot, entries = screenshot_entries(device, helpers, work, "plus-panel-open")
    file_matches = exact(entries, "文件")
    music_matches = exact(entries, "音乐")
    if not file_matches:
        device.swipe(int(width * .82), int(height * .89), int(width * .20), int(height * .89), .25)
        time.sleep(.75)
        shot, entries = screenshot_entries(device, helpers, work, "plus-panel-2a")
        time.sleep(.35)
        stable_shot, stable_entries = screenshot_entries(device, helpers, work, "plus-panel-2b")
        first_file, second_file = exact(entries, "文件"), exact(stable_entries, "文件")
        first_music, second_music = exact(entries, "音乐"), exact(stable_entries, "音乐")
        if not all(len(items) == 1 for items in (first_file, second_file, first_music, second_music)):
            raise StopRun(f"file-music-evidence-incomplete:{stable_shot}")
        if (abs(first_file[0]["x"] - second_file[0]["x"]) > 10 or
                abs(first_file[0]["y"] - second_file[0]["y"]) > 10):
            raise StopRun("file-panel-still-moving")
        file_matches, music_matches, shot = second_file, second_music, stable_shot
    if len(file_matches) != 1 or len(music_matches) != 1:
        raise StopRun(f"file-entry-count:{len(file_matches)}:{shot}")
    file_entry, music_entry = file_matches[0], music_matches[0]
    if not (file_entry["x"] < music_entry["x"] and abs(file_entry["y"] - music_entry["y"]) < 30):
        raise StopRun("file-not-left-of-music")
    ui_node = device(text="文件")
    method = "ui-tree"
    if ui_node.exists(timeout=.4):
        ui_node.click()
    else:
        # 微信当前 Flutter 页面只暴露空根节点；用两帧稳定 OCR 和相邻标签关系兜底，
        # 点击「文件」格图标中心而不是动画中的文字坐标。
        method = "stable-ocr-structural"
        device.click(file_entry["x"], max(1, file_entry["y"] - 125))
    return {"panelScreenshot": str(shot), "entry": file_entry, "music": music_entry, "method": method}


def current_file_screen(device, helpers, work: Path, name: str) -> tuple[Path, list[dict]]:
    return screenshot_entries(device, helpers, work, name)


def load_delivery_ledger(path=DELIVERY_LEDGER):
    if not path.exists():
        return {"groupName": TARGET_GROUP, "files": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("groupName") != TARGET_GROUP:
        raise StopRun("ledger-group-mismatch")
    return value


def wait_screen(device, helpers, work, name, predicate, timeout=15):
    deadline = time.monotonic() + timeout
    while True:
        shot, entries = screenshot_entries(device, helpers, work, name)
        if predicate(entries):
            return shot, entries
        if time.monotonic() >= deadline:
            raise StopRun(f"page-not-ready:{name}:{shot}")
        time.sleep(.3)


def click_label(device, helpers, work, label, name):
    node = device(text=label)
    if node.exists(timeout=.3):
        if node.count != 1:
            raise StopRun(f"label-not-unique:{label}")
        node.click()
        return
    _, entries = wait_screen(device, helpers, work, name,
                             lambda e: len(exact(e, label)) == 1)
    entry = exact(entries, label)[0]
    device.click(entry["x"], entry["y"])


def select_phone_file(device, helpers, work, item):
    wait_screen(device, helpers, work, "file-selector-ready",
                lambda e: bool(exact(e, "手机文件")) and bool(exact(e, "选择文件")))
    if "FileSelectorUI" not in device.app_current().get("activity", ""):
        raise StopRun("wrong-file-selector-activity")
    click_label(device, helpers, work, "手机文件", "phone-files-tab")
    click_label(device, helpers, work, "选取", "phone-files-pick")
    deadline = time.monotonic() + 15
    while device.app_current().get("package") != "com.android.documentsui":
        if time.monotonic() >= deadline:
            raise StopRun("system-file-picker-not-ready")
        time.sleep(.3)
    return choose_system_file(device, item)


def current_picker_folder(device, name):
    root = ET.fromstring(device.dump_hierarchy())
    for parent in root.iter('node'):
        if parent.get('resource-id') == 'com.android.documentsui:id/dropdown_breadcrumb':
            if any(n.get('text') == name for n in parent.iter('node')):
                return True
    return False


def open_picker_folder(device, name):
    # 已知目录只做精确点击；绝不把已定位的条目滚回顶部。
    target = device(resourceId="android:id/title", text=name)
    click_stable_picker_node(device, target, name)
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if current_picker_folder(device, name):
            return
        time.sleep(.25)
    raise StopRun("page-not-ready:folder-transition:" + name)


def click_stable_picker_node(device, target, label):
    previous = None
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if device.app_current().get("package") != "com.android.documentsui":
            raise StopRun("not-system-file-picker")
        if target.exists(timeout=.2):
            if target.count != 1:
                raise StopRun("picker-target-not-unique:" + label)
            bounds = target.info.get("bounds", {})
            valid = (bounds.get("right", 0) > bounds.get("left", 0) >= 0 and
                     bounds.get("bottom", 0) > bounds.get("top", 0) >= 0)
            if valid and bounds == previous:
                target.click()
                return
            previous = dict(bounds) if valid else None
        else:
            previous = None
        time.sleep(.2)
    raise StopRun("page-not-ready:picker-target:" + label)


def choose_system_file(device, item):
    if device.app_current().get("package") != "com.android.documentsui":
        raise StopRun("not-system-file-picker")
    roots = device(resourceId="com.android.documentsui:id/roots_list")
    if roots.exists and current_picker_folder(device, "zhensi_reports"):
        device.press("back")
        if not roots.wait_gone(timeout=5):
            raise StopRun("page-not-ready:storage-drawer-not-closed")
    route = "current-report-folder"
    if not current_picker_folder(device, "zhensi_reports"):
        folder = device(resourceId="android:id/title", text="zhensi_reports")
        header = device(resourceId="com.android.documentsui:id/header_title",
                        text="下载内容上的文件")
        if not roots.exists and header.exists and folder.exists:
            open_picker_folder(device, "zhensi_reports")
            evidence = choose_visible_report_file(device, item)
            return {**evidence, "navigationRoute": "current-downloads/report-folder"}
        # 使用系统提供的下载内容根入口，不再枚举内部存储根目录。
        if not roots.exists:
            device(description="显示根目录").click()
        if not roots.wait(timeout=5):
            raise StopRun("page-not-ready:storage-drawer-missing")
        root = roots.child(resourceId="android:id/title", text="下载内容")
        click_stable_picker_node(device, root, "下载内容")
        if not roots.wait_gone(timeout=8):
            raise StopRun("page-not-ready:storage-drawer-not-closed")
        if not device(resourceId="com.android.documentsui:id/header_title",
                      text="下载内容上的文件").wait(timeout=8):
            raise StopRun("page-not-ready:downloads-root-not-verified")
        open_picker_folder(device, "zhensi_reports")
        route = "downloads-shortcut/report-folder"
    evidence = choose_visible_report_file(device, item)
    return {**evidence, "navigationRoute": route}


def stable_report_rows(device, timeout=8):
    """Wait for the actual rows, not just the disappearing view-toggle."""
    previous = None
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if device.app_current().get("package") != "com.android.documentsui":
            raise StopRun("not-system-file-picker")
        root = ET.fromstring(device.dump_hierarchy())
        folder = any(n.get("text") == "zhensi_reports" for n in root.iter("node"))
        if not folder:
            raise StopRun("report-folder-not-verified")
        rows = tuple((n.get("text"), n.get("bounds")) for n in root.iter("node")
                     if n.get("resource-id") == "android:id/title" and n.get("text", "").endswith(".xlsx"))
        if rows and rows == previous:
            return rows
        previous = rows
        time.sleep(.25)
    raise StopRun("report-list-not-stable")


def stable_visible_report_target(device, item, timeout=3):
    """Only the bound target row must stabilize; unrelated history may keep loading."""
    previous = None
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if device.app_current().get("package") != "com.android.documentsui":
            raise StopRun("not-system-file-picker")
        target = device(text=item["name"])
        if target.exists(timeout=.15):
            if target.count != 1:
                raise StopRun("exact-filename-not-unique")
            bounds = target.info.get("bounds", {})
            if report_row_visible(device, bounds):
                if bounds == previous:
                    return target, bounds
                previous = dict(bounds)
            else:
                previous = None
        else:
            previous = None
        time.sleep(.2)
    return None, None


def choose_visible_report_file(device, item):
    if not device(text="zhensi_reports").exists:
        raise StopRun("report-folder-not-verified")
    list_toggle = device(resourceId="com.android.documentsui:id/sub_menu_list")
    if list_toggle.exists:
        if list_toggle.count != 1:
            raise StopRun("list-view-toggle-not-unique")
        list_toggle.click()
        if not list_toggle.wait_gone(timeout=5):
            raise StopRun("list-view-not-ready")
    listing = device(resourceId="com.android.documentsui:id/dir_list")
    target, bounds = stable_visible_report_target(device, item)
    # 文件列表可能先出现但暂时报 scrollable=false；目标行会稍后完成绑定。
    if target is None and listing.exists:
        target, bounds = stable_visible_report_target(device, item, timeout=5)
    listing_info = listing.info if listing.exists else {}
    can_scroll = isinstance(listing_info, dict) and listing_info.get("scrollable") is True
    if target is None and can_scroll:
        listing.scroll.toBeginning(steps=30, max_swipes=10)
        target, bounds = stable_visible_report_target(device, item)
    for attempt in range(11):
        if target is not None:
            break
        raw = device(text=item["name"])
        if raw.exists(timeout=.15) and raw.count == 1:
            raw_bounds = raw.info.get("bounds", {})
            # UI树可包含顶栏下面被裁剪的文件行；不得点击它。
            if can_scroll and raw_bounds.get("top", 0) < 300:
                listing.scroll.backward(steps=30)
            elif can_scroll:
                listing.scroll.forward(steps=30)
        elif can_scroll:
            listing.scroll.forward(steps=30)
        if attempt == 10 or not can_scroll:
            break
        target, bounds = stable_visible_report_target(device, item)
    if target is None:
        raise StopRun("exact-filename-not-unique")
    evidence = {"name": item["name"], "selector": "UI-tree-exact-text",
                "bounds": bounds, "sha256": item["sha256"]}
    target.click()
    return evidence


def report_row_visible(device, bounds):
    width, height = device.window_size()
    return (0 <= bounds.get("left", -1) < bounds.get("right", -1) <= width and
            300 <= bounds.get("top", -1) < bounds.get("bottom", -1) <= height - 160 and
            bounds.get("bottom", 0) - bounds.get("top", 0) >= 30)


def selected_send_signature(entries, item):
    compact = re.sub(r"\s+", "", "".join(x["text"] for x in sorted(entries, key=lambda x: (x["y"], x["x"]))))
    compact = compact.replace(".xIsx", ".xlsx")
    sends = exact(entries, "发送")
    if ("已选中1个文件" not in compact or item["name"] not in compact or
            f"{item['size'] / 1024:.1f}KB" not in compact or len(sends) != 1):
        return None
    return sends[0]


def stable_selected_send(device, helpers, work, item):
    deadline = time.monotonic() + 8
    previous = None
    while time.monotonic() < deadline:
        shot, entries = screenshot_entries(device, helpers, work, f"selected-file-{item['platform']}-stable")
        current = selected_send_signature(entries, item)
        if (current and previous and abs(current['x'] - previous['x']) <= 3
                and abs(current['y'] - previous['y']) <= 3):
            return shot, entries, current
        previous = current
        time.sleep(.25)
    raise StopRun("selected-file-animation-not-stable")


def timed_call(result, name, function, *args, **kwargs):
    start = time.monotonic()
    wall = time.time()
    ok = False
    try:
        value = function(*args, **kwargs)
        ok = True
        return value
    finally:
        result.setdefault("nodes", []).append({"name": name,
            "elapsedMs": round((time.monotonic() - start) * 1000), "ok": ok,
            "startedAt": wall, "finishedAt": time.time(),
            "llmIntervention": False})


def wait_group_title(device, helpers, merchant, work, group):
    return bool(helpers.poll(lambda: merchant.unique_group_in_title(device, helpers, work, group), bool, 8))


def prepare_selected_send(device, helpers, work, item, ledger_path=DELIVERY_LEDGER):
    ledger = load_delivery_ledger(ledger_path)
    previous = ledger["files"].get(item["sha256"])
    if previous:
        raise StopRun(f"already-attempted:{previous['state']}")
    size_label = f"{item['size'] / 1024:.1f}KB"
    prefix = item["name"].split("_")[0]
    shot, entries = wait_screen(device, helpers, work, f"selected-file-{item['platform']}",
        lambda e: any("已选中1个文件" in re.sub(r"\s+", "", x["text"]) for x in e))
    compact = re.sub(r"\s+", "", "".join(x["text"] for x in entries)).replace(".xIsx", ".xlsx")
    if prefix not in compact or size_label not in compact or len(exact(entries, "发送")) != 1:
        raise StopRun("selected-file-name-size-mismatch")
    shot, entries, send = stable_selected_send(device, helpers, work, item)
    ledger["files"][item["sha256"]] = {
        "name": item["name"], "size": item["size"], "state": "in-flight",
        "selectionScreenshot": str(shot), "attemptedAt": time.time(),
        "filePickerSendClicks": 1, "confirmSendClicks": 0}
    atomic_json(ledger_path, ledger)
    device.click(send["x"], send["y"])
    return ledger


def bubble_matches(entries, item):
    title = [x for x in entries if x["y"] < 280 and
             re.fullmatch(re.escape(TARGET_GROUP) + r"[（(]\d+[）)]",
                          re.sub(r"\s+", "", x["text"]))]
    body = re.sub(r"\s+", "", "".join(x["text"] for x in
                      sorted(entries, key=lambda x: (x["y"], x["x"])) if x["y"] > 280
                      and not (x["text"] == "X" and x["x"] > 750 and x.get("w", 999) < 60)))
    # Vision 对同一气泡的 xlsx 偶发读成 xIsx；仅纠正扩展名，不放宽日期/群名。
    body = body.replace(".xIsx", ".xlsx")
    return (len(title) == 1 and item["name"] in body and
            f"{item['size'] / 1024:.1f}KB" in body)


def bubble_upload_pending(entries, item):
    compact = re.sub(r"\s+", "", "".join(x["text"] for x in entries)).replace(".xIsx", ".xlsx")
    group = re.search(re.escape(TARGET_GROUP) + r"[（(]\d+[）)]", compact)
    return bool(group and item["name"] in compact and any(word in compact for word in ("上传中", "发送中")))


def verify_sent_file(device, helpers, work, item, ledger_path=DELIVERY_LEDGER):
    ledger = load_delivery_ledger(ledger_path)
    record = ledger["files"].get(item["sha256"])
    if not record or record["state"] not in ("in-flight", "confirmed"):
        raise StopRun("send-attempt-receipt-missing")
    deadline = time.monotonic() + 50
    consecutive = 0
    pending_frames = 0
    while time.monotonic() < deadline:
        if device.app_current().get("package") != "com.tencent.mm":
            raise StopRun("wechat-not-foreground-after-send")
        shot, entries = screenshot_entries(device, helpers, work, f"sent-{item['platform']}-stable")
        consecutive = consecutive + 1 if bubble_matches(entries, item) else 0
        pending_frames += int(bubble_upload_pending(entries, item))
        if consecutive >= 2:
            break
        time.sleep(.25)
    else:
        raise StopRun("sent-bubble-not-stable-within-50s")
    record.update({"state": "confirmed", "confirmedAt": time.time(),
                   "bubbleScreenshot": str(shot), "fullNameVerified": True,
                   "groupTitleVerified": True, "sizeVerified": True,
                   "uploadPendingFrames": pending_frames})
    atomic_json(ledger_path, ledger)
    return record


def local_group_candidate(entries):
    sections = [e['y'] for e in entries if e['text'] in ('最常使用', '群聊')]
    network = [e['y'] for e in entries if '搜索网络结果' in e['text']]
    if not sections or not network:
        return None
    matches = [e for e in entries if min(sections) < e['y'] < min(network)
               and re.fullmatch(re.escape(TARGET_GROUP)+r'[（(]\d+[）)]Q?', re.sub(r'\s+', '', e['text']))]
    return matches[0] if len(matches) == 1 else None


def is_main_wechat_chooser(device):
    current = device.app_current()
    activity = current.get("activity", "") if isinstance(current, dict) else ""
    return isinstance(activity, str) and "HwChooserActivity" in activity


def resolve_main_wechat_chooser(device, helpers, serial):
    if not is_main_wechat_chooser(device):
        return False
    main = device(description="微信")
    clone = device(description="微信分身")
    if not main.exists(timeout=.5) or main.count != 1 or not clone.exists(timeout=.5) or clone.count != 1:
        raise StopRun("main-wechat-chooser-identity-not-unique")
    main.click()
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        current = device.app_current()
        if current.get("package") == "com.tencent.mm" and "HwChooserActivity" not in current.get("activity", ""):
            processes = helpers.adb(serial, "shell", "ps", "-A", "-o", "USER,PID,NAME")
            if not re.search(r"^u0_a\d+\s+" + re.escape(str(current.get("pid"))) + r"\s+com\.tencent\.mm$", processes, re.MULTILINE):
                raise StopRun("foreground-main-wechat-identity-mismatch")
            return True
        time.sleep(.25)
    raise StopRun("main-wechat-chooser-transition-timeout")


def observe_file_page(device, helpers, work, item, serial=None):
    current = device.app_current()
    if current.get('package') == 'com.huawei.android.launcher':
        until = time.monotonic() + 5
        while time.monotonic() < until:
            time.sleep(.25)
            current = device.app_current()
            if current.get('package') != 'com.huawei.android.launcher':
                break
    package, activity = current.get("package"), current.get("activity", "")
    if package == "com.android.documentsui":
        return "picker"
    if package == "com.huawei.android.launcher":
        return "home"
    if package != "com.tencent.mm":
        return "obscured"
    if serial:
        processes = helpers.adb(serial, "shell", "ps", "-A", "-o", "USER,PID,NAME")
        if not re.search(r"^u0_a\d+\s+" + re.escape(str(current.get("pid"))) + r"\s+com\.tencent\.mm$", processes, re.MULTILINE):
            raise StopRun("foreground-main-wechat-identity-mismatch")
    _, entries = screenshot_entries(device, helpers, work, "flow-observe")
    compact = "".join(re.sub(r"\s+", "", e["text"]) for e in entries)
    if "已选中1个文件" in compact:
        if not selected_send_signature(entries, item):
            if "FileSelectorUI" in activity and not re.search(r"\.x[lI]sx", compact, re.I):
                selected = [e for e in entries if "已选中1个文件" in re.sub(r"\s+", "", e['text'])]
                if len(selected) == 1:
                    # 1080x2340已核验机型：已选栏左侧展开箭头，与标签同行；仅展开，不发送。
                    row = selected[0]
                    device.click(75, row['y'])
                    return "obscured"
            raise StopRun("selected-file-name-size-mismatch")
        return "selected"
    if "FileSelectorUI" in activity:
        return "file_selector"
    title = [e for e in entries if e["y"] < 280 and re.fullmatch(
        re.escape(TARGET_GROUP) + r"[（(]\d+[）)]", re.sub(r"\s+", "", e["text"]))]
    if len(title) == 1:
        return "group"
    candidate = local_group_candidate(entries)
    if candidate:
        device.click(candidate['x'], candidate['y'])
        return "obscured"
    if all(exact(entries, label) for label in ("微信", "通讯录", "发现", "我")):
        return "home"
    return "obscured"


def retry_proven_unsent(device, helpers, work, item, bound):
    """Only a still-open exact selected-file sheet proves a missed UI click."""
    ledger = load_delivery_ledger()
    record = ledger["files"].get(item["sha256"], {})
    if not bound or record.get("state") != "in-flight" or record.get("filePickerSendClicks", 0) >= 2:
        raise StopRun("send-recovery-not-authorized-by-state")
    shot, _, button = stable_selected_send(device, helpers, work, item)
    record.setdefault("recoveryAttempts", []).append({"at": time.time(), "proof": str(shot),
        "reason": "same-file-still-selected-two-stable-frames", "authorization": AUTHORIZATION})
    record["filePickerSendClicks"] += 1
    atomic_json(DELIVERY_LEDGER, ledger)
    device.click(button["x"], button["y"])


def deliver_with_resume(device, serial, helpers, merchant, work, files, result, checkpoint):
    hashes = {item["platform"]: item["sha256"] for item in files}
    saved = json.loads(checkpoint.read_text()) if checkpoint.exists() else {}
    validate_binding(saved, TARGET_GROUP, hashes)
    saved = saved or {"group": TARGET_GROUP, "hashes": hashes, "events": [], "createdAt": time.time()}
    result["checkpoint"] = str(checkpoint)
    for item in files:
        failures = 0
        while True:
            record = load_delivery_ledger()["files"].get(item["sha256"], {})
            if record.get("state") == "confirmed":
                result["sent"].append({"name": item["name"], "sha256": item["sha256"],
                    "verification": record, "reused": not any(e.get("action") in ("send", "retry_unsent")
                        and e.get("platform") == item["platform"] for e in saved["events"])})
                break
            start_wall, start_mono = time.time(), time.monotonic()
            event = {"platform": item["platform"], "startedAt": start_wall, "action": "observe", "llmIntervention": False}
            saved["current"] = event
            atomic_json(checkpoint, saved)
            try:
                if is_main_wechat_chooser(device):
                    timed_call(result, "main_wechat_chooser", resolve_main_wechat_chooser,
                               device, helpers, serial)
                try:
                    page = observe_file_page(device, helpers, work, item, serial)
                except StopRun as error:
                    if record.get('state') == 'in-flight' and str(error) == 'selected-file-name-size-mismatch':
                        page = 'obscured'  # 只读复验，不放宽发送身份或补点权限。
                    else:
                        raise
                bound = saved.get("groupVerified") and saved.get("activeHash") == item["sha256"]
                action = next_action(record.get("state"), page, bound)
                event.update({"page": page, "action": action})
                result["stage"] = action
                if action == "verify":
                    if page == "selected":
                        retry_proven_unsent(device, helpers, work, item, bound)
                        result["sendAttempts"] += 1
                        event["action"] = "retry_unsent"
                    elif page == "home":
                        merchant.open_main_wechat_group(device, serial, helpers, work, TARGET_GROUP)
                    # Unknown result: read-only verification, never open file picker again.
                    timed_call(result, item["platform"] + ".verify", verify_sent_file, device, helpers, work, item)
                elif action == "locate":
                    timed_call(result, "locate_group", merchant.open_main_wechat_group, device, serial, helpers, work, TARGET_GROUP)
                elif action == "panel":
                    saved.update({"groupVerified": True, "activeHash": item["sha256"]})
                    atomic_json(checkpoint, saved)
                    result["panel"] = timed_call(result, item["platform"] + ".file_panel", open_file_panel, device, helpers, work)
                elif action == "select":
                    result["selection"] = timed_call(result, item["platform"] + ".select_file", select_phone_file, device, helpers, work, item)
                elif action == "choose":
                    result["selection"] = timed_call(result, item["platform"] + ".choose_file", choose_system_file, device, item)
                elif action == "send":
                    timed_call(result, item["platform"] + ".send", prepare_selected_send, device, helpers, work, item)
                    result["sendAttempts"] += 1
                    timed_call(result, item["platform"] + ".verify", verify_sent_file, device, helpers, work, item)
                else:
                    raise StopRun("transient-page-obscured")
                event["ok"] = True
                failures = 0
            except Exception as error:
                event.update({"ok": False, "reason": str(error)})
                failures += 1
                if not retryable(error) or failures > 5:
                    raise
                delay = retry_delay(failures)
                event.update({"retry": failures, "backoffMs": round(delay * 1000)})
                time.sleep(delay)
            finally:
                event.update({"finishedAt": time.time(), "elapsedMs": round((time.monotonic()-start_mono)*1000)})
                saved["events"].append(event)
                saved["current"] = event
                atomic_json(checkpoint, saved)
    saved.update({"businessCompleted": True, "finishedAt": time.time()})
    atomic_json(checkpoint, saved)
    result["flowEvents"] = saved["events"]


def run(args) -> dict:
    started = time.monotonic()
    result = {"ok": False, "executor": "wechat-file-sender", "groupName": args.group,
              "sent": [], "sendAttempts": 0, "stage": "contract"}
    work = Path(tempfile.mkdtemp(prefix="zhensi-jinsha-wechat-"))
    try:
        # 保留参数兼容旧调用者，但效率时间戳不再中断业务。
        _, files = load_build_receipt(Path(args.build_receipt))
        if args.group != TARGET_GROUP:
            raise StopRun("target-group-mismatch")
        if args.execute and args.authorization != AUTHORIZATION:
            raise StopRun("standing-authorization-missing")
        helpers = load_module("zhensi_phone_helpers_files", PHONE_EXECUTOR)
        merchant = load_module("zhensi_merchant_sender_files", MERCHANT_SENDER)
        serial, identity = timed_call(result, "device_identity", select_verified_device, helpers)
        device = u2.connect(serial)
        if tuple(device.window_size()) != (1080, 2340):
            raise StopRun(f"unverified-display-geometry:{device.window_size()}")
        result["device"] = identity
        result["files"] = [{key: str(value) if isinstance(value, Path) else value for key, value in item.items()} for item in files]
        if args.verify_only:
            for item in files:
                verified = verify_sent_file(device, helpers, work, item)
                result["sent"].append({"name": item["name"], "sha256": item["sha256"], "verification": verified})
            result.update({"ok": True, "mode": "verify-only", "stage": "complete",
                           "totalConfirmedFiles": len(result["sent"]), "ledger": str(DELIVERY_LEDGER)})
            return result
        if not args.execute and not args.probe_panel:
            result.update({"ok": True, "mode": "dry-run", "stage": "complete"})
            return result

        result["stage"] = "push"
        remote_dir = "/sdcard/Download/zhensi_reports"
        helpers.adb(serial, "shell", "mkdir", "-p", remote_dir)
        for item in files:
            remote = f"{remote_dir}/{item['name']}"
            subprocess.run([helpers.ADB, "-s", serial, "push", str(item["file"]), remote],
                           check=True, capture_output=True, timeout=30)
            remote_hash = helpers.adb(serial, "shell", "sha256sum", remote).split()[0]
            if remote_hash != item["sha256"]:
                raise StopRun(f"device-hash-mismatch:{item['platform']}")
            item["remote"] = remote

        if args.execute and not args.probe_panel:
            checkpoint = Path(getattr(args, "checkpoint", "") or (str(args.send_receipt) + ".checkpoint.json"))
            deliver_with_resume(device, serial, helpers, merchant, work, files, result, checkpoint)
            result.update({"ok": True, "stage": "complete", "ledger": str(DELIVERY_LEDGER)})
            return result

        result["stage"] = "locate_group"
        try:
            if not (device.app_current().get("package") == "com.tencent.mm" and
                    wait_group_title(device, helpers, merchant, work, args.group)):
                merchant.open_main_wechat_group(device, serial, helpers, work, args.group)
        except Exception as first_error:
            # HarmonyOS 双开启动偶发先返回桌面焦点、随后才把主微信置前；只允许一次
            # 同通道恢复，且恢复前必须实证当前包已是 com.tencent.mm。
            current = helpers.poll(lambda: device.app_current(),
                                   lambda value: value.get("package") == "com.tencent.mm", 3)
            if "main-wechat-not-foreground" not in str(first_error) or current.get("package") != "com.tencent.mm":
                raise
            time.sleep(.4)
            merchant.open_main_wechat_group(device, serial, helpers, work, args.group)
            result["mainWechatRecovery"] = 1
        if not wait_group_title(device, helpers, merchant, work, args.group):
            raise StopRun("group-title-not-verified")
        result["groupTitleVerified"] = True

        ledger = load_delivery_ledger()
        if any(ledger["files"].get(item["sha256"], {}).get("state") == "in-flight" for item in files):
            raise StopRun("unresolved-send-attempt-verify-before-resume")
        for item in files:
            previous = ledger["files"].get(item["sha256"], {})
            if previous.get("state") == "confirmed":
                result["sent"].append({"name": item["name"], "sha256": item["sha256"], "reused": True})
                continue
            if not wait_group_title(device, helpers, merchant, work, args.group):
                raise StopRun("group-title-not-verified-before-file")
            result["stage"] = "file_panel"
            result["panel"] = timed_call(result, item["platform"] + ".file_panel", open_file_panel, device, helpers, work)
            file_screen, entries = wait_screen(device, helpers, work, "file-screen",
                lambda e: bool(exact(e, "手机文件")) and bool(exact(e, "选择文件")))
            if "FileSelectorUI" not in device.app_current().get("activity", ""):
                raise StopRun("wrong-file-selector-activity")
            if args.probe_panel:
                result.update({"ok": True, "mode": "probe-panel", "stage": "complete"})
                return result
            result["stage"] = "select_file"
            result["selection"] = timed_call(result, item["platform"] + ".select_file", select_phone_file, device, helpers, work, item)
            result["stage"] = "send_file"
            timed_call(result, item["platform"] + ".send", prepare_selected_send, device, helpers, work, item)
            result["sendAttempts"] += 1
            verified = timed_call(result, item["platform"] + ".verify", verify_sent_file, device, helpers, work, item)
            result["sent"].append({"name": item["name"], "sha256": item["sha256"], "verification": verified})
        result.update({"ok": True, "stage": "complete", "ledger": str(DELIVERY_LEDGER)})
        return result
    except Exception as error:
        result["reason"] = str(error)
        return result
    finally:
        result["businessCompleted"] = result["ok"]
        if args.deadline_unix:
            result["efficiencyExceeded"] = time.time() > args.deadline_unix
            result["efficiencyStatus"] = ("效率未达标" if result["efficiencyExceeded"]
                                          else ("效率达标" if result["ok"] else "尚未完成"))
        result["elapsedMs"] = round((time.monotonic() - started) * 1000)
        if args.keep_work:
            result["workDir"] = str(work)
        else:
            shutil.rmtree(work, ignore_errors=True)
        atomic_json(Path(args.send_receipt), result)


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-receipt", default=str(BUILD_RECEIPT))
    parser.add_argument("--send-receipt", default=str(SEND_RECEIPT))
    parser.add_argument("--group", default=TARGET_GROUP)
    parser.add_argument("--authorization", default="")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--probe-panel", action="store_true")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing sent bubbles; never click send")
    parser.add_argument("--deadline-unix", type=float, default=0, help="Efficiency target timestamp only; never interrupts delivery")
    parser.add_argument("--keep-work", action="store_true")
    parser.add_argument("--checkpoint", default="", help="Hash-bound persistent per-file workflow state")
    return parser.parse_args()


if __name__ == "__main__":
    payload = run(parse_args())
    print(json.dumps(payload, ensure_ascii=False))
    raise SystemExit(0 if payload.get("ok") else 1)
