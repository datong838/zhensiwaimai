#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出站闸门离线测试（无任何网络/真机调用）。

第一条用例就是**2026-09-30 事故的原样复现**：那两个真实落群的夹具文件名必须被拒。
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import egress_policy as egress  # noqa: E402

PRODUCTION_GROUP = "李老哈（品牌）💰臻肆外卖运营对接群"

# 事故物证：驱动 inbox 里那两个文件（大小 3570 / 4140，与本机渲染夹具字节一致）
INCIDENT = [
    {"itemId": "appeal-" + "a" * 20, "type": "image", "name": "a" * 64 + ".png"},
    {"itemId": "appeal-" + "b" * 20, "type": "image", "name": "b" * 64 + ".png"},
]


class IncidentRegression(unittest.TestCase):
    """回归：本次事故必须被闸门拦下（否则闸门等于没做）。"""

    def test_incident_fixture_payload_is_denied(self):
        verdict = egress.check(group=PRODUCTION_GROUP, resolved_group=PRODUCTION_GROUP,
                               items=INCIDENT)
        self.assertFalse(verdict["allow"])
        self.assertEqual(verdict["reason"], "egress-degenerate-payload")
        self.assertEqual(verdict["payload"], "degenerate")

    def test_incident_is_denied_even_when_resolved_group_is_unknown(self):
        # 服务器搜索兜底时 resolved 可能为 None，用请求群名兜底——仍必须拒。
        verdict = egress.check(group=PRODUCTION_GROUP, resolved_group=None, items=INCIDENT)
        self.assertFalse(verdict["allow"])

    def test_incident_degenerate_item_id_alone_is_enough(self):
        items = [{"itemId": "appeal-" + "a" * 20, "type": "image",
                  "name": "9a4576c4f2a1b6cc0e45.png"}]
        self.assertFalse(egress.check(group="g", resolved_group="g", items=items)["allow"])


class DegenerateThreshold(unittest.TestCase):
    def test_nineteen_repeats_is_not_degenerate(self):
        items = [{"itemId": "x", "type": "image", "name": "c" * 19 + ".png"}]
        self.assertTrue(egress.check(group="g", resolved_group="g", items=items)["allow"])

    def test_twenty_repeats_is_degenerate(self):
        items = [{"itemId": "x", "type": "image", "name": "c" * 20 + ".png"}]
        self.assertFalse(egress.check(group="g", resolved_group="g", items=items)["allow"])

    def test_mixed_characters_is_not_degenerate(self):
        items = [{"itemId": "x", "type": "image", "name": "ab" * 30 + ".png"}]
        self.assertTrue(egress.check(group="g", resolved_group="g", items=items)["allow"])


class SentinelPayloads(unittest.TestCase):
    def test_text_sentinel_is_denied_in_production_group(self):
        items = [{"itemId": "appeal-x", "type": "text", "text": "正文甲"}]
        verdict = egress.check(group=PRODUCTION_GROUP, resolved_group=PRODUCTION_GROUP,
                               items=items)
        self.assertFalse(verdict["allow"])
        self.assertEqual(verdict["reason"], "egress-sentinel-payload")

    def test_reserved_name_is_denied(self):
        items = [{"itemId": "x", "type": "image", "name": "__TEST__通知.png"}]
        self.assertFalse(egress.check(group="g", resolved_group="g", items=items)["allow"])

    def test_test_img_marker_is_denied(self):
        items = [{"itemId": "x", "type": "image", "name": "TEST-IMG-A.png"}]
        self.assertFalse(egress.check(group="g", resolved_group="g", items=items)["allow"])

    def test_sentinel_match_is_case_insensitive(self):
        items = [{"itemId": "x", "type": "text", "text": "hello WORLD"}]
        self.assertFalse(egress.check(group="g", resolved_group="g", items=items)["allow"])


