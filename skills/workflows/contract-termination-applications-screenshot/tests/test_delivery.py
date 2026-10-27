import contextlib
import importlib.util
import io
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
PENDING={'status':'unknown','sendAttempts':1,'resolvedGroup':subject.GROUP,'inputEmpty':True,
         'backend':'system-events-ui-tree','reason':'native-ui-inline-image-not-exposed'}
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
    def test_submitted_pending_images_continue_only_unattempted_pages(self):
        adapter=Adapter([PENDING,PENDING,OK]);adapter.owner_lifetime=True
        result=self.execute(self.images,adapter)
        self.assertEqual(result['status'],'unknown');self.assertEqual(result['sendAttempts'],3)
        self.assertTrue(result['executionComplete'])
        self.assertEqual(result['verificationPending'],['contract-termination-p1','contract-termination-p2'])
        self.assertEqual(len(adapter.calls),3);self.assertEqual(self.marker()['state'],'unknown')
        before=next(self.events.glob('*.json')).read_bytes()
        self.assertEqual(self.execute(self.images,adapter)['status'],'unknown')
        self.assertEqual(len(adapter.calls),3);self.assertEqual(before,next(self.events.glob('*.json')).read_bytes())
    def test_unsafe_unknown_never_allows_next_page(self):
        for change in ({'resolvedGroup':'wrong'},{'inputEmpty':False},{'sendAttempts':0},
                       {'sendAttempts':2},{'sendAttempts':True},{'backend':'other'},
                       {'reason':'timeout'},{'status':'blocked'}):
            with self.subTest(change=change):
                for p in self.events.glob('*.json'):p.unlink()
                adapter=Adapter([PENDING|change,OK]);adapter.owner_lifetime=True
                result=self.execute(self.images[:2],adapter)
                self.assertEqual(result['status'],'unknown');self.assertEqual(len(adapter.calls),1)
                self.assertFalse(result.get('executionComplete',False))
    def test_pending_requires_current_native_owner(self):
        adapter=Adapter([PENDING,OK])
        self.assertEqual(self.execute(self.images[:2],adapter)['status'],'unknown')
        self.assertEqual(len(adapter.calls),1)
    def pending_marker(self, day, **changes):
        data={'event':day+'-contract-termination-ops','state':'unknown','groupName':subject.GROUP,
              'sha256':'a'*64,'images':[day+'_合同解约申请_处理中_p1.png']}
        data.update(changes)
        path=self.events/(day+'-contract-termination-ops.json')
        path.write_text(json.dumps(data));return path
    def test_pending_main_never_collects_or_creates_run(self):
        day=subject.datetime.now(subject.LOCAL_TZ).date().isoformat()
        for state in ('attempted','unknown'):
            path=self.pending_marker(day,state=state);before=path.read_bytes()
            with patch.object(sys,'argv',['entry','--execute']), patch.object(subject,'shot') as shot, patch.object(subject,'deliver') as send, patch.object(subject,'RUNS',self.root/'new-runs'), contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaises(SystemExit) as caught:subject.main()
            self.assertEqual(caught.exception.code,1)
            self.assertEqual(json.loads(output.getvalue())['sendAttempts'],0)
            shot.assert_not_called();send.assert_not_called()
            self.assertFalse((self.root/'new-runs').exists());self.assertEqual(before,path.read_bytes())
    def test_pending_requires_exact_current_binding(self):
        day='2026-10-26'
        for change in ({'event':'old'},{'state':'verified'},{'groupName':'wrong'},
                       {'sha256':'bad'},{'images':[]},{'images':['2026-10-25_合同解约申请_处理中_p1.png']}):
            self.pending_marker(day,**change);self.assertIsNone(subject.pending_today(day))
        self.pending_marker(day);self.assertIsNone(subject.pending_today('2026-10-27'))
        (self.events/(day+'-contract-termination-ops.json')).write_text('{')
        self.assertIsNone(subject.pending_today(day))
    def test_capture_and_deliver_run_keep_original_paths(self):
        for args in ([],['--execute','--deliver-run',str(self.root)]):
            with patch.object(sys,'argv',['entry']+args), patch.object(subject,'pending_today') as guard, patch.object(subject,'shot',return_value={}) as shot, patch.object(subject,'RUNS',self.root/'runs'), patch.object(subject,'find_run_images',return_value=self.images[:1]), patch.object(subject,'deliver',return_value={'status':'verified'}) as send, contextlib.redirect_stdout(io.StringIO()):
                subject.main()
            guard.assert_not_called()
            if args:shot.assert_not_called();send.assert_called_once()
            else:shot.assert_called_once();send.assert_not_called()
if __name__=='__main__':unittest.main()
