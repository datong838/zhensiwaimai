import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import business_delivery_facts as facts


class BusinessFactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        p=patch.object(facts,'ROOT',self.root);p.start();self.addCleanup(p.stop)
        self.now=datetime(2026,10,25,18,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.folder=self.root/'skills/wechat-messaging/.runtime/ui-post-queue/original-task'
        self.folder.mkdir(parents=True)
        self.audit=self.root/'runtime/state/delivery-audits/20261025-decoration-observed.json'
        self.audit.parent.mkdir(parents=True)
        self.text='合成装修提醒，仅离线测试'
        self.sha=hashlib.sha256(self.text.encode()).hexdigest()
        item={'type':'text','text':self.text,'sha256':self.sha}
        task={'taskId':'original-task','stage':'send','item':item,'request':{
            'groupName':facts.GROUP,'items':[item],'context':{
            'workflowId':'daily-new-stores-decoration-reminder',
            'eventId':'2026-10-25-taobao-123-decoration-reminder'}}}
        task['binding']=hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        frame={'groupName':facts.GROUP,'inputEmpty':True,'newMessageVisible':True,
               'visibleText':self.text,'visibleTextSha256':self.sha}
        epoch=self.now.timestamp()
        result={'status':'unknown','sendAttempts':1,'resolvedGroup':facts.GROUP,'sha256':self.sha,
                'observations':[frame|{'observedAt':epoch-20},frame|{'observedAt':epoch-10}]}
        self.originals={'task.json':task,'response.json':{'taskId':task['taskId'],'binding':task['binding'],'result':result},
                        'send-intent.json':{'taskId':task['taskId'],'binding':task['binding'],'sha256':self.sha,'at':epoch-30}}
        self.write()
    def write(self):
        hashes={}
        for name,value in self.originals.items():
            raw=json.dumps(value,ensure_ascii=False).encode();(self.folder/name).write_bytes(raw)
            hashes[name]=hashlib.sha256(raw).hexdigest()
        self.audit.write_text(json.dumps({'date':'2026-10-25','groupName':facts.GROUP,
            'source':str(self.folder),'taskId':'original-task','sourceFiles':hashes,'contentSha256':self.sha}))
    def test_bound_complete_text_is_business_fact_without_writes(self):
        before={p:p.read_bytes() for p in self.folder.iterdir()}
        result=facts.read_fact(facts.FLOW,self.now)
        self.assertTrue(result['businessDelivered']);self.assertEqual(result['technicalStatusPreserved'],'unknown')
        self.assertEqual(before,{p:p.read_bytes() for p in self.folder.iterdir()})
    def test_other_workflow_and_other_day_never_inherit(self):
        self.assertIsNone(facts.read_fact('daily-taobao-download-to-jinsha',self.now))
        self.assertIsNone(facts.read_fact(facts.FLOW,self.now.replace(day=26)))
    def test_changed_source_bytes_reject(self):
        (self.folder/'response.json').write_text('{}')
        self.assertIsNone(facts.read_fact(facts.FLOW,self.now))
    def test_wrong_group_reject_even_if_audit_hash_updated(self):
        self.originals['response.json']['result']['observations'][0]['groupName']='wrong'
        self.write();self.assertIsNone(facts.read_fact(facts.FLOW,self.now))
    def test_different_text_reject_even_if_declared_hash_matches(self):
        self.originals['response.json']['result']['observations'][0]['visibleText']='different'
        self.write();self.assertIsNone(facts.read_fact(facts.FLOW,self.now))
    def test_missing_second_observation_reject(self):
        self.originals['response.json']['result']['observations'].pop()
        self.write();self.assertIsNone(facts.read_fact(facts.FLOW,self.now))
    def test_zero_attempt_or_future_observation_reject(self):
        self.originals['response.json']['result']['sendAttempts']=0
        self.write();self.assertIsNone(facts.read_fact(facts.FLOW,self.now))
        self.originals['response.json']['result']['sendAttempts']=1
        self.originals['response.json']['result']['observations'][-1]['observedAt']=self.now.timestamp()+10
        self.write();self.assertIsNone(facts.read_fact(facts.FLOW,self.now))


if __name__=='__main__':unittest.main()
