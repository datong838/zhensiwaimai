import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import daily_progress as progress

class LatestSlotTests(unittest.TestCase):
    def row(self, now, success, fixed=True):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skill = {'name':'example','dev_state':'active','enabled':True,'earliest_hour':13}
            if fixed:
                skill['schedule_times'] = ['13:00','15:00','17:00','18:30']
            (root/'manifest.json').write_text(json.dumps({'skills':[skill]}))
            (root/'last_success.json').write_text(json.dumps({'example':success}))
            with patch.object(progress,'MANIFEST',root/'manifest.json'), patch.object(progress,'STATE',root), patch.object(progress,'RUN_HISTORY',root):
                return progress.build(dt.datetime.fromisoformat(now))['rows'][0]
    def test_old_success_does_not_cover_later_slots(self):
        for hour in ['15:00','17:00','18:55']:
            row=self.row('2026-10-24T'+hour,'2026-10-24T13:10:00')
            self.assertTrue(row['due']); self.assertFalse(row['done'])
    def test_current_slot_success(self):
        self.assertTrue(self.row('2026-10-24T18:55','2026-10-24T18:31:00')['done'])
    def test_before_first_slot(self):
        row=self.row('2026-10-24T12:55','2026-10-24T12:30:00')
        self.assertFalse(row['done']);self.assertFalse(row['due'])
    def test_single_slot_behavior_preserved(self):
        self.assertTrue(self.row('2026-10-24T18:55','2026-10-24T13:10:00',False)['done'])

    def test_bound_same_day_business_acceptance_is_read_only_completion(self):
        import business_delivery_facts
        with patch.object(business_delivery_facts, 'read_fact', return_value={'businessDelivered': True}):
            row=self.row('2026-10-24T18:55',None,False)
        self.assertTrue(row['done'])
        self.assertEqual(row['state'],'已完成·业务送达已核对')
        self.assertEqual(row['last_success'],'')

    def test_absent_acceptance_preserves_unfinished_and_future_slot(self):
        import business_delivery_facts
        with patch.object(business_delivery_facts, 'read_fact', return_value=None):
            self.assertFalse(self.row('2026-10-24T18:55',None)['done'])
            self.assertFalse(self.row('2026-10-24T12:55',None)['done'])

    def test_coverage_gap_still_blocks_acceptance(self):
        import business_delivery_facts, business_coverage
        with patch.object(business_delivery_facts, 'read_fact', return_value={'businessDelivered': True}), \
             patch.object(business_coverage, 'read_daily_coverage', return_value={'complete':False,'reason':'missing shop'}):
            row=self.row('2026-10-24T18:55',None,False)
        self.assertFalse(row['done'])
        self.assertEqual(row['reason'],'missing shop')

    def test_prior_day_acceptance_does_not_cover_new_day(self):
        import business_delivery_facts
        def accepted(name,now):
            return {'businessDelivered':True} if now.date().isoformat()=='2026-10-24' else None
        with patch.object(business_delivery_facts, 'read_fact', side_effect=accepted):
            self.assertTrue(self.row('2026-10-24T18:55',None,False)['done'])
            self.assertFalse(self.row('2026-10-25T18:55',None,False)['done'])

    def test_remote_summary_scope_never_changes_local_completion(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            skill = {'name':'example','dev_state':'active','enabled':True,'earliest_hour':13}
            (root/'manifest.json').write_text(json.dumps({'skills':[skill]}))
            (root/'last_success.json').write_text(json.dumps({'example':'2026-10-29T13:10:00'}))
            remote = {
                'business_date':'2026-10-29','effective':True,'global_total':27,
                'local_ledger_identities':24,'remote_flow_count':3,'remote_done':0,
                'remote_state':'missing_nonblocking','nonblocking_local_execution':True,
                'source':'','errors':[],'rows':[]}
            with patch.object(progress,'MANIFEST',root/'manifest.json'), \
                 patch.object(progress,'STATE',root), patch.object(progress,'RUN_HISTORY',root), \
                 patch('remote_flow_summary.read_customer_scope', return_value=remote):
                result = progress.build(dt.datetime.fromisoformat('2026-10-29T18:55:00'))
        self.assertTrue(result['all_green'])
        self.assertEqual(result['total_active'],1)
        self.assertEqual(result['customer_scope']['global_total'],27)

if __name__=='__main__': unittest.main()
