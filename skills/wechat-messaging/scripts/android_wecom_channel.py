"""Independent Android Enterprise WeChat adapter for the shared delivery engine.

This adapter owns only ``com.tencent.wework``. It never imports, patches, or
changes the personal-WeChat MobileAdapter or the Mac desktop sender.
"""
from __future__ import annotations

import fcntl
import hashlib
import os
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from contextlib import contextmanager
from pathlib import Path

from contract import Rejected

PACKAGE = "com.tencent.wework"
ADB = os.environ.get("ANDROID_ADB", "/Users/os/.local/opt/android-sdk/platform-tools/adb")
ROOT = Path(__file__).resolve().parents[1]
_UI = Path(__file__).resolve().parent
if str(_UI) not in sys.path:
    sys.path.insert(0, str(_UI))
import android_wecom_acceptance as ui


def _canon(value):
    return re.sub(r"[^0-9A-Za-z\u3400-\u9fff]", "", value or "")


def _wait(fn, predicate, timeout=8, interval=.2, reason="ui-state-timeout"):
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        last = fn()
        if predicate(last):
            return last
        time.sleep(interval)
    raise Rejected(reason)


def _adb(serial, *args):
    if not serial or serial.startswith("emulator-"):
        raise Rejected("physical-device-required")
    return subprocess.run([ADB, "-s", serial, *args], check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()


def _import_u2():
    try:
        import uiautomator2 as u2
        return u2
    except ImportError:
        # Keep the dependency isolated from the system Python and the personal
        # WeChat channel. The user-approved, dedicated venv is the fallback.
        site = Path("/Users/os/.local/share/zhensi-mobile-wecom-venv/lib/python3.9/site-packages")
        if site.is_dir() and str(site) not in sys.path:
            sys.path.insert(0, str(site))
        import uiautomator2 as u2
        return u2


def _group_core(group):
    # Group headers truncate the final emoji/character on this WeCom build.
    # The exact search result and external-group subtitle are checked separately.
    return _canon(group)[:10]


class AndroidWeComAdapter:
    channel = "mobile-wecom"
    supported = {"text", "image", "file"}

    def __init__(self, serial):
        if not serial or serial.startswith("emulator-"):
            raise Rejected("physical-device-required")
        self.serial = serial
        self.device = None
        self.device_hash = hashlib.sha256(serial.encode()).hexdigest()[:12]
        self.group_display = None
        self.group_name = None
        self._attempted = False

    @contextmanager
    def session(self, request):
        lock = ROOT / ".runtime" / f"mobile-{self.device_hash}.lock"
        lock.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with lock.open("a") as stream:
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise Rejected("phone-busy-on-another-channel") from error
            self.device = _import_u2().connect(self.serial)
            if self.device.app_current().get("package") != PACKAGE:
                fcntl.flock(stream, fcntl.LOCK_UN)
                raise Rejected("enterprise-wechat-not-foreground")
            if tuple(self.device.window_size()) != (1220, 2712):
                fcntl.flock(stream, fcntl.LOCK_UN)
                raise Rejected("unverified-enterprise-phone-geometry")
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    def _chat_header(self):
        return ui.nodes(self.device, rid=f"{PACKAGE}:id/o6j")

    def _assert_target_chat(self):
        if self.device.app_current().get("package") != PACKAGE:
            raise Rejected("wecom-not-foreground")
        headers = self._chat_header()
        if len(headers) != 1 or not _canon(headers[0].get("text", "")).startswith(_group_core(self.group_name)):
            raise Rejected("target-group-header-mismatch")

    def _search_group(self, request):
        group = request["groupName"]
        search_name = request["context"].get("searchGroupName") or group
        if self.device.app_current().get("package") != PACKAGE:
            raise Rejected("wecom-not-foreground")
        search_nodes = ui.nodes(self.device, rid=f"{PACKAGE}:id/m0f")
        if not search_nodes:
            for _ in range(3):
                if len(ui.nodes(self.device, rid=f"{PACKAGE}:id/m0f")) == 1:
                    break
                backs = ui.nodes(self.device, rid=f"{PACKAGE}:id/o62", clickable=True, enabled=True)
                if len(backs) != 1:
                    raise Rejected("wecom-chat-back-control-not-unique")
                self.device(resourceId=f"{PACKAGE}:id/o62").click()
                try:
                    _wait(lambda: ui.nodes(self.device, rid=f"{PACKAGE}:id/m0f"),
                          lambda xs: len(xs) == 1, timeout=2, reason="global-search-not-opened")
                except Rejected:
                    pass
            if len(ui.nodes(self.device, rid=f"{PACKAGE}:id/m0f")) != 1:
                raise Rejected("global-search-not-opened")
        search = self.device(resourceId=f"{PACKAGE}:id/m0f")
        if search.count != 1:
            raise Rejected("group-search-control-not-unique")
        search.set_text(search_name)
        expected_prefix = _group_core(group)
        _wait(lambda: ui.nodes(self.device, rid=f"{PACKAGE}:id/mid1Txt"),
              lambda xs: len([n for n in xs if _canon(n.get("text", "")).startswith(expected_prefix)]) == 1,
              reason="exact-group-search-result-not-unique")
        rows = [n for n in ui.nodes(self.device, rid=f"{PACKAGE}:id/mid1Txt")
                if _canon(n.get("text", "")).startswith(expected_prefix)]
        if len(rows) != 1:
            raise Rejected("exact-group-search-result-not-unique")
        row_text = rows[0].get("text", "")
        row = self.device.xpath(f'//*[@resource-id="{PACKAGE}:id/mid1Txt"]/../..').all()
        if len(row) != 1 or not row[0].info.get("clickable"):
            raise Rejected("group-result-row-not-clickable-unique")
        state = ui.tree(self.device)
        row_nodes = [n for n in state.iter("node") if n.get("resource-id") == f"{PACKAGE}:id/mid1Txt"
                     and n.get("text") == row_text]
        if len(row_nodes) != 1:
            raise Rejected("group-result-row-evidence-ambiguous")
        parent_map = {child: parent for parent in state.iter("node") for child in parent}
        ancestor = row_nodes[0]
        member_count_proven = False
        for _ in range(5):
            ancestor = parent_map.get(ancestor)
            if ancestor is None:
                break
            if any(re.fullmatch(r"\(\d+\)", n.get("text", "")) for n in ancestor.iter("node")):
                member_count_proven = True
                break
        if not member_count_proven:
            raise Rejected("group-member-count-proof-missing")
        row[0].click()
        self.group_name = group
        _wait(self._chat_header,
              lambda xs: len(xs) == 1 and _canon(xs[0].get("text", "")).startswith(_group_core(group)),
              reason="selected-group-header-mismatch")
        subtitles = ui.nodes(self.device, rid=f"{PACKAGE}:id/o6t")
        if len(subtitles) != 1 or "外部群" not in subtitles[0].get("text", ""):
            raise Rejected("external-group-proof-missing")
        self.group_display = row_text
        return {"ok": True, "groupName": group, "candidate": row_text,
                "groupTypeVerified": True, "groupTypeProof": "unique-search-row-member-count-and-external-subtitle",
                "transport": "android-uiautomator-accessibility"}

    def preflight(self, request, output):
        output.mkdir(parents=True, exist_ok=True, mode=0o700)
        result = self._search_group(request)
        self._assert_target_chat()
        composers = ui.nodes(self.device, rid=f"{PACKAGE}:id/iu5", clickable=True, enabled=True)
        if len(composers) != 1 or composers[0].get("text", "") not in ("", "发消息或按住..."):
            raise Rejected("composer-not-empty")
        return result | {"composerVerifiedEmpty": True, "deviceHash": self.device_hash}

    def _tap_send_by_text(self, text):
        self._assert_target_chat()
        control = ui.nodes(self.device, rid=f"{PACKAGE}:id/iu1", text=text,
                           clickable=True, enabled=True)
        if len(control) != 1:
            raise Rejected("text-send-control-not-unique")
        self._attempted = True
        ui.tap_node(self.device, control[0])

    def _send_text(self, item):
        text = item["text"]
        before = sum(n.get("text") == text for n in ui.nodes(self.device, rid=f"{PACKAGE}:id/ith"))
        composer = self.device(resourceId=f"{PACKAGE}:id/iu5")
        if composer.count != 1 or composer.get_text() not in ("", "发消息或按住..."):
            raise Rejected("composer-not-uniquely-empty")
        composer.click()
        composer.set_text(text)
        if composer.get_text() != text:
            raise Rejected("composer-exact-readback-failed")
        self._tap_send_by_text("发送")
        _wait(lambda: [n.get("text", "") for n in ui.nodes(self.device, rid=f"{PACKAGE}:id/ith")],
              lambda xs: sum(x == text for x in xs) > before,
              reason="sent-text-not-exactly-read-back")
        return {"verificationLevel": "accessibility-tree-exact-new-message"}

    def _panel_first(self):
        labels = ui.nodes(self.device)
        if any(n.get("text") == "图片" for n in labels):
            return
        if any(n.get("text") == "文件" for n in labels):
            self.device.swipe(180, 2300, 1040, 2300, .6)
        else:
            add = ui.nodes(self.device, rid=f"{PACKAGE}:id/its", clickable=True, enabled=True)
            if len(add) != 1:
                raise Rejected("chat-add-control-not-unique")
            ui.tap_node(self.device, add[0])
            if not any(n.get("text") == "图片" for n in ui.nodes(self.device)):
                self.device.swipe(180, 2300, 1040, 2300, .6)
        _wait(lambda: ui.nodes(self.device, text="图片"), lambda xs: len(xs) == 1,
              reason="attachment-image-entry-not-ready")

    def _panel_second(self):
        labels = ui.nodes(self.device)
        if any(n.get("text") == "文件" for n in labels):
            return
        if any(n.get("text") == "图片" for n in labels):
            self.device.swipe(1040, 2300, 180, 2300, .6)
        else:
            add = ui.nodes(self.device, rid=f"{PACKAGE}:id/its", clickable=True, enabled=True)
            if len(add) != 1:
                raise Rejected("chat-add-control-not-unique")
            ui.tap_node(self.device, add[0])
            if not any(n.get("text") == "文件" for n in ui.nodes(self.device)):
                self.device.swipe(1040, 2300, 180, 2300, .6)
        _wait(lambda: ui.nodes(self.device, text="文件"), lambda xs: len(xs) == 1,
              reason="attachment-file-entry-not-ready")

    def _send_image(self, item, request):
        path = Path(item["path"]).resolve()
        if not path.is_file():
            raise Rejected("image-payload-missing")
        album = "zwm_" + hashlib.sha256((request["context"]["eventId"] + item["itemId"]).encode()).hexdigest()[:12]
        remote = f"/sdcard/Pictures/{album}/{path.name}"
        _adb(self.serial, "shell", "mkdir", "-p", f"/sdcard/Pictures/{album}")
        _adb(self.serial, "push", str(path), remote)
        _adb(self.serial, "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
             "-d", f"file://{remote}")
        before = len(ui.nodes(self.device, rid=f"{PACKAGE}:id/kj3"))
        self._panel_first()
        ui.click_exact(self.device, text="图片")
        _wait(lambda: self.device.app_current(),
              lambda x: x.get("activity") == ".msg.controller.CustomAlbumSlideSelectActivity",
              reason="gallery-page-not-ready")
        time.sleep(.5)
        if not any(n.get("text") == album for n in ui.nodes(self.device, rid=f"{PACKAGE}:id/nxd")):
            ui.click_exact(self.device, rid=f"{PACKAGE}:id/o6j")
            try:
                _wait(lambda: ui.nodes(self.device, rid=f"{PACKAGE}:id/nxd"),
                      lambda xs: any(n.get("text") == album for n in xs), timeout=2,
                      reason="album-selector-not-ready")
            except Rejected:
                if self.device.app_current().get("activity") != ".msg.controller.CustomAlbumSlideSelectActivity":
                    raise
                ui.click_exact(self.device, rid=f"{PACKAGE}:id/o6j")
                _wait(lambda: ui.nodes(self.device, rid=f"{PACKAGE}:id/nxd"),
                      lambda xs: any(n.get("text") == album for n in xs), reason="unique-album-not-found")
        rows = self.device.xpath(f'//*[@resource-id="{PACKAGE}:id/nxd" and @text="{album}"]/..').all()
        if len(rows) != 1:
            raise Rejected("unique-image-album-not-found")
        rows[0].click()
        _wait(lambda: ui.nodes(self.device, rid=f"{PACKAGE}:id/o6j"),
              lambda xs: (len(xs) == 1 and len(_canon(xs[0].get("text", ""))) >= 10
                          and _canon(album).startswith(_canon(xs[0].get("text", "")))),
              reason="unique-image-album-not-selected")
        tiles = [n for n in ui.nodes(self.device, rid=f"{PACKAGE}:id/a35", clickable=True, enabled=True)]
        if len(tiles) != 1:
            raise Rejected("single-image-album-tile-not-unique")
        ui.tap_node(self.device, tiles[0])
        _wait(lambda: ui.nodes(self.device, rid=f"{PACKAGE}:id/m6d"),
              lambda xs: any(n.get("text") == "1" for n in xs), reason="single-image-selection-not-visible")
        ui.click_exact(self.device, rid=f"{PACKAGE}:id/koh", text="预览", enabled=True)
        _wait(lambda: self.device.app_current(),
              lambda x: x.get("activity") == ".msg.controller.AlbumPreviewActivity",
              reason="image-preview-not-opened")
        sends = _wait(lambda: ui.nodes(self.device, rid=f"{PACKAGE}:id/bv1"),
                      lambda xs: len([n for n in xs if n.get("text", "").startswith("发送") and n.get("enabled") == "true"]) == 1,
                      reason="selected-image-send-not-unique")
        time.sleep(.7)
        sends = [n for n in ui.nodes(self.device, rid=f"{PACKAGE}:id/bv1")
                 if n.get("text", "").startswith("发送") and n.get("enabled") == "true"]
        if len(sends) != 1:
            raise Rejected("selected-image-send-not-unique")
        self._attempted = True
        ui.tap_node(self.device, sends[0])
        _wait(lambda: self.device.app_current(),
              lambda x: x.get("activity") == ".msg.controller.ExternalGroupMessageListActivity",
              reason="image-send-chat-not-restored")
        self._assert_target_chat()
        _wait(lambda: len(ui.nodes(self.device, rid=f"{PACKAGE}:id/kj3")),
              lambda count: count > before, reason="new-image-message-not-visible")
        return {"verificationLevel": "single-image-album-and-new-image-message-node"}

    def _send_file(self, item, request):
        path = Path(item["path"]).resolve()
        if not path.is_file():
            raise Rejected("file-payload-missing")
        unique = hashlib.sha256((request["context"]["eventId"] + item["itemId"]).encode()).hexdigest()[:10]
        name = f"wcom_{unique}_{path.name}"
        if not re.fullmatch(r"[\w.\-\u3400-\u9fff ]+", name):
            raise Rejected("file-name-not-supported")
        _adb(self.serial, "push", str(path), f"/sdcard/Download/{name}")
        self._panel_second()
        ui.click_exact(self.device, text="文件")
        time.sleep(.6)
        ui.click_exact(self.device, text="从本地文件选择")
        _wait(lambda: self.device.app_current(), lambda x: x.get("package") == "com.google.android.documentsui",
              timeout=12, reason="system-document-picker-not-ready")
        ui.click_exact(self.device, package="com.google.android.documentsui", text="文档")
        ui.click_exact(self.device, package="com.google.android.documentsui", desc="显示根目录")
        ui.click_exact(self.device, package="com.google.android.documentsui", rid="android:id/title", text="下载内容")
        _wait(lambda: ui.nodes(self.device, package="com.google.android.documentsui",
                               rid="com.google.android.documentsui:id/breadcrumb_text"),
              lambda xs: any("下载内容" in n.get("text", "") for n in xs),
              reason="downloads-folder-not-open")
        time.sleep(.3)
        target = self.device(resourceId="android:id/title", text=name)
        if target.count != 1:
            raise Rejected("exact-local-file-not-unique")
        target.click()
        _wait(lambda: self.device.app_current(), lambda x: x.get("activity") == ".msg.utils.ForwardDialogUtil",
              reason="file-send-confirmation-not-open")
        state = ui.tree(self.device)
        groups = [n for n in state.iter("node") if n.get("package") == PACKAGE and
                  n.get("resource-id") == f"{PACKAGE}:id/e7d"]
        files = [n for n in state.iter("node") if n.get("package") == PACKAGE and
                 n.get("resource-id") == f"{PACKAGE}:id/fih" and name in n.get("text", "")]
        if len(groups) != 1 or _canon(groups[0].get("text", "")) != _canon(self.group_display):
            raise Rejected("file-target-group-confirmation-mismatch")
        if len(files) != 1:
            raise Rejected("file-name-confirmation-mismatch")
        send = ui.nodes(self.device, rid=f"{PACKAGE}:id/dnf", text="发送", clickable=True, enabled=True)
        if len(send) != 1:
            raise Rejected("file-confirm-send-control-not-unique")
        self._attempted = True
        ui.tap_node(self.device, send[0])
        _wait(lambda: self.device.app_current(),
              lambda x: x.get("activity") == ".msg.controller.ExternalGroupMessageListActivity",
              reason="file-send-chat-not-restored")
        self._assert_target_chat()
        if len(self._sent_file_cards(name)) != 1:
            raise Rejected("sent-file-card-not-uniquely-read-back")
        return {"verificationLevel": "unique-file-card-event-prefix-extension-and-target-confirmation",
                "sentName": name, "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def _sent_file_cards(self, name):
        prefix = name[:16]  # Includes the per-event 10-hex suffix before UI truncation.
        suffix = Path(name).suffix
        return [normalized for normalized in
                ("".join(n.get("text", "").split()) for n in
                 ui.nodes(self.device, rid=f"{PACKAGE}:id/iui"))
                if normalized.startswith(prefix) and normalized.endswith(suffix)]

    def send_one(self, request, item, work, grant, deadline):
        self._attempted = False
        try:
            self._assert_target_chat()
            if item["type"] == "text":
                proof = self._send_text(item)
            elif item["type"] == "image":
                proof = self._send_image(item, request)
            elif item["type"] == "file":
                proof = self._send_file(item, request)
            else:
                raise Rejected("unsupported-payload-type")
            return {"status": "verified", "sendAttempts": 1, "deviceHash": self.device_hash,
                    "verificationLevel": proof.pop("verificationLevel"), "evidence": proof,
                    "backend": "android-uiautomator-wecom"}
        except Exception as error:
            return {"status": "unknown" if self._attempted else "blocked",
                    "sendAttempts": 1 if self._attempted else 0,
                    "reason": str(error), "deviceHash": self.device_hash,
                    "backend": "android-uiautomator-wecom"}

    def reconcile(self, request, item, work, prior):
        if item["type"] == "file":
            self._assert_target_chat()
            unique = hashlib.sha256((request["context"]["eventId"] + item["itemId"]).encode()).hexdigest()[:10]
            name = f"wcom_{unique}_{Path(item['path']).name}"
            cards = self._sent_file_cards(name)
            if len(cards) == 1:
                return {"status": "verified", "sendAttempts": 1,
                        "verificationLevel": "read-only-unique-file-card-prefix-and-extension",
                        "evidence": {"matchedCard": cards[0], "sentName": name}}
        return {"status": "unknown", "sendAttempts": 0,
                "reason": "mobile-wecom-readonly-reconcile-not-implemented"}
