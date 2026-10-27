import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import workflow_executor as workflow
import runtime_contract as contract
import wechat_sender_executor as sender
import structured_merchant_collector as collector


class ProductionOnlyTests(unittest.TestCase):
    def args(self, output, group=None, authorization=None):
        argv = ["--output-dir", str(output), "--standing-authorization",
                authorization or contract.PRODUCTION_AUTHORIZATION]
        if group:
            argv += ["--group", group]
        return workflow.build_parser().parse_args(argv)

    def test_default_is_production(self):
        args = self.args("unused")
        self.assertEqual(args.group, sender.PRODUCTION_GROUP)
        self.assertEqual(contract.validate_policy(args, sender)["cursorFile"],
                         str(sender.cursor_file(sender.PRODUCTION_GROUP)))

    def test_test_or_unknown_group_is_rejected_before_ui(self):
        for group in (sender.TEST_GROUP, "other"):
            with self.subTest(group=group), tempfile.TemporaryDirectory() as directory, \
                 patch.object(sender, "STATE_DIR", Path(directory)), \
                 patch.object(workflow.executor_integrity, "verify_for_run", return_value={"ok": True, "status": "SEALED"}), \
                 patch.object(workflow.desktop_wechat_sender, "preflight") as preflight, \
                 patch.object(workflow.collector, "collect") as collect, \
                 patch.object(workflow.desktop_wechat_sender, "run") as send:
                result = workflow.execute(self.args(Path(directory) / "run", group, sender.TEST_AUTHORIZATION))
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], "production-only-target-required")
                preflight.assert_not_called()
                collect.assert_not_called()
                send.assert_not_called()

    def test_wrong_authorization_and_mobile_are_rejected(self):
        args = self.args("unused", authorization=sender.TEST_AUTHORIZATION)
        with self.assertRaisesRegex(RuntimeError, "authorization"):
            contract.validate_policy(args, sender)
        args = self.args("unused")
        args.wechat_channel = "mobile"
        with self.assertRaisesRegex(RuntimeError, "channel"):
            contract.validate_policy(args, sender)

    def test_readonly_collector_rejects_nonproduction_before_browser(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(collector.subprocess, "run") as browser:
            output = Path(directory) / "collection.json"
            receipt = collector.collect(sender.TEST_GROUP, Path(directory) / "cursor.test.json", output)
            self.assertFalse(receipt["ok"])
            self.assertEqual(receipt["error"], "production-only-target-required")
            browser.assert_not_called()
            self.assertTrue(output.with_name("collection.review.json").is_file())
            self.assertTrue(output.with_name("collection.review.md").is_file())


if __name__ == "__main__":
    unittest.main()
