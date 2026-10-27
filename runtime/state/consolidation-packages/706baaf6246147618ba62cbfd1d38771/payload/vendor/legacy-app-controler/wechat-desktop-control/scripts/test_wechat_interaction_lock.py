#!/usr/bin/env python3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from wechat_interaction_lock import WeChatInteractionLock


class InteractionLockTests(unittest.TestCase):
    def test_two_workflows_cannot_touch_wechat_together(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "wechat.lock"
            first = WeChatInteractionLock("first", timeout_seconds=1, poll_seconds=.01, lock_path=lock_path).acquire()
            acquired = threading.Event()
            second = WeChatInteractionLock("second", timeout_seconds=1, poll_seconds=.01, lock_path=lock_path)
            thread = threading.Thread(target=lambda: (second.acquire(), acquired.set()), daemon=True)
            thread.start(); time.sleep(.04)
            self.assertFalse(acquired.is_set())
            first.release(); thread.join(timeout=1)
            self.assertTrue(acquired.is_set())
            self.assertGreater(second.receipt()["waitCycles"], 0)
            second.release()


if __name__ == "__main__":
    unittest.main()
