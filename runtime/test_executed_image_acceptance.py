import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import business_delivery_facts as facts


class ExecutedImageAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mocked = patch.object(facts, 'ROOT', self.root); mocked.start(); self.addCleanup(mocked.stop)
        self.now = datetime(2026, 10, 26, 18, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.flow = 'contract-termination-applications-screenshot'
        self.folder = self.root/'skills/wechat-messaging/.runtime/ui-post-queue/original'
        self.folder.mkdir(parents=True)
        image = self.root/'source.png'; image.write_bytes(b'offline-image-fixture')
        sha = hashlib.sha256(image.read_bytes()).hexdigest()
        item = {'type':'image', 'name':'source.png', 'path':str(image), 'sha256':sha}
        task = {'taskId':'original', 'stage':'send', 'item':item, 'request':{
            'groupName':facts.GROUP, 'items':[item], 'context':{
                'workflowId':'contract-termination-ops', 'eventId':'2026-10-26-contract'}}}
        binding = hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        task['binding'] = binding
        self.task = task
        self.dump('task.json', task)
        self.dump('response.json', {'taskId':'original','binding':binding,'result':{
            'resolvedGroup':facts.GROUP,'status':'unknown','sendAttempts':1,
            'backend':'system-events-ui-tree','inputEmpty':True}})
        self.dump('send-intent.json', {'taskId':'original','binding':binding,'sha256':sha,
            'at':self.now.replace(hour=16).timestamp()})
        self.acceptance = {'source':'explicit-user-confirmation','businessAccepted':True,'date':'2026-10-26',
            'recordedAt':self.now.replace(hour=17,minute=30).isoformat(),
            'userQuotes':facts.EXECUTED_IMAGE_QUOTES,'items':[{
                'taskId':'original','workflowId':'contract-termination-ops','eventId':'2026-10-26-contract',
                'groupName':facts.GROUP,'name':item['name'],'sha256':sha,'sources':self.hashes()}]}
        self.accept_path = self.root/'runtime/state/user-confirmed-deliveries/20261026-executed-image-submissions-173035.json'
        self.accept_path.parent.mkdir(parents=True); self.save()
    def dump(self, name, value): (self.folder/name).write_text(json.dumps(value,ensure_ascii=False))
    def hashes(self): return {n:hashlib.sha256((self.folder/n).read_bytes()).hexdigest() for n in ['task.json','response.json','send-intent.json']}
    def save(self): self.accept_path.write_text(json.dumps(self.acceptance,ensure_ascii=False))
    def fact(self): return facts.read_fact(self.flow,self.now)
    def test_acceptance_keeps_original_unknown_bytes(self):
        before=self.hashes(); self.assertTrue(self.fact()['businessDelivered'])
        self.assertEqual(self.fact()['technicalStatusPreserved'],'unknown'); self.assertEqual(before,self.hashes())
    def test_bridge_frozen_path_preserves_original_payload_identity(self):
        t=self.task.copy();t['request']=dict(t['request']);t['request']['items']=[dict(t['item'],path='/prior/source/path.png')]
        t.pop('binding');binding=hashlib.sha256(json.dumps(t,sort_keys=True,ensure_ascii=False).encode()).hexdigest();t['binding']=binding
        self.dump('task.json',t)
        for name in ['response.json','send-intent.json']:
            d=json.loads((self.folder/name).read_text());d['binding']=binding;self.dump(name,d)
        self.acceptance['items'][0]['sources']=self.hashes();self.save()
        self.assertTrue(self.fact()['businessDelivered'])
    def test_original_director_naive_local_time_is_supported(self):
        self.assertTrue(facts.read_fact(self.flow,self.now.replace(tzinfo=None))['businessDelivered'])
    def test_next_day_and_future_slots_not_accepted(self):
        self.assertIsNone(facts.read_fact(self.flow,self.now.replace(day=27)))
        self.assertIsNone(facts.read_fact('taobao-flash-sale-negative-review-appeals',self.now))
    def test_unbound_quote_rejected(self):
        self.acceptance['userQuotes']=['looks fine'];self.save();self.assertIsNone(self.fact())
    def test_tampered_original_rejected(self):
        p=self.folder/'response.json';p.write_text(p.read_text()+' ');self.assertIsNone(self.fact())
    def test_post_confirmation_intent_rejected_even_with_refreshed_hash(self):
        p=self.folder/'send-intent.json';d=json.loads(p.read_text());d['at']=self.now.timestamp();self.dump(p.name,d)
        self.acceptance['items'][0]['sources']=self.hashes();self.save();self.assertIsNone(self.fact())
    def test_missing_second_taobao_image_rejected(self):
        self.assertIsNone(facts.read_fact('daily-taobao-download-to-jinsha',self.now))
    def test_diagnostic_route_cannot_be_business_acceptance(self):
        self.assertIsNone(facts.read_fact('native-ui-acceptance-20261026',self.now))

if __name__=='__main__':unittest.main()
