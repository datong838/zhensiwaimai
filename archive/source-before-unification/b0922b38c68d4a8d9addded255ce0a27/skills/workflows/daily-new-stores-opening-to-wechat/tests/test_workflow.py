import importlib.util
import hashlib
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "workflow.py"
SPEC = importlib.util.spec_from_file_location("daily_new_stores_workflow", SCRIPT)
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


def receipt():
    hit = {"channel": "淘宝", "name": "伊戈塔可(雨花店)", "days": "3天", "page": 2, "row": 1}
    data = {
        "status": "complete", "checkedAt": "2026-09-28T02:00:00Z", "hits": [hit],
        "meituan": {"channel": "美团", "total": 1, "size": 10, "pages": 1,
                    "visited": [{"page": 1, "count": 1}], "hits": []},
        "taobao": {"channel": "淘宝", "total": 51, "size": 50, "pages": 2,
                   "visited": [{"page": 1, "count": 50}, {"page": 2, "count": 1}], "hits": [hit]},
    }
    data["taobaoPasses"] = [{"total": 51, "hits": [hit]}, {"total": 51, "hits": [hit]}]
    return data


class WorkflowTests(unittest.TestCase):
    def test_complete_receipt_and_message_format(self):
        data = receipt()
        self.assertEqual(workflow.validate_collection(data), data["hits"])
        self.assertEqual(workflow.message_lines(data["hits"]), ["淘宝  伊戈塔可(雨花店)  新店铺（开业3天）"])
        self.assertIn("第2页", workflow.render_report("2026-09-28", data, {"status": "待发送"}))

    def test_incomplete_page_and_wrong_page_size_rejected(self):
        data = receipt()
        data["taobao"]["visited"][1]["count"] = 0
        with self.assertRaisesRegex(ValueError, "row-count-incomplete"):
            workflow.validate_collection(data)
        data = receipt()
        data["taobao"]["size"] = 30
        with self.assertRaisesRegex(ValueError, "taobao-not-50-per-page"):
            workflow.validate_collection(data)

    def test_four_day_hit_rejected_and_no_hit_report(self):
        data = receipt()
        data["hits"][0]["days"] = "4天"
        with self.assertRaisesRegex(ValueError, "hit-invalid"):
            workflow.validate_collection(data)
        data = receipt()
        data["hits"] = []
        data["taobao"]["hits"] = []
        for item in data["taobaoPasses"]:
            item["hits"] = []
        report = workflow.render_report("2026-09-28", data, {"status": "无命中，不发送"})
        self.assertIn("无命中，不发送", report)
        self.assertIn("完整核验后无 0–3 天店铺", report)

    def test_taobao_recheck_must_agree(self):
        data = receipt()
        data["taobaoPasses"][0]["total"] = 52
        with self.assertRaisesRegex(ValueError, "taobao-recheck-unstable"):
            workflow.validate_collection(data)

    def test_missing_days_are_reported_as_unresolved_not_as_no_hit(self):
        data = receipt()
        missing = {"channel": "淘宝", "name": "暂停营业门店", "days": "", "page": 1, "row": 2}
        data["taobao"]["unresolved"] = [missing]
        data["taobaoPasses"] = [
            {"total": 51, "hits": data["hits"], "unresolved": [missing]},
            {"total": 51, "hits": data["hits"], "unresolved": [missing]},
        ]
        data["unresolved"] = [missing]
        self.assertEqual(workflow.validate_collection(data), data["hits"])
        report = workflow.render_report("2026-09-30", data, {"status": "字段缺失，暂缓发送"})
        self.assertIn("暂停营业门店", report)
        self.assertIn("字段缺失，暂缓发送", report)

    def test_verified_reconcile_keeps_original_physical_attempt(self):
        result = {"items": [{"status": "verified", "sendAttempts": 0,
                             "reconciled": True, "transport": {"sendAttempts": 1}}]}
        self.assertEqual(workflow.verified_send_counts(result),
                         {"sendAttempts": 1, "reconcileSendAttempts": 0})

    def test_same_day_verified_record_never_reaches_gateway(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            ledger = root / ".runtime" / "new-stores-send-ledger"
            ledger.mkdir(parents=True)
            body = workflow.message_body(receipt()["hits"])
            digest = hashlib.sha256(body.encode()).hexdigest()
            (ledger / f"2026-09-30-{digest[:16]}.json").write_text(json.dumps({
                "state": "verified", "verified": True, "groupName": workflow.GROUP,
                "payloads": [{"text": body, "sha256": digest}], "sendAttempts": 1,
            }))
            with patch.object(workflow, "SKILL", root):
                result = workflow.run_send(receipt()["hits"], "2026-09-30", root)
            self.assertEqual(result["status"], "既有发送已验证")
            self.assertEqual(result["sendAttempts"], 0)
            self.assertEqual(result["priorSendAttempts"], 1)

    def test_same_day_changed_text_and_attempted_record_block(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            ledger = root / ".runtime" / "new-stores-send-ledger"
            ledger.mkdir(parents=True)
            body = workflow.message_body(receipt()["hits"])
            digest = hashlib.sha256(body.encode()).hexdigest()
            marker = ledger / f"2026-09-30-{digest[:16]}.json"
            marker.write_text(json.dumps({"state": "attempted", "verified": False,
                                          "groupName": workflow.GROUP,
                                          "payloads": [{"text": body, "sha256": digest}]}))
            with patch.object(workflow, "SKILL", root):
                attempted = workflow.run_send(receipt()["hits"], "2026-09-30", root)
                changed = receipt()["hits"]
                changed[0]["name"] = "另一家店"
                conflict = workflow.run_send(changed, "2026-09-30", root)
            self.assertEqual(attempted["status"], "unknown")
            self.assertEqual(attempted["sendAttempts"], 0)
            self.assertEqual(conflict["status"], "blocked")
            self.assertEqual(conflict["reason"], "same-day-payload-conflict-or-multiple-events")


if __name__ == "__main__":
    unittest.main()
