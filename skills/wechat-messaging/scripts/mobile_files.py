"""Generic WeChat file-picker navigation; no production ledger or send action."""
import re,time,xml.etree.ElementTree as ET
from pathlib import Path
from contract import Rejected as StopRun
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
    if device.app_current().get('package')!='com.tencent.mm':raise StopRun('file-label-foreground-lost')
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
    import mobile_helpers as helpers
    import tempfile
    with tempfile.TemporaryDirectory(prefix='wechat-picker-check-') as d:
        helpers.screenshot(device,Path(d),'notification-clear')
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
    if roots.exists and current_picker_folder(device, "wechat_messaging"):
        device.press("back")
        if not roots.wait_gone(timeout=5):
            raise StopRun("page-not-ready:storage-drawer-not-closed")
    route = "current-report-folder"
    if not current_picker_folder(device, "wechat_messaging"):
        folder = device(resourceId="android:id/title", text="wechat_messaging")
        header = device(resourceId="com.android.documentsui:id/header_title",
                        text="下载内容上的文件")
        if not roots.exists and header.exists and folder.exists:
            open_picker_folder(device, "wechat_messaging")
            evidence = choose_visible_report_file(device, item)
            return {**evidence, "navigationRoute": "current-downloads/report-folder"}
        # 使用系统提供的下载内容根入口，不再枚举内部存储根目录。
        if not roots.exists:
            if device.app_current().get('package')!='com.android.documentsui':raise StopRun('picker-foreground-lost')
            click_stable_picker_node(device,device(description="显示根目录"),"显示根目录")
        if not roots.wait(timeout=5):
            raise StopRun("page-not-ready:storage-drawer-missing")
        root = roots.child(resourceId="android:id/title", text="下载内容")
        click_stable_picker_node(device, root, "下载内容")
        if not roots.wait_gone(timeout=8):
            raise StopRun("page-not-ready:storage-drawer-not-closed")
        if not device(resourceId="com.android.documentsui:id/header_title",
                      text="下载内容上的文件").wait(timeout=8):
            raise StopRun("page-not-ready:downloads-root-not-verified")
        open_picker_folder(device, "wechat_messaging")
        route = "downloads-shortcut/report-folder"
    evidence = choose_visible_report_file(device, item)
    return {**evidence, "navigationRoute": route}

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
    if not device(text="wechat_messaging").exists:
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
