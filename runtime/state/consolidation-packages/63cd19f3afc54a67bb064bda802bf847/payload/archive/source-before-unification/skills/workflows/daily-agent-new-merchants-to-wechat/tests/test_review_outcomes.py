import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import runtime_contract as contract


def delivery_item(send=False, commit=True, recover=False):
    rows = [{"stage": "定位、输入与单次发送" if send else "已有attempt只读复核", "status": "PASS"}]
    if recover:
        rows.append({"stage": "发送后只读恢复", "status": "PASS"})
    rows.append({"stage": "成功历史与原子游标提交", "status": "PASS" if commit else "FAIL"})
    return {"review": rows}


class ReviewOutcomeTests(unittest.TestCase):
    def test_existing_reconcile_is_not_counted_as_new_send(self):
        self.assertEqual(contract.delivery_counts({"sent": 1, "items": [delivery_item()]}), {
            "verifiedNewSends": 0, "verifiedExisting": 1, "unresolvedItems": 0})

    def test_current_send_recovered_after_attempt_remains_new_send(self):
        self.assertEqual(contract.delivery_counts({"items": [delivery_item(send=True, recover=True)]})[
            "verifiedNewSends"], 1)

    def test_mixed_results_and_commit_failure(self):
        self.assertEqual(contract.delivery_counts({
            "items": [delivery_item(), delivery_item(send=True), delivery_item(send=True, commit=False)]}), {
            "verifiedNewSends": 1, "verifiedExisting": 1, "unresolvedItems": 1})

    def test_noop_is_not_rendered_as_a_send_pass(self):
        review = contract.build_review({"runId": "test", "ok": True, "elapsedMs": 5,
                                        "stageMs": {"desktop_wechat": 0},
                                        "stageResults": {"desktop_wechat": "PASS"},
                                        "wechat": {"mode": "execute-noop", "sent": 0}})
        row = next(item for item in review["rows"] if item["stage"] == "desktop_wechat")
        self.assertEqual(row["status"], "NOOP")
        self.assertIn("未触发发送", contract.render_review(review))
        self.assertIn("<0.001秒", contract.render_review(review))
        self.assertEqual(review["verifiedNewSends"], 0)

    def test_early_failure_is_skipped_not_noop(self):
        review = contract.build_review({"runId": "test", "ok": False, "elapsedMs": 5,
                                        "stage": "executor_integrity", "error": "hash-mismatch",
                                        "stageMs": {"executor_integrity": 5},
                                        "stageResults": {"executor_integrity": "FAIL"}})
        row = next(item for item in review["rows"] if item["stage"] == "desktop_wechat")
        self.assertEqual(row["status"], "SKIPPED")
        self.assertIsNone(row["elapsedMs"])


if __name__ == "__main__":
    unittest.main()
