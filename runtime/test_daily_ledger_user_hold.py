import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import daily_ledger_delivery as daily
import authorized_supplement as supplement


class UserLedgerHoldTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        root_patch = patch.object(daily, 'ROOT', self.root)
        root_patch.start(); self.addCleanup(root_patch.stop)
        facts = patch('business_delivery_facts.read_fact', return_value=None)
        facts.start(); self.addCleanup(facts.stop)
        self.now = datetime(2026, 10, 28, 19, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.hold = daily.directory(self.now) / 'user-send-hold.json'
        self.hold.parent.mkdir(parents=True)

    def mark(self, data='explicit user hold'):
        self.hold.write_text(data)

    def test_current_day_and_clock_do_not_release(self):
        self.mark()
        for hour in (8, 18, 19, 23):
            self.assertEqual(daily.readiness(self.now.replace(hour=hour)),
                             (False, ['daily-ledger-user-hold']))

    def test_next_day_not_implicitly_held(self):
        self.mark()
        tomorrow = self.now.replace(day=29, hour=17)
        self.assertFalse(daily.user_send_held(tomorrow))
        self.assertEqual(daily.readiness(tomorrow), (False, ['final-slot-not-due']))

    def test_bad_json_or_false_field_cannot_accidentally_release(self):
        for content in ('bad-json', '', '{"sendHeld":false}'):
            self.mark(content)
            self.assertTrue(daily.user_send_held(self.now))

    def test_directory_and_broken_symlink_are_held(self):
        self.hold.mkdir()
        self.assertTrue(daily.user_send_held(self.now))
        self.hold.rmdir()
        self.hold.symlink_to(self.root / 'absent-target')
        self.assertTrue(daily.user_send_held(self.now))

    def test_deliver_and_request_gate_have_no_effect(self):
        self.mark()
        before = self.hold.read_bytes()
        result = daily.deliver_once(self.root/'not-created.xlsx', adapter=object(), now=self.now)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['sendAttempts'], 0)
        self.assertEqual(result['pending'], ['daily-ledger-user-hold'])
        self.assertFalse(daily.request_enabled({}, self.now))
        self.assertEqual(list(self.hold.parent.iterdir()), [self.hold])
        self.assertEqual(self.hold.read_bytes(), before)

    def test_all_success_does_not_override_hold(self):
        names = daily.FINAL | {'meituan-intelligent-customer-service'}
        runtime = self.root/'runtime'
        (runtime/'skills_manifest.json').write_text(json.dumps({'skills':[
            {'name': n, 'enabled': True, 'dev_state':'active'} for n in names]}))
        history = runtime/'run_history/2026-10-28'; history.mkdir(parents=True)
        for name in names:
            (history/(name+'--record.json')).write_text(json.dumps({
                'skill':name,'status':'SUCCESS','finished_at':'2026-10-28T18:45:00'}))
        self.assertTrue(daily.readiness(self.now)[0])
        self.mark()
        self.assertEqual(daily.readiness(self.now), (False, ['daily-ledger-user-hold']))

    def test_only_explicit_external_release_removes_presence(self):
        self.mark()
        released = self.hold.parent/'release-history'
        released.mkdir()
        self.hold.rename(released/'original-user-hold.json')
        self.assertFalse(daily.user_send_held(self.now))
        self.assertTrue((released/'original-user-hold.json').is_file())

    def test_supplement_cannot_bypass_and_never_reads_payload(self):
        self.mark()
        with patch.object(supplement, 'ROOT', self.root), patch.object(supplement, 'datetime') as clock:
            clock.now.return_value = self.now
            with patch.object(supplement, 'table', side_effect=AssertionError('must not read grant')):
                self.assertIsNone(supplement.load_grant('daily-work-ledger'))
                self.assertIsNone(supplement.deliver_once('daily-work-ledger', self.root, adapter=object()))
                self.assertFalse(supplement.request_enabled({'context':{
                    'workflowId':'daily-work-ledger','supplementAuthorization':supplement.AUTH}}))

    def test_other_supplement_workflows_are_not_held(self):
        self.mark()
        with patch.object(supplement, 'ROOT', self.root):
            with patch.object(supplement, 'table', return_value=self.root/'no-grant.json') as table:
                self.assertIsNone(supplement.load_grant('daily-new-stores-opening-to-wechat'))
                table.assert_called_once()


if __name__ == '__main__':
    unittest.main()
