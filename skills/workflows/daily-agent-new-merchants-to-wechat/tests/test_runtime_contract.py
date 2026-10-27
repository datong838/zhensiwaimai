import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, Mock
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import runtime_contract as contract
import workflow_executor as workflow
import wechat_sender_executor as sender
import desktop_wechat_sender as desktop
import structured_merchant_collector as collector
import executor_integrity as integrity


def current_collection(value):
    """Keep orchestration stubs within the real collection date/group contract."""
    return value | {'groupName': sender.PRODUCTION_GROUP,
                    'businessDate': datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')}


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

    def test_blocked_zero_send_draft_marker_requires_full_item_binding(self):
        text = "城市\n联系人\n商家\n地址"
        digest = hashlib.sha256(text.encode()).hexdigest()
        item = {"type": "text", "text": text, "sha256": digest}
        transport = {"groupName": sender.PRODUCTION_GROUP, "payloadType": "text",
                     "stage": "prepare_payload", "sendAttempts": 0,
                     "reason": "desktop-text-input-write-failed",
                     "payloads": [{"text": text, "sha256": digest}]}
        nested = {"status": "blocked", "type": "text", "sendAttempts": 0,
                  "sha256": digest, "reason": "desktop-text-input-write-failed",
                  "transport": transport}
        marker_data = {"bridgeVersion": 1, "state": "blocked", "stage": "prepare_payload",
                       "reason": "desktop-text-input-write-failed", "sendAttempts": 0,
                       "physicalSendAttempts": 0, "groupName": sender.PRODUCTION_GROUP,
                       "payloadType": "text", "payloads": [{"text": text, "sha256": digest}],
                       "commonReceipt": {"status": "blocked", "groupName": sender.PRODUCTION_GROUP,
                                         "reason": "desktop-text-input-write-failed", "items": [nested]}}
        with tempfile.TemporaryDirectory() as directory, patch.object(sender, "STATE_DIR", Path(directory)):
            root = Path(directory) / "send-attempts"; root.mkdir()
            marker = root / "receipt.json"; marker.write_text(json.dumps(marker_data))
            self.assertTrue(desktop.blocked_zero_send_text_marker_matches(sender.PRODUCTION_GROUP, item, marker))
            for mutate in (
                lambda data: data.update(physicalSendAttempts=None),
                lambda data: data["commonReceipt"]["items"][0]["transport"]["payloads"][0].update(text="other"),
            ):
                changed = json.loads(json.dumps(marker_data)); mutate(changed); marker.write_text(json.dumps(changed))
                self.assertFalse(desktop.blocked_zero_send_text_marker_matches(sender.PRODUCTION_GROUP, item, marker))
            marker.write_text(json.dumps(marker_data))
            outside = Path(directory) / "receipt.json"; outside.write_text(marker.read_text())
            self.assertFalse(desktop.blocked_zero_send_text_marker_matches(sender.PRODUCTION_GROUP, item, outside))
            symlink = root / "linked-receipt.json"; symlink.symlink_to(marker)
            self.assertFalse(desktop.blocked_zero_send_text_marker_matches(sender.PRODUCTION_GROUP, item, symlink))
            preflight_only = json.loads(json.dumps(marker_data))
            preflight_only.pop("physicalSendAttempts", None)
            preflight_only.pop("stage", None)
            preflight_only["reason"] = "resume-prepared-text-readback-mismatch"
            preflight_only["commonReceipt"].update(
                reason=preflight_only["reason"], items=[], requestDigest="a" * 64,
                review=[{"stage": "authorization", "status": "completed"},
                        {"stage": "freeze:0", "status": "completed"},
                        {"stage": "preflight", "status": "completed"}],
                reviewSummary={"result": "blocked", "failedStages": []})
            marker.write_text(json.dumps(preflight_only))
            self.assertTrue(desktop.blocked_zero_send_text_marker_matches(
                sender.PRODUCTION_GROUP, item, marker))
            preflight_only["commonReceipt"]["items"] = [{"sendAttempts": None}]
            marker.write_text(json.dumps(preflight_only))
            self.assertFalse(desktop.blocked_zero_send_text_marker_matches(
                sender.PRODUCTION_GROUP, item, marker))

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

    def test_unknown_null_attempt_is_accepted_only_as_exact_read_only_reconcile(self):
        item, receipt = item_and_receipt()
        receipt.update({"sendAttempts": None, "physicalSendAttempts": None,
                        "reconciledWithoutSend": True, "postSendInputCleared": []})
        receipt["copyReadback"]["frameAnchors"] = [{"ok": True}, {"ok": True}]
        self.assertIsNone(contract.verify_delivery(receipt, sender.TEST_GROUP, item)["physicalSendAttempts"])
        for key, value in [("reconciledWithoutSend", False), ("groupName", sender.PRODUCTION_GROUP),
                           ("physicalSendAttempts", 1)]:
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                contract.verify_delivery(receipt | {key: value}, sender.TEST_GROUP, item)

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
        good = current_collection({"ok": True, "messages": [], "cursor": {}, "stageMs": {"navigation": 3},
                "stageResults": {"navigation": "PASS"}})
        receipts = [current_collection(row) if row.get('ok') else row for row in receipts]
        with patch.object(sender, "STATE_DIR", Path(directory)), \
             patch.object(integrity, "verify_for_run", return_value={"ok": True, "status": "SEALED"}), \
             patch.object(contract, "offline_selftest", side_effect=selftest_error, return_value={"ok": True}), \
             patch.object(desktop, "preflight", return_value={"ok": True}) as preflight, \
             patch.object(collector, "collect", side_effect=receipts) as collect, \
             patch.object(sender, "load_collection", return_value=good), \
             patch.object(sender, "audit_collection"), \
             patch.object(desktop, "run", return_value={"ok": True, "sent": 0}) as send, \
             patch.object(workflow, "send_empty_notice", return_value={"verified": True, "sendAttempts": 1}) as empty_notice, \
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

    def test_empty_notice_does_not_use_merchant_preflight(self):
        good = {"ok": True, "messages": [], "cursor": {}, "stageMs": {"navigation": 3},
                "stageResults": {"navigation": "PASS"}}
        with tempfile.TemporaryDirectory() as directory:
            result, collection, preflight, sends = self.execute_fake(directory, [good])
            review = json.loads((Path(directory)/"run/review.json").read_text())
        self.assertTrue(result["ok"])
        self.assertEqual((collection, preflight, sends), (1, 0, 1))
        self.assertTrue(result["emptyNotice"]["verified"])
        row = next(r for r in review["rows"] if r["stage"] == "desktop_wechat_preflight")
        self.assertEqual(row["status"], "NOOP")
        self.assertIn("代码跳过微信预检", row["pitfalls"][0])

    def test_pending_merchants_preflight_once_before_delivery(self):
        item, _ = item_and_receipt()
        receipt = current_collection({"ok": True, "messages": [item], "cursor": {}, "stageMs": {"navigation": 3},
                   "stageResults": {"navigation": "PASS"}})
        order = []
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(sender, "STATE_DIR", Path(directory)), \
             patch.object(integrity, "verify_for_run", return_value={"ok": True, "status": "SEALED"}), \
             patch.object(contract, "offline_selftest", return_value={"ok": True}), \
             patch.object(desktop, "preflight", side_effect=lambda *a, **kw: order.append("preflight") or {"ok": True}), \
             patch.object(collector, "collect", return_value=receipt), \
             patch.object(sender, "load_collection", return_value=receipt), \
             patch.object(sender, "audit_collection"), \
             patch.object(desktop, "run", side_effect=lambda *a, **kw: order.append("delivery") or {"ok": True, "items": []}), \
             patch.object(contract, "audit_final", return_value={"verified": True}):
            result = workflow.execute(self.args(Path(directory)/"run"))
        self.assertTrue(result["ok"])
        self.assertEqual(order, ["preflight", "delivery"])

    def test_real_new_send_in_unsealed_run_invokes_code_owned_reseal(self):
        item, _ = item_and_receipt()
        receipt = current_collection({"ok": True, "messages": [item], "cursor": {}, "stageMs": {"navigation": 3},
                   "stageResults": {"navigation": "PASS"}})
        delivery = {"ok": True, "items": [{"merchantId": item["merchantId"],
            "merchantName": item["merchantName"], "review": [
                {"stage": "定位、输入与单次发送", "status": "PASS", "elapsedMs": 1},
                {"stage": "成功历史与原子游标提交", "status": "PASS", "elapsedMs": 1}]}]}
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(sender, "STATE_DIR", Path(directory)), \
             patch.object(integrity, "verify_for_run", return_value={"ok": True, "status": "UNSEALED_ACCEPTANCE"}), \
             patch.object(integrity, "seal_from_nonempty_acceptance", return_value={"ok": True, "resealed": True}) as seal, \
             patch.object(contract, "offline_selftest", return_value={"ok": True}), \
             patch.object(desktop, "preflight", return_value={"ok": True}), \
             patch.object(collector, "collect", return_value=receipt), \
             patch.object(sender, "load_collection", return_value=receipt), \
             patch.object(sender, "audit_collection"), \
             patch.object(desktop, "run", return_value=delivery), \
             patch.object(contract, "audit_final", return_value={"verified": True, "merchantId": item["merchantId"]}):
            result = workflow.execute(self.args(Path(directory)/"run"))
        self.assertTrue(result["ok"])
        self.assertTrue(result["executorSeal"]["resealed"])
        seal.assert_called_once()

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

    def test_completion_state_requires_recovery_or_read_only_reconcile(self):
        recoverable = contract.completion_state({"ok": False, "error": "exact-group-result-count:0", "wechat": {}})
        self.assertEqual(recoverable["state"], "RECOVERABLE_NO_SEND")
        self.assertTrue(recoverable["automaticRecoveryAllowed"])
        self.assertEqual(recoverable["recoveryAttemptBudget"], 1)
        reconcile = contract.completion_state({"ok": False, "error": "post-send-check-failed", "wechat": {
            "items": [{"review": [{"stage": "定位、输入与单次发送", "status": "FAIL"}]}]}})
        self.assertEqual(reconcile["state"], "RECONCILE_ONLY")
        self.assertEqual(reconcile["nextAction"], "native-copy-read-only-reconcile-no-resend")
        null_attempt = contract.completion_state({"ok": False, "error": "Quartz capture failed", "wechat": {
            "items": [{"desktop": {"state": "unknown", "sendAttempts": None,
                                     "groupName": sender.PRODUCTION_GROUP}}]}})
        self.assertEqual(null_attempt["state"], "RECONCILE_ONLY")
        self.assertEqual(null_attempt["nextAction"], "native-copy-read-only-reconcile-no-resend")
        user = contract.completion_state({"ok": False, "error": "desktop-login-required", "wechat": {}})
        self.assertEqual(user["state"], "USER_ACTION_REQUIRED")
        complete = contract.completion_state({"ok": True, "wechat": {"items": []}})
        self.assertEqual(complete["state"], "COMPLETE")

    def test_review_sent_count_comes_from_item_evidence(self):
        committed = {"merchantId": "1", "merchantName": "新商家", "review": [
            {"stage": "定位、输入与单次发送", "status": "PASS", "elapsedMs": 1},
            {"stage": "成功历史与原子游标提交", "status": "PASS", "elapsedMs": 1},
        ]}
        reconciled = {"merchantId": "2", "merchantName": "旧attempt", "review": [
            {"stage": "已有attempt只读复核", "status": "PASS", "elapsedMs": 1},
            {"stage": "成功历史与原子游标提交", "status": "PASS", "elapsedMs": 1},
        ]}
        review = contract.build_review({"runId": "test", "ok": True, "elapsedMs": 3,
                                        "stage": "complete", "stageMs": {}, "stageResults": {},
                                        "wechat": {"sent": 99, "items": [committed, reconciled]}})
        self.assertEqual(review["sent"], 1)
        self.assertEqual(review["verifiedNewSends"], 1)
        self.assertEqual(review["verifiedExisting"], 1)

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

    def test_selection_audit_is_a_send_precondition(self):
        item, _ = item_and_receipt()
        today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        cursor = {"merchantId": "11111111", "recommendTime": today + " 16:00:00"}
        item["recommendTime"] = today + " 17:00:00"
        item["tableOrder"] = 2
        item["detailVerified"] = True
        item["status"] = "待处理"
        base = {"businessDate": today, "createdAt": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                "dateFilterVerified": True, "paginationComplete": True, "ascending": True,
                "detailsVerified": True, "filterStartDate": today, "filterEndDate": today,
                "dateFilter": today + ".." + today, "messages": [item], "cursor": cursor,
                "totalRows": 2, "pendingRows": 2, "targetCount": 1,
                "selectionAudit": {"totalRows": 2, "pendingRows": 2, "excludedAtOrBeforeCursor": 1,
                                   "excludedAfterCursorNotPending": 0, "targetCount": 1,
                                   "rows": [cursor | {"status": "待处理"},
                                            {"merchantId": item["merchantId"], "recommendTime": item["recommendTime"], "status": "待处理"}]}}
        sender.audit_collection(base)
        for change in ({"targetCount": 0}, {"excludedAtOrBeforeCursor": 0}, {"rows": base["selectionAudit"]["rows"][:1]}):
            receipt = json.loads(json.dumps(base))
            receipt["selectionAudit"].update(change)
            with self.subTest(change=change), self.assertRaisesRegex(sender.StopRun, "selection-audit"):
                sender.audit_collection(receipt)

    def test_collection_audit_accepts_collector_utc_z_timestamp(self):
        item, _ = item_and_receipt()
        today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
        cursor = {"merchantId": "11111111", "recommendTime": today + " 16:00:00"}
        item.update({"recommendTime": today + " 17:00:00", "tableOrder": 2,
                     "detailVerified": True, "status": "待处理"})
        receipt = {"businessDate": today, "createdAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                   "dateFilterVerified": True, "paginationComplete": True, "ascending": True,
                   "detailsVerified": True, "filterStartDate": today, "filterEndDate": today,
                   "dateFilter": today + ".." + today, "messages": [item], "cursor": cursor,
                   "totalRows": 2, "pendingRows": 2, "targetCount": 1,
                   "selectionAudit": {"totalRows": 2, "pendingRows": 2, "excludedAtOrBeforeCursor": 1,
                                      "excludedAfterCursorNotPending": 0, "targetCount": 1,
                                      "rows": [cursor | {"status": "待处理"},
                                               {"merchantId": item["merchantId"], "recommendTime": item["recommendTime"], "status": "待处理"}]}}
        sender.audit_collection(receipt)


class ReconciliationOnlyTests(unittest.TestCase):
    def test_existing_attempt_skips_outer_preflight_and_cannot_send_next_merchant(self):
        first, receipt = item_and_receipt()
        second = first | {"merchantId": "87654321", "merchantName": "后续商家"}
        second["sha256"] = __import__("hashlib").sha256(second["text"].encode()).hexdigest()
        collection = current_collection({"ok": True, "messages": [first, second], "cursor": {}})
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"; state.mkdir()
            marker_dir = state / "send-attempts"; marker_dir.mkdir()
            marker = marker_dir / (sender.send_identity(sender.PRODUCTION_GROUP, first) + ".json")
            marker.write_text(json.dumps({"state": "unknown", "sendAttempts": None}))
            receipt.update({"sendAttempts": None, "physicalSendAttempts": None,
                            "reconciledWithoutSend": True})
            with patch.object(sender, "STATE_DIR", state), \
                 patch.object(sender, "HISTORY_FILE", state / "send-history.jsonl"), \
                 patch.object(integrity, "verify_for_run", return_value={"ok": True, "status": "SEALED"}), \
                 patch.object(contract, "offline_selftest", return_value={"ok": True}), \
                 patch.object(collector, "collect", return_value=collection), \
                 patch.object(sender, "load_collection", return_value=collection), \
                 patch.object(sender, "audit_collection"), \
                 patch.object(desktop, "preflight") as preflight, \
                 patch.object(desktop, "_reconcile_unknown", return_value=receipt) as reconcile, \
                 patch.object(contract, "verify_delivery", return_value={"ok": True}), \
                 patch.object(sender, "append_history_then_cursor"), \
                 patch.object(contract, "audit_final", return_value={"verified": True}) as final, \
                 patch.object(desktop.subprocess, "run") as execute:
                args = workflow.build_parser().parse_args([
                    "--group", sender.PRODUCTION_GROUP,
                    "--standing-authorization", contract.PRODUCTION_AUTHORIZATION,
                    "--output-dir", str(Path(directory) / "run"),
                ])
                result = workflow.execute(args)
        self.assertTrue(result["ok"])
        preflight.assert_not_called()
        reconcile.assert_called_once()
        execute.assert_not_called()
        self.assertEqual(len(result["wechat"]["items"]), 1)
        self.assertEqual(result["wechat"]["mode"], "reconcile-only")
        self.assertEqual(result["wechat"]["sent"], 0)
        self.assertTrue(final.call_args.kwargs["reconciliation_only"])

    def test_null_attempt_unknown_marker_cannot_enter_send_preflight_or_send(self):
        first, receipt = item_and_receipt()
        collection = current_collection({"ok": True, "messages": [first], "cursor": {}})
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / "state"; state.mkdir()
            marker_dir = state / "send-attempts"; marker_dir.mkdir()
            marker = marker_dir / (sender.send_identity(sender.PRODUCTION_GROUP, first) + ".json")
            marker.write_text(json.dumps({"state": "unknown", "sendAttempts": None}))
            with patch.object(sender, "STATE_DIR", state), \
                 patch.object(sender, "HISTORY_FILE", state / "send-history.jsonl"), \
                 patch.object(integrity, "verify_for_run", return_value={"ok": True, "status": "SEALED"}), \
                 patch.object(contract, "offline_selftest", return_value={"ok": True}), \
                 patch.object(collector, "collect", return_value=collection), \
                 patch.object(sender, "load_collection", return_value=collection), \
                 patch.object(sender, "audit_collection"), \
                 patch.object(desktop, "preflight") as preflight, \
                 patch.object(desktop, "_reconcile_unknown", return_value=receipt | {
                     "sendAttempts": None, "physicalSendAttempts": None, "reconciledWithoutSend": True}) as reconcile, \
                 patch.object(contract, "verify_delivery", return_value={"ok": True}), \
                 patch.object(sender, "append_history_then_cursor"), \
                 patch.object(contract, "audit_final", return_value={"verified": True}) as final, \
                 patch.object(desktop.subprocess, "run") as execute:
                args = workflow.build_parser().parse_args([
                    "--group", sender.PRODUCTION_GROUP,
                    "--standing-authorization", contract.PRODUCTION_AUTHORIZATION,
                    "--output-dir", str(Path(directory) / "run"),
                ])
                result = workflow.execute(args)
        self.assertTrue(result["ok"])
        self.assertTrue(result["wechat"]["verified"])
        self.assertEqual(result["wechat"]["sent"], 0)
        preflight.assert_not_called(); execute.assert_not_called()
        reconcile.assert_called_once()
        self.assertTrue(final.call_args.kwargs["reconciliation_only"])

class MissingMarkerRecoveryTests(unittest.TestCase):
    def test_private_unknown_receipt_recovers_only_matching_marker(self):
        item, receipt = item_and_receipt()
        receipt.update({"bridgeVersion": 1, "state": "unknown", "sendAttempts": 1,
                        "physicalSendAttempts": 1, "stage": "post_send_verify", "groupName": sender.PRODUCTION_GROUP})
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory); target = state / "runs" / "prior" / "desktop-wechat" / item["merchantId"]
            target.mkdir(parents=True); (target / "receipt.json").write_text(json.dumps(receipt))
            with patch.object(sender, "STATE_DIR", state):
                marker, recovered = workflow.recover_unknown_marker_from_receipt(item, sender.PRODUCTION_GROUP)
            self.assertTrue(recovered)
            self.assertEqual(json.loads(marker.read_text())["state"], "unknown")
            self.assertEqual(json.loads(marker.read_text())["sendAttempts"], 1)

    def test_existing_incomplete_marker_recovers_from_private_workflow_runs(self):
        item, receipt = item_and_receipt()
        receipt.update({"bridgeVersion": 1, "state": "unknown", "verified": False,
                        "sendAttempts": 1, "physicalSendAttempts": 1,
                        "stage": "post_send_verify", "groupName": sender.PRODUCTION_GROUP,
                        "payloads": [{"text": item["text"], "sha256": item["sha256"]}]})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / "state"; marker_dir = state / "send-attempts"; marker_dir.mkdir(parents=True)
            marker = marker_dir / (sender.send_identity(sender.PRODUCTION_GROUP, item) + ".json")
            marker.write_text(json.dumps({"state": "unknown", "sendAttempts": 1,
                                          "groupName": sender.PRODUCTION_GROUP,
                                          "merchantId": None, "sha256": None}))
            receipt_dir = root / "runs" / "prior" / "desktop-wechat" / item["merchantId"]
            receipt_dir.mkdir(parents=True); (receipt_dir / "receipt.json").write_text(json.dumps(receipt))
            with patch.object(sender, "STATE_DIR", state), \
                 patch.object(workflow, "WORKFLOW_RUNS_ROOT", root / "runs"):
                recovered_marker, recovered = workflow.recover_unknown_marker_from_receipt(
                    item, sender.PRODUCTION_GROUP)
            self.assertTrue(recovered)
            value = json.loads(recovered_marker.read_text())
            self.assertEqual(value["merchantId"], item["merchantId"])
            self.assertEqual(value["messageSha256"], item["sha256"])
            self.assertEqual(value["payloads"][0]["text"], item["text"])

    def test_existing_marker_accepts_completed_wrapper_with_unknown_common_receipt(self):
        item, receipt = item_and_receipt()
        receipt.update({"bridgeVersion": 1, "state": "unknown", "verified": False,
                        "sendAttempts": 1, "physicalSendAttempts": 1,
                        "stage": "completed", "commonReceipt": {"status": "unknown"},
                        "groupName": sender.PRODUCTION_GROUP,
                        "payloads": [{"text": item["text"], "sha256": item["sha256"]}]})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state = root / "state"; marker_dir = state / "send-attempts"
            marker_dir.mkdir(parents=True)
            marker = marker_dir / (sender.send_identity(sender.PRODUCTION_GROUP, item) + ".json")
            marker.write_text(json.dumps({"state": "unknown", "sendAttempts": 1,
                                          "groupName": sender.PRODUCTION_GROUP,
                                          "payloads": receipt["payloads"]}))
            receipt_dir = root / "runs" / "prior" / "desktop-wechat" / item["merchantId"]
            receipt_dir.mkdir(parents=True); (receipt_dir / "receipt.json").write_text(json.dumps(receipt))
            with patch.object(sender, "STATE_DIR", state), \
                 patch.object(workflow, "WORKFLOW_RUNS_ROOT", root / "runs"):
                recovered_marker, recovered = workflow.recover_unknown_marker_from_receipt(
                    item, sender.PRODUCTION_GROUP)
            self.assertTrue(recovered)
            self.assertEqual(json.loads(recovered_marker.read_text())["messageSha256"], item["sha256"])

    def test_existing_incomplete_marker_rejects_ambiguous_private_receipts(self):
        item, receipt = item_and_receipt()
        receipt.update({"bridgeVersion": 1, "state": "unknown", "verified": False,
                        "sendAttempts": 1, "physicalSendAttempts": 1,
                        "stage": "post_send_verify", "groupName": sender.PRODUCTION_GROUP,
                        "payloads": [{"text": item["text"], "sha256": item["sha256"]}]})
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); state = root / "state"; marker_dir = state / "send-attempts"
            marker_dir.mkdir(parents=True)
            marker = marker_dir / (sender.send_identity(sender.PRODUCTION_GROUP, item) + ".json")
            marker.write_text(json.dumps({"state": "unknown", "sendAttempts": 1,
                                          "groupName": sender.PRODUCTION_GROUP,
                                          "merchantId": None, "sha256": None}))
            for name in ("one", "two"):
                receipt_dir = root / "runs" / name / "desktop-wechat" / item["merchantId"]
                receipt_dir.mkdir(parents=True); (receipt_dir / "receipt.json").write_text(json.dumps(receipt))
            with patch.object(sender, "STATE_DIR", state), \
                 patch.object(workflow, "WORKFLOW_RUNS_ROOT", root / "runs"):
                recovered_marker, recovered = workflow.recover_unknown_marker_from_receipt(
                    item, sender.PRODUCTION_GROUP)
            self.assertFalse(recovered)
            self.assertIsNone(json.loads(recovered_marker.read_text()).get("merchantId"))


if __name__ == "__main__":
    unittest.main()
