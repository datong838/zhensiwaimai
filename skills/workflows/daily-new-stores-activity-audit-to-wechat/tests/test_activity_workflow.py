import importlib.util
import json
import hashlib
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "activity_workflow.py"
SPEC = importlib.util.spec_from_file_location("activity_workflow", SCRIPT)
WORKFLOW = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WORKFLOW)


class ActivityWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.receipt = {
            "status": "complete", "checkedAt": datetime.now(timezone.utc).isoformat(),
            "account": "gmfmmZH", "shopId": "1364123817",
            "shopName": "EGO TACO ·伊戈塔可·香辣蟹(雨花店)",
            "pageUrl": "https://melody.shop.ele.me/app/shop/1364123817/activity__myActivity#app.shop.activity.myActivity",
            "store": {
                "pending": {"status": "待开始", "total": 0, "names": []},
                "active": {"status": "进行中", "total": 2, "names": ["减配送费", "店铺满减"]},
            },
            "flow": {"status": "进行中", "total": 1, "pageSize": 10,
                     "names": ["爆单红包阶梯爆涨红包-全国阶梯爆涨招商活动"]},
            "targetStatus": {"减配送费": "present", "新阶梯红包": "missing", "店铺满减": "present"},
        }

    def test_live_receipt_has_only_new_ladder_missing(self):
        self.assertEqual(WORKFLOW.validate_receipt(self.receipt), ["新阶梯红包"])
        self.assertEqual(WORKFLOW.message(self.receipt),
                         "淘宝  EGO TACO ·伊戈塔可·香辣蟹(雨花店)  待配置活动：新阶梯红包；请尽快配置。")

    def test_similar_platform_red_packet_is_not_exact_target(self):
        self.assertIn("爆单红包阶梯爆涨红包-全国阶梯爆涨招商活动", self.receipt["flow"]["names"])
        self.assertNotIn("新阶梯红包", self.receipt["flow"]["names"])

    def test_incomplete_flow_rejected(self):
        altered = json.loads(json.dumps(self.receipt))
        altered["flow"]["total"] += 1
        with self.assertRaisesRegex(ValueError, "flow-list-incomplete"):
            WORKFLOW.validate_receipt(altered)

    def test_empty_active_flow_requires_explicit_empty_evidence(self):
        altered = json.loads(json.dumps(self.receipt))
        altered["flow"] = {"status": "进行中", "total": 0, "pageSize": 0,
                           "names": [], "emptyEvidence": "暂无数据"}
        self.assertEqual(WORKFLOW.validate_receipt(altered), ["新阶梯红包"])
        del altered["flow"]["emptyEvidence"]
        with self.assertRaisesRegex(ValueError, "flow-list-incomplete"):
            WORKFLOW.validate_receipt(altered)

    def test_wrong_target_conclusion_rejected(self):
        altered = json.loads(json.dumps(self.receipt))
        altered["targetStatus"]["新阶梯红包"] = "present"
        with self.assertRaisesRegex(ValueError, "target-conclusion-mismatch"):
            WORKFLOW.validate_receipt(altered)

    def test_existing_verified_event_does_not_reach_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            event_dir = Path(directory)
            day = datetime.now(WORKFLOW.LOCAL_TZ).date().isoformat()
            marker = event_dir / f"{day}-taobao-1364123817-activity-reminder.json"
            body = WORKFLOW.message(self.receipt)
            marker.write_text(json.dumps({"state": "verified", "sha256": hashlib.sha256(body.encode()).hexdigest()}))
            with patch.object(WORKFLOW, "EVENTS", event_dir):
                result = WORKFLOW.deliver(self.receipt, event_dir)
            self.assertEqual(result["status"], "already_verified")
            self.assertEqual(result["sendAttempts"], 0)

    def test_existing_event_text_conflict_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            event_dir = Path(directory)
            day = datetime.now(WORKFLOW.LOCAL_TZ).date().isoformat()
            marker = event_dir / f"{day}-taobao-1364123817-activity-reminder.json"
            marker.write_text(json.dumps({"state": "verified", "sha256": "different"}))
            with patch.object(WORKFLOW, "EVENTS", event_dir):
                result = WORKFLOW.deliver(self.receipt, event_dir)
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "same-event-payload-conflict")

    def test_prior_attempt_unknown_never_reaches_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            event_dir = Path(directory)
            day = datetime.now(WORKFLOW.LOCAL_TZ).date().isoformat()
            marker = event_dir / f"{day}-taobao-1364123817-activity-reminder.json"
            body = WORKFLOW.message(self.receipt)
            marker.write_text(json.dumps({"state": "attempted", "sha256": hashlib.sha256(body.encode()).hexdigest()}))
            with patch.object(WORKFLOW, "EVENTS", event_dir):
                result = WORKFLOW.deliver(self.receipt, event_dir)
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["sendAttempts"], 0)
            self.assertEqual(result["reason"], "prior-attempt-requires-read-only-reconciliation")

    def test_missing_canonical_ledger_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent"
            with patch.object(WORKFLOW, "EVENTS", missing):
                result = WORKFLOW.deliver(self.receipt, Path(directory))
            self.assertEqual(result["reason"], "canonical-activity-ledger-unavailable")

    def test_current_new_store_uses_its_own_id_and_exact_name(self):
        current = json.loads(json.dumps(self.receipt))
        name = "渔味妙酸菜鱼·肥肠鱼·烤鱼(浦东大道店)"
        current["shopId"] = "546835175"
        current["shopName"] = name
        current["pageUrl"] = current["pageUrl"].replace("1364123817", "546835175")
        self.assertEqual(WORKFLOW.validate_receipt(current, name), ["新阶梯红包"])
        self.assertIn(name, WORKFLOW.message(current, name))
        with self.assertRaisesRegex(ValueError, "shop-name-invalid"):
            WORKFLOW.validate_receipt(current, "渔味妙酸菜鱼·烤鱼(其他店)")

    def test_current_shop_prior_attempt_is_never_resent(self):
        current = json.loads(json.dumps(self.receipt))
        name = "渔味妙酸菜鱼·肥肠鱼·烤鱼(浦东大道店)"
        current["shopId"] = "546835175"
        current["shopName"] = name
        current["pageUrl"] = current["pageUrl"].replace("1364123817", "546835175")
        with tempfile.TemporaryDirectory() as directory:
            event_dir = Path(directory)
            day = datetime.now(WORKFLOW.LOCAL_TZ).date().isoformat()
            marker = event_dir / f"{day}-taobao-546835175-activity-reminder.json"
            body = WORKFLOW.message(current, name)
            marker.write_text(json.dumps({"state": "attempted", "sha256": hashlib.sha256(body.encode()).hexdigest()}))
            with patch.object(WORKFLOW, "EVENTS", event_dir):
                result = WORKFLOW.deliver(current, event_dir, name)
            self.assertEqual(result["status"], "unknown")
            self.assertEqual(result["sendAttempts"], 0)


if __name__ == "__main__":
    unittest.main()
