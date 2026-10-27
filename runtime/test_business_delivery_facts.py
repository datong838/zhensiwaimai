import hashlib
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo
import business_delivery_facts as facts


class ClosingStageContractTests(unittest.TestCase):
    def modern(self):
        return {'results': [
            {'stage': 'build', 'receipt': {'ok': True, 'businessDate': '2026-10-26',
                                         'recordCount': 53, 'counts': {'全部': 53}}},
            {'stage': 'deliver', 'receipt': {'ok': False, 'reason': 'image-pending'}},
        ]}

    def test_new_closing_has_no_appeal_but_still_needs_independent_delivery_proof(self):
        self.assertTrue(facts.closing_stages_valid(self.modern(), '2026-10-26', '2026-10-27'))

    def test_new_closing_rejects_wrong_date_count_failed_build_and_extra_appeal(self):
        for change in [{'businessDate': '2026-10-25'}, {'recordCount': 52},
                       {'recordCount': 0, 'counts': {'全部': 0}}, {'ok': False}]:
            closing = self.modern();closing['results'][0]['receipt'].update(change)
            with self.subTest(change=change):
                self.assertFalse(facts.closing_stages_valid(closing, '2026-10-26', '2026-10-27'))
        closing = self.modern();closing['results'].insert(0, {'stage': 'appeal', 'receipt': {'ok': True}})
        self.assertFalse(facts.closing_stages_valid(closing, '2026-10-26', '2026-10-27'))

    def test_legacy_closing_still_requires_original_appeal(self):
        closing = self.modern()
        self.assertFalse(facts.closing_stages_valid(closing, '2026-10-26', '2026-10-26'))
        closing['results'].insert(0, {'stage': 'appeal', 'receipt': {
            'ok': True, 'businessDate': '2026-10-26', 'unknown': [], 'blocked': []}})
        self.assertTrue(facts.closing_stages_valid(closing, '2026-10-26', '2026-10-26'))
        closing['results'][0]['receipt']['unknown'] = ['unconfirmed']
        self.assertFalse(facts.closing_stages_valid(closing, '2026-10-26', '2026-10-26'))


class SinglePlatformClosingConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = patch.object(facts, 'ROOT', self.root);p.start();self.addCleanup(p.stop)
        self.now = datetime(2026, 10, 27, 19, tzinfo=ZoneInfo('Asia/Shanghai'))
        self.source = self.root/'runtime/state/user-confirmed-deliveries/20261027-taobao-appeals-summary-user-visible.json'
        self.source.parent.mkdir(parents=True)
        self.source.write_text(json.dumps({'at': '2026-10-27T18:47:20',
            'userQuote': facts.TAOBAO_CLOSING_QUOTE, 'flow': 'taobao-flash-sale-negative-review-appeals',
            'businessDate': '2026-10-26'}))
        self.acceptance = {'source': 'explicit-user-confirmation', 'businessAccepted': True,
            'date': '2026-10-27', 'groupName': facts.GROUP, 'userQuote': facts.TAOBAO_CLOSING_QUOTE,
            'confirmedPlatforms': ['taobao'], 'platforms': {'taobao': {}},
            'userConfirmationSha256': hashlib.sha256(self.source.read_bytes()).hexdigest()}

    def test_taobao_only_and_originals_untouched(self):
        before = self.source.read_bytes()
        self.assertTrue(facts.closing_confirmation_valid(self.acceptance, 'taobao', self.now))
        self.assertFalse(facts.closing_confirmation_valid(self.acceptance, 'meituan', self.now))
        self.assertEqual(before, self.source.read_bytes())

    def test_wrong_day_quote_or_platform_scope_rejected(self):
        for changed in [{'date': '2026-10-26'}, {'userQuote': '都发了'},
                        {'confirmedPlatforms': ['taobao', 'meituan']},
                        {'platforms': {'taobao': {}, 'meituan': {}}}, {'groupName': 'wrong'}]:
            with self.subTest(changed=changed):
                self.assertFalse(facts.closing_confirmation_valid(self.acceptance | changed, 'taobao', self.now))
        self.assertFalse(facts.closing_confirmation_valid(self.acceptance, 'taobao', self.now.replace(day=28)))

    def test_changed_or_unbound_user_evidence_rejected(self):
        self.source.write_text('{}')
        self.assertFalse(facts.closing_confirmation_valid(self.acceptance, 'taobao', self.now))

    def test_legacy_dual_confirmation_still_supported(self):
        self.assertTrue(facts.closing_confirmation_valid(self.acceptance | {'userQuote': '两张图都能看到'}, 'meituan', self.now))


