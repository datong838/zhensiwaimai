import json
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock
from pathlib import Path
from types import SimpleNamespace

import runtime_guard as guard
import workflow_executor as workflow


def canonical_args(**changes):
    values = dict(
        browser_profile=guard.CANONICAL_BROWSER_PROFILE,
        browser_port=guard.CANONICAL_BROWSER_PORT,
        wechat_channel=guard.CANONICAL_WECHAT_CHANNEL,
        transport_file=None,
        execute=True,
        standing_authorization=guard.CANONICAL_AUTHORIZATION,
    )
    values.update(changes)
    return SimpleNamespace(**values)


class RuntimePolicyTests(unittest.TestCase):
    def test_current_policy_and_files_are_valid(self):
        policy = guard.validate_runtime_policy()
        self.assertEqual(policy["policyId"], "daily-top10-desktop-v1")
        self.assertEqual(set(policy["validatedFiles"]), set(guard.EXPECTED_POLICY_FILES))

    def test_runtime_arguments_cannot_override_fixed_identity(self):
        guard.validate_runtime_arguments(canonical_args())
        cases = [
            ("browser_profile", "other-profile", "browser-profile"),
            ("browser_port", 9222, "browser-port"),
            ("wechat_channel", "mobile", "wechat-channel"),
            ("transport_file", "/tmp/device.json", "transport-not-allowed"),
            ("standing_authorization", "other", "authorization"),
        ]
        for field, value, reason in cases:
            with self.subTest(field=field), self.assertRaisesRegex(guard.RuntimePolicyError, reason):
                guard.validate_runtime_arguments(canonical_args(**{field: value}))

    def test_policy_field_and_digest_drift_fail_closed(self):
        source = json.loads(guard.POLICY_PATH.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / "policy.json"
            field_drift = source | {"browserPort": 9222}
            policy_path.write_text(json.dumps(field_drift), encoding="utf-8")
            with self.assertRaisesRegex(guard.RuntimePolicyError, "field-mismatch:browserPort"):
                guard.validate_runtime_policy(policy_path)

            digest_drift = json.loads(json.dumps(source))
            digest_drift["files"]["background_executor"]["sha256"] = "0" * 64
            policy_path.write_text(json.dumps(digest_drift), encoding="utf-8")
            with self.assertRaisesRegex(guard.RuntimePolicyError, "file-digest-mismatch:background_executor"):
                guard.validate_runtime_policy(policy_path)

    def test_policy_binds_guard_and_reports_all_digest_drifts_in_stable_order(self):
        source = json.loads(guard.POLICY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(source["files"]["runtime_guard"]["path"], str(Path(guard.__file__).resolve()))
        with tempfile.TemporaryDirectory() as directory:
            policy_path = Path(directory) / "policy.json"
            digest_drift = json.loads(json.dumps(source))
            digest_drift["files"]["runtime_guard"]["sha256"] = "0" * 64
            digest_drift["files"]["desktop_sender"]["sha256"] = "1" * 64
            digest_drift["files"]["messaging_dependencies"]["sha256"] = "2" * 64
            policy_path.write_text(json.dumps(digest_drift), encoding="utf-8")
            with self.assertRaisesRegex(
                guard.RuntimePolicyError,
                "runtime-policy-file-digest-mismatch:runtime_guard,desktop_sender,messaging_dependencies",
            ):
                guard.validate_runtime_policy(policy_path)

    def test_workflow_avoids_preflight_self_deadlock_and_releases_before_sender(self):
        workflow = Path(__file__).with_name("workflow_executor.py").read_text(encoding="utf-8")
        acquire = workflow.index("result['wechatGuard']=wechat_guard.acquire()")
        preflight = workflow.index("run_exact_group_preflight")
        browser = workflow.index("str(ROOT/'desktop_background_executor.mjs')")
        sender = workflow.index("str(DESKTOP_SENDER)")
        self.assertLess(preflight, acquire)
        self.assertLess(acquire, browser)
        self.assertLess(acquire, sender)
        self.assertLess(workflow.index("result['wechatGuard']=wechat_guard.release()"), sender)
        self.assertIn("result['wechatGuard']=wechat_guard.wait_until_quiet()", workflow)
        self.assertIn("result['wechatGuard']=wechat_guard.release()", workflow)
        self.assertIn("CANONICAL_BROWSER_PROFILE", workflow)
        self.assertIn("CANONICAL_BROWSER_PORT", workflow)

    def test_preflight_retries_only_transient_search_contention(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Mock()
            module.run_exact_group_preflight.side_effect = [
                {"ok": False, "reason": "wechat-search-region-contended", "sendAttempts": 0},
                {"ok": True, "reason": None, "sendAttempts": 0},
            ]
            waited = []
            result, attempts, elapsed = workflow.run_desktop_preflight_until_ready(
                module, "FEIBING NEO AI数字员工", Path(directory), sleep=waited.append)
            self.assertTrue(result["ok"])
            self.assertEqual(attempts, 2)
            self.assertEqual(waited, [5])
            self.assertGreaterEqual(elapsed, 0)

    def test_preflight_retries_exact_zero_result_once_then_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Mock()
            module.run_exact_group_preflight.side_effect = [
                {"ok": False, "reason": "exact-group-result-count:0", "sendAttempts": 0, "hardGate": False},
                {"ok": True, "reason": None, "sendAttempts": 0},
            ]
            waited = []
            result, attempts, elapsed = workflow.run_desktop_preflight_until_ready(
                module, "FEIBING NEO AI数字员工", Path(directory), sleep=waited.append)
            self.assertTrue(result["ok"])
            self.assertEqual(attempts, 2)
            self.assertEqual(waited, [5])
            self.assertEqual(result["retryHistory"], [{"reason": "exact-group-result-count:0", "waitMs": 5000}])
            self.assertGreaterEqual(elapsed, 0)

    def test_preflight_zero_result_has_one_retry_max_and_needs_explicit_zero_attempts(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Mock()
            failure = {"ok": False, "reason": "exact-group-result-count:0", "sendAttempts": 0, "hardGate": False}
            module.run_exact_group_preflight.return_value = failure
            waited = []
            result, attempts, _ = workflow.run_desktop_preflight_until_ready(
                module, "FEIBING NEO AI数字员工", Path(directory), sleep=waited.append)
            self.assertIs(result, failure)
            self.assertEqual(attempts, 2)
            self.assertEqual(waited, [5])

            for blocked in [
                {"ok": False, "reason": "exact-group-result-count:0", "hardGate": False},
                {"ok": False, "reason": "exact-group-result-count:0", "sendAttempts": 1, "hardGate": False},
                {"ok": False, "reason": "exact-group-result-count:multiple", "sendAttempts": 0, "hardGate": True},
                {"ok": False, "reason": "blocked-login", "sendAttempts": 0, "hardGate": False},
            ]:
                with self.subTest(blocked=blocked):
                    module.run_exact_group_preflight.reset_mock()
                    module.run_exact_group_preflight.return_value = blocked
                    waited.clear()
                    result, attempts, _ = workflow.run_desktop_preflight_until_ready(
                        module, "FEIBING NEO AI数字员工", Path(directory), sleep=waited.append)
                    self.assertIs(result, blocked)
                    self.assertEqual(attempts, 1)
                    self.assertEqual(waited, [])
                    self.assertEqual(module.run_exact_group_preflight.call_count, 1)

    def test_image_prepare_retry_requires_current_run_verified_cleanup_and_zero_send(self):
        safe = {
            "ok": False, "reason": "desktop-image-preview-not-prepared", "payloadType": "image",
            "sendAttempts": 0, "uncommittedPreviewCleanup": "attempted",
            "uncommittedPreviewCleared": True,
        }
        self.assertTrue(workflow.can_retry_cleaned_image_prepare(safe))
        unsafe = [
            safe | {"sendAttempts": 1},
            safe | {"sendAttempts": None},
            safe | {"attemptMarker": "/tmp/attempt.json"},
            safe | {"uncommittedPreviewCleared": False},
            safe | {"uncommittedPreviewCleanup": "failed"},
            safe | {"payloadType": "file"},
            safe | {"reason": "desktop-chat-input-not-empty"},
            safe | {"state": "unknown"},
            safe | {"ok": True},
        ]
        for result in unsafe:
            with self.subTest(result=result):
                self.assertFalse(workflow.can_retry_cleaned_image_prepare(result))

    def test_preflight_does_not_retry_hard_gate_or_other_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            module = Mock()
            failure = {"ok": False, "reason": "wechat-search-region-contended", "sendAttempts": 0, "hardGate": True}
            module.run_exact_group_preflight.return_value = failure
            waited = []
            result, attempts, _ = workflow.run_desktop_preflight_until_ready(
                module, "FEIBING NEO AI数字员工", Path(directory), sleep=waited.append)
            self.assertIs(result, failure)
            self.assertEqual(attempts, 1)
            self.assertEqual(waited, [])

            module.run_exact_group_preflight.return_value = {
                "ok": False, "reason": "blocked-login", "sendAttempts": 0, "hardGate": False}
            result, attempts, _ = workflow.run_desktop_preflight_until_ready(
                module, "FEIBING NEO AI数字员工", Path(directory), sleep=waited.append)
            self.assertEqual(result["reason"], "blocked-login")
            self.assertEqual(attempts, 1)
            self.assertEqual(waited, [])

    def test_preflight_contention_retry_is_bounded(self):
        # Persistent contention must never hold the shared WeChat interaction
        # lock forever: the outer retry is capped by attempt count and, when
        # exhausted, surfaces the last receipt with the original reason.
        with tempfile.TemporaryDirectory() as directory:
            module = Mock()
            failure = {"ok": False, "reason": "wechat-search-region-contended",
                       "sendAttempts": 0, "hardGate": False}
            module.run_exact_group_preflight.return_value = failure
            waited = []
            result, attempts, _ = workflow.run_desktop_preflight_until_ready(
                module, "FEIBING NEO AI数字员工", Path(directory), sleep=waited.append)
            self.assertEqual(attempts, workflow.MAX_CONTENTION_ATTEMPTS)
            self.assertEqual(waited, [5] * (workflow.MAX_CONTENTION_ATTEMPTS - 1))
            self.assertEqual(result["reason"], "wechat-search-region-contended")
            self.assertIs(result["contentionExhausted"], True)
            self.assertEqual(
                result["retryHistory"],
                [{"reason": "wechat-search-region-contended", "waitMs": 5000}]
                * workflow.MAX_CONTENTION_ATTEMPTS)


class WeChatExecutionGuardTests(unittest.TestCase):
    def make_guard(self, owner, path):
        return guard.WeChatExecutionGuard(
            owner,
            lock_path=path,
            poll_seconds=0.01,
            stable_checks=2,
            process_provider=lambda: [],
        )

    def test_second_guard_waits_until_first_releases(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "wechat.lock"
            first = self.make_guard("first", lock_path)
            second = self.make_guard("second", lock_path)
            first.acquire()
            acquired = threading.Event()

            def acquire_second():
                second.acquire()
                acquired.set()

            thread = threading.Thread(target=acquire_second, daemon=True)
            thread.start()
            time.sleep(0.04)
            self.assertFalse(acquired.is_set())
            first.release()
            thread.join(timeout=1)
            self.assertTrue(acquired.is_set())
            self.assertGreater(second.stats["lockWaitCycles"], 0)
            second.release()

    def test_competitor_requires_two_stable_checks(self):
        with tempfile.TemporaryDirectory() as directory:
            states = iter(([123], [], []))
            item = guard.WeChatExecutionGuard(
                "owner",
                lock_path=Path(directory) / "wechat.lock",
                poll_seconds=0.01,
                stable_checks=2,
                process_provider=lambda: next(states),
            )
            stats = item.acquire()
            self.assertEqual(stats["contentionChecks"], 3)
            self.assertEqual(stats["contentionWaitMs"], 20)
            item.release()

    def test_context_manager_releases_after_exception_without_deleting_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "wechat.lock"
            item = self.make_guard("owner", lock_path)
            with self.assertRaisesRegex(RuntimeError, "boom"):
                with item:
                    raise RuntimeError("boom")
            self.assertTrue(item.stats["released"])
            self.assertTrue(lock_path.exists())
            replacement = self.make_guard("replacement", lock_path)
            replacement.acquire()
            replacement.release()


if __name__ == "__main__":
    unittest.main()
