import fcntl
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import run_now_watcher as watcher


class WatcherOwnership(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.lock = self.root / 'runner.lock'
        self.control = self.root / 'control.json'
        self.control.write_text(json.dumps({'force_run_now': ['a'], 'note': 'keep'}))
        self.patch = patch.multiple(watcher, RUNNER_LOCK=self.lock, CONTROL_FILE=self.control)
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_busy_original_lock_preserves_all_requests_and_lock_bytes(self):
        self.lock.write_text('original-lock-bytes')
        holder = subprocess.Popen([sys.executable, '-c',
            'import fcntl,sys;f=open(sys.argv[1]);fcntl.flock(f,fcntl.LOCK_EX);print("held",flush=True);sys.stdin.readline()', str(self.lock)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(holder.stdout.readline().strip(), 'held')
            before = self.control.read_bytes()
            with patch.object(watcher, 'run_once') as run:
                self.assertTrue(watcher.runner_lock_held());self.assertEqual(watcher.process(), 0);run.assert_not_called()
            self.assertEqual(self.control.read_bytes(), before)
            self.assertEqual(self.lock.read_text(), 'original-lock-bytes')
        finally:
            holder.communicate('\n', timeout=5)
        self.assertFalse(watcher.runner_lock_held())

    def test_missing_lock_does_not_create_one(self):
        self.assertFalse(watcher.runner_lock_held());self.assertFalse(self.lock.exists())

    def test_idle_preserves_original_once_path(self):
        self.lock.write_text('unchanged')
        with patch.object(watcher, 'run_once', return_value=True) as run, patch.object(watcher, 'log'):
            watcher.process();run.assert_called_once_with('a')
        self.assertEqual(json.loads(self.control.read_text()), {'note':'keep'})
        self.assertEqual(self.lock.read_text(), 'unchanged')

    def test_unreadable_lock_yields_without_consuming(self):
        self.lock.mkdir()
        before = self.control.read_bytes()
        with patch.object(watcher, 'run_once') as run:
            watcher.process();run.assert_not_called()
        self.assertEqual(self.control.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
