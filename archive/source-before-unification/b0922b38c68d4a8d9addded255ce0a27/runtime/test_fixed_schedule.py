import unittest
from datetime import datetime
from unittest.mock import patch
import fixed_schedule as fixed
import run_all

class FixedScheduleTests(unittest.TestCase):
    def setUp(self):
        self.skill={'name':'appeal','enabled':True,'earliest_hour':13,'latest_hour':19,'cadence_hours':24,'schedule_times':['13:00','15:00','17:00','18:30']}
    def at(self,time):return datetime.fromisoformat('2026-10-24T'+time+':00')
    def test_four_boundaries_and_success_does_not_cover_next(self):
        for when,last,expected in [('12:59',None,(True,'not_due')),('13:00','10:12',(False,'')),('14:59','13:10',(True,'done_today')),('15:00','13:10',(False,'')),('17:00','15:03',(False,'')),('18:29','17:03',(True,'done_today')),('18:30','17:03',(False,'')),('18:45','18:40',(True,'done_today'))]:
            with self.subTest(when=when):self.assertEqual(fixed.gate(self.skill,self.at(when),self.at(last).isoformat() if last else None),expected)
    def test_integration_closes_after_19(self):
        with patch.object(run_all.sr,'get_last_success',return_value=None):self.assertEqual(run_all._cadence_gate(self.skill,self.at('19:00')),(True,'past_latest'))
        with patch.object(run_all.sr,'get_last_success',return_value=self.at('13:10').isoformat()):self.assertEqual(run_all._cadence_gate(self.skill,self.at('19:00')),(True,'past_latest'))
        with patch.object(run_all.sr,'get_last_success',return_value=self.at('18:40').isoformat()):self.assertEqual(run_all._cadence_gate(self.skill,self.at('19:00')),(True,'done_today'))
    def test_normal_flow_unchanged(self):
        normal={'name':'normal','earliest_hour':8,'cadence_hours':24}
        with patch.object(run_all.sr,'get_last_success',return_value=self.at('09:00').isoformat()):self.assertEqual(run_all._cadence_gate(normal,self.at('10:00')),(True,'done_today'))
    def test_invalid_slots(self):
        for values in [[],['15:00','13:00'],['13:00','13:00'],['25:00'],['8:20']]:
            with self.subTest(values=values),self.assertRaises(ValueError):fixed.boundaries({'schedule_times':values},self.at('10:00'))
    def test_morning_recovery_wake_does_not_reopen_completed_slot(self):
        skill={'name':'feedback','enabled':True,'schedule_times':['08:20'],'retry_check_times':['08:22','08:25','08:28']}
        self.assertEqual(fixed.next_boundary([skill],self.at('08:21')),self.at('08:22'))
        self.assertEqual(fixed.gate(skill,self.at('08:25'),self.at('08:21').isoformat()),(True,'done_today'))
        self.assertEqual(fixed.gate(skill,self.at('08:25'),None),(False,''))
    def test_dependency_requires_today_after_start(self):
        skill={'name':'summary','enabled':True,'earliest_hour':8,'earliest_minute':20,'schedule_times':['08:20'],'depends_on':['appeal']}
        for last in [None,self.at('08:10').isoformat(),'2026-10-23T08:25:00']:
            with patch.object(run_all.sr,'get_last_success',return_value=last):self.assertEqual(run_all._cadence_gate(skill,self.at('08:22')),(True,'dependency_pending'))
        with patch.object(run_all.sr,'get_last_success',side_effect=lambda n:self.at('08:21').isoformat() if n=='appeal' else None):self.assertEqual(run_all._cadence_gate(skill,self.at('08:22')),(False,''))

if __name__=='__main__':unittest.main()
