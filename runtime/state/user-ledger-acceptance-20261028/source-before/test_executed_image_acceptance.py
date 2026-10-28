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

    def current_confirmation(self):
        self.now = self.now.replace(day=27, hour=20)
        item = self.task['item'];item['name'] = '2026-10-27_合同解约申请_处理中_p1.png'
        self.task['request']['context']['eventId'] = '2026-10-27-contract'
        self.task.pop('binding')
        binding = hashlib.sha256(json.dumps(self.task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.task['binding'] = binding;self.dump('task.json',self.task)
        for name in ['response.json','send-intent.json']:
            d=json.loads((self.folder/name).read_text());d['binding']=binding
            if name=='send-intent.json':d['at']=self.now.replace(hour=9).timestamp()
            self.dump(name,d)
        proof=self.acceptance['items'][0]
        proof.update(name=item['name'],eventId='2026-10-27-contract',sources=self.hashes())
        self.acceptance.update(date='2026-10-27',recordedAt=self.now.replace(hour=19).isoformat(),
                               userQuotes=[facts.EXECUTED_IMAGE_QUOTE_20261027])
        self.accept_path=self.accept_path.with_name('20261027-executed-image-submissions-user-confirmed.json');self.save()

    def test_current_explicit_confirmation_does_not_inherit_tomorrow(self):
        self.current_confirmation();before=self.hashes()
        self.assertTrue(self.fact()['businessDelivered'])
        self.assertEqual(before,self.hashes())
        self.assertIsNone(facts.read_fact(self.flow,self.now.replace(day=28)))

    def test_current_confirmation_rejects_old_business_filename(self):
        self.current_confirmation();self.acceptance['items'][0]['name']='old.png';self.save()
        self.assertIsNone(self.fact())

if __name__=='__main__':unittest.main()

class ExecutionNoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);p=patch.object(facts,'ROOT',self.root);p.start();self.addCleanup(p.stop)
        self.now=datetime(2026,10,26,21,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.base=self.root/'skills/workflows/daily-quality-products-optimization/.runtime/days/2026-10-26';self.base.mkdir(parents=True)
        self.proof={'day':'2026-10-26','workflowId':'daily-quality-products-optimization','groupName':facts.GROUP,'attemptedUnconfirmed':1,'handled':251}
        self.delivery={'state':'verified','deliveries':[{'receipt':{'status':'verified'}},{'receipt':{'status':'verified'}}]}
        self.save()
    def save(self):
        (self.base/'completion.json').write_text(json.dumps(self.proof))
        (self.base/'delivery.json').write_text(json.dumps(self.delivery))
    def test_note_preserves_unconfirmed_execution_without_editing_receipts(self):
        before=(self.base/'delivery.json').read_bytes()
        self.assertEqual(facts.read_execution_note('daily-quality-products-optimization',self.now),'已执行，1家结果待确认')
        self.assertEqual(before,(self.base/'delivery.json').read_bytes())
    def test_no_note_before_both_deliveries_verified(self):
        self.delivery['deliveries'][1]['receipt']['status']='unknown';self.save()
        self.assertIsNone(facts.read_execution_note('daily-quality-products-optimization',self.now))
    def test_no_cross_day_note(self):
        self.assertIsNone(facts.read_execution_note('daily-quality-products-optimization',self.now.replace(day=27)))
    def test_customer_view_keeps_explicit_note_and_original_default(self):
        import run_all
        rows=[{'name':'整改','done':'是','note':'internal','customer_note':'已执行，1家结果待确认','dev_state':'active'},
              {'name':'原任务','done':'是','note':'internal','dev_state':'active'}]
        shown,_,_=run_all.customer_ledger_view(rows,'2026-10-26')
        self.assertEqual([r['note'] for r in shown],['已执行，1家结果待确认','当日已完成'])
