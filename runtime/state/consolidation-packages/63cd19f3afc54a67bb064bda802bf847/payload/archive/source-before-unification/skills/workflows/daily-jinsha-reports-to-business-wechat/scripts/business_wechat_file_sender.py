#!/usr/bin/env python3
"""Business-group profile for the frozen Jinsha WeChat file sender."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path


THIS_DIR = Path(__file__).resolve().parent
FROZEN_DIR = THIS_DIR.parents[2] / ".daily-jinsha-reports-core" / "scripts"
FROZEN_SENDER = FROZEN_DIR / "wechat_file_sender.py"
TARGET_GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
AUTHORIZATION = "zhensi-business-main-wechat-shanghai-zhensi-operations-ding-fandang-daily-v2-reauthorized-20260917"
DELIVERY_LEDGER = THIS_DIR.parents[3] / ".local/state/jinsha-report-send-shanghai-zhensi-operations-ding-fandang-reauthorized-20260917-v2.json"
BUSINESS_GROUP_LOCATOR = THIS_DIR / "business_wechat_group_locator.py"
INTERNAL_INVOCATION = "business-workflow-executor-v1"


def normalize_business_group_ocr(value):
    return re.sub(r"\s+", "", value).replace("Al数字员工", "AI数字员工")


def business_search_results(entries):
    pattern = re.escape(normalize_business_group_ocr(TARGET_GROUP)) + r"[（(]\d+[）)]"
    return [
        entry for entry in entries
        if 280 < entry["y"] < 900
        and re.fullmatch(pattern, normalize_business_group_ocr(entry["text"]))
    ]


def load_frozen_sender():
    sys.path.insert(0, str(FROZEN_DIR))
    spec = importlib.util.spec_from_file_location("frozen_jinsha_wechat_sender", FROZEN_SENDER)
    if spec is None or spec.loader is None:
        raise RuntimeError("frozen-sender-load-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TARGET_GROUP = TARGET_GROUP
    module.AUTHORIZATION = AUTHORIZATION
    module.DELIVERY_LEDGER = DELIVERY_LEDGER
    module.MERCHANT_SENDER = BUSINESS_GROUP_LOCATOR
    # The frozen sender binds its ledger path in three function defaults at
    # import time. Rebind only those defaults so the business profile never
    # reads or writes the sealed test-group ledger.
    for name in ("load_delivery_ledger", "prepare_selected_send", "verify_sent_file"):
        function = getattr(module, name)
        defaults = list(function.__defaults__ or ())
        if not defaults:
            raise RuntimeError(f"frozen-ledger-default-missing:{name}")
        defaults[-1] = DELIVERY_LEDGER
        function.__defaults__ = tuple(defaults)

    # The frozen test group has no spaces.  Its title matcher removes OCR
    # whitespace but not whitespace from TARGET_GROUP, which makes a real
    # group containing spaces impossible to recognize.  Patch only this
    # business-loaded module instance and keep the exact target unchanged.
    original_observe_file_page = module.observe_file_page

    def compact_group_pattern():
        return re.escape(re.sub(r"\s+", "", TARGET_GROUP)) + r"[（(]\d+[）)]"

    def normalize_group_ocr(value):
        # In the WeChat title font OCR consistently confuses uppercase I with
        # lowercase l.  Normalize only this exact ASCII token; all Chinese
        # characters and the member count remain mandatory.
        return normalize_business_group_ocr(value)

    def business_group_title(entries):
        return [
            entry for entry in entries
            if entry["y"] < 280
            and re.fullmatch(compact_group_pattern(), normalize_group_ocr(entry["text"]))
        ]

    def business_observe_file_page(device, helpers, work, item, serial=None):
        page = original_observe_file_page(device, helpers, work, item, serial)
        if page != "obscured" or device.app_current().get("package") != "com.tencent.mm":
            return page
        _, entries = module.screenshot_entries(device, helpers, work, "flow-observe-business-title")
        if "FTSMainUI" in device.app_current().get("activity", "") and len(business_search_results(entries)) == 1:
            # A failed zero-send locate may leave the exact search result open.
            # Route back through the sealed locate action instead of treating it
            # as an unknown page; in-flight records still take the verify path.
            return "home"
        return "group" if len(business_group_title(entries)) == 1 else page

    def business_bubble_matches(entries, item):
        body = re.sub(
            r"\s+",
            "",
            "".join(
                entry["text"] for entry in sorted(entries, key=lambda value: (value["y"], value["x"]))
                if entry["y"] > 280
                and not (entry["text"] == "X" and entry["x"] > 750 and entry.get("w", 999) < 60)
            ),
        ).replace(".xIsx", ".xlsx")
        stem = item["name"][:-5]
        prefix, business_date = stem.rsplit("_", 1)
        filename_seen = bool(re.search(
            re.escape(prefix) + r"_?" + re.escape(business_date) + r"\.xlsx",
            body,
        ))
        return (
            len(business_group_title(entries)) == 1
            and filename_seen
            and f"{item['size'] / 1024:.1f}KB" in body
        )

    def business_bubble_upload_pending(entries, item):
        compact = normalize_group_ocr("".join(entry["text"] for entry in entries)).replace(
            ".xIsx", ".xlsx"
        )
        stem = item["name"][:-5]
        prefix, business_date = stem.rsplit("_", 1)
        filename_seen = bool(re.search(
            re.escape(prefix) + r"_?" + re.escape(business_date) + r"\.xlsx",
            compact,
        ))
        return bool(
            re.search(compact_group_pattern(), compact)
            and filename_seen
            and any(word in compact for word in ("上传中", "发送中"))
        )

    def business_choose_visible_report_file(device, item):
        """Select the exact file even when DocumentsUI reports scrollable=false."""
        if not device(text="zhensi_reports").exists:
            raise module.StopRun("report-folder-not-verified")
        width, height = device.window_size()
        previous = None
        for _ in range(12):
            if device.app_current().get("package") != "com.android.documentsui":
                raise module.StopRun("not-system-file-picker")
            targets = device(text=item["name"])
            if targets.exists(timeout=0.2):
                # DocumentsUI can expose duplicate parent/child nodes.  They
                # are one file only when every exact node has identical bounds.
                infos = [targets[index].info for index in range(targets.count)]
                bounds_set = {
                    tuple(info.get("bounds", {}).get(key, -1) for key in ("left", "top", "right", "bottom"))
                    for info in infos
                }
                if len(bounds_set) != 1:
                    raise module.StopRun("exact-filename-real-duplicate")
                left, top, right, bottom = next(iter(bounds_set))
                bounds = {"left": left, "top": top, "right": right, "bottom": bottom}
                visible = 300 <= top < bottom <= height - 160 and 0 <= left < right <= width
                if visible and bounds == previous:
                    device.click((left + right) // 2, (top + bottom) // 2)
                    return {
                        "name": item["name"],
                        "selector": "business-exact-text-stable-bounds",
                        "bounds": bounds,
                        "sha256": item["sha256"],
                    }
                previous = dict(bounds) if visible else None
                if bottom > height - 160:
                    device.swipe(width // 2, height - 360, width // 2, height // 2, 0.25)
                elif top < 300:
                    device.swipe(width // 2, height // 2, width // 2, height - 360, 0.25)
            else:
                previous = None
                device.swipe(width // 2, height - 360, width // 2, height // 2, 0.25)
            time.sleep(0.3)
        raise module.StopRun("exact-filename-not-visible-after-bounded-scroll")

    module.observe_file_page = business_observe_file_page
    module.bubble_matches = business_bubble_matches
    module.bubble_upload_pending = business_bubble_upload_pending
    module.choose_visible_report_file = business_choose_visible_report_file
    return module


def main() -> int:
    if os.environ.get("JINSHA_WORKFLOW_INTERNAL") != INTERNAL_INVOCATION:
        print(json.dumps({"ok": False, "reason": "direct-stage-invocation-forbidden"}, ensure_ascii=False))
        return 1
    module = load_frozen_sender()
    args = module.parse_args()
    if args.group != TARGET_GROUP:
        payload = {"ok": False, "reason": "target-group-mismatch", "groupName": args.group}
        print(json.dumps(payload, ensure_ascii=False))
        return 1
    if args.execute and args.authorization != AUTHORIZATION:
        payload = {"ok": False, "reason": "standing-authorization-missing", "groupName": args.group}
        print(json.dumps(payload, ensure_ascii=False))
        return 1
    payload = module.run(args)
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
