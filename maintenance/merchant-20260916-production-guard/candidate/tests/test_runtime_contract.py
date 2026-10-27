import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import runtime_contract as contract
import workflow_executor as workflow
import wechat_sender_executor as sender
import desktop_wechat_sender as desktop
import structured_merchant_collector as collector
import executor_integrity as integrity


def item_and_receipt():
    text = "城市\n联系人\n商家\n地址"
    digest = hashlib.sha256(text.encode()).hexdigest()
    item = {"merchantId": "12345678", "merchantName": "商家", "recommendTime": "2026-09-15 17:00:00",
            "tableOrder": 1, "text": text, "sha256": digest}
    receipt = {"ok": True, "verified": True, "state": "verified", "groupName": sender.TEST_GROUP,
               "sendAttempts": 1, "physicalSendAttempts": 1, "merchantId": item["merchantId"],
               "messageSha256": digest, "payloads": [{"text": text, "sha256": digest}],
               "postSendInputCleared": [True, True],
               "copyReadback": {"ok": True, "composerEmpty": True, "copyMenuCount": 1,
                                "bubblePositions": [[1, 2], [1, 2]], "copiedTextSha256": digest}}
    return item, receipt


class RuntimeContractTests(unittest.TestCase):
    def args(self, out):
        return workflow.build_parser().parse_args([
            "--group", sender.PRODUCTION_GROUP, "--standing-authorization", contract.PRODUCTION_AUTHORIZATION,
            "--output-dir", str(out)])

    def test_policy_rejects_wrong_production_authority_and_channel(self):
        args = self.args("unused")
        args.group = sender.PRODUCTION_GROUP
        args.standing_authorization = sender.TEST_AUTHORIZATION
        with self.assertRaisesRegex(RuntimeError, "authorization"):
            contract.validate_policy(args, sender)
        args.standing_authorization = contract.PRODUCTION_AUTHORIZATION
        self.assertTrue(contract.validate_policy(args, sender)["ok"])
        args.wechat_channel = "mobile"
        with self.assertRaisesRegex(RuntimeError, "channel"):
            contract.validate_policy(args, sender)

    def test_wait_budget_rejects_nan_infinite_negative_or_unbounded(self):
        for value in [float("nan"), float("inf"), -1, 901]:
            args = self.args("unused"); args.wechat_contention_wait_seconds = value
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, "budget"):
                contract.validate_policy(args, sender)

    def test_unknown_and_any_multiple_candidates_do_not_retry(self):
        for reason in ["desktop-group-title-not-unique:4", "exact-group-result-count:12",
                       "desktop-send-invalid-receipt", "some-new-error", "desktop-wechat-operation-timeout"]:
            operation = Mock(return_value={"ok": False, "reason": reason, "sendAttempts": 0})
            with tempfile.TemporaryDirectory() as directory, patch.object(desktop.time, "sleep") as sleep:
                result = desktop._wait_before_send(operation, phase="test", output_dir=Path(directory),
                                                   wait_seconds=900, poll_seconds=5)
            self.assertFalse(result["ok"]); self.assertEqual(operation.call_count, 1); sleep.assert_not_called()

    def test_recovered_contention_keeps_each_attempt_review(self):
        operation = Mock(side_effect=[{"ok": False, "reason": "desktop-chat-input-focus-failed", "sendAttempts": 0},
                                     {"ok": True, "sendAttempts": 0}])
        with tempfile.TemporaryDirectory() as directory, patch.object(desktop.time, "sleep"):
            result = desktop._wait_before_send(operation, phase="test", output_dir=Path(directory),
                                               wait_seconds=10, poll_seconds=1)
        self.assertEqual(len(result["attemptReviews"]), 2)
        self.assertFalse(result["attemptReviews"][0]["ok"])
        self.assertEqual(result["contentionEvents"][0]["reason"], "desktop-chat-input-focus-failed")

    def test_delivery_flags_without_copy_evidence_cannot_commit(self):
        item, receipt = item_and_receipt()
        self.assertTrue(contract.verify_delivery(receipt, sender.TEST_GROUP, item)["ok"])
        for key, value in [("copyReadback", {}), ("groupName", sender.PRODUCTION_GROUP),
                           ("sendAttempts", 2), ("postSendInputCleared", [True, False])]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                contract.verify_delivery(receipt | {key: value}, sender.TEST_GROUP, item)

    def test_reconcile_needs_two_fresh_frames_if_original_verification_failed(self):
        item, receipt = item_and_receipt()
        receipt["postSendInputCleared"] = []
        receipt["reconciledWithoutSend"] = True
        with self.assertRaises(RuntimeError):
            contract.verify_delivery(receipt, sender.TEST_GROUP, item)
        receipt["copyReadback"]["frameAnchors"] = [{"ok": True}, {"ok": True}]
        self.assertTrue(contract.verify_delivery(receipt, sender.TEST_GROUP, item)["ok"])

    def test_adapter_rejects_evidence_before_history_commit(self):
        item, receipt = item_and_receipt()
        collection = {"messages": [item], "businessDate": "2026-09-15"}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(sender, "STATE_DIR", Path(directory)), \
             patch.object(sender, "HISTORY_FILE", Path(directory)/"history.jsonl"), \
             patch.object(sender, "load_collection", return_value=collection), \
             patch.object(sender, "audit_collection"), \
             patch.object(desktop, "_wait_before_send", return_value=receipt), \
             patch.object(desktop, "_copy_verify_successful_send", return_value=receipt | {"copyReadback": {}}), \
             patch.object(sender, "append_history_then_cursor") as commit:
            result = desktop.run(Path("unused"), sender.TEST_GROUP, sender.TEST_AUTHORIZATION, Path(directory)/"out")
        commit.assert_not_called()
        self.assertFalse(result["ok"])
        self.assertIn("delivery-evidence", result["reason"])
        self.assertTrue(any(r["status"] == "FAIL" for r in result["items"][0]["review"]))
        self.assertEqual(result["items"][0]["review"][-1]["status"], "SKIPPED")

    def test_final_audit_rejects_duplicate_verified_history(self):
        item, receipt = item_and_receipt()
        with tempfile.TemporaryDirectory() as directory, patch.object(sender, "STATE_DIR", Path(directory)), \
             patch.object(sender, "HISTORY_FILE", Path(directory)/"history.jsonl"):
            current = item | {"groupName": sender.TEST_GROUP, "verified": True, "messageSha256": item["sha256"]}
            sender.cursor_file(sender.TEST_GROUP).write_text(json.dumps(current))
            sender.HISTORY_FILE.write_text(json.dumps(current)+"\n"+json.dumps(current)+"\n")
            with self.assertRaisesRegex(RuntimeError, "history-not-unique"):
                contract.audit_final(sender, sender.TEST_GROUP, {"messages": [item]}, "desktop")

    def test_noop_cannot_hide_cursor_change(self):
        item, _ = item_and_receipt()
        with tempfile.TemporaryDirectory() as directory, patch.object(sender, "STATE_DIR", Path(directory)):
            sender.cursor_file(sender.TEST_GROUP).write_text(json.dumps(item | {"groupName": sender.TEST_GROUP, "verified": True}))
            with self.assertRaisesRegex(RuntimeError, "noop-cursor-changed"):
                contract.audit_final(sender, sender.TEST_GROUP,
                                     {"messages": [], "cursor": item | {"merchantId": "different"}}, "desktop")

    def execute_fake(self, directory, receipts, selftest_error=None):
        good = {"ok": True, "messages": [], "cursor": {}, "stageMs": {"navigation": 3},
                "stageResults": {"navigation": "PASS"}}
        with patch.object(sender, "STATE_DIR", Path(directory)), \
             patch.object(integrity, "verify", return_value={"ok": True}), \
             patch.object(contract, "offline_selftest", side_effect=selftest_error, return_value={"ok": True}), \
             patch.object(desktop, "preflight", return_value={"ok": True}) as preflight, \
             patch.object(collector, "collect", side_effect=receipts) as collect, \
             patch.object(sender, "load_collection", return_value=good), \
             patch.object(sender, "audit_collection"), \
             patch.object(desktop, "run", return_value={"ok": True, "sent": 0}) as send, \
             patch.object(contract, "audit_final", return_value={"verified": True}):
            result = workflow.execute(self.args(Path(directory)/"run"))
            return result, collect.call_count, preflight.call_count, send.call_count

    def test_selftest_failure_has_no_ui_actions_and_has_review(self):
        with tempfile.TemporaryDirectory() as directory:
            result, collection, preflight, sends = self.execute_fake(directory, [], RuntimeError("selftest-failed"))
            review = json.loads((Path(directory)/"run/review.json").read_text())
        self.assertFalse(result["ok"]); self.assertEqual((collection, preflight, sends), (0, 0, 0))
        self.assertTrue(any(r["status"] == "FAIL" and "selftest-failed" in r["pitfalls"] for r in review["rows"]))
        self.assertTrue(any(r["status"] == "SKIPPED" and r["elapsedMs"] is None for r in review["rows"]))

    def test_known_navigation_retries_once_preserving_failure_review(self):
        failure = {"ok": False, "error": "agent-menu-count:0", "stageMs": {"navigation": 7},
                   "stageResults": {"navigation": "FAIL"}}
        success = {"ok": True, "messages": [], "cursor": {}, "stageMs": {"navigation": 2},
                   "stageResults": {"navigation": "PASS"}}
        with tempfile.TemporaryDirectory() as directory:
            result, count, _, sends = self.execute_fake(directory, [failure, success])
            review = json.loads((Path(directory)/"run/review.json").read_text())
        self.assertTrue(result["ok"]); self.assertEqual((count, sends), (2, 1))
        self.assertTrue(any(r["pitfalls"] == ["agent-menu-count:0"] for r in review["rows"]))

    def test_second_navigation_failure_never_sends_or_third_attempt(self):
        failure = {"ok": False, "error": "intention-list-not-open", "stageMs": {"navigation": 7},
                   "stageResults": {"navigation": "FAIL"}}
        with tempfile.TemporaryDirectory() as directory:
            result, count, _, sends = self.execute_fake(directory, [failure, failure])
        self.assertFalse(result["ok"]); self.assertEqual((count, sends), (2, 0))

    def test_login_and_ambiguous_navigation_fail_without_retry(self):
        for reason in ["service-login-required", "agent-menu-count:4", "unknown-page-state"]:
            failure = {"ok": False, "error": reason, "stageMs": {"navigation": 7}, "stageResults": {"navigation": "FAIL"}}
            with tempfile.TemporaryDirectory() as directory:
                result, count, _, sends = self.execute_fake(directory, [failure])
            self.assertFalse(result["ok"]); self.assertEqual((count, sends), (1, 0))

    def test_review_renderer_does_not_invent_elapsed_for_skipped_steps(self):
        review = contract.build_review({"runId": "test", "ok": False, "elapsedMs": 9,
                                        "stage": "runtime_policy", "stageMs": {"runtime_policy": 9},
                                        "stageResults": {"runtime_policy": "FAIL"}, "error": "bad|policy"})
        rendered = contract.render_review(review)
        self.assertIn("bad\\|policy", rendered)
        self.assertIn("— | 未执行", rendered)


if __name__ == "__main__":
    unittest.main()
