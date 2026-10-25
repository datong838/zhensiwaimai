import datetime as dt
import json
from pathlib import Path
import tempfile
import unittest
import history_retention as retention


class HistoryRetentionTests(unittest.TestCase):
    def root(self, td):
        root = Path(td)
        (root / 'runtime/run_history').mkdir(parents=True)
        return root

    def test_dates_are_canonical_and_real(self):
        for value in ('2026-1-01', '../2026-01-01', '2026-02-30', 'not-a-date'):
            self.assertIsNone(retention.dated(value))
        self.assertEqual(retention.dated('2026-10-25'), dt.date(2026, 10, 25))

    def test_three_day_window_cannot_be_archived(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            for day in ('2026-10-23', '2026-10-24', '2026-10-25', '2026-10-26'):
                folder = root / 'runtime/run_history' / day; folder.mkdir()
                with self.assertRaisesRegex(ValueError, 'three-day-window'):
                    retention.archive_day(root, folder, today=dt.date(2026, 10, 25))
                self.assertTrue(folder.exists())

    def test_verified_archive_retains_exact_bytes_and_protected_state(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            day = root / 'runtime/run_history/2026-10-20'
            day.mkdir(); (day / 'one.log').write_bytes(b'hello' * 1000)
            protected = root / 'runtime/state/cursor.json'
            protected.parent.mkdir(); protected.write_text('unchanged')
            result = retention.archive_day(root, day)
            self.assertFalse(day.exists())
            self.assertEqual(result['originalBytes'], 5000)
            index = json.loads((root / '.local/history-archive/2026-10-20.index.json').read_text())
            retention.verify_archive(root / '.local/history-archive/2026-10-20.tar.gz', '2026-10-20', index['files'])
            self.assertEqual(protected.read_text(), 'unchanged')

    def test_symlink_and_live_work_are_preserved(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td); day = root / 'runtime/run_history/2026-10-20'
            day.mkdir(); (day / 'link').symlink_to(root / 'runtime')
            with self.assertRaisesRegex(ValueError, 'non-regular'):
                retention.archive_day(root, day)
            (day / 'link').unlink()
            live = root / 'runtime/state/live_steps'; live.mkdir(parents=True)
            (live / 'busy').write_text('{}')
            with self.assertRaisesRegex(ValueError, 'active-workflow'):
                retention.archive_day(root, day)
            self.assertTrue(day.exists())

    def test_archive_collision_keeps_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td); day = root / 'runtime/run_history/2026-10-20'
            day.mkdir(); (day / 'one.log').write_text('one')
            target = root / '.local/history-archive'; target.mkdir(parents=True)
            (target / '2026-10-20.tar.gz').write_bytes(b'invalid')
            with self.assertRaises(Exception):
                retention.archive_day(root, day)
            self.assertEqual((day / 'one.log').read_text(), 'one')

    def test_reference_only_projects_safe_fields_and_recent_days(self):
        with tempfile.TemporaryDirectory() as td:
            root = self.root(td)
            (root / 'runtime/skills_manifest.json').write_text(json.dumps({'skills': [{'name': 'known'}]}))
            for day in ('2026-10-22', '2026-10-23', '2026-10-25'):
                folder = root / 'runtime/run_history' / day; folder.mkdir()
                record = {'skill': 'known', 'status': 'FAILED', 'category': 'UNKNOWN',
                          'detail': 'private phone', 'logs': ['secret'], 'duration_seconds': 1.5,
                          'started_at': day + 'T10:00:00'}
                (folder / 'one--record.json').write_text(json.dumps(record))
                (folder / 'bad--record.json').write_text(json.dumps(record | {'skill': 'private name'}))
            data = retention.reference_rows(root, dt.date(2026, 10, 25))
            self.assertEqual(len(data['runs']), 2)
            self.assertNotIn('private', json.dumps(data))
            self.assertNotIn('secret', json.dumps(data))
            self.assertEqual(data['runs'][0]['status'], 'FAILED')


if __name__ == '__main__':
    unittest.main()
