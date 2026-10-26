#!/usr/bin/env python3

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from business_desktop_wechat_file_sender import TARGET_GROUP  # noqa: E402
import business_desktop_wechat_file_sender as sender  # noqa: E402

# 《测试隔离契约》：测试必须能在全离线下通过、不得驱动真实 Windows 驱动通道，
# 因此 WeComAdapter 一律打桩到真实接缝（preflight 在内部
# `from wecom_adapter import WeComAdapter as WindowsAdapter`）。
_WM_SCRIPTS = Path(__file__).resolve().parents[3] / "wechat-messaging" / "scripts"
if str(_WM_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_WM_SCRIPTS))
import wecom_adapter  # noqa: E402  (仅用于打桩，绝不构造其真实实例)


class DesktopPreflightTests(unittest.TestCase):
    def test_receipt_items_convert_paths_to_json_strings(self):
        items = sender.json_items([{"file": Path("/tmp/report.xlsx"), "name": "report.xlsx"}])
        self.assertEqual(items[0]["file"], "/tmp/report.xlsx")
        json.dumps(items)

    def test_confirmed_delivery_name_handles_regenerated_xlsx_hash(self):
        ledger = {"files": {"old-hash": {"name": "美团外卖日报_2026-09-09.xlsx", "state": "confirmed",
                                            "fullNameVerified": True, "groupTitleVerified": True}}}
        item = {"name": "美团外卖日报_2026-09-09.xlsx", "sha256": "new-hash"}
        self.assertTrue(sender.item_confirmed(ledger, item))

    def test_delivery_name_requires_unique_strong_confirmation(self):
        confirmed = {"name": "日报.xlsx", "state": "confirmed", "fullNameVerified": True, "groupTitleVerified": True}
        self.assertFalse(sender.item_confirmed({"files": {"a": confirmed, "b": confirmed}}, {"name": "日报.xlsx", "sha256": "new"}))
        weak = {"name": "日报.xlsx", "state": "confirmed", "fullNameVerified": False, "groupTitleVerified": True}
        self.assertFalse(sender.item_confirmed({"files": {"a": weak}}, {"name": "日报.xlsx", "sha256": "new"}))

    def test_uses_exact_shared_group_locator(self):
        class _FakeAdapter:
            def preflight(self, request, output):
                return {"ok": True, "action": "open-group",
                        "group": TARGET_GROUP,
                        "header": TARGET_GROUP + "（18）", "note": None}
        with patch.object(wecom_adapter, "WeComAdapter", return_value=_FakeAdapter()):
            receipt = sender.preflight(TARGET_GROUP)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["group"], TARGET_GROUP)

    def test_rejects_failed_group_preflight(self):
        class _FakeAdapter:
            def preflight(self, request, output):
                return {"ok": False, "reason": "blocked-login"}
        with patch.object(wecom_adapter, "WeComAdapter", return_value=_FakeAdapter()):
            with self.assertRaisesRegex(RuntimeError, "windows-wechat-blocked-login"):
                sender.preflight(TARGET_GROUP)


if __name__ == "__main__":
    unittest.main()
