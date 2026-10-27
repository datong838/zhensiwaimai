import hashlib
import json
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
import run_all


class Top10PendingDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.skill = {'name': 'daily-top10-to-wechat-group', 'target_group': 'exact-group',
                      'enabled': True, 'earliest_hour': 8, 'cadence_hours': 24}
        self.now = datetime(2026, 10, 26, 8, 35)
        key = hashlib.sha256(b'exact-group').hexdigest()[:12]
        self.marker = self.root / ('skills/workflows/daily-top10-to-wechat-group/'
                                  f'.runtime/send-ledger/2026-10-25-main-{key}.json')
        self.marker.parent.mkdir(parents=True)
        self.value = {'bridgeVersion': 1, 'payloadType': 'image', 'state': 'unknown',
                      'groupName': 'exact-group', 'sendAttempts': 1,
                      'payloads': [{'name': '2026-10-25_top10seller.png', 'sha256': 'a' * 64}]}
        self.scope = patch.object(run_all, 'REPO_ROOT', self.root)
        self.scope.start()
        self.addCleanup(self.scope.stop)

    def write(self, **changes):
        self.marker.write_text(json.dumps(self.value | changes))

    def test_attempted_and_unknown_block_without_changing_marker(self):
        for state in ['attempted', 'unknown']:
            self.write(state=state)
            before = self.marker.read_bytes()
            self.assertTrue(run_all.top10_delivery_pending(self.skill, self.now))
            self.assertEqual(self.marker.read_bytes(), before)

    def test_zero_verified_wrong_group_kind_and_payload_do_not_match(self):
        for changes in [{'sendAttempts': 0}, {'sendAttempts': True}, {'state': 'verified'},
                        {'state': 'blocked'}, {'groupName': 'other'}, {'payloadType': 'file'},
                        {'payloads': []}, {'payloads': [{'name': 'old.png', 'sha256': 'a' * 64}]},
                        {'payloads': [{'name': '2026-10-25_top10seller.png', 'sha256': 'bad'}]}]:
            with self.subTest(changes=changes):
                self.write(**changes)
                self.assertFalse(run_all.top10_delivery_pending(self.skill, self.now))

    def test_previous_marker_never_blocks_next_business_day_or_other_flow(self):
        self.write()
        self.assertFalse(run_all.top10_delivery_pending(self.skill, datetime(2026, 10, 27, 8)))
        self.assertFalse(run_all.top10_delivery_pending(self.skill | {'name': 'other'}, self.now))

    def test_missing_or_invalid_marker_preserves_existing_executor_validation(self):
        self.assertFalse(run_all.top10_delivery_pending(self.skill, self.now))
        self.marker.write_text('{invalid')
        self.assertFalse(run_all.top10_delivery_pending(self.skill, self.now))

    def test_cadence_is_pending_not_success(self):
        self.write()
        with patch('business_delivery_facts.read_fact', return_value=None):
            self.assertEqual(run_all._cadence_gate(self.skill, self.now),
                             (True, 'delivery_verification_pending'))
        record = run_all._pending_record(self.skill, 'delivery_verification_pending')
        self.assertEqual(record['category'], 'PENDING')
        self.assertEqual(record['finished_at'], '')
        self.assertIn('不重发', record['note'])

    def test_direct_run_never_acquires_post_or_probes_ui(self):
        with patch.object(run_all, 'top10_delivery_pending', return_value=True), \
             patch.object(run_all, 'acquire_post_group_lock', side_effect=AssertionError('lock')), \
             patch.object(run_all, 'probe_wechat_foreground', side_effect=AssertionError('UI')), \
             patch.object(run_all.sr, 'run_skill', side_effect=AssertionError('workflow')):
            record = run_all.run_one({'skills': [self.skill]}, self.skill['name'], {})
        self.assertEqual(record['detail'], 'delivery_verification_pending')

    def test_forced_daemon_cannot_bypass_pending_gate(self):
        with ExitStack() as stack:
            for name, value in [('login_health_gate', None), ('merchant_priority_checkpoint', None),
                                ('write_ledger_xlsx', False), ('_maybe_send_ledger', None),
                                ('write_last_cycle', None)]:
                stack.enter_context(patch.object(run_all, name, return_value=value))
            stack.enter_context(patch.object(run_all, 'pop_forced_runs',
                                            return_value=([self.skill['name']], None)))
            stack.enter_context(patch.object(run_all, '_cadence_gate',
                                            return_value=(True, 'delivery_verification_pending')))
            stack.enter_context(patch.object(run_all, 'build_ledger_rows', return_value=[]))
            stack.enter_context(patch.object(run_all, 'alert_store', None))
            stack.enter_context(patch.object(run_all.aw, 'run_auth_watch', return_value=[]))
            stack.enter_context(patch('group_consistency_check.check_flow', return_value=[]))
            stack.enter_context(patch('triage.run_triage'))
            launch = stack.enter_context(patch.object(run_all, 'run_one'))
            run_all.daemon_cycle({'skills': [self.skill]}, {}, False, force_all=True,
                                 forced_extra={self.skill['name']})
            launch.assert_not_called()


if __name__ == '__main__':
    unittest.main()

