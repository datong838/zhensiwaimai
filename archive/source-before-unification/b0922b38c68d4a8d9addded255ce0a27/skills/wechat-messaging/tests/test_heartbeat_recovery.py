import sys
import tempfile
import unittest
from types import SimpleNamespace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import heartbeat_recovery
from heartbeat_recovery import run


class HeartbeatRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.request = Path(self.tmp.name) / "request.json"
        self.authorization = Path(self.tmp.name) / "authorization.json"
        self.request.write_text("{}")
        self.authorization.write_text("{}")

    def tearDown(self):
        self.tmp.cleanup()

    def call(self, outcomes, maintenance=None):
        calls = []
        def runner(*_):
            calls.append("executor")
            return outcomes.pop(0)
        result = run("execute", self.request, self.authorization, runner=runner,
                     maintainer=maintenance or (lambda *_: {"ok": True, "status": "prepared"}),
                     now=datetime(2026, 9, 19, tzinfo=timezone.utc))
        return result, calls

    def test_dependency_drift_repairs_then_retries_once(self):
        result, calls = self.call([
            {"ok": False, "status": "blocked", "reason": "dependency-drift:/x", "sendAttempts": 0},
            {"ok": True, "status": "verified", "sendAttempts": 0},
        ])
        self.assertTrue(result["ok"])
        self.assertTrue(result["recoveryUsed"])
        self.assertEqual(calls, ["executor", "executor"])
        self.assertEqual(result["reviewSummary"]["stageCount"], 3)

    def test_attempted_never_maintains_or_retries(self):
        result, calls = self.call([{
            "ok": False, "status": "unknown", "reason": "dependency-drift:/x",
            "items": [{"status": "attempted", "sendAttempts": None}], "sendAttempts": 0,
        }])
        self.assertFalse(result["recoveryUsed"])
        self.assertEqual(calls, ["executor"])

    def test_missing_send_count_never_maintains_or_retries(self):
        result, calls = self.call([{
            "ok": False, "status": "blocked", "reason": "ImportError: missing",
        }])
        self.assertFalse(result["recoveryUsed"])
        self.assertEqual(result["sendAttempts"], -1)
        self.assertEqual(calls, ["executor"])

    def test_no_json_child_result_is_not_zero_attempts(self):
        old = heartbeat_recovery.subprocess.run
        heartbeat_recovery.subprocess.run = lambda *_args, **_kwargs: SimpleNamespace(
            stdout="", stderr="", returncode=1)
        try:
            result = heartbeat_recovery._run_executor("execute", self.request, self.authorization)
        finally:
            heartbeat_recovery.subprocess.run = old
        self.assertIsNone(result["sendAttempts"])
        self.assertEqual(result["returnCode"], 1)

    def test_nonzero_exit_is_preserved_with_valid_json(self):
        old = heartbeat_recovery.subprocess.run
        heartbeat_recovery.subprocess.run = lambda *_args, **_kwargs: SimpleNamespace(
            stdout='{"ok":true,"status":"verified","sendAttempts":0}\n', stderr="", returncode=1)
        try:
            result = heartbeat_recovery._run_executor("execute", self.request, self.authorization)
        finally:
            heartbeat_recovery.subprocess.run = old
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "total-executor-exit-code-mismatch")
        self.assertEqual(result["returnCode"], 1)

    def test_business_failure_never_maintains_or_retries(self):
        result, calls = self.call([{
            "ok": False, "status": "blocked", "reason": "group-type-not-proven", "sendAttempts": 0,
        }])
        self.assertFalse(result["recoveryUsed"])
        self.assertEqual(calls, ["executor"])

    def test_failed_maintenance_blocks_final_retry(self):
        result, calls = self.call(
            [{"ok": False, "status": "blocked", "reason": "ImportError: missing", "sendAttempts": 0}],
            maintenance=lambda *_: {"ok": False, "status": "blocked", "reason": "tests-failed"},
        )
        self.assertEqual(calls, ["executor"])
        self.assertEqual(result["reason"], "maintenance-failed")

    def test_final_failure_does_not_loop(self):
        result, calls = self.call([
            {"ok": False, "status": "blocked", "reason": "dependency-drift:/x", "sendAttempts": 0},
            {"ok": False, "status": "blocked", "reason": "dependency-drift:/x", "sendAttempts": 0},
        ])
        self.assertFalse(result["ok"])
        self.assertEqual(calls, ["executor", "executor"])


if __name__ == "__main__":
    unittest.main()
