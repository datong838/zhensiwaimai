import contextlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(ROOT/'runtime'))
sys.path.insert(0,str(ROOT/'skills/wechat-messaging/scripts'))
spec=importlib.util.spec_from_file_location('contract_delivery',Path(__file__).resolve().parents[1]/'scripts/contract_termination_workflow.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)
class Adapter:
    def __init__(self,outcomes):self.outcomes=iter(outcomes);self.calls=[]
    def session(self,request):return contextlib.nullcontext()
    def preflight(self,*args):return {'ok':True}
    def send_one(self,request,item,work,*args):
        self.calls.append((item,work));result=next(self.outcomes)
        if isinstance(result,Exception):raise result
        return result
OK={'status':'verified','sendAttempts':1,'verificationLevel':'test-only'}
class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.events=self.root/'events';self.events.mkdir()
        self.images=[]
        for i in range(3):
            p=self.root/f'p{i+1}.png';p.write_bytes(f'fixture{i}'.encode());self.images.append(str(p))
        for p in [patch.object(subject,'EVENTS',self.events),patch.object(subject,'arm_state',return_value={'armed':True}),patch('authorized_supplement.deliver_once',return_value=None),patch('wecom_adapter.target_preflight_verified',return_value=True)]:p.start();self.addCleanup(p.stop)
    def execute(self,images,adapter):
        with patch('wecom_adapter.WeComAdapter',return_value=adapter):
            return subject.deliver(images,self.root,'2026-10-25')
    def marker(self):return json.loads(next(self.events.glob('*.json')).read_text())
    def test_all_pages_required_and_ordered(self):
        adapter=Adapter([OK,OK]);result=self.execute(self.images[:2],adapter)
        self.assertEqual(result['status'],'verified');self.assertEqual(result['sendAttempts'],2)
        self.assertEqual([x[0]['itemId'] for x in adapter.calls],['contract-termination-p1','contract-termination-p2'])
        self.assertEqual([x[1].name for x in adapter.calls],['p1','p2'])
        self.assertEqual(len(self.marker()['pageReceipts']),2)
    def test_unknown_stops_remaining_pages_and_never_retries(self):
        adapter=Adapter([OK,{'status':'unknown','sendAttempts':1}])
        self.assertEqual(self.execute(self.images,adapter)['status'],'unknown')
        self.assertEqual(len(adapter.calls),2)
        self.assertEqual(self.execute(self.images,adapter)['status'],'unknown');self.assertEqual(len(adapter.calls),2)
    def test_exception_retains_completed_page_evidence(self):
        adapter=Adapter([OK,RuntimeError('lost response')])
        result=self.execute(self.images,adapter)
        self.assertEqual(result['status'],'unknown');self.assertIsNone(result['sendAttempts'])
        self.assertEqual(self.marker()['pageReceipts'][0]['result']['status'],'verified')
    def test_single_page_remains_compatible(self):
        result=self.execute(self.images[:1],Adapter([OK]))
        self.assertEqual(result['status'],'verified');self.assertEqual(result['sendAttempts'],1)
if __name__=='__main__':unittest.main()
