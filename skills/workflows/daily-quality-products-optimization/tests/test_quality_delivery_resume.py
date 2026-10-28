import copy
import hashlib
import json
import os
import unittest
import uuid
from unittest.mock import patch
import test_quality_workflow as baseline

w=baseline.w

class NativeFixtureAdapter(baseline.Adapter):
    def __init__(self,queue,*,blocked_at=0,intent=False,count=0):
        super().__init__();self.queue=queue;self.blocked_at=blocked_at;self.intent=intent;self.count=count;self.blocked=False
    def send_one(self,request,item,*args):
        index=len(self.calls);self.calls.append(copy.deepcopy(item))
        if not self.blocked and index==self.blocked_at:
            self.blocked=True
            result={'status':'blocked','sendAttempts':self.count,'resolvedGroup':w.GROUP,'sha256':item['sha256'],
                    'backend':'system-events-ui-tree','reason':'isolated-before-submit','inputEmpty':True}
            name=str(uuid.uuid4());folder=self.queue/name;folder.mkdir(parents=True)
            task={'taskId':name,'stage':'send','lifetime':'owner-process','owner':{'pid':os.getpid()},
                  'request':copy.deepcopy(request),'item':copy.deepcopy(item)}
            task['binding']=hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            (folder/'task.json').write_text(json.dumps(task));(folder/'response.json').write_text(json.dumps({'taskId':name,'binding':task['binding'],'result':result}))
            (folder/'claim.json').write_text(json.dumps({'worker':'native-system-ui-post'}))
            if self.intent:(folder/'send-intent.json').write_text('{}')
            return result
        frame={'groupName':w.GROUP,'inputEmpty':True,'newMessageVisible':True}
        if item['type']=='file':frame.update(visibleFileName=item['name'],visibleFileSize='0K')
        else:frame.update(visibleTextSha256=item['sha256'],visibleText=item['text'])
        return {'status':'verified','sendAttempts':1,'resolvedGroup':w.GROUP,'sha256':item['sha256'],
                'observations':[dict(frame),dict(frame)]}

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.f=baseline.Tests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.queue=self.f.root/'native-queue';self.queue.mkdir()
        patcher=patch.object(w,'QUEUE',self.queue);patcher.start();self.addCleanup(patcher.stop)
    def run_flow(self,adapter):return self.f.run_flow(adapter)
    def marker(self):return json.loads((self.f.folder/'delivery.json').read_text())
    def test_proven_zero_first_item_resumes_same_frozen_request_without_optimizer_or_export(self):
        a=NativeFixtureAdapter(self.queue);self.assertFalse(self.run_flow(a)['ok']);old=self.marker();self.assertEqual(old['state'],'blocked')
        frozen=(self.f.folder/'request.json').read_bytes();queue_before={str(p):p.read_bytes() for p in self.queue.rglob('*') if p.is_file()}
        with patch.object(self.f,'export',side_effect=AssertionError('must not rebuild')):
            self.assertTrue(self.run_flow(a)['ok'])
        self.assertEqual(self.f.optimizer.call_count,1);self.assertEqual(len(a.calls),3);self.assertEqual((self.f.folder/'request.json').read_bytes(),frozen)
        self.assertEqual(queue_before,{str(p):p.read_bytes() for p in self.queue.rglob('*') if p.is_file()});self.assertEqual(self.marker()['state'],'verified')
    def test_verified_excel_is_not_resent_when_only_text_was_zero_blocked(self):
        a=NativeFixtureAdapter(self.queue,blocked_at=1);self.assertFalse(self.run_flow(a)['ok']);before=self.marker();self.assertEqual(before['state'],'blocked')
        file_receipt=before['deliveries'][0];resumed=self.run_flow(a);self.assertTrue(resumed['ok']);self.assertEqual(resumed['newSendAttempts'],1);self.assertEqual(resumed['sendAttempts'],2)
        self.assertEqual([x['type'] for x in a.calls],['file','text','text']);self.assertEqual(self.marker()['deliveries'][0],file_receipt)
        self.assertEqual(self.f.optimizer.call_count,1)
    def test_existing_unknown_is_never_reclassified_or_resumed_even_with_zero_proof(self):
        a=NativeFixtureAdapter(self.queue);self.run_flow(a);m=self.marker();m['state']='unknown';p=self.f.folder/'delivery.json';p.write_text(json.dumps(m));raw=p.read_bytes()
        self.assertEqual(self.run_flow(a)['status'],'unknown');self.assertEqual(len(a.calls),1);self.assertEqual(p.read_bytes(),raw)
    def test_existing_attempted_stays_read_only(self):
        a=NativeFixtureAdapter(self.queue);self.run_flow(a);m=self.marker();m['state']='attempted';p=self.f.folder/'delivery.json';p.write_text(json.dumps(m));raw=p.read_bytes()
        self.assertEqual(self.run_flow(a)['status'],'unknown');self.assertEqual(len(a.calls),1);self.assertEqual(p.read_bytes(),raw)
    def test_zero_count_without_native_proof_remains_unknown(self):
        class Unproven(baseline.Adapter):
            def send_one(self,request,item,*args):self.calls.append(item);return {'status':'blocked','sendAttempts':0}
        a=Unproven();self.run_flow(a);self.assertEqual(self.marker()['state'],'unknown');self.run_flow(a);self.assertEqual(len(a.calls),1)
    def test_any_native_send_intent_excludes_zero_recovery(self):
        a=NativeFixtureAdapter(self.queue,intent=True);self.run_flow(a);self.assertEqual(self.marker()['state'],'unknown');self.run_flow(a);self.assertEqual(len(a.calls),1)
    def test_boolean_or_missing_count_is_not_integer_zero(self):
        for count in [False,None,1]:
            a=NativeFixtureAdapter(self.queue,count=count)
            self.run_flow(a);self.assertEqual(self.marker()['state'],'unknown')
            (self.f.folder/'delivery.json').unlink()
    def test_changed_frozen_request_is_rejected_before_any_new_attempt(self):
        a=NativeFixtureAdapter(self.queue);self.run_flow(a);p=self.f.folder/'request.json';r=json.loads(p.read_text());r['groupName']='other';p.write_text(json.dumps(r))
        with self.assertRaisesRegex(ValueError,'frozen-source-changed'):self.run_flow(a)
        self.assertEqual(len(a.calls),1);self.assertEqual(self.f.optimizer.call_count,1)
    def test_native_response_or_intent_drift_cannot_authorize_resume(self):
        a=NativeFixtureAdapter(self.queue);self.run_flow(a);p=next(self.queue.glob('*/task.json')).parent
        (p/'response.json').write_text('{}')
        with self.assertRaises(ValueError):self.run_flow(a)
        self.assertEqual(len(a.calls),1)
    def test_native_intent_created_after_zero_proof_still_prevents_resume(self):
        a=NativeFixtureAdapter(self.queue);self.run_flow(a);p=next(self.queue.glob('*/task.json')).parent
        (p/'send-intent.json').write_text('{}')
        with self.assertRaises(ValueError):self.run_flow(a)
        self.assertEqual(len(a.calls),1)
    def test_changed_frozen_excel_is_not_rebuilt_or_resent(self):
        a=NativeFixtureAdapter(self.queue,blocked_at=1);self.run_flow(a);report=json.loads((self.f.folder/'report.json').read_text());baseline.Path(report['file']).write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'frozen-report-binding-invalid'):self.run_flow(a)
        self.assertEqual(len(a.calls),2);self.assertEqual(self.f.optimizer.call_count,1)
    def test_weak_verified_prefix_cannot_skip_excel_or_authorize_text(self):
        a=NativeFixtureAdapter(self.queue,blocked_at=1);self.run_flow(a);p=self.f.folder/'delivery.json';m=self.marker()
        m['deliveries'][0]['receipt']['observations'][0]['groupName']='other';p.write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'evidence-invalid'):self.run_flow(a)
        self.assertEqual(len(a.calls),2)
    def test_zero_proof_wrong_claim_is_not_a_recovery_contract(self):
        a=NativeFixtureAdapter(self.queue);self.run_flow(a);p=next(self.queue.glob('*/task.json')).parent
        (p/'claim.json').write_text(json.dumps({'worker':'other-worker'}))
        with self.assertRaisesRegex(ValueError,'claim-invalid'):self.run_flow(a)
        self.assertEqual(len(a.calls),1)
    def test_multiple_matching_new_tasks_remain_unknown(self):
        class Ambiguous(NativeFixtureAdapter):
            def send_one(self,request,item,*args):
                result=super().send_one(request,item,*args)
                original=next(self.queue.glob('*/task.json'));task=json.loads(original.read_text());task.pop('binding')
                task['taskId']=str(uuid.uuid4());task['binding']=hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
                folder=self.queue/task['taskId'];folder.mkdir();(folder/'task.json').write_text(json.dumps(task));(folder/'response.json').write_text(json.dumps({'taskId':task['taskId'],'binding':task['binding'],'result':result}));return result
        a=Ambiguous(self.queue);self.run_flow(a);self.assertEqual(self.marker()['state'],'unknown')
        self.run_flow(a);self.assertEqual(len(a.calls),1)
    def test_wrong_event_is_rejected_even_if_request_file_hash_was_rebound(self):
        a=NativeFixtureAdapter(self.queue);self.run_flow(a);p=self.f.folder/'request.json';request=json.loads(p.read_text())
        request['context']['eventId']='2026-10-25-quality-optimization-completed';p.write_text(json.dumps(request))
        m=self.marker();m['requestSha256']=hashlib.sha256(p.read_bytes()).hexdigest();(self.f.folder/'delivery.json').write_text(json.dumps(m))
        with self.assertRaisesRegex(ValueError,'request-scope'):self.run_flow(a)
        self.assertEqual(len(a.calls),1)
    def test_prior_day_unknown_never_blocks_a_new_day_or_changes_old_evidence(self):
        a=NativeFixtureAdapter(self.queue,intent=True);self.run_flow(a);p=self.f.folder/'delivery.json';before=p.read_bytes()
        self.f.optimizer.return_value={'ok':False,'continuation':False,'summary':{'pending':1}}
        with patch.object(w,'day_now',return_value='2026-10-27'):
            result=self.run_flow(a)
        self.assertFalse(result['ok']);self.assertEqual(self.f.optimizer.call_count,2);self.assertEqual(len(a.calls),1)
        self.assertEqual(p.read_bytes(),before);self.assertFalse((self.f.state/'days/2026-10-27/delivery.json').exists())
    def test_local_queue_inventory_failure_does_not_create_attempted_marker(self):
        a=NativeFixtureAdapter(self.queue)
        with patch.object(w,'queue_names',side_effect=OSError('local-read-failure')):
            with self.assertRaisesRegex(OSError,'local-read-failure'):self.run_flow(a)
        self.assertEqual(a.calls,[]);self.assertFalse((self.f.folder/'delivery.json').exists())

if __name__=='__main__':unittest.main()
