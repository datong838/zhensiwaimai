import copy
import hashlib
import json
import sys
import tempfile
import time
import unittest
from contextlib import contextmanager
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from contract import Rejected, check_grant, event_key, normalize, request_digest
from ledger import event_lock, read_json
from executor import deliver, freeze_item
from evidence import file_frame_matches, image_distance, recovery_decision, retryable_preflight, text_proof


def sample():
    return {'schemaVersion':1,'groupName':'臻肆测试群',
            'items':[{'itemId':'one','type':'text','text':'测试正文\n第二行'}],
            'context':{'workflowId':'test','eventId':'event-one','accountAlias':'main',
                       'channel':'desktop','deadlineAt':time.time()+120}}


def grant(request):
    return {'schemaVersion':1,'requestDigest':request_digest(request),
            'accountAlias':request['context']['accountAlias'],'groupName':request['groupName'],
            'channel':request['context']['channel'],'expiresAt':time.time()+120,
            'authorizationRef':'unit-test-fixture-never-live'}


class Fake:
    channel='desktop';supported={'text','image','file'}
    def __init__(self, outcomes=None):
        self.sent=[]; self.opened=0; self.outcomes=outcomes or []
    @contextmanager
    def session(self,request):
        self.opened+=1;yield
    def preflight(self,request,output):
        return {'ok':True}
    def send_one(self,request,item,work,authorization,deadline):
        self.sent.append(item['itemId'])
        value=self.outcomes.pop(0) if self.outcomes else {'status':'verified','sendAttempts':1}
        if isinstance(value,BaseException):raise value
        return value
    def reconcile(self,request,item,work,prior):
        return {'status':'unknown','sendAttempts':0}


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.r=normalize(sample());self.g=grant(self.r)
    def tearDown(self):self.tmp.cleanup()
    def run_delivery(self,adapter=None,reconcile=False):
        adapter=adapter or Fake()
        return deliver(self.r,self.g,self.root,adapter,reconcile=reconcile),adapter
    def test_real_engine_idempotent(self):
        a=Fake();first,_=self.run_delivery(a);again,_=self.run_delivery(a)
        self.assertEqual(first['status'],'verified');self.assertEqual(again['status'],'already_verified')
        self.assertEqual(a.sent,['one']);self.assertEqual(a.opened,1)
        self.assertEqual(first['reviewSummary']['result'],'verified')
        self.assertGreaterEqual(first['reviewSummary']['totalElapsedMs'],0)
        self.assertEqual(first['reviewSummary']['stageCount'],len(first['review']))
    def test_unknown_never_resends(self):
        a=Fake([{'status':'unknown','sendAttempts':1}]);self.run_delivery(a);again,_=self.run_delivery(a)
        self.assertEqual(again['status'],'unknown');self.assertEqual(a.sent,['one']);self.assertEqual(a.opened,1)
        self.assertTrue(again['reviewSummary']['failedStages'])
    def test_crash_never_resends(self):
        a=Fake([TimeoutError('lost response')]);first,_=self.run_delivery(a);self.run_delivery(a)
        self.assertEqual(first['status'],'unknown');self.assertEqual(a.sent,['one'])
    def test_interrupt_is_durable(self):
        a=Fake([KeyboardInterrupt()])
        with self.assertRaises(KeyboardInterrupt):self.run_delivery(a)
        result,_=self.run_delivery(a);self.assertEqual(result['status'],'unknown');self.assertEqual(a.sent,['one'])
    def test_partial_stops_remaining(self):
        raw=sample();raw['items'] += [{'itemId':n,'type':'text','text':n} for n in ('two','three')]
        self.r=normalize(raw);self.g=grant(self.r)
        a=Fake([{'status':'verified','sendAttempts':1},{'status':'unknown','sendAttempts':1}])
        result,_=self.run_delivery(a);self.assertEqual(result['status'],'partial');self.assertEqual(a.sent,['one','two'])
    def test_payload_change_same_event_rejected(self):
        self.run_delivery();self.r['items'][0]['text']='different';self.r['items'][0]['sha256']='f'*64;self.g=grant(self.r)
        r,a=self.run_delivery();self.assertEqual(r['status'],'blocked');self.assertFalse(a.sent);self.assertEqual(a.opened,0)
    def test_different_event_may_repeat(self):
        a=Fake();self.run_delivery(a);self.r['context']['eventId']='two';self.g=grant(self.r);self.run_delivery(a)
        self.assertEqual(len(a.sent),2)
    def test_cross_channel_event_identity(self):
        other=copy.deepcopy(self.r);other['context']['channel']='mobile'
        self.assertEqual(event_key(self.r),event_key(other))
    def test_filename_path_movement_same_digest(self):
        a=self.root/'a';b=self.root/'b';a.mkdir();b.mkdir()
        (a/'report.xlsx').write_bytes(b'same');(b/'report.xlsx').write_bytes(b'same')
        raw=sample();raw['items']=[{'itemId':'one','type':'file','path':str(a/'report.xlsx')}]
        first=normalize(raw);raw['items'][0]['path']=str(b/'report.xlsx');second=normalize(raw)
        self.assertEqual(request_digest(first),request_digest(second))
    def test_whole_batch_unsupported_before_ui(self):
        self.r['items'].append({'itemId':'video','type':'video','path':'unused','sha256':'a'})
        self.g=grant(self.r);r,a=self.run_delivery();self.assertFalse(a.sent);self.assertEqual(a.opened,0)
    def test_wrong_grant_before_ui(self):
        self.g['groupName']='别的群';r,a=self.run_delivery();self.assertEqual(a.opened,0);self.assertFalse(a.sent)
    def test_expired_before_ui(self):
        self.g['expiresAt']=time.time()-1;r,a=self.run_delivery();self.assertEqual(a.opened,0)
    def test_reconcile_cannot_send(self):
        a=Fake([{'status':'unknown','sendAttempts':1}]);self.run_delivery(a);self.run_delivery(a,reconcile=True)
        self.assertEqual(a.sent,['one'])
    def test_reconcile_preserves_original_transport_proof(self):
        a=Fake([{'status':'unknown','sendAttempts':1,'transport':{'original':'evidence'}}])
        self.run_delivery(a);self.run_delivery(a,reconcile=True)
        records=list((self.root/'events').glob('*/*/delivery.json'))
        self.assertEqual(read_json(records[0])['transport'],{'original':'evidence'})
    def test_verified_reconcile_clears_stale_failure_reason(self):
        a=Fake([{'status':'unknown','sendAttempts':1,'reason':'old-failure'}]);self.run_delivery(a)
        a.reconcile=lambda *args:{'status':'verified','sendAttempts':0,'reconciled':True}
        result,_=self.run_delivery(a,reconcile=True)
        self.assertTrue(result['ok']);self.assertNotIn('reason',result['items'][0])
    def test_deadline_interrupt_retains_attempt(self):
        self.r['context']['deadlineAt']=time.time()+.05;self.g=grant(self.r)
        a=Fake()
        def slow(*_):
            a.sent.append('one');time.sleep(.5)
        a.send_one=slow
        r,_=self.run_delivery(a)
        self.assertEqual(r['status'],'unknown')
        self.assertEqual(len(a.sent),1)
    def test_event_lock_conflict(self):
        with event_lock(self.root,self.r):
            with self.assertRaises(Rejected):
                with event_lock(self.root,self.r):pass
    def test_freeze_detects_content_changed(self):
        p=self.root/'file';p.write_bytes(b'old')
        item={'type':'file','path':str(p),'name':'file','sha256':hashlib.sha256(b'old').hexdigest(),'size':3}
        p.write_bytes(b'new')
        with self.assertRaises(Rejected):freeze_item(item,self.root/'work')
    def test_duplicate_item_rejected(self):
        raw=sample();raw['items']*=2
        with self.assertRaises(Rejected):normalize(raw)
    def test_unknown_fields_rejected(self):
        raw=sample();raw['senderCommand']='arbitrary'
        with self.assertRaises(Rejected):normalize(raw)
    def test_optional_search_group_is_bound_and_validated(self):
        raw=sample();raw['context']['searchGroupName']='上海臻肆外卖运营-盯个盯-饭敢当'
        value=normalize(raw)
        self.assertEqual(value['context']['searchGroupName'],raw['context']['searchGroupName'])
        raw['context']['searchGroupName']='错误\n群名'
        with self.assertRaisesRegex(Rejected,'search-group-invalid'):normalize(raw)
    def test_empty_rejected(self):
        raw=sample();raw['items']=[]
        with self.assertRaises(Rejected):normalize(raw)
    def test_nonfinite_deadline_rejected(self):
        raw=sample();raw['context']['deadlineAt']=float('nan')
        with self.assertRaises(Rejected):normalize(raw)
    def test_grant_content_bound(self):
        self.r['items'][0]['text']='changed'
        with self.assertRaises(Rejected):check_grant(self.r,self.g)
    def test_evidence_file_requires_full_name(self):
        self.assertTrue(file_frame_matches('日报.xlsx 1.0KB','日报.xlsx',1024))
        for value in ('日报 1.0KB','日报.xlsx 2.0KB','日报.xlsx 1.0KB发送中','日报.xlsx 1.0KB发送失败'):
            self.assertFalse(file_frame_matches(value,'日报.xlsx',1024))
    def test_retry_whitelist_and_any_ambiguity(self):
        self.assertTrue(retryable_preflight({'sendAttempts':0,'reason':'wechat-search-region-contended'}))
        for reason in ('exact-group-result-count:4','random-failure','blocked-login','desktop-chat-input-not-empty'):
            self.assertFalse(retryable_preflight({'sendAttempts':0,'reason':reason}))
        self.assertFalse(retryable_preflight({'sendAttempts':1,'reason':'wechat-search-region-contended'}))
    def test_restart_never_after_attempt(self):
        self.assertEqual(recovery_decision(component='wechat-app',attempted=True,authorized=True,other_draft=False,lock_held=True,used=0),'reconcile-only')
    def test_copy_requires_exact_hash_and_stability(self):
        item=self.r['items'][0];p={'ok':True,'composerEmpty':True,'copyMenuCount':1,'copiedTextSha256':item['sha256'],'bubblePositions':[[1,2],[2,3]]}
        self.assertTrue(text_proof(item,p));p['copiedTextSha256']='wrong';self.assertFalse(text_proof(item,p))
    def test_image_discriminates(self):
        from PIL import Image,ImageDraw
        a=Image.new('RGB',(100,100),'white');ImageDraw.Draw(a).rectangle((0,0,40,100),fill='black')
        b=Image.new('RGB',(100,100),'white');ImageDraw.Draw(b).rectangle((60,0,100,100),fill='black')
        self.assertEqual(image_distance(a,a),0);self.assertGreater(image_distance(a,b),8)
        self.assertEqual(image_distance(Image.new('RGB',(100,100),'white'),Image.new('RGB',(100,100),'white')),float('inf'))

if __name__=='__main__':unittest.main()
