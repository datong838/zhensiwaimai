#!/usr/bin/env python3
"""Repeatable UI-tree-only real-device acceptance for Android Enterprise WeChat.

Creates synthetic text/image/XLSX payloads and sends them only to the named
acceptance group. No screenshots, OCR, clipboard injection, or personal WeChat.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path

PACKAGE = "com.tencent.wework"
GROUP_PREFIX = "临时测试群请忽略"
SEARCH_ROW = f"{PACKAGE}:id/mid1Txt"
ADB = "/Users/os/.local/opt/android-sdk/platform-tools/adb"


def require(condition, reason):
    if not condition:
        raise RuntimeError(reason)


def wait_for(fn, predicate, timeout=8, interval=.2):
    until = time.monotonic() + timeout
    last = None
    while time.monotonic() < until:
        last = fn()
        if predicate(last):
            return last
        time.sleep(interval)
    raise RuntimeError("wait-timeout:" + str(last))


def tree(d):
    return ET.fromstring(d.dump_hierarchy())


def nodes(d, package=PACKAGE, rid=None, text=None, content_desc=None,
          clickable=None, enabled=None):
    result = []
    for n in tree(d).iter("node"):
        if package is not None and n.get("package") != package:
            continue
        if rid is not None and n.get("resource-id") != rid:
            continue
        if text is not None and n.get("text", "") != text:
            continue
        if content_desc is not None and n.get("content-desc", "") != content_desc:
            continue
        if clickable is not None and n.get("clickable") != str(clickable).lower():
            continue
        if enabled is not None and n.get("enabled") != str(enabled).lower():
            continue
        result.append(n)
    return result


def selector(d, *, package=PACKAGE, rid=None, text=None, desc=None):
    kw = {}
    if package is not None:
        kw["packageName"] = package
    if rid is not None:
        kw["resourceId"] = rid
    if text is not None:
        kw["text"] = text
    if desc is not None:
        kw["description"] = desc
    return d(**kw)


def bounds(n):
    vals = list(map(int, re.findall(r"\d+", n.get("bounds", ""))))
    require(len(vals) == 4, "control-bounds-invalid")
    return vals


def tap_node(d, n):
    x1, y1, x2, y2 = bounds(n)
    d.click((x1 + x2) // 2, (y1 + y2) // 2)


def click_exact(d, *, package=PACKAGE, rid=None, text=None, desc=None, enabled=None):
    target = selector(d, package=package, rid=rid, text=text, desc=desc)
    require(target.count == 1, "selector-not-unique:" + str((package, rid, text, desc, target.count)))
    if enabled is not None:
        require(target.info.get("enabled") is enabled, "selector-not-enabled:" + str(text or rid))
    target.click()
    return target


def adb(serial, *args):
    return subprocess.run([ADB, "-s", serial, *args], check=True,
                          capture_output=True, text=True, timeout=20).stdout.strip()


def prepare_assets(round_id: str, output: Path):
    from PIL import Image, ImageDraw
    from openpyxl import Workbook
    output.mkdir(parents=True, exist_ok=False)
    image = output / f"wecom_{round_id}_image.png"
    book = output / f"wecom_{round_id}_excel.xlsx"
    canvas = Image.new("RGB", (960, 600), "#eef6ff")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((20, 20, 940, 580), radius=24, outline="#145a8d", width=12)
    draw.text((80, 100), "Android WeCom • " + round_id, fill="#145a8d")
    draw.text((80, 220), "Blind UI tree test image", fill="#222222")
    draw.text((80, 340), "Synthetic only — no business data", fill="#222222")
    canvas.save(image)
    wb = Workbook()
    ws = wb.active
    ws.title = "Test"
    ws.append(["Round", "Payload", "Data"])
    ws.append([round_id, "Excel attachment", "Synthetic only"])
    wb.save(book)
    return image, book


def search_group(d):
    if d.app_current().get("package") != PACKAGE:
        raise RuntimeError("wecom-not-foreground")
    # The confirmed group back button returns to the global search screen from
    # the search-result route. If already there, do not navigate elsewhere.
    if not nodes(d, rid=f"{PACKAGE}:id/m0f"):
        click_exact(d, rid=f"{PACKAGE}:id/o62")
    wait_for(lambda: nodes(d, rid=f"{PACKAGE}:id/m0f"), lambda x: len(x) == 1)
    search = selector(d, rid=f"{PACKAGE}:id/m0f")
    search.set_text(GROUP_PREFIX)
    wait_for(lambda: nodes(d, rid=SEARCH_ROW),
             lambda xs: len([n for n in xs if n.get("text", "").startswith(GROUP_PREFIX)]) == 1)
    hits = [n for n in nodes(d, rid=SEARCH_ROW) if n.get("text", "").startswith(GROUP_PREFIX)]
    require(len(hits) == 1, "acceptance-group-search-not-unique")
    row = d.xpath(f'//*[@resource-id="{SEARCH_ROW}"]/../..').all()
    require(len(row) == 1 and row[0].info.get("clickable"), "acceptance-group-row-not-clickable-unique")
    row[0].click()
    wait_for(lambda: nodes(d, rid=f"{PACKAGE}:id/o6j"),
             lambda xs: len(xs) == 1 and xs[0].get("text", "").startswith(GROUP_PREFIX))


def send_text(d, round_id):
    text = f"【Android企业微信UI树盲操作 {round_id}】本轮文字验收，纯合成数据，请忽略。"
    composer = selector(d, rid=f"{PACKAGE}:id/iu5")
    require(composer.count == 1 and composer.get_text() in ("", "发消息或按住..."), "composer-not-empty")
    composer.click()
    composer.set_text(text)
    require(composer.get_text() == text, "text-composer-readback-mismatch")
    state = tree(d)
    require(sum(n.get("resource-id") == f"{PACKAGE}:id/o6j" and n.get("text", "").startswith(GROUP_PREFIX) for n in state.iter("node")) == 1,
            "target-group-header-changed")
    send = [n for n in state.iter("node") if n.get("package") == PACKAGE and
            n.get("resource-id") == f"{PACKAGE}:id/iu1" and n.get("text") == "发送" and
            n.get("clickable") == "true" and n.get("enabled") == "true"]
    require(len(send) == 1, "text-send-control-not-unique")
    tap_node(d, send[0])
    wait_for(lambda: [n.get("text", "") for n in nodes(d, rid=f"{PACKAGE}:id/ith")],
             lambda xs: text in xs)


def open_second_attachment_page(d):
    visible = nodes(d)
    if any(n.get("text") == "文件" for n in visible):
        return
    if not any(n.get("text") in ("图片", "拍摄", "文档") for n in visible):
        add = selector(d, rid=f"{PACKAGE}:id/its")
        require(add.count == 1 and add.info.get("enabled"), "add-control-not-unique-enabled")
        add.click()
    # The WeCom attachment sheet has two horizontal pages; use a slow, long
    # swipe within its lower tile row. A short swipe can be swallowed by the
    # chat underneath on high-density devices.
    d.swipe(1040, 2300, 180, 2300, .6)
    wait_for(lambda: nodes(d, text="文件"), lambda xs: len(xs) == 1)


def open_first_attachment_page(d):
    visible = nodes(d)
    if any(n.get("text") == "图片" for n in visible):
        return
    if any(n.get("text") == "文件" for n in visible):
        d.swipe(180, 2300, 1040, 2300, .6)
    else:
        add = selector(d, rid=f"{PACKAGE}:id/its")
        require(add.count == 1 and add.info.get("enabled"), "add-control-not-unique-enabled")
        add.click()
    wait_for(lambda: nodes(d, text="图片"), lambda xs: len(xs) == 1)


def send_image(d, serial, round_id, image):
    album = round_id
    remote = f"/sdcard/Pictures/{album}/{image.name}"
    adb(serial, "shell", "mkdir", "-p", f"/sdcard/Pictures/{album}")
    adb(serial, "push", str(image), remote)
    adb(serial, "shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d", f"file://{remote}")
    open_first_attachment_page(d)
    click_exact(d, text="图片")
    wait_for(lambda: d.app_current(), lambda x: x.get("activity") == ".msg.controller.CustomAlbumSlideSelectActivity")
    wait_for(lambda: nodes(d, rid=f"{PACKAGE}:id/o6j"), lambda xs: len(xs) == 1)
    time.sleep(.5)  # Allow the custom gallery's first frame to finish binding.
    if not any(n.get("text") == album for n in nodes(d, rid=f"{PACKAGE}:id/nxd")):
        click_exact(d, rid=f"{PACKAGE}:id/o6j")  # Open album selector.
        try:
            wait_for(lambda: nodes(d, rid=f"{PACKAGE}:id/nxd"),
                     lambda xs: any(n.get("text") == album for n in xs), timeout=2)
        except RuntimeError:
            # The first title tap can land during the custom gallery transition.
            # Retry only this read-only navigation if the album row is still absent.
            require(d.app_current().get("activity") == ".msg.controller.CustomAlbumSlideSelectActivity",
                    "gallery-lost-before-album-navigation")
            require(len(nodes(d, rid=f"{PACKAGE}:id/o6j")) == 1, "gallery-title-not-unique")
            click_exact(d, rid=f"{PACKAGE}:id/o6j")
            wait_for(lambda: nodes(d, rid=f"{PACKAGE}:id/nxd"),
                     lambda xs: any(n.get("text") == album for n in xs))
    wait_for(lambda: nodes(d, rid=f"{PACKAGE}:id/nxd"), lambda xs: any(n.get("text") == album for n in xs))
    album_row = d.xpath(f'//*[@resource-id="{PACKAGE}:id/nxd" and @text="{album}"]/..').all()
    require(len(album_row) == 1, "unique-image-album-not-found")
    # The visible album row is a non-clickable wrapper in this release, but its
    # accessibility-node click action is routed to the row's album handler.
    album_row[0].click()
    wait_for(lambda: nodes(d, rid=f"{PACKAGE}:id/o6j"),
             lambda xs: len(xs) == 1 and xs[0].get("text") == album)
    # This album is created for this one payload; the hierarchy must expose one
    # selectable media tile, which binds selection to the unique filename.
    tiles = [n for n in nodes(d, rid=f"{PACKAGE}:id/a35", clickable=True) if n.get("enabled") == "true"]
    require(len(tiles) == 1, "single-image-album-tile-not-unique")
    tap_node(d, tiles[0])
    require(any(n.get("text", "").replace(" ", "").startswith("1") for n in nodes(d, rid=f"{PACKAGE}:id/m6d")),
            "single-image-selection-not-visible")
    click_exact(d, rid=f"{PACKAGE}:id/koh", text="预览", enabled=True)
    wait_for(lambda: d.app_current(), lambda x: x.get("activity") == ".msg.controller.AlbumPreviewActivity")
    sends = wait_for(lambda: nodes(d, rid=f"{PACKAGE}:id/bv1"),
                     lambda xs: len([n for n in xs if n.get("text", "").startswith("发送") and n.get("enabled") == "true"]) == 1)
    time.sleep(.7)  # The enabled tree node appears before the preview send control is ready.
    sends = [n for n in nodes(d, rid=f"{PACKAGE}:id/bv1") if n.get("text", "").startswith("发送") and n.get("enabled") == "true"]
    require(len(sends) == 1, "selected-image-send-not-unique")
    tap_node(d, sends[0])
    wait_for(lambda: d.app_current(), lambda x: x.get("activity") == ".msg.controller.ExternalGroupMessageListActivity")
    require(selector(d, rid=f"{PACKAGE}:id/o6j").get_text().startswith(GROUP_PREFIX), "image-send-group-mismatch")


def send_file(d, serial, book):
    name = book.name
    remote = f"/sdcard/Download/{name}"
    adb(serial, "push", str(book), remote)
    open_second_attachment_page(d)
    click_exact(d, text="文件")
    time.sleep(.6)  # Attachment mode sheet animates before local/cloud choices bind.
    click_exact(d, text="从本地文件选择")
    wait_for(lambda: d.app_current(), lambda x: x.get("package") == "com.google.android.documentsui", timeout=12)
    click_exact(d, package="com.google.android.documentsui", text="文档")
    click_exact(d, package="com.google.android.documentsui", desc="显示根目录")
    click_exact(d, package="com.google.android.documentsui", rid="android:id/title", text="下载内容")
    wait_for(lambda: nodes(d, package="com.google.android.documentsui", rid="com.google.android.documentsui:id/breadcrumb_text"),
             lambda xs: any("下载内容" in n.get("text", "") for n in xs))
    time.sleep(.3)
    target = selector(d, package="com.google.android.documentsui", rid="android:id/title", text=name)
    require(target.count == 1, "exact-local-xlsx-not-unique")
    target.click()
    wait_for(lambda: d.app_current(), lambda x: x.get("activity") == ".msg.utils.ForwardDialogUtil")
    dialog = tree(d)
    group_name = "临时测试群请忽略 ..发财精英荟.."
    require(sum(n.get("resource-id") == f"{PACKAGE}:id/e7d" and n.get("text") == group_name for n in dialog.iter("node")) == 1,
            "xlsx-target-group-confirmation-mismatch")
    require(sum(n.get("resource-id") == f"{PACKAGE}:id/fih" and name in n.get("text", "") for n in dialog.iter("node")) == 1,
            "xlsx-name-confirmation-mismatch")
    click_exact(d, rid=f"{PACKAGE}:id/dnf", text="发送", enabled=True)
    wait_for(lambda: d.app_current(), lambda x: x.get("activity") == ".msg.controller.ExternalGroupMessageListActivity")
    cards = [n.get("text", "").replace("\n", "") for n in nodes(d, rid=f"{PACKAGE}:id/iui")]
    require(name in cards, "xlsx-file-card-not-read-back")


def run_round(serial, round_id, output):
    import uiautomator2 as u2
    image, book = prepare_assets(round_id, output)
    d = u2.connect(serial)
    if d.app_current().get("package") != PACKAGE:
        raise RuntimeError("enterprise-wechat-not-foreground")
    started = time.monotonic()
    search_group(d)
    send_text(d, round_id)
    send_image(d, serial, round_id, image)
    send_file(d, serial, book)
    elapsed = round(time.monotonic() - started, 2)
    return {"round": round_id, "ok": True, "channel": "mobile-wecom",
            "groupPrefix": GROUP_PREFIX, "items": ["text", "image", "xlsx"],
            "uiMode": "uiautomator-accessibility-tree-only", "screenshots": 0,
            "ocr": 0, "elapsedSeconds": elapsed,
            "image": str(image), "xlsx": str(book)}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--serial", required=True)
    p.add_argument("--round", required=True)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    print(run_round(a.serial, a.round, Path(a.output)), flush=True)


if __name__ == "__main__":
    main()
