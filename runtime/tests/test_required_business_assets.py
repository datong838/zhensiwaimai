import hashlib
import importlib.util
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SOURCE = Path(__file__).resolve().parents[1] / "supervisor_patrol.py"
spec = importlib.util.spec_from_file_location("required_assets_patrol", SOURCE)
patrol = importlib.util.module_from_spec(spec)
spec.loader.exec_module(patrol)


class RequiredAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "repo"
        self.root.mkdir()
        self.relative = "data/template.xlsx"
        self.file = self.root / self.relative
        self.file.parent.mkdir()
        with zipfile.ZipFile(self.file, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("[Content_Types].xml", "content-marker")
            archive.writestr("xl/workbook.xml", "workbook-marker")
        self.digest = hashlib.sha256(self.file.read_bytes()).hexdigest()
        self.root_patch = patch.object(patrol, "ROOT", self.root)
        self.assets_patch = patch.object(patrol, "BUSINESS_ASSETS", {self.relative: self.digest})
        self.root_patch.start()
        self.assets_patch.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.root_patch.stop)
        self.addCleanup(self.assets_patch.stop)

    def inspect(self, phase="business"):
        return patrol.check_business_assets(phase)

    def assert_red(self):
        snapshot, findings = self.inspect()
        self.assertEqual(findings[0]["level"], "RED")
        self.assertEqual(snapshot["files"][0]["status"], "invalid")

    def test_healthy_read_only_in_day_and_night(self):
        before = (self.file.read_bytes(), self.file.stat().st_mtime_ns)
        for phase in ("business", "night"):
            snapshot, findings = self.inspect(phase)
            self.assertFalse(findings)
            self.assertEqual(snapshot["files"][0]["status"], "valid")
        self.assertEqual((self.file.read_bytes(), self.file.stat().st_mtime_ns), before)

    def test_missing_empty_directory_and_bad_zip(self):
        original = self.file.read_bytes()
        self.file.unlink()
        self.assert_red()
        self.assertFalse(self.file.exists())
        self.file.mkdir()
        self.assert_red()
        self.file.rmdir()
        for content in (b"", b"bad", original + b"changed"):
            self.file.write_bytes(content)
            self.assert_red()

    def test_outside_symlink_is_not_self_contained(self):
        outside = self.root.parent / "outside.xlsx"
        outside.write_bytes(self.file.read_bytes())
        self.file.unlink()
        self.file.symlink_to(outside)
        self.assert_red()
        self.assertTrue(outside.exists())

    def test_mutable_roster_not_pinned_but_requires_xlsx(self):
        with patch.object(patrol, "BUSINESS_ASSETS", {self.relative: None}):
            with zipfile.ZipFile(self.file, "a") as archive:
                archive.writestr("xl/worksheets/sheet1.xml", "new business data")
            self.assertFalse(self.inspect()[1])
            self.file.write_bytes(b"not xlsx")
            self.assert_red()

    def test_missing_parts_and_bad_crc_are_detected(self):
        with patch.object(patrol, "BUSINESS_ASSETS", {self.relative: None}):
            original = self.file.read_bytes()
            self.file.write_bytes(original.replace(b"content-marker", b"CONTENT-marker"))
            self.assert_red()
            with zipfile.ZipFile(self.file, "w") as archive:
                archive.writestr("only.txt", "wrong container")
            self.assert_red()

    def test_registered_inputs_equal_live_pipeline_inputs(self):
        # Read the actual production caller; this catches a new or renamed format input.
        root = SOURCE.parent.parent
        text = (root / "skills/workflows/daily-jinsha-reports-to-business-wechat/scripts/business_exam_pipeline.mjs").read_text()
        names = set(re.findall(r"path\.join\(FIXED\.outputRoot,'([^']+\.xlsx)'\)", text))
        original_spec = importlib.util.spec_from_file_location("original_assets_patrol", SOURCE)
        original = importlib.util.module_from_spec(original_spec)
        original_spec.loader.exec_module(original)
        self.assertEqual({Path(name).name for name in original.BUSINESS_ASSETS}, names)
        self.assertEqual(len(names), 3)


if __name__ == "__main__":
    unittest.main()
