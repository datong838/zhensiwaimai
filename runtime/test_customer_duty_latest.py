import unittest
from datetime import datetime
from unittest.mock import patch
import fixed_schedule as fixed
import run_all
import daily_progress

class CustomerDutyTests(unittest.TestCase):
    def at(self, clock):
        return datetime.fromisoformat('2026-10-24T' + clock + ':00')

    def test_slot_boundaries(self):
        for clock, old in [('11:59', []), ('12:00', []), ('14:59', []),
                           ('15:00', [12]), ('16:59', [12]), ('17:00', [12, 15])]:
            for name, hour in fixed.CUSTOMER_DUTY_HOURS.items():
                with self.subTest(clock=clock, name=name):
                    self.assertEqual(fixed.customer_slot_superseded(name, self.at(clock)), hour in old)
        self.assertFalse(fixed.customer_slot_superseded('other-flow', self.at('18:00')))

    def test_original_gate_and_manual_entry_reject_old_slot(self):
        skill = {'name':'meituan-intelligent-customer-service-12', 'steps':[{'cmd':['never']}],
                 'earliest_hour':12, 'cadence_hours':24}
        self.assertEqual(run_all._cadence_gate(skill, self.at('17:10')), (True, 'superseded_customer_slot'))
        with patch.object(run_all, 'datetime') as clock, patch.object(run_all.sr, 'run_skill') as execute:
            clock.now.return_value = self.at('17:10')
            result = run_all.run_one({'skills':[skill]}, skill['name'], {})
            self.assertEqual(result['status'], 'SKIPPED_SUPERSEDED')
            execute.assert_not_called()

    def test_final_slot_needs_own_real_success(self):
        final = 'meituan-intelligent-customer-service'
        for value in [None, '', 'bad', '2026-10-23T17:20:00', '2026-10-24T09:51:00',
                      '2026-10-24T16:46:00']:
            self.assertFalse(fixed.customer_success_in_slot(final, value, self.at('18:00')))
        self.assertTrue(fixed.customer_success_in_slot(final, '2026-10-24T17:35:00', self.at('18:00')))
        self.assertTrue(fixed.customer_success_in_slot('other-flow', None, self.at('18:00')))

    def test_ledger_retains_history_without_counting_old_slot(self):
        name = 'meituan-intelligent-customer-service-12'
        data = {'skills':[{'name':name}], 'ledger_template':[{'skill':name,'row':1,
                'ledger_name':'customer','schedule':'12:00','dev_state':'active'}]}
        with patch.object(run_all, 'datetime') as clock:
            clock.now.return_value = self.at('17:10')
            rows = run_all.build_ledger_rows(data, {})
        self.assertTrue(rows[0]['superseded'])
        self.assertEqual(rows[0]['done'], '不补跑')

    def test_progress_uses_final_slot_without_faking_old_success(self):
        skills=[{'name':name,'earliest_hour':hour,'enabled':True,'dev_state':'active'}
                for name,hour in fixed.CUSTOMER_DUTY_HOURS.items()]
        def load(path, default):
            if path == daily_progress.MANIFEST:
                return {'skills':skills}
            if path.name == 'last_success.json':
                return {'meituan-intelligent-customer-service':'2026-10-24T17:35:00'}
            return default
        with patch.object(daily_progress,'_load',side_effect=load), \
             patch.object(daily_progress,'_latest_record',return_value=None):
            result=daily_progress.build(self.at('18:00'))
        self.assertEqual((result['done'],result['total_active']),(1,1))
        self.assertTrue(result['all_green'])
        old=[row for row in result['rows'] if row['superseded']]
        self.assertEqual(len(old),2)
        self.assertTrue(all(not row['done'] for row in old))
        self.assertNotIn('未完成跟进',daily_progress.render_md(result))

if __name__ == '__main__':
    unittest.main()
