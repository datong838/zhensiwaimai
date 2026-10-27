"""Pure scheduling tests for three existing midday flows; no business execution."""
import json
from contextlib import ExitStack
from datetime import datetime, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch
import fixed_schedule
import run_all

class MiddayScheduleMinuteTests(unittest.TestCase):
    TIMES = {
        'daily-store-basic-diagnosis-to-wechat': '11:18',
        'daily-new-stores-decoration-audit-to-wechat': '11:30',
        'daily-new-stores-not-nourished-ops-to-wechat': '11:40',
    }
    def setUp(self):
        manifest = json.loads(Path(__file__).with_name('skills_manifest.json').read_text())
        self.skills = {s['name']: s for s in manifest['skills'] if s['name'] in self.TIMES}
        self.assertEqual(set(self.skills), set(self.TIMES))
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch('business_delivery_facts.read_fact', return_value=None))
        stack.enter_context(patch.object(run_all, 'top10_delivery_pending', return_value=False))
        stack.enter_context(patch.object(fixed_schedule, 'customer_duty_user_accepted', return_value=False))
        self.success = stack.enter_context(patch.object(run_all.sr, 'get_last_success', return_value=None))
    @staticmethod
    def at(time):
        return datetime.fromisoformat('2026-10-27T' + time + ':00')
    def test_manifest_matches_minutes(self):
        for name, time in self.TIMES.items():
            with self.subTest(name=name):
                skill = self.skills[name]
                self.assertEqual(skill['schedule_times'], [time])
                self.assertEqual((skill['earliest_hour'], skill['earliest_minute']), (11, int(time[-2:])))
    def test_every_earlier_minute_and_exact_slot(self):
        for name, time in self.TIMES.items():
            slot = self.at(time)
            for minute in range(11 * 60 + int(time[-2:])):
                now = self.at('00:00') + timedelta(minutes=minute)
                with self.subTest(name=name, now=now):
                    self.assertEqual(run_all._cadence_gate(self.skills[name], now), (True, 'not_due'))
            self.assertEqual(run_all._cadence_gate(self.skills[name], slot), (False, ''))
    def test_success_dedup_and_late_window(self):
        for name, time in self.TIMES.items():
            slot = self.at(time)
            with self.subTest(name=name):
                for last in [slot - timedelta(days=1), slot - timedelta(minutes=1)]:
                    self.success.return_value = last.isoformat()
                    self.assertEqual(run_all._cadence_gate(self.skills[name], slot), (False, ''))
                self.success.return_value = slot.isoformat()
                self.assertEqual(run_all._cadence_gate(self.skills[name], slot), (True, 'done_today'))
                self.assertEqual(run_all._cadence_gate(self.skills[name], self.at('18:00')), (True, 'done_today'))
                self.success.return_value = None
                self.assertEqual(run_all._cadence_gate(self.skills[name], self.at('17:59')), (False, ''))
                self.assertEqual(run_all._cadence_gate(self.skills[name], self.at('18:00')), (True, 'past_latest'))
    def test_daemon_wakes_at_each_slot(self):
        skills = list(self.skills.values())
        for after, expected in [('11:00', '11:18'), ('11:18', '11:30'), ('11:30', '11:40')]:
            self.assertEqual(fixed_schedule.next_boundary(skills, self.at(after)), self.at(expected))
        self.assertIsNone(fixed_schedule.next_boundary(skills, self.at('11:40')))

if __name__ == '__main__':
    unittest.main()
