#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""skill_runner 超时/后代进程清理的真实隔离回归。"""
from __future__ import annotations

import dataclasses
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import skill_runner as runner  # noqa: E402


CHILD_CODE = r"""
import os, signal, sys, time
path, mode = sys.argv[1], sys.argv[2]
with open(path + '.pid', 'w', encoding='utf-8') as fh:
    fh.write(str(os.getpid()))
if mode == 'ignore':
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
while True:
    with open(path, 'a', encoding='utf-8') as fh:
        fh.write('beat\n')
        fh.flush()
    time.sleep(0.03)
"""

PARENT_CODE = r"""
import subprocess, sys, time
path, mode, parent_mode = sys.argv[1:4]
child = subprocess.Popen([sys.executable, '-c', %r, path, mode])
deadline = time.time() + 3
while time.time() < deadline:
    try:
        if open(path, encoding='utf-8').read():
            break
    except OSError:
        pass
    time.sleep(0.02)
if parent_mode == 'exit':
    raise SystemExit(0)
time.sleep(60)
""" % CHILD_CODE


class StepProcessCleanupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory(prefix="runner-cleanup-test-")
        self.root = Path(self.tmp.name)
        self.live = self.root / "live_steps"
        self.live.mkdir()
        self.owned_steps = []
        original_register = runner._register_step

        def tracked_register(proc, argv, identity):
            self.owned_steps.append((proc, identity))
            return original_register(proc, argv, identity)

        self.patchers = [
            mock.patch.object(runner, "LIVE_STEPS_DIR", self.live),
            mock.patch.object(runner, "PROCESS_GROUP_TERM_GRACE_SECONDS", 0.2),
            mock.patch.object(runner, "PROCESS_GROUP_KILL_GRACE_SECONDS", 0.8),
            mock.patch.object(runner, "PROCESS_GROUP_POLL_SECONDS", 0.02),
            mock.patch.object(runner, "_register_step", new=tracked_register),
        ]
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self) -> None:
        # 仅处理本测试实际Popen并记录了身份锚点的进程组；临时目录里的伪造
        # legacy record不是进程所有权证明，只删除文件，绝不按其PGID发信号。
        for proc, identity in self.owned_steps:
            try:
                runner._cleanup_process_group(identity, term_grace=0, kill_grace=0.5)
                proc.poll()
            except (OSError, subprocess.SubprocessError):
                pass
        for record in list(self.live.glob("*.json")):
            record.unlink(missing_ok=True)
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.tmp.cleanup()

    def _argv(self, heartbeat: Path, child_mode: str, parent_mode: str):
        return [sys.executable, "-c", PARENT_CODE,
                str(heartbeat), child_mode, parent_mode]

    @staticmethod
    def _file_stopped(path: Path) -> bool:
        before = path.stat().st_size if path.exists() else 0
        time.sleep(0.15)
        after = path.stat().st_size if path.exists() else 0
        return before == after

    def _assert_fixture_pid_gone(self, heartbeat: Path) -> None:
        pid = int(Path(str(heartbeat) + ".pid").read_text(encoding="utf-8"))
        deadline = time.time() + 3
        while time.time() < deadline:
            status = subprocess.run(
                ["ps", "-p", str(pid), "-o", "pid="],
                capture_output=True, text=True, check=False)
            if not status.stdout.strip():
                return
            time.sleep(0.03)
        self.fail("fixture PID仍存在: %s" % pid)

    def test_timeout_kills_descendant_that_ignores_term(self) -> None:
        heartbeat = self.root / "ignore.log"
        result = runner.run_step(
            self._argv(heartbeat, "ignore", "wait"), self.root, 0.25,
            self.root / "timeout.log")
        self.assertTrue(result.timed_out)
        self.assertFalse(result.cleanup_uncertain, result.cleanup_detail)
        self.assertTrue(self._file_stopped(heartbeat))
        self._assert_fixture_pid_gone(heartbeat)
        self.assertEqual([], list(self.live.glob("*.json")))
        follow_up = runner.run_step(
            [sys.executable, "-c", "print('next-ok')"], self.root, 3,
            self.root / "follow-up.log")
        self.assertEqual(0, follow_up.exit_code)

    def test_timeout_allows_term_cooperative_group_to_exit(self) -> None:
        heartbeat = self.root / "cooperative.log"
        result = runner.run_step(
            self._argv(heartbeat, "default", "wait"), self.root, 0.25,
            self.root / "cooperative-run.log")
        self.assertTrue(result.timed_out)
        self.assertFalse(result.cleanup_uncertain, result.cleanup_detail)
        self.assertEqual("process-group-clean-after-term", result.cleanup_detail)
        self.assertTrue(self._file_stopped(heartbeat))
        self._assert_fixture_pid_gone(heartbeat)

    def test_normal_leader_exit_with_live_descendant_is_failed_and_cleaned(self) -> None:
        heartbeat = self.root / "early-exit.log"
        result = runner.run_step(
            self._argv(heartbeat, "ignore", "exit"), self.root, 3,
            self.root / "early-exit-run.log")
        self.assertFalse(result.timed_out)
        self.assertTrue(result.process_group_leak)
        self.assertFalse(result.cleanup_uncertain, result.cleanup_detail)
        self.assertNotEqual(0, result.exit_code)
        self.assertTrue(self._file_stopped(heartbeat))
        self._assert_fixture_pid_gone(heartbeat)
        self.assertEqual([], list(self.live.glob("*.json")))

    def test_normal_success_keeps_success_semantics(self) -> None:
        result = runner.run_step(
            [sys.executable, "-c", "print('ok')"], self.root, 3,
            self.root / "ok.log")
        self.assertEqual(0, result.exit_code)
        self.assertFalse(result.timed_out)
        self.assertFalse(result.process_group_leak)
        self.assertFalse(result.cleanup_uncertain)

    def test_timeout_is_not_retried_even_when_manifest_allows_retries(self) -> None:
        starts = self.root / "starts.log"
        heartbeat = self.root / "retry-child.log"
        script = (
            "from pathlib import Path; import subprocess,sys,time; "
            "Path(sys.argv[1]).open('a').write('start\\n'); "
            "subprocess.Popen([sys.executable,'-c',%r,sys.argv[2],'ignore']); "
            "time.sleep(60)" % CHILD_CODE
        )
        entry = {
            "name": "timeout-once",
            "cwd": ".",
            "max_retries": 2,
            "cooldown_seconds": 0,
            "steps": [{"argv": [sys.executable, "-c", script,
                                  str(starts), str(heartbeat)]}],
        }
        with mock.patch.object(runner, "REPO_ROOT", self.root), \
                mock.patch.object(runner, "RUN_DIR_ROOT", self.root / "runs"):
            record = runner.run_skill(
                entry, history_dir=self.root / "history", timeout_override=0.25)
        self.assertEqual(1, record["attempts"])
        self.assertEqual(1, len(starts.read_text(encoding="utf-8").splitlines()))
        self.assertTrue(self._file_stopped(heartbeat))
        self._assert_fixture_pid_gone(heartbeat)

    def test_identity_mismatch_sends_no_signal_to_unrelated_group(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True)
        real_killpg = os.killpg
        try:
            identity = runner._capture_process_group_identity(proc)
            wrong = dataclasses.replace(identity, leader_started="not-the-same-process")
            with mock.patch.object(runner.os, "killpg") as killpg:
                outcome = runner._cleanup_process_group(
                    wrong, term_grace=0.05, kill_grace=0.05)
            killpg.assert_not_called()
            self.assertTrue(outcome.uncertain)
            self.assertIsNone(proc.poll())
        finally:
            try:
                real_killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=3)

    def test_same_second_fake_birth_sends_no_signal(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True)
        real_killpg = os.killpg
        try:
            identity = runner._capture_process_group_identity(proc)
            prefix, seconds, micros = identity.leader_started.split(":", 2)
            self.assertEqual("darwin", prefix)
            wrong = dataclasses.replace(
                identity,
                leader_started="darwin:%s:%s" % (seconds, int(micros) + 1))
            with mock.patch.object(runner.os, "killpg") as killpg:
                outcome = runner._cleanup_process_group(
                    wrong, term_grace=0.05, kill_grace=0.05)
            killpg.assert_not_called()
            self.assertTrue(outcome.uncertain)
            self.assertIsNone(proc.poll())
        finally:
            try:
                real_killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=3)

    def test_empty_birth_anchor_sends_no_signal(self) -> None:
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            start_new_session=True)
        real_killpg = os.killpg
        try:
            identity = runner._capture_process_group_identity(proc)
            empty = dataclasses.replace(identity, leader_started="")
            with mock.patch.object(runner.os, "killpg") as killpg:
                outcome = runner._cleanup_process_group(
                    empty, term_grace=0.05, kill_grace=0.05)
            killpg.assert_not_called()
            self.assertTrue(outcome.uncertain)
            self.assertIsNone(proc.poll())
        finally:
            try:
                real_killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=3)

    def test_legacy_record_without_identity_is_retained_without_signal(self) -> None:
        record = self.live / "12345.json"
        record.write_text(json.dumps({"pgid": 12345, "pid": 12345}),
                          encoding="utf-8")
        with mock.patch.object(runner.os, "killpg") as killpg:
            self.assertEqual([], runner.kill_live_steps("test", grace=0))
        killpg.assert_not_called()
        self.assertTrue(record.exists())


if __name__ == "__main__":
    unittest.main()
