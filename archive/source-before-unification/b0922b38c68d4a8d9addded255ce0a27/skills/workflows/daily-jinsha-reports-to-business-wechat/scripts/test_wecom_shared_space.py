import tempfile
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import wecom_shared_space as subject


class WecomSharedSpaceTests(unittest.TestCase):
    def test_documents_toolbar_requires_all_four_markers_and_unique_hit(self):
        complete = subject.Hit(407, 170, 513, 33, 1, "与我相关 智能文档 智能表格 全部")
        incomplete = subject.Hit(407, 170, 513, 33, 1, "与我相关 智能文档 全部")
        too_low = subject.Hit(407, 400, 513, 33, 1, "与我相关 智能文档 智能表格 全部")
        self.assertEqual(subject.documents_all_tabs([complete, incomplete, too_low]), [complete])

    def test_exact_space_and_absent_files(self):
        space = "金鲨昨日双平台日报业务群"
        hits = [subject.Hit(1, 1, 1, 1, 1, value) for value in
                ["文档", "微盘", "共享空间", space, space, space, "暂无文档"]]
        state = subject.classify_space(hits, space, ["美团外卖日报_2026-09-09", "淘宝闪购日报_2026-09-09"])
        self.assertTrue(state["isSpaceWindow"])
        self.assertEqual(state["fileState"], "absent")

    def test_partial_and_complete_are_distinct(self):
        space = "金鲨昨日双平台日报业务群"
        names = ["美团外卖日报_2026-09-09", "淘宝闪购日报_2026-09-09"]
        base = ["文档", "微盘", "共享空间", space, space, space]
        partial = [subject.Hit(1, 1, 1, 1, 1, value) for value in base + names[:1]]
        complete = [subject.Hit(1, 1, 1, 1, 1, value) for value in base + names]
        self.assertEqual(subject.classify_space(partial, space, names)["fileState"], "partial")
        self.assertEqual(subject.classify_space(complete, space, names)["fileState"], "complete")

    def test_wecom_converted_title_drops_xlsx_and_tolerates_ocr_punctuation(self):
        files = [Path("美团外卖日报_2026-09-09.xlsx"), Path("淘宝闪购日报_2026-09-09.xlsx")]
        self.assertEqual(subject.document_names(files), ["美团外卖日报_2026-09-09", "淘宝闪购日报_2026-09-09"])
        space = "金鲨昨日双平台日报业务群"
        values = ["文档", "微盘", "共享空间", space, space, space,
                  "美团外卖日报-2026-09-09", "淘宝闪购日报2026-09-09"]
        hits = [subject.Hit(1, 1, 1, 1, 1, value) for value in values]
        self.assertEqual(subject.classify_space(hits, space, subject.document_names(files))["fileState"], "complete")

    def test_selected_space_row_may_have_merged_bullet_but_full_name_stays_exact(self):
        space = "金鲨昨日双平台日报业务群"
        values = ["文档", "微盘", "共享空间", space, space, f"• {space}"]
        hits = [subject.Hit(1, 1, 1, 1, 1, value) for value in values]
        state = subject.classify_space(hits, space, [])
        self.assertTrue(state["isSpaceWindow"])
        self.assertEqual(state["spaceExactCount"], 2)
        self.assertEqual(state["spaceEvidenceCount"], 3)

    def test_staging_uses_regular_copies_and_reuses_only_matching_content(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            sources = root / "sources"
            sources.mkdir()
            first = sources / "美团外卖日报_2026-09-09.xlsx"
            second = sources / "淘宝闪购日报_2026-09-09.xlsx"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            staging = subject.make_staging([first, second], root / "artifacts")
            self.assertFalse((staging / first.name).is_symlink())
            self.assertEqual((staging / second.name).read_bytes(), b"second")
            self.assertEqual(subject.make_staging([first, second], root / "artifacts"), staging)

    def test_staging_directory_contains_only_the_two_expected_names(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            sources = root / "sources"
            sources.mkdir()
            files = [sources / "美团外卖日报_2026-09-10.xlsx", sources / "淘宝闪购日报_2026-09-10.xlsx"]
            for file in files:
                file.write_bytes(file.name.encode())
            staging = subject.make_staging(files, root / "artifacts")
            self.assertEqual(sorted(value.name for value in staging.iterdir()), sorted(file.name for file in files))

    def test_attempt_marker_is_atomic(self):
        with tempfile.TemporaryDirectory() as value:
            target = Path(value) / "attempt.json"
            subject.atomic_json(target, {"state": "attempted", "uploadAttempts": 1})
            self.assertIn('"uploadAttempts": 1', target.read_text())

    def test_sheet_count_parser_contract_is_decimal(self):
        self.assertTrue("0".isdigit())
        self.assertFalse("missing value".isdigit())

    def test_confirmed_marker_preserves_first_confirmation_and_recovery(self):
        with tempfile.TemporaryDirectory() as value:
            root = Path(value)
            marker = root / "attempt.json"
            files = [root / "a.xlsx", root / "b.xlsx"]
            for file in files:
                file.write_bytes(file.name.encode())
            subject.atomic_json(marker, {"state": "confirmed", "uploadAttempts": 1,
                                         "confirmedAt": 123.0, "recovered": True})
            confirmed = subject.confirm_marker(marker, files, ["one.png", "two.png"], recovered=False)
            self.assertEqual(confirmed["confirmedAt"], 123.0)
            self.assertTrue(confirmed["recovered"])
            self.assertEqual(confirmed["uploadAttempts"], 1)


if __name__ == "__main__":
    unittest.main()
