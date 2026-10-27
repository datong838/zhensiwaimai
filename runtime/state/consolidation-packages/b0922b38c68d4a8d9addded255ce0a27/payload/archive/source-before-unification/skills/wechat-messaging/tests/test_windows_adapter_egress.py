#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出站通道层闸门的接线测试（离线，绝不触达驱动）。

覆盖两件事：
1. **进程级守卫**：测试进程内不允许构造真实 `WindowsAdapter`（大同铁律：
   测试脚本不允许驱动线上业务逻辑）。
2. **载荷闸门接线**：`send_one` 命中闸门时必须在**调用驱动之前**返回 blocked，
   写 `egress-denied.json` 留痕，且**完全不触碰 client**。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import egress_policy as egress  # noqa: E402
import windows_adapter as w  # noqa: E402

PRODUCTION_GROUP = "李老哈（品牌）💰臻肆外卖运营对接群"


def _request(group=PRODUCTION_GROUP):
    return {"schemaVersion": 1, "operation": "send", "groupName": group,
            "items": [], "context": {"workflowId": "test", "eventId": "e",
                                     "accountAlias": "main-wechat", "channel": "desktop",
                                     "deadlineAt": 0}}


class TestProcessGuard(unittest.TestCase):
    def test_unittest_process_is_detected(self):
        self.assertTrue(w._test_process_active())

    def test_explicit_override_disables_detection(self):
        with patch.dict("os.environ", {w.TEST_MODE_ENV: "0"}):
            self.assertFalse(w._test_process_active())

    def test_explicit_override_enables_detection(self):
        with patch.dict("os.environ", {w.TEST_MODE_ENV: "1"}):
            self.assertTrue(w._test_process_active())

    def test_adapter_construction_is_refused_in_test_process(self):
        with self.assertRaises(Exception) as caught:
            w.WindowsAdapter()
        self.assertIn("windows-adapter-forbidden-in-test-process", str(caught.exception))


class _ExplodingClientAdapter(w.WindowsAdapter):
    """任何对 client 的访问都当场失败 —— 用于证明拒发路径不触达驱动。"""

    @property
    def client(self):
        raise AssertionError("egress-denied must not touch the driver client")


class EgressGateWiring(unittest.TestCase):
    def _adapter(self, resolved):
        adapter = object.__new__(_ExplodingClientAdapter)
        adapter._resolved = resolved
        adapter._client = None
        adapter._last_transport = None
        return adapter

    def test_incident_payload_is_blocked_before_touching_driver(self):
        adapter = self._adapter(PRODUCTION_GROUP)
        item = {"itemId": "appeal-" + "a" * 20, "type": "image",
                "name": "a" * 64 + ".png", "path": "/nonexistent/a.png"}
        with tempfile.TemporaryDirectory() as workspace:
            work = Path(workspace)
            receipt = adapter.send_one(_request(), item, work, {}, deadline=10 ** 12)
            self.assertEqual(receipt["status"], "blocked")
            self.assertEqual(receipt["sendAttempts"], 0)
            self.assertTrue(receipt["reason"].startswith("egress-denied:"))
            denied = json.loads((work / "egress-denied.json").read_text(encoding="utf-8"))
            self.assertEqual(denied["reason"], "egress-degenerate-payload")
            self.assertEqual(denied["resolvedGroup"], PRODUCTION_GROUP)

    def test_production_payload_is_not_intercepted_by_the_gate(self):
        # 未授权出站仍要由原有逻辑判定（此处用不存在的文件路径触发 payload-file-missing
        # 之外的路径：闸门放行后才会走到驱动搜索键计算，故断言"未被闸门拦下"）。
        adapter = self._adapter(PRODUCTION_GROUP)
        item = {"itemId": "top10-2026-09-29", "type": "image",
                "name": "2026-09-29_top10seller.png", "path": "/nonexistent/ok.png"}
        verdict = egress.check(group=PRODUCTION_GROUP, resolved_group=PRODUCTION_GROUP,
                               items=(item,))
        self.assertTrue(verdict["allow"])

    def test_gate_uses_request_group_when_resolver_returns_none(self):
        # 服务器搜索兜底时 resolve_group 返回 (None, 'server-search')，此时
        # _require_resolved 回落到请求群名，闸门**仍必须拒**。
        adapter = self._adapter(None)
        adapter.resolve_group = lambda group, search_group=None: (None, "server-search")
        item = {"itemId": "appeal-" + "b" * 20, "type": "image",
                "name": "b" * 64 + ".png"}
        with tempfile.TemporaryDirectory() as workspace:
            receipt = adapter.send_one(_request(), item, Path(workspace), {}, deadline=10 ** 12)
            self.assertEqual(receipt["status"], "blocked")
            self.assertIn("egress-degenerate-payload", receipt["reason"])


if __name__ == "__main__":
    unittest.main()
