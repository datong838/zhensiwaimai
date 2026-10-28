import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from registered_ui_routes import allowed,WORKFLOWS
from workflow_bridge import REGISTRY
from wecom_adapter import WeComAdapter
class RegisteredRoutes(unittest.TestCase):
    def requests(self):
        for workflow in sorted(WORKFLOWS):
            group,kind,count,_,ledger=REGISTRY[workflow]
            number=count[0] if isinstance(count,tuple) else count
            yield {'groupName':group,'context':{'workflowId':workflow,'eventId':str(ledger.resolve()/'test-only.json')},'items':[{'type':kind,'path':f'/fixture/{i}'+('.png' if kind=='image' else '.xlsx')} for i in range(number)]}
    def test_registered_scope(self):
        for request in self.requests():self.assertTrue(allowed(request))
    def test_wrong_group_count_kind_event_rejected(self):
        for original in self.requests():
            for change in [{'groupName':'wrong'},{'items':[]},{'context':original['context']|{'eventId':'/tmp/test-only.json'}}]:self.assertFalse(allowed(original|change))
            request=copy.deepcopy(original);request['items'][0]['type']='text';self.assertFalse(allowed(request))
    def test_evidence_one_or_two_only(self):
        request=next(r for r in self.requests() if r['context']['workflowId']=='taobao-evidence')
        self.assertTrue(allowed(request|{'items':request['items']*2}))
        self.assertFalse(allowed(request|{'items':request['items']*3}))
    def test_repair_scope_not_opened(self):
        for workflow in ['jinsha-reports-taobao-repair-20261023','unregistered']:
            self.assertFalse(allowed({'context':{'workflowId':workflow}}))
    def test_summary_cannot_reuse_excel_ledger(self):
        requests = {r['context']['workflowId']: r for r in self.requests()}
        for workflow in ('taobao-flash-appeals', 'meituan-waimai-appeals'):
            request = copy.deepcopy(requests[workflow + '-summary'])
            request['context']['eventId'] = requests[workflow]['context']['eventId']
            self.assertFalse(allowed(request))
    def test_negative_review_summary_uses_full_registered_contract(self):
        request=next(r for r in self.requests() if r['context']['workflowId']=='negative-reviews-summary')
        self.assertTrue(allowed(request))
        for change in ({'groupName':'wrong'}, {'items':[]},
                       {'context':request['context']|{'eventId':'/tmp/wrong-ledger.json'}}):
            self.assertFalse(allowed(request|change))
    def test_adapter_preflight_uses_ui_only(self):
        for request in self.requests():
            with patch('wecom_ui_queue.exchange',return_value={'ok':True,'resolvedGroup':request['groupName'],'inputEmpty':True}) as queue,patch.object(WeComAdapter,'_run_sender',side_effect=AssertionError('legacy')):
                self.assertTrue(WeComAdapter().preflight(request,'unused')['ok']);queue.assert_called_once()
if __name__=='__main__':unittest.main()
