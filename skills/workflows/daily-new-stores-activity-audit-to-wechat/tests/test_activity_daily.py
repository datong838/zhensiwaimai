import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("activity_daily", SCRIPTS / "activity_daily.py")
DAILY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(DAILY)


class ActivityDailyTests(unittest.TestCase):
    def test_only_same_day_validated_taobao_hits_are_selected(self):
        day = datetime.now(DAILY.activity.LOCAL_TZ).date().isoformat()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / f"{(datetime.now(DAILY.activity.LOCAL_TZ)-timedelta(days=1)):%Y-%m-%d}-old"
            old.mkdir()
            (old / "collection.json").write_text(json.dumps({"checkedAt": (datetime.now(DAILY.activity.LOCAL_TZ)-timedelta(days=1)).isoformat()}))
            current = root / f"{day}-current"
            current.mkdir()
            (current / "collection.json").write_text(json.dumps({"checkedAt": datetime.now(DAILY.activity.LOCAL_TZ).isoformat(), "unresolved": []}))
            hits = [{"channel": "美团", "name": "美团店", "days": "1天"},
                    {"channel": "淘宝", "name": "淘宝店", "days": "2天"}]
            with patch.object(DAILY.new_stores, "RUNTIME", root), patch.object(DAILY.new_stores, "validate_collection", return_value=hits):
                source, targets = DAILY.todays_source(day)
            self.assertEqual(source, current / "collection.json")
            self.assertEqual([target["name"] for target in targets], ["淘宝店"])

    def test_no_complete_today_source_blocks_before_browser(self):
        day = datetime.now(DAILY.activity.LOCAL_TZ).date().isoformat()
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(DAILY.new_stores, "RUNTIME", Path(directory)):
                with self.assertRaisesRegex(ValueError, "today-complete-new-store-receipt-missing"):
                    DAILY.todays_source(day)

    def test_missing_source_runs_only_read_only_scan(self):
        with patch.object(DAILY, "todays_source",
                          side_effect=[ValueError("today-complete-new-store-receipt-missing"),
                                       (Path("/tmp/current-collection.json"), [])]), \
             patch.object(DAILY.subprocess, "run",
                          return_value=type("Result", (), {"returncode": 0, "stdout": ""})()) as scan:
            result = DAILY.run(execute=True)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["targetCount"], 0)
        self.assertEqual(scan.call_args.args[0][-1], "--collect-only")


if __name__ == "__main__":
    unittest.main()
