import datetime as dt
import json
from pathlib import Path
import unittest
import fixed_schedule


class MorningFixedWakeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skills = json.loads(Path(__file__).with_name('skills_manifest.json').read_text())['skills']
        cls.by_name = {skill['name']: skill for skill in cls.skills}

    def test_critical_entries_have_exact_enabled_slots(self):
        expected = {'daily-top10-to-wechat-group': '08:00',
                    'negative-feedback-list-appeals-0930': '08:20',
                    'negative-feedback-list-appeals-1230': '08:20',
                    'daily-negative-reviews': '08:30',
                    'daily-agent-new-merchants-to-wechat': '08:30',
                    'contract-termination-applications-screenshot': '09:00'}
        for name, slot in expected.items():
            self.assertTrue(self.by_name[name]['enabled'], name)
            self.assertIn(slot, self.by_name[name]['schedule_times'], name)
        self.assertIn('negative-feedback-list-appeals-0930',
                      self.by_name['negative-feedback-list-appeals-1230']['depends_on'])

    def test_original_boundary_wakes_at_top10_and_feedback(self):
        at = dt.datetime(2026, 10, 26, 7, 55)
        self.assertEqual(fixed_schedule.next_boundary(self.skills, at), at.replace(hour=8, minute=0))
        self.assertEqual(fixed_schedule.next_boundary(self.skills, at.replace(hour=8, minute=0)),
                         at.replace(hour=8, minute=20))
        self.assertEqual(fixed_schedule.next_boundary(self.skills, at.replace(hour=8, minute=29)),
                         at.replace(hour=8, minute=30))

    def test_yesterday_success_does_not_complete_new_day(self):
        top = self.by_name['daily-top10-to-wechat-group']
        now = dt.datetime(2026, 10, 26, 8, 0)
        self.assertEqual(fixed_schedule.gate(top, now, '2026-10-25T08:10:00'), (False, ''))
        self.assertEqual(fixed_schedule.gate(top, now, '2026-10-26T08:00:00'), (True, 'done_today'))
        self.assertEqual(fixed_schedule.gate(top, now.replace(hour=7), None), (True, 'not_due'))


if __name__ == '__main__':
    unittest.main()
