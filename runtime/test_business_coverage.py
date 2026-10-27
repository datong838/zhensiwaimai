import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from business_coverage import assess_receipt, read_daily_coverage

DAY = '2026-10-27'
FLOW = 'daily-new-stores-activity-audit-to-wechat'


class CoverageTests(unittest.TestCase):
    def payload(self, status='verified', reason=''):
        return {'day': DAY, 'status': 'complete', 'targetCount': 1,
                'shops': [{'sourceName': '目标门店', 'status': status, 'reason': reason}]}

    def test_not_found_timeout_and_busy_are_not_completed(self):
        for reason in ['shop-not-found:未搜索到店铺', 'shop-search-timeout', 'post-lease-busy']:
            with self.subTest(reason=reason):
                self.assertFalse(assess_receipt(self.payload('skipped', 'activity-collection-skipped:' + reason), DAY)['complete'])

    def test_complete_and_zero_target_receipts(self):
        self.assertTrue(assess_receipt(self.payload(), DAY)['complete'])
        self.assertTrue(assess_receipt({'day': DAY, 'status': 'complete', 'targetCount': 0, 'shops': []}, DAY)['complete'])

    def test_existing_non_operating_exception_is_retained(self):
        self.assertTrue(assess_receipt(self.payload('skipped', 'activity-collection-skipped:shop-not-operating:暂停营业'), DAY)['complete'])

    def test_historical_days_keep_their_original_interpretation(self):
        self.assertIsNone(read_daily_coverage(FLOW,'2026-10-26'))

    def test_missing_duplicate_wrong_day_and_ready_do_not_pass(self):
        self.assertFalse(assess_receipt({**self.payload(), 'targetCount': 2}, DAY)['complete'])
        self.assertFalse(assess_receipt(self.payload(), '2026-10-28')['complete'])
        self.assertFalse(assess_receipt(self.payload('ready'), DAY)['complete'])
        payload=self.payload();payload['shops']*=2;payload['targetCount']=2
        self.assertFalse(assess_receipt(payload, DAY)['complete'])

    def test_only_same_flow_same_day_bound_history_can_prove_coverage(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);folder=root/'runtime/run_history'/DAY;folder.mkdir(parents=True)
            log=folder/(FLOW+'--20261027-110000--a1--s1.log');log.write_text(json.dumps(self.payload()))
            record={'skill': FLOW,'started_at': DAY+'T11:00:00','finished_at': DAY+'T11:00:10','logs':[str(log)],'status':'SUCCESS'}
            source=folder/(FLOW+'--20261027-110000--record.json');source.write_text(json.dumps(record))
            self.assertTrue(read_daily_coverage(FLOW,DAY,root)['complete'])
            record['logs']=[str(root/'outside.log')];(root/'outside.log').write_text(log.read_text());source.write_text(json.dumps(record))
            self.assertFalse(read_daily_coverage(FLOW,DAY,root)['complete'])

    def test_success_record_is_not_rewritten_when_customer_row_is_incomplete(self):
        import run_all
        record={'category':'SUCCESS','status':'SUCCESS','finished_at':DAY+'T11:00:10'}
        before=dict(record)
        data={'skills':[{'name':FLOW,'enabled':True,'schedule':'每日11:00'}],
              'ledger_template':[{'row':1,'skill':FLOW,'ledger_name':'活动巡检','schedule':'每日11:00','dev_state':'active'}]}
        with patch('business_coverage.read_daily_coverage',return_value={'complete':False,'reason':'1家门店未检查'}):
            rows=run_all.build_ledger_rows(data,{FLOW:record})
        self.assertEqual(rows[0]['done'],'否')
        self.assertEqual(record,before)


if __name__ == '__main__':
    unittest.main()
