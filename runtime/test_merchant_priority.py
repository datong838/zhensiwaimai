import unittest
from datetime import datetime
from unittest.mock import patch
import run_all


class MerchantPriorityTests(unittest.TestCase):
    def setUp(self):
        self.data={'skills':[{'name':'daily-agent-new-merchants-to-wechat','enabled':True,
                   'schedule_times':['08:30','09:00','09:30'],'earliest_hour':8,
                   'earliest_minute':30,'latest_hour':19}]}
    def test_same_slot_once_but_new_slot_runs(self):
        seen=set();records={}
        with patch.object(run_all,'_cadence_gate',return_value=(False,'')), \
             patch.object(run_all,'run_one',return_value={'category':'UNKNOWN'}) as run, \
             patch.object(run_all,'record_outcome'):
            for time in ['09:00','09:05','09:30']:
                run_all.merchant_priority_checkpoint(self.data,{},records,seen,
                    datetime.fromisoformat('2026-10-26T'+time))
        self.assertEqual(run.call_count,2)
    def test_not_due_done_and_after_hours_do_not_run(self):
        for reason in ['not_due','done_today','past_latest']:
            with self.subTest(reason=reason), \
                 patch.object(run_all,'_cadence_gate',return_value=(True,reason)), \
                 patch.object(run_all,'run_one') as run:
                run_all.merchant_priority_checkpoint(self.data,{},{},set(),datetime(2026,10,26,19))
                run.assert_not_called()
    def test_disabled_does_not_run(self):
        self.data['skills'][0]['enabled']=False
        with patch.object(run_all,'run_one') as run:
            run_all.merchant_priority_checkpoint(self.data,{},{},set())
            run.assert_not_called()


if __name__=='__main__':unittest.main()