class BusinessFactTests(unittest.TestCase):
    def test_closing_without_user_confirmation_stays_unresolved(self):
        for flow in facts.CLOSING:
            self.assertIsNone(facts.read_fact(flow,self.now))
    def test_closing_rejection_does_not_prove_delivery(self):
        p=self.root/'runtime/state/user-confirmed-deliveries/20261025-appeal-closing-images.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'source':'explicit-user-confirmation','businessAccepted':True,
            'date':'2026-10-25','groupName':facts.GROUP,'userQuote':'只看到其中一张'}))
        for flow in facts.CLOSING:
            self.assertIsNone(facts.read_fact(flow,self.now))
    def test_closing_unbound_user_text_does_not_prove_delivery(self):
        p=self.root/'runtime/state/user-confirmed-deliveries/20261025-appeal-closing-images.json'
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'source':'explicit-user-confirmation','businessAccepted':True,
            'date':'2026-10-25','groupName':facts.GROUP,'userQuote':'两张图都能看到',
            'platforms':{'meituan':{},'taobao':{}}}))
        for flow in facts.CLOSING:
            self.assertIsNone(facts.read_fact(flow,self.now))
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


class UserImageFactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);p=patch.object(facts,'ROOT',self.root)
        p.start();self.addCleanup(p.stop)
        self.now=datetime(2026,10,25,18,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.queue=self.root/'skills/wechat-messaging/.runtime/ui-post-queue'
        self.tasks=[]
        for index,name in enumerate(['jinsha-store-final.png','jinsha-review-final.png']):
            folder=self.queue/str(index);folder.mkdir(parents=True)
            image=folder/name;image.write_bytes(('synthetic-'+name).encode())
            sha=hashlib.sha256(image.read_bytes()).hexdigest()
            item={'type':'image','name':name,'path':str(image),'sha256':sha}
            task={'taskId':str(index),'stage':'send','item':item,'request':{
                'groupName':facts.GROUP,'items':[item],'context':{'workflowId':'taobao-evidence'}}}
            task['binding']=hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            reply={'taskId':str(index),'binding':task['binding'],'result':{
                'status':'unknown','sendAttempts':1,'resolvedGroup':facts.GROUP}}
            intent={'taskId':str(index),'binding':task['binding'],'sha256':sha,'at':self.now.timestamp()-60}
            hashes={}
            for filename,value in [('task.json',task),('response.json',reply),('send-intent.json',intent)]:
                raw=json.dumps(value,ensure_ascii=False).encode();(folder/filename).write_bytes(raw)
                hashes[filename]=hashlib.sha256(raw).hexdigest()
            self.tasks.append((folder,task,hashes))
        screenshot=self.root/'runtime/state/ui-user-evidence/20261025/first.png'
        screenshot.parent.mkdir(parents=True);screenshot.write_bytes(b'user-attached-evidence-fixture')
        self.receipt=self.root/'upload-receipt.json'
        self.receipt.write_text(json.dumps({'ok':True,'phase':'completed','cleanupStatus':'completed',
            'businessDate':'2026-10-24','evidenceManifest':{'businessDate':'2026-10-24',
            'images':[{'sha256':task['item']['sha256']} for _,task,_ in self.tasks]}}))
        self.prefix=self.root/'runtime/state/taobao-image-user-prefix-2026-10-24.json'
        self.prefix.write_text(json.dumps({'source':'explicit-user-business-confirmation','businessDate':'2026-10-24',
            'groupName':facts.GROUP,'confirmation':'上传金鲨 这个 还差一个 图片 。','screenshot':str(screenshot),
            'screenshotSha256':hashlib.sha256(screenshot.read_bytes()).hexdigest(),
            'taskDirectory':str(self.tasks[0][0]),'sha256':self.tasks[0][1]['item']['sha256'],
            'receiptFile':str(self.receipt)}))
        folder,task,hashes=self.tasks[1]
        self.acceptance=self.root/'runtime/state/user-confirmed-deliveries/20261025-taobao-jinsha-second-image.json'
        self.acceptance.parent.mkdir(parents=True)
        self.acceptance.write_text(json.dumps({'source':'explicit-user-confirmation','businessAccepted':True,
            'date':'2026-10-25','groupName':facts.GROUP,'userQuote':'能看到第二张图',
            'firstImageAcceptance':str(self.prefix),'taskId':task['taskId'],'binding':task['binding'],
            'item':task['item'],'sourceFiles':hashes}))
    def test_explicit_acceptance_is_separate_and_read_only(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=facts.read_fact(facts.TAOBAO_IMAGES,self.now)
        self.assertTrue(result['businessDelivered'])
        self.assertEqual(result['basis'],'explicit-user-confirmation')
        self.assertEqual(result['technicalStatusPreserved'],'unknown')
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
    def test_absent_confirmation_cannot_infer_from_submit(self):
        self.acceptance.unlink();self.assertIsNone(facts.read_fact(facts.TAOBAO_IMAGES,self.now))
    def test_other_day_does_not_inherit_acceptance(self):
        self.assertIsNone(facts.read_fact(facts.TAOBAO_IMAGES,self.now.replace(day=26)))
    def test_changed_frozen_image_reject(self):
        Path(self.tasks[1][1]['item']['path']).write_bytes(b'changed')
        self.assertIsNone(facts.read_fact(facts.TAOBAO_IMAGES,self.now))
    def test_noncompleted_upload_cannot_be_accepted(self):
        data=json.loads(self.receipt.read_text());data['phase']='failed'
        self.receipt.write_text(json.dumps(data));self.assertIsNone(facts.read_fact(facts.TAOBAO_IMAGES,self.now))
    def test_explicit_rejection_is_not_acceptance(self):
        data=json.loads(self.acceptance.read_text());data['userQuote']='只看到第一张图'
        self.acceptance.write_text(json.dumps(data));self.assertIsNone(facts.read_fact(facts.TAOBAO_IMAGES,self.now))



class ServiceRankingFactTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);p=patch.object(facts,'ROOT',self.root);p.start();self.addCleanup(p.stop)
        self.now=datetime(2026,10,26,14,10,tzinfo=ZoneInfo('Asia/Shanghai'))
        self.base=self.root/'skills/workflows/daily-service-market-ranking-to-wechat/.runtime/days/2026-10-26'
        self.base.mkdir(parents=True);image=self.base/'2026-10-26-服务市场排名与考核指标.png';image.write_bytes(b'fixture')
        sha=hashlib.sha256(image.read_bytes()).hexdigest()
        item={'itemId':'service-ranking','type':'image','name':image.name,'path':str(image),'size':7,'sha256':sha}
        self.folder=self.root/'skills/wechat-messaging/.runtime/ui-post-queue/original-rank'
        self.folder.mkdir(parents=True)
        self.task={'taskId':'original-rank','stage':'send','item':item,'request':{'groupName':facts.GROUP,'items':[item],'context':{'workflowId':'daily-service-market-ranking-ops','eventId':'2026-10-26-service-market-ranking'}}}
        self.task['binding']=hashlib.sha256(json.dumps(self.task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        self.reply={'taskId':'original-rank','binding':self.task['binding'],'result':{'status':'unknown','sendAttempts':1,'resolvedGroup':facts.GROUP,'inputEmpty':True,'backend':'system-events-ui-tree'}}
        intent={'taskId':'original-rank','binding':self.task['binding'],'sha256':sha,'at':self.now.timestamp()-60}
        self.hashes={}
        for name,data in [('task.json',self.task),('response.json',self.reply),('send-intent.json',intent)]:
            raw=json.dumps(data,ensure_ascii=False).encode();(self.folder/name).write_bytes(raw);self.hashes[name]=hashlib.sha256(raw).hexdigest()
        self.frozen={'day':'2026-10-26','item':item,'collection':{'ok':True,'browserPort':9231,'collectedAt':'2026-10-26T05:34:18Z','metrics':[{}]*10}}
        self.marker={'state':'unknown','sendAttempts':1,'eventId':'2026-10-26-service-market-ranking','groupName':facts.GROUP,'sha256':sha}
        self.originals={}
        for name,data in [('frozen.json',self.frozen),('delivery.json',self.marker)]:
            raw=json.dumps(data).encode();(self.base/name).write_bytes(raw);self.originals[name]=hashlib.sha256(raw).hexdigest()
        self.acceptance=self.root/'runtime/state/user-confirmed-deliveries/20261026-service-market-ranking.json'
        self.acceptance.parent.mkdir(parents=True)
        self.accept={'source':'explicit-user-confirmation','businessAccepted':True,'date':'2026-10-26','groupName':facts.GROUP,'userQuote':facts.SERVICE_RANKING_QUOTE,'taskId':'original-rank','sourceFiles':self.hashes,'originalFiles':self.originals}
        self.acceptance.write_text(json.dumps(self.accept))
    def test_bound_acceptance_preserves_originals(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result=facts.read_fact(facts.SERVICE_RANKING,self.now)
        self.assertTrue(result['businessDelivered']);self.assertEqual(result['technicalStatusPreserved'],'unknown')
        self.assertEqual(before,{p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
    def test_missing_confirmation_reject(self):
        self.acceptance.unlink();self.assertIsNone(facts.read_fact(facts.SERVICE_RANKING,self.now))
    def test_wrong_quote_reject(self):
        self.accept['userQuote']='还没发';self.acceptance.write_text(json.dumps(self.accept));self.assertIsNone(facts.read_fact(facts.SERVICE_RANKING,self.now))
    def test_tomorrow_does_not_inherit(self):
        self.assertIsNone(facts.read_fact(facts.SERVICE_RANKING,self.now.replace(day=27)))
    def test_changed_original_bytes_reject(self):
        (self.folder/'response.json').write_text('{}');self.assertIsNone(facts.read_fact(facts.SERVICE_RANKING,self.now))
    def test_changed_image_reject(self):
        Path(self.frozen['item']['path']).write_bytes(b'changed');self.assertIsNone(facts.read_fact(facts.SERVICE_RANKING,self.now))
    def test_no_original_send_reject_even_with_updated_hash(self):
        self.reply['result']['sendAttempts']=0;raw=json.dumps(self.reply).encode();(self.folder/'response.json').write_bytes(raw)
        self.accept['sourceFiles']['response.json']=hashlib.sha256(raw).hexdigest();self.acceptance.write_text(json.dumps(self.accept))
        self.assertIsNone(facts.read_fact(facts.SERVICE_RANKING,self.now))


if __name__=='__main__':unittest.main()