class ProductionPayloadsUnaffected(unittest.TestCase):
    """生产载荷必须逐字不变地放行——闸门不得有误伤。"""

    def _allow(self, items):
        return egress.check(group=PRODUCTION_GROUP, resolved_group=PRODUCTION_GROUP,
                            items=items)["allow"]

    def test_real_appeal_notice_image_is_allowed(self):
        self.assertTrue(self._allow([{
            "itemId": "appeal-9a4576c4f2a1b6cc0e45", "type": "image",
            "name": "9a4576c4f2a1b6cc0e45e0f0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c.png"}]))

    def test_real_top10_png_is_allowed(self):
        self.assertTrue(self._allow([{"itemId": "top10-2026-09-29", "type": "image",
                                      "name": "2026-09-29_top10seller.png"}]))

    def test_real_jinsha_report_file_is_allowed(self):
        self.assertTrue(self._allow([{"itemId": "jinsha-2026-09-29", "type": "file",
                                      "name": "2026-09-29美团外卖日报.xlsx"}]))

    def test_real_multiline_notice_text_is_allowed(self):
        self.assertTrue(self._allow([{
            "itemId": "appeal-x", "type": "text",
            "text": "--- 通知 ---\n李老哈·东北农家小院(海上海店)\n【美团】\n"
                    "评价时间: 2026-09-29\n评价等级: 2星\n"
                    "申诉结果：---申诉中---\n评价内容: 最难吃的炖白菜"}]))

    def test_long_dash_separator_in_real_notice_is_not_flagged(self):
        # 防误伤：正文里的长破折号分隔线不是"退化载荷"（连排检测只作用于标识符）。
        self.assertTrue(self._allow([{
            "itemId": "appeal-abc", "type": "text",
            "text": "--- 通知 ---\n--------------------\n申诉结果：---申诉中---"}]))

    def test_empty_items_are_allowed(self):
        self.assertTrue(self._allow([]))


class TestGroupGate(unittest.TestCase):
    def test_default_test_group_set_is_empty(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(egress.TEST_GROUP_ENV, None)
            self.assertEqual(egress.test_groups(), frozenset())

    def test_test_groups_parses_comma_separated_env(self):
        with patch.dict(os.environ, {egress.TEST_GROUP_ENV: "臻肆测试群, 二号测试群 ,"}):
            self.assertEqual(egress.test_groups(), frozenset({"臻肆测试群", "二号测试群"}))

    def test_degenerate_payload_is_allowed_inside_a_test_group(self):
        verdict = egress.check(group="臻肆测试群", resolved_group="臻肆测试群",
                               items=INCIDENT, test_groups=frozenset({"臻肆测试群"}))
        self.assertTrue(verdict["allow"])

    def test_degenerate_payload_is_denied_when_test_group_is_another_group(self):
        verdict = egress.check(group=PRODUCTION_GROUP, resolved_group=PRODUCTION_GROUP,
                               items=INCIDENT, test_groups=frozenset({"臻肆测试群"}))
        self.assertFalse(verdict["allow"])
        self.assertEqual(verdict["reason"], "egress-degenerate-payload")

    def test_production_payload_into_production_group_allowed_with_test_groups_set(self):
        verdict = egress.check(group=PRODUCTION_GROUP, resolved_group=PRODUCTION_GROUP,
                               items=[{"itemId": "top10-1", "type": "image",
                                       "name": "2026-09-29_top10seller.png"}],
                               test_groups=frozenset({"臻肆测试群"}))
        self.assertTrue(verdict["allow"])


class BusinessSnapshotRule(unittest.TestCase):
    def test_rule_inactive_when_no_snapshot_supplied(self):
        items = [{"itemId": "appeal-not-registered", "type": "image", "name": "abc.png"}]
        self.assertTrue(egress.check(group="g", resolved_group="g", items=items)["allow"])

    def test_registered_key_is_allowed(self):
        items = [{"itemId": "appeal-9a4576c4f2a1", "type": "image", "name": "abc.png"}]
        verdict = egress.check(group="g", resolved_group="g", items=items,
                               business_keys={"appeal-9a4576c4f2a1"})
        self.assertTrue(verdict["allow"])

    def test_unregistered_key_is_denied(self):
        items = [{"itemId": "appeal-6bb67a74b7426ed8804d", "type": "image",
                  "name": "abc.png"}]
        verdict = egress.check(group="g", resolved_group="g", items=items,
                               business_keys={"appeal-9a4576c4f2a1"})
        self.assertFalse(verdict["allow"])
        self.assertEqual(verdict["reason"], "egress-payload-not-in-business-snapshot")


class SelfTest(unittest.TestCase):
    def test_module_self_test_passes(self):
        self.assertTrue(egress.self_test()["ok"])

    def test_denied_verdict_is_never_silently_empty(self):
        verdict = egress.check(group=PRODUCTION_GROUP, resolved_group=PRODUCTION_GROUP,
                               items=INCIDENT)
        self.assertFalse(verdict["allow"])
        self.assertTrue(verdict["reason"])
        self.assertTrue(verdict["detail"])


if __name__ == "__main__":
    unittest.main()
