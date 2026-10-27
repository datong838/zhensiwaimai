import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import structured_merchant_collector as collector


class ReadOnlyReviewTests(unittest.TestCase):
    def test_success_review_has_deterministic_stage_rows_and_counts(self):
        receipt = {"ok": True, "elapsedMs": 12, "totalRows": 3, "pendingRows": 2, "targetCount": 1,
                   "stageMs": {"background_preflight": 1, "task_page": 2, "navigation": 3,
                               "date_filter": 4, "page_1_read": 1, "selection_audit": 0},
                   "stageResults": {key: "PASS" for key in ("background_preflight", "task_page", "navigation",
                                                              "date_filter", "page_1_read", "selection_audit")},
                   "selectionAudit": {"totalRows": 3, "excludedAtOrBeforeCursor": 1,
                                      "excludedAfterCursorNotPending": 1, "targetCount": 1}}
        review = collector.build_collection_review(receipt)
        self.assertTrue(review["ok"])
        self.assertEqual(review["targetCount"], 1)
        selection = next(row for row in review["rows"] if row["stage"] == "selection_audit")
        self.assertIn("总3", selection["label"])
        self.assertIn("<0.001秒", collector.render_collection_review(review))

    def test_failure_review_marks_later_core_stages_skipped(self):
        receipt = {"ok": False, "elapsedMs": 9, "error": "bad|navigation",
                   "stageMs": {"background_preflight": 1, "task_page": 2, "navigation": 6},
                   "stageResults": {"background_preflight": "PASS", "task_page": "PASS", "navigation": "FAIL"}}
        review = collector.build_collection_review(receipt)
        self.assertEqual(next(row for row in review["rows"] if row["stage"] == "date_filter")["status"], "SKIPPED")
        rendered = collector.render_collection_review(review)
        self.assertIn("bad\\|navigation", rendered)
        self.assertIn("— | 未执行", rendered)

    def test_review_sidecars_are_written_by_code(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "collection.json"
            json_path, markdown_path = collector.write_collection_review(output, {
                "ok": False, "elapsedMs": 1, "error": "preflight", "stageMs": {}, "stageResults": {}})
            self.assertTrue(Path(json_path).is_file())
            self.assertTrue(Path(markdown_path).is_file())


if __name__ == "__main__":
    unittest.main()
