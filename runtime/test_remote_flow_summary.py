import json
import tempfile
import unittest
import os
from pathlib import Path

import remote_flow_summary as summary


class RemoteFlowSummaryTests(unittest.TestCase):
    day = "2026-10-29"

    def write(self, root, value):
        path = summary.summary_path(self.day, root)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def valid(self):
        return {
            "schemaVersion": 1,
            "businessDate": self.day,
            "owner": "另一台电脑",
            "providedAt": "2026-10-29T20:00:00+08:00",
            "flows": [
                {"name": name, "status": "completed", "evidenceSummary": f"{name} 原机摘要"}
                for name in summary.REMOTE_FLOWS
            ],
        }

    def test_before_effective_date_is_not_applicable(self):
        value = summary.read_customer_scope("2026-10-28")
        self.assertEqual(value["remote_state"], "not_applicable")
        self.assertEqual(value["global_total"], 24)
        self.assertEqual(value["rows"], [])

    def test_missing_summary_is_nonblocking_and_never_completed(self):
        with tempfile.TemporaryDirectory() as folder:
            value = summary.read_customer_scope(self.day, Path(folder))
        self.assertEqual(value["remote_state"], "missing_nonblocking")
        self.assertTrue(value["nonblocking_local_execution"])
        self.assertEqual((value["global_total"], value["local_ledger_identities"], value["remote_flow_count"]), (27, 24, 3))
        self.assertEqual(value["remote_done"], 0)
        self.assertTrue(all(not row["done"] for row in value["rows"]))

    def test_valid_summary_is_displayed_without_local_execution_claim(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.write(root, self.valid())
            value = summary.read_customer_scope(self.day, root)
        self.assertEqual(value["remote_state"], "provided_valid")
        self.assertEqual(value["remote_done"], 3)
        self.assertTrue(all(row["owner"] == "另一台电脑" for row in value["rows"]))
        self.assertTrue(all(row["done"] for row in value["rows"]))

    def test_pending_failed_and_unknown_are_not_completed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = self.valid()
            for flow, status in zip(value["flows"], ("pending", "failed", "unknown")):
                flow["status"] = status
                flow.pop("evidenceSummary", None)
            self.write(root, value)
            result = summary.read_customer_scope(self.day, root)
        self.assertEqual(result["remote_state"], "provided_valid")
        self.assertEqual(result["remote_done"], 0)

    def test_contract_rejects_wrong_shape_without_raising(self):
        mutations = []
        wrong_day = self.valid(); wrong_day["businessDate"] = "2026-10-28"; mutations.append(wrong_day)
        wrong_owner = self.valid(); wrong_owner["owner"] = "本机"; mutations.append(wrong_owner)
        missing = self.valid(); missing["flows"] = missing["flows"][:-1]; mutations.append(missing)
        duplicate = self.valid(); duplicate["flows"][1]["name"] = duplicate["flows"][0]["name"]; mutations.append(duplicate)
        bad_status = self.valid(); bad_status["flows"][0]["status"] = "success"; mutations.append(bad_status)
        no_evidence = self.valid(); no_evidence["flows"][0].pop("evidenceSummary"); mutations.append(no_evidence)
        for value in mutations:
            with self.subTest(value=value):
                with tempfile.TemporaryDirectory() as folder:
                    root = Path(folder)
                    self.write(root, value)
                    result = summary.read_customer_scope(self.day, root)
                self.assertEqual(result["remote_state"], "invalid_nonblocking")
                self.assertEqual(result["remote_done"], 0)

    def test_symlink_and_oversized_summary_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            target = root / "target.json"
            target.write_text(json.dumps(self.valid()), encoding="utf-8")
            path = summary.summary_path(self.day, root)
            path.parent.mkdir(parents=True)
            os.symlink(target, path)
            self.assertIn("summary-symlink-rejected", summary.read_customer_scope(self.day, root)["errors"])
            path.unlink()
            path.write_text("x" * (summary.MAX_FILE_BYTES + 1), encoding="utf-8")
            self.assertIn("summary-file-too-large", summary.read_customer_scope(self.day, root)["errors"])

    def test_display_text_cannot_break_markdown_table(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            value = self.valid()
            value["flows"][0]["evidenceSummary"] = "第一行|A\n第二行"
            self.write(root, value)
            result = summary.read_customer_scope(self.day, root)
        self.assertEqual(result["remote_state"], "provided_valid")
        self.assertEqual(result["rows"][0]["reason"], "第一行\\|A 第二行")


if __name__ == "__main__":
    unittest.main()
