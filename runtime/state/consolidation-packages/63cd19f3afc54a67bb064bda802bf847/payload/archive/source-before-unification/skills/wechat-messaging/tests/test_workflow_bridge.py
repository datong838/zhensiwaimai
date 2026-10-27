import sys, tempfile, unittest, json, hashlib
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import workflow_bridge as b
from contract import Rejected
from ledger import atomic_json

class Fake:
    channel='desktop';supported={'text','file','image'}
    def __init__(self,outcomes=None):self.calls=0;self.lookups=0;self.outcomes=outcomes or ['verified']
    @contextmanager
    def session(self,r):yield
    def preflight(self,r,o):self.lookups+=1;return {'ok':True}
    def send_one(self,r,i,w,g,d):
        state=self.outcomes[min(self.calls,len(self.outcomes)-1)];self.calls+=1
        if state=='crash':raise RuntimeError('interrupted')
        return {'status':state,'sendAttempts':0 if state=='blocked' else 1,
                'transport':{'sendAttempts':1,'postSendInputCleared':[True,True]},'evidence':{}}
    def reconcile(self,*a):return {'status':'unknown','sendAttempts':0,'reason':'not-proven'}

class Bridge(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.args=SimpleNamespace(workflow_id='merchants',group='电销+直播攻坚组',payload_type='text',item=['hello'],
            authorization='user-20260915-production-hourly',ledger=str(self.root/'ledger'),marker_name='event.json',output_dir=str(self.root/'out'),execute=True,reconcile=False)
        original=b.REGISTRY['merchants'];self.registry=patch.dict(b.REGISTRY,{'merchants':(*original[:4],self.root/'ledger')});self.registry.start()
        self.real_registry_ledger=b.registry_ledger
        self.ledger_resolver=patch.object(b,'registry_ledger',side_effect=lambda workflow_id:Path(b.REGISTRY[workflow_id][4]));self.ledger_resolver.start()
        self.verify=patch.object(b,'verify_dependencies',return_value=True);self.verify.start()
    def tearDown(self):self.verify.stop();self.ledger_resolver.stop();self.registry.stop();self.tmp.cleanup()

    def test_business_ledgers_use_three_activated_keys_for_five_registry_entries(self):
        expected={
            'taobao-flash-appeals':('taobao-appeals','wechat-attempts'),
            'taobao-flash-appeals-summary':('taobao-appeals','summary-attempts'),
            'meituan-waimai-appeals':('meituan-appeals','wechat-attempts'),
            'meituan-waimai-appeals-summary':('meituan-appeals','summary-attempts'),
            'negative-feedback-appeals':('negative-feedback','wechat-attempts'),
        }
        roots={key:b.PROJECT/'state/shared'/name for key,name in {
            'taobao-appeals':'taobao-flash-sale-negative-review-appeals',
            'meituan-appeals':'meituan-waimai-negative-review-appeals',
            'negative-feedback':'negative-feedback-list-appeals'}.items()}
        with patch.object(b,'business_path',side_effect=lambda key,root:roots[key]) as resolve:
            for workflow_id,(key,leaf) in expected.items():
                self.assertEqual(self.real_registry_ledger(workflow_id),roots[key]/leaf)
        self.assertEqual([call.args[0] for call in resolve.call_args_list],
                         [value[0] for value in expected.values()])

    def test_prepare_accepts_activated_internal_ledger_and_rejects_external_ledger(self):
        workflow='taobao-flash-appeals';day='2026-09-21';run_key='20260922'
        internal=b.PROJECT/'state/shared/taobao-flash-sale-negative-review-appeals'
        ledger=internal/'wechat-attempts';name=f'淘宝闪购差评申诉汇总-{day}.xlsx'
        report=b.PROJECT/'outputs'/f'taobao-flash-sale-negative-review-appeals-{run_key}'/name
        report.parent.mkdir(parents=True,exist_ok=True);created=not report.exists()
        if created:report.write_bytes(b'fixture')
        args=SimpleNamespace(workflow_id=workflow,group=b.REGISTRY[workflow][0],payload_type='file',
            item=[str(report)],authorization=b.REGISTRY[workflow][3],ledger=str(ledger),
            marker_name=f'taobao-flash-appeals-{day}.json',output_dir=str(self.root/'out'),
            execute=True,reconcile=False,deadline_unix=None,correction_v1=False)
        try:
            with patch.object(b,'registry_ledger',side_effect=self.real_registry_ledger), \
                 patch.object(b,'business_path',return_value=internal), \
                 patch.object(b,'taobao_flash_appeals_scope',return_value=(day,run_key)):
                self.assertEqual(b.prepare(args)[0]['context']['workflowId'],workflow)
                args.ledger=str(b.WORKSPACE/'state/taobao-flash-sale-negative-review-appeals/wechat-attempts')
                with self.assertRaisesRegex(Rejected,'ledger-mismatch'):b.prepare(args)
        finally:
            if created:report.unlink()

    def test_bad_activation_fails_before_adapter(self):
        workflow='taobao-flash-appeals';self.args.workflow_id=workflow
        self.args.group=b.REGISTRY[workflow][0];self.args.payload_type='file';self.args.item=['missing.xlsx']
        self.args.authorization=b.REGISTRY[workflow][3];self.args.ledger=str(b.REGISTRY[workflow][4])
        adapter=Mock(side_effect=AssertionError('adapter must not run'))
        with patch.object(b,'registry_ledger',side_effect=self.real_registry_ledger), \
             patch.object(b,'business_path',side_effect=ValueError('storage-activation-proof-invalid')):
            with self.assertRaisesRegex(Rejected,'activation-invalid'):b.execute(self.args,adapter_factory=adapter)
        adapter.assert_not_called()
    def test_taobao_repair_registry_is_one_file_new_group_only(self):
        group,kind,count,authorization,ledger=b.REGISTRY['jinsha-reports-taobao-repair-20260917']
        self.assertEqual(group,b.JINSHA_GROUP)
        self.assertEqual((kind,count),('file',1))
        self.assertIn('taobao-repair-v3-user-20260917',authorization)
        self.assertIn('taobao-repair-20260917-v3.desktop-attempts',str(ledger))
    def test_taobao_repair_rejects_other_file(self):
        _,_,_,authorization,ledger=b.REGISTRY['jinsha-reports-taobao-repair-20260917']
        wrong=self.root/'美团外卖日报_2026-09-16.xlsx';wrong.write_bytes(b'wrong')
        args=SimpleNamespace(workflow_id='jinsha-reports-taobao-repair-20260917',group=b.JINSHA_GROUP,
            payload_type='file',item=[str(wrong)],authorization=authorization,ledger=str(ledger),
            marker_name='wrong.json',output_dir=str(self.root/'out'),execute=True,reconcile=False,deadline_unix=None)
        with self.assertRaisesRegex(Rejected,'taobao-repair-payload-mismatch'):b.prepare(args)
    def test_jinsha_reports_uses_core_group_search_and_full_group_contract(self):
        _,_,_,authorization,ledger=b.REGISTRY['jinsha-reports']
        paths=[]
        for n in (1,2):
            p=self.root/f'{n}.xlsx';p.write_bytes(b'payload');paths.append(str(p))
        args=SimpleNamespace(workflow_id='jinsha-reports',group=b.JINSHA_GROUP,payload_type='file',item=paths,
            authorization=authorization,ledger=str(ledger),marker_name='daily.json',output_dir=str(self.root/'out'),
            execute=True,reconcile=False,deadline_unix=None)
        request,_=b.prepare(args)
        self.assertEqual(request['groupName'],b.JINSHA_GROUP)
        self.assertEqual(request['context']['searchGroupName'],b.NEGATIVE_REVIEW_GROUP_SEARCH)

    def test_negative_review_uses_visible_unique_core_prefix(self):
        self.assertEqual(b.NEGATIVE_REVIEW_GROUP_SEARCH,'上海臻肆外卖运营-盯个盯')

    def test_blocked_zero_send_marker_must_bind_full_text_and_nested_receipt(self):
        import hashlib
        from contract import normalize
        text='city\ncontact\nmerchant\naddress'
        request=normalize({'schemaVersion':1,'groupName':'电销+直播攻坚组',
            'items':[{'itemId':'0','type':'text','text':text}],
            'context':{'workflowId':'merchants','eventId':'event','accountAlias':'main-wechat',
                       'channel':'desktop','deadlineAt':1}})
        digest=hashlib.sha256(text.encode()).hexdigest()
        transport={'groupName':'电销+直播攻坚组','payloadType':'text','stage':'prepare_payload',
            'sendAttempts':0,'reason':'desktop-text-input-write-failed',
            'payloads':[{'text':text,'sha256':digest}]}
        common_item={'status':'blocked','type':'text','sendAttempts':0,
            'reason':'desktop-text-input-write-failed','sha256':digest,'transport':transport}
        marker={'bridgeVersion':1,'state':'blocked','stage':'prepare_payload',
            'reason':'desktop-text-input-write-failed','sendAttempts':0,'physicalSendAttempts':0,
            'groupName':'电销+直播攻坚组','payloadType':'text',
            'payloads':[{'text':text,'sha256':digest}],
            'commonReceipt':{'status':'blocked','groupName':'电销+直播攻坚组',
                'reason':'desktop-text-input-write-failed','items':[common_item]}}
        path=self.root/'ledger'/'event.json';path.parent.mkdir();path.write_text(json.dumps(marker))
        self.assertTrue(b.validate_blocked_zero_text_marker(path,path.parent,'event.json',request))
        marker['physicalSendAttempts']=None
        path.write_text(json.dumps(marker))
        self.assertFalse(b.validate_blocked_zero_text_marker(path,path.parent,'event.json',request))

    def test_resume_flag_is_rejected_for_unbound_marker(self):
        self.args.resume_blocked_zero_marker=str(self.root/'ledger'/'event.json')
        with self.assertRaisesRegex(Rejected,'resume-blocked-zero-marker-contract-mismatch'):
            b.prepare(self.args)

    def test_preflight_only_null_physical_count_is_zero_send_only_with_exact_stage_chain(self):
        import hashlib
        from contract import normalize
        text='city\ncontact\nmerchant\naddress';digest=hashlib.sha256(text.encode()).hexdigest()
        request=normalize({'schemaVersion':1,'groupName':'电销+直播攻坚组',
            'items':[{'itemId':'0','type':'text','text':text}],
            'context':{'workflowId':'merchants','eventId':'event','accountAlias':'main-wechat',
                       'channel':'desktop','deadlineAt':1}})
        stages=[{'stage':'authorization','status':'completed'},
                {'stage':'freeze:0','status':'completed'},
                {'stage':'preflight','status':'completed'}]
        marker={'bridgeVersion':1,'state':'blocked','sendAttempts':0,'newSendAttempts':0,
            'physicalSendAttempts':None,'reason':'resume-prepared-text-readback-mismatch',
            'groupName':'电销+直播攻坚组','payloadType':'text',
            'payloads':[{'text':text,'sha256':digest}],
            'commonReceipt':{'status':'blocked','groupName':'电销+直播攻坚组',
                'reason':'resume-prepared-text-readback-mismatch','items':[],
                'requestDigest':'a'*64,'review':stages,
                'reviewSummary':{'result':'blocked','failedStages':[]}}}
        path=self.root/'ledger'/'event.json';path.parent.mkdir();path.write_text(json.dumps(marker))
        self.assertTrue(b.validate_blocked_zero_text_marker(path,path.parent,'event.json',request))
        marker['commonReceipt']['items']=[{'status':'unknown','sendAttempts':None}]
        path.write_text(json.dumps(marker))
        self.assertFalse(b.validate_blocked_zero_text_marker(path,path.parent,'event.json',request))
    def test_negative_review_accepts_only_dated_output_path(self):
        _,_,_,authorization,ledger=b.REGISTRY['negative-reviews']
        day='2026-09-17';name=f'差评分析数据_{day}_{day}.xlsx'
        expected=b.PROJECT/'outputs'/'yesterday-negative-20260917'/name
        expected.parent.mkdir(parents=True,exist_ok=True)
        created=not expected.exists()
        if created:expected.write_bytes(b'report')
        args=SimpleNamespace(workflow_id='negative-reviews',group=b.JINSHA_GROUP,
            payload_type='file',item=[str(expected)],authorization=authorization,ledger=str(ledger),
            marker_name='negative-review-2026-09-17.json',output_dir=str(self.root/'out'),execute=True,reconcile=False,deadline_unix=None)
        try:
            request,_=b.prepare(args)
            self.assertEqual(request['items'][0]['name'],name)
            self.assertEqual(request['context']['searchGroupName'],b.NEGATIVE_REVIEW_GROUP_SEARCH)
            wrong=self.root/name;wrong.write_bytes(expected.read_bytes());args.item=[str(wrong)]
            with self.assertRaisesRegex(Rejected,'path-mismatch'):b.prepare(args)
        finally:
            if created:expected.unlink()
    def test_negative_review_accepts_only_fixed_correction_name_path_and_marker(self):
        _,_,_,authorization,ledger=b.REGISTRY['negative-reviews']
        day='2026-09-18';name=f'差评分析数据_{day}_{day}_更正.xlsx'
        expected=b.PROJECT/'outputs'/'yesterday-negative-20260918'/name
        expected.parent.mkdir(parents=True,exist_ok=True)
        created=not expected.exists()
        if created:expected.write_bytes(b'corrected-report')
        args=SimpleNamespace(workflow_id='negative-reviews',group=b.JINSHA_GROUP,
            payload_type='file',item=[str(expected)],authorization=authorization,ledger=str(ledger),
            marker_name='negative-review-2026-09-18-correction-v1.json',output_dir=str(self.root/'out'),
            execute=True,reconcile=False,deadline_unix=None)
        try:
            request,_=b.prepare(args)
            self.assertEqual(request['items'][0]['name'],name)
            args.marker_name='negative-review-2026-09-18.json'
            with self.assertRaisesRegex(Rejected,'marker-mismatch'):b.prepare(args)
            args.marker_name='negative-review-2026-09-18-correction-v1.json'
            wrong=self.root/name;wrong.write_bytes(expected.read_bytes());args.item=[str(wrong)]
            with self.assertRaisesRegex(Rejected,'path-mismatch'):b.prepare(args)
        finally:
            if created:expected.unlink()
    def test_negative_review_standard_marker_cannot_use_correction_identity(self):
        _,_,_,authorization,ledger=b.REGISTRY['negative-reviews']
        day='2026-09-17';name=f'差评分析数据_{day}_{day}.xlsx'
        expected=b.PROJECT/'outputs'/'yesterday-negative-20260917'/name
        expected.parent.mkdir(parents=True,exist_ok=True)
        created=not expected.exists()
        if created:expected.write_bytes(b'report')
        args=SimpleNamespace(workflow_id='negative-reviews',group=b.JINSHA_GROUP,
            payload_type='file',item=[str(expected)],authorization=authorization,ledger=str(ledger),
            marker_name='negative-review-2026-09-17-correction-v1.json',output_dir=str(self.root/'out'),
            execute=True,reconcile=False,deadline_unix=None)
        try:
            with self.assertRaisesRegex(Rejected,'marker-mismatch'):b.prepare(args)
        finally:
            if created:expected.unlink()
    def test_taobao_flash_appeals_binds_current_business_date_path_and_marker(self):
        _,_,_,authorization,ledger=b.REGISTRY['taobao-flash-appeals']
        day='2026-09-21';run_key='20260922';name=f'淘宝闪购差评申诉汇总-{day}.xlsx'
        expected=b.PROJECT/'outputs'/f'taobao-flash-sale-negative-review-appeals-{run_key}'/name
        expected.parent.mkdir(parents=True,exist_ok=True)
        created=not expected.exists()
        if created:expected.write_bytes(b'report')
        args=SimpleNamespace(workflow_id='taobao-flash-appeals',group=b.REGISTRY['taobao-flash-appeals'][0],payload_type='file',item=[str(expected)],
            authorization=authorization,ledger=str(ledger),marker_name=f'taobao-flash-appeals-{day}.json',
            output_dir=str(self.root/'out'),execute=True,reconcile=False,deadline_unix=None)
        try:
            with patch.object(b,'taobao_flash_appeals_scope',return_value=(day,run_key)):
                request,_=b.prepare(args)
                self.assertEqual(request['items'][0]['name'],name)
                wrong=self.root/name;wrong.write_bytes(expected.read_bytes());args.item=[str(wrong)]
                with self.assertRaisesRegex(Rejected,'path-mismatch'):b.prepare(args)
                args.item=[str(expected)];args.marker_name='taobao-flash-appeals-2026-09-20.json'
                with self.assertRaisesRegex(Rejected,'marker-mismatch'):b.prepare(args)
        finally:
            if created:expected.unlink()
    def test_meituan_waimai_appeals_binds_current_business_date_path_and_marker(self):
        _,_,_,authorization,ledger=b.REGISTRY['meituan-waimai-appeals']
        day='2026-09-22';run_key='20260923';name=f'美团外卖差评申诉汇总-{day}.xlsx'
        expected=b.WORKSPACE/'zhensi_waimai_back'/'outputs'/f'meituan-waimai-negative-review-appeals-{run_key}'/name
        expected.parent.mkdir(parents=True,exist_ok=True)
        created=not expected.exists()
        if created:expected.write_bytes(b'report')
        args=SimpleNamespace(workflow_id='meituan-waimai-appeals',group=b.REGISTRY['meituan-waimai-appeals'][0],payload_type='file',item=[str(expected)],
            authorization=authorization,ledger=str(ledger),marker_name=f'meituan-waimai-appeals-{day}.json',
            output_dir=str(self.root/'out'),execute=True,reconcile=False,deadline_unix=None)
        try:
            with patch.object(b,'meituan_waimai_appeals_scope',return_value=(day,run_key)):
                request,_=b.prepare(args)
                self.assertEqual(request['items'][0]['name'],name)
                wrong=self.root/name;wrong.write_bytes(expected.read_bytes());args.item=[str(wrong)]
                with self.assertRaisesRegex(Rejected,'path-mismatch'):b.prepare(args)
                args.item=[str(expected)];args.marker_name='meituan-waimai-appeals-2026-09-21.json'
                with self.assertRaisesRegex(Rejected,'marker-mismatch'):b.prepare(args)
        finally:
            if created:expected.unlink()
    def test_meituan_customer_reply_daily_binds_today_records_path_and_marker(self):
        from datetime import datetime as _dt
        from zoneinfo import ZoneInfo as _ZI
        day=_dt.now(_ZI('Asia/Shanghai')).strftime('%Y-%m-%d')
        name=f'美团客户回复记录-{day}.xlsx'
        group,_,_,authorization,ledger=b.REGISTRY['meituan-customer-reply-daily']
        with patch.object(b,'SKILLS',self.root):
            # 2026-10-05：智能客服技能包已迁入 skills/workflows/，桥的路径锚点同步下移一层。
            expected=(self.root/'workflows'/'meituan-intelligent-customer-service'/'records'/name).resolve()
            expected.parent.mkdir(parents=True,exist_ok=True)
            expected.write_bytes(b'report')
            args=SimpleNamespace(workflow_id='meituan-customer-reply-daily',group=group,payload_type='file',
                item=[str(expected)],authorization=authorization,ledger=str(ledger),
                marker_name=f'meituan-customer-reply-daily-{day}.json',output_dir=str(self.root/'out'),
                execute=True,reconcile=False,deadline_unix=None)
            try:
                request,_=b.prepare(args)
                self.assertEqual(request['items'][0]['name'],name)
                wrong=self.root/name;wrong.write_bytes(expected.read_bytes());args.item=[str(wrong)]
                with self.assertRaisesRegex(Rejected,'path-mismatch'):b.prepare(args)
                args.item=[str(expected)];args.marker_name='meituan-customer-reply-daily-baddate.json'
                with self.assertRaisesRegex(Rejected,'marker-mismatch'):b.prepare(args)
            finally:
                if expected.exists():expected.unlink()
    def _correction_fixture(self, workflow):
        # Correction tests must not depend on a real daily report already existing
        # under the workspace outputs directory. Keep all fixture I/O temporary.
        if not getattr(self, '_workspace_fixture_patch', None):
            self._workspace_fixture_patch=patch.object(b,'WORKSPACE',self.root)
            self._workspace_fixture_patch.start()
            self.addCleanup(self._workspace_fixture_patch.stop)
        if not getattr(self, '_project_fixture_patch', None):
            self._project_fixture_patch=patch.object(b,'PROJECT',self.root)
            self._project_fixture_patch.start()
            self.addCleanup(self._project_fixture_patch.stop)
        is_taobao=workflow=='taobao-flash-appeals'
        prefix=workflow
        day,run_key=(b.taobao_flash_appeals_scope() if is_taobao else b.meituan_waimai_appeals_scope())
        platform='taobao-flash-sale-negative-review-appeals' if is_taobao else 'meituan-waimai-negative-review-appeals'
        name=('淘宝闪购差评申诉汇总-' if is_taobao else '美团外卖差评申诉汇总-')+day+'.xlsx'
        if is_taobao:
            report=(b.PROJECT/'outputs'/f'{platform}-{run_key}'/name).resolve()
        else:
            report=(b.WORKSPACE/'zhensi_waimai_back'/'outputs'/f'{platform}-{run_key}'/name).resolve()
        report.parent.mkdir(parents=True,exist_ok=True)
        report.write_bytes(b'report fixture')
        ledger=self.root/f'{workflow}-correction-ledger';ledger.mkdir()
        auth=f'user-{run_key}-{workflow}-correction-v1'
        args=SimpleNamespace(workflow_id=workflow,group=b.GROUP,payload_type='file',item=[str(report)],
            authorization=auth,ledger=str(ledger),marker_name=f'{prefix}-{day}-correction-v1.json',
            output_dir=str(report.parent/'wechat-delivery'/'correction-v1'),execute=True,reconcile=False,
            deadline_unix=None,correction_v1=True)
        return args,day,report,ledger
    def test_correction_event_reuses_sender_and_preserves_standard_marker(self):
        for workflow in ('taobao-flash-appeals','meituan-waimai-appeals'):
            with self.subTest(workflow=workflow):
                args,day,report,ledger=self._correction_fixture(workflow)
                original_marker=ledger/f'{workflow}-{day}.json'
                corrected_marker=ledger/args.marker_name
                actual_hash=hashlib.sha256(report.read_bytes()).hexdigest()
                old={'state':'verified','verified':True,'sendAttempts':1,'groupName':b.GROUP,'payloadType':'file',
                     'payloads':[{'path':str(report),'name':report.name,'size':report.stat().st_size,'sha256':'0'*64}]}
                atomic_json(original_marker,old)
                before=original_marker.read_bytes()
                original_scope=b.taobao_flash_appeals_scope if workflow=='taobao-flash-appeals' else b.meituan_waimai_appeals_scope
                with patch.dict(b.REGISTRY,{workflow:(b.GROUP,'file',1,b.REGISTRY[workflow][3],ledger)}), \
                     patch.object(b,original_scope.__name__,return_value=(day,report.parent.name.rsplit('-',1)[-1])), \
                     patch.object(b,'verify_dependencies',return_value=True):
                    request,_=b.prepare(args)
                    b.assert_correction_origin(args,request)
                    fake=Fake();result=b.execute(args,adapter_factory=lambda:fake)
                    self.assertTrue(result['verified']);self.assertEqual(fake.calls,1)
                    self.assertEqual(b.execute(args,adapter_factory=lambda:fake)['newSendAttempts'],0)
                    self.assertEqual(fake.calls,1)
                    self.assertEqual(original_marker.read_bytes(),before)
                self.assertEqual(json.loads(corrected_marker.read_text())['payloads'][0]['sha256'],actual_hash)
    def test_correction_event_rejects_unverified_or_identical_original(self):
        args,day,report,ledger=self._correction_fixture('taobao-flash-appeals')
        orig=ledger/f'taobao-flash-appeals-{day}.json'
        with patch.dict(b.REGISTRY,{'taobao-flash-appeals':(b.GROUP,'file',1,b.REGISTRY['taobao-flash-appeals'][3],ledger)}):
            request,_=b.prepare(args)
        same=hashlib.sha256(report.read_bytes()).hexdigest()
        for state,verified,digest,expected in [('attempted',False,'0'*64,'original-not-verified'),
                                               ('verified',True,same,'original-payload-mismatch')]:
            atomic_json(orig,{'state':state,'verified':verified,'sendAttempts':1,'groupName':b.GROUP,'payloadType':'file',
                'payloads':[{'path':str(report),'name':report.name,'size':report.stat().st_size,'sha256':digest}]})
            with patch.dict(b.REGISTRY,{'taobao-flash-appeals':(b.GROUP,'file',1,b.REGISTRY['taobao-flash-appeals'][3],ledger)}):
                with self.assertRaisesRegex(Rejected,expected):b.assert_correction_origin(args,request)
    def test_correction_event_requires_exact_scope_and_mode(self):
        args,day,report,ledger=self._correction_fixture('meituan-waimai-appeals')
        with patch.object(b,'meituan_waimai_appeals_scope',return_value=(day,report.parent.name.rsplit('-',1)[-1])):
            with patch.dict(b.REGISTRY,{'meituan-waimai-appeals':(b.GROUP,'file',1,b.REGISTRY['meituan-waimai-appeals'][3],ledger)}):
                args.authorization='wrong'
                with self.assertRaisesRegex(Rejected,'authorization'):b.prepare(args)
                args.authorization=f'user-{report.parent.name.rsplit("-",1)[-1]}-meituan-waimai-appeals-correction-v1'
                args.reconcile=True
                with self.assertRaisesRegex(Rejected,'execute-only'):b.prepare(args)
    def run_bridge(self,fake=None):
        fake=fake or Fake();return b.execute(self.args,adapter_factory=lambda:fake)
    def old(self,**kw):
        req,_=b.prepare(self.args)
        value={'groupName':req['groupName'],'payloads':b.payloads(req),'state':'unknown','sendAttempts':1,'verified':False}|kw
        atomic_json(Path(self.args.ledger)/self.args.marker_name,value);return value
    def test_success_and_replay_without_ui(self):
        f=Fake();self.assertTrue(self.run_bridge(f)['verified']);self.assertTrue(self.run_bridge(f)['reusedExisting']);self.assertEqual(f.calls,1);self.assertEqual(f.lookups,1)
    def test_old_verified_no_ui(self):
        self.old(state='verified',verified=True);f=Fake();self.assertTrue(self.run_bridge(f)['ok']);self.assertEqual(f.lookups,0)
    def test_old_verified_explicit_reconcile_refreshes_proof_without_send(self):
        req,_=b.prepare(self.args);self.old(state='verified',verified=True,stage='post_send_verify');self.args.reconcile=True
        proof={'ok':True,'composerEmpty':True,'copyMenuCount':1,'copiedTextSha256':req['items'][0]['sha256'],
               'bubblePositions':[[1,2],[1,2]],'frameAnchors':[{'ok':True},{'ok':True}]}
        with patch('desktop_text_readback._copy_exact_bubble',return_value=proof):
            f=Fake();r=self.run_bridge(f)
        self.assertTrue(r['verified']);self.assertTrue(r['reconciledWithoutSend'])
        self.assertEqual(r['bridgeVersion'],1);self.assertEqual(r['physicalSendAttempts'],1);self.assertEqual(f.calls,0);self.assertEqual(f.lookups,1)
    def test_bridge_v1_unknown_reconcile_uses_native_copy_without_send(self):
        req,_=b.prepare(self.args)
        self.old(bridgeVersion=1,stage='post_send_verify');self.args.reconcile=True
        proof={'ok':True,'composerEmpty':True,'copyMenuCount':1,'copiedTextSha256':req['items'][0]['sha256'],
               'bubblePositions':[[1,2],[1,2]],'frameAnchors':[{'ok':True},{'ok':True}]}
        with patch('desktop_text_readback._copy_exact_bubble',return_value=proof):
            f=Fake();r=self.run_bridge(f)
        self.assertTrue(r['verified']);self.assertTrue(r['reconciledWithoutSend'])
        self.assertEqual(f.calls,0);self.assertEqual(f.lookups,1)

    def test_old_unknown_no_send(self):
        self.old();f=Fake();self.assertFalse(self.run_bridge(f)['ok']);self.assertEqual(f.lookups,0)
    def test_unknown_with_transport_sent_evidence_reuses_without_send(self):
        self.old(commonReceipt={'items':[{'transport':{'data':{'sent':True}}}]});f=Fake()
        r=self.run_bridge(f)
        self.assertTrue(r['ok']);self.assertTrue(r['reusedExisting']);self.assertEqual(r.get('verificationMethod'),'transport-sent-evidence')
        self.assertEqual(f.calls,0);self.assertEqual(f.lookups,0)
    def test_unknown_without_transport_sent_evidence_still_blocks(self):
        self.old(commonReceipt={'items':[{'transport':{'sendAttempts':1}}]},physicalSendAttempts=1);f=Fake()
        self.assertFalse(self.run_bridge(f)['ok']);self.assertEqual(f.calls,0)
    def test_blocked_never_sent_payload_drift_rebinds_and_sends(self):
        # 闪购实证：step1 每轮重生成 xlsx（sha 漂移），从未发出的 blocked 标记应重绑新字节而不是永久卡死
        self.old(state='blocked',sendAttempts=0,bridgeVersion=1)
        m=Path(self.args.ledger)/self.args.marker_name;v=json.loads(m.read_text())
        v['payloads'][0]['sha256']='f'*64;v['payloads'][0]['text']='changed'
        atomic_json(m,v)
        f=Fake();r=self.run_bridge(f)
        self.assertTrue(r['ok']);self.assertEqual(f.calls,1)
    def test_attempted_payload_drift_still_rejected(self):
        # 已发出（attempted）后内容漂移必须拒绝——防「换文件重发」
        self.old(state='attempted',sendAttempts=1,physicalSendAttempts=1)
        m=Path(self.args.ledger)/self.args.marker_name;v=json.loads(m.read_text())
        v['payloads'][0]['sha256']='f'*64;v['payloads'][0]['text']='changed'
        atomic_json(m,v)
        with self.assertRaisesRegex(Rejected,'binding-mismatch'):self.run_bridge()
    def test_check_old_never_sent_file_drift_name_still_enforced(self):
        new={'type':'file','name':'a.xlsx','size':20,'sha256':'2'*64,'path':'/x'}
        req={'groupName':'g','items':[new]}
        prior={'state':'blocked','sendAttempts':0,'groupName':'g','payloadType':'file',
               'payloads':[{'name':'a.xlsx','size':10,'sha256':'1'*64,'path':'/y'}]}
        b.check_old(prior,req)
        prior2=dict(prior);prior2['payloads']=[{'name':'b.xlsx','size':10,'sha256':'1'*64}]
        with self.assertRaisesRegex(Rejected,'binding-mismatch'):b.check_old(prior2,req)
        prior3=dict(prior);prior3['state']='attempted';prior3['sendAttempts']=1;prior3['physicalSendAttempts']=1
        with self.assertRaisesRegex(Rejected,'binding-mismatch'):b.check_old(prior3,req)
    def test_blocked_never_sent_stale_event_binding_rebinds_and_sends(self):
        # 事件层同源修复：binding.json 钉死旧内容摘要时，从未发出的标记应刷新绑定而不是永久 event-payload-conflict
        from contract import content_binding, event_key as _event_key
        from ledger import digest
        self.old(state='blocked',sendAttempts=0,bridgeVersion=1)
        req,_=b.prepare(self.args)
        import ledger as _ledger
        edir=Path(self.args.ledger)/'.wechat-messaging'/'events'/_ledger.event_key(req)
        edir.mkdir(parents=True,exist_ok=True)
        atomic_json(edir/'binding.json',{'digest':'0'*64})
        f=Fake();r=self.run_bridge(f)
        self.assertTrue(r['ok']);self.assertEqual(f.calls,1)
        self.assertNotEqual(json.loads((edir/'binding.json').read_text())['digest'],'0'*64)
    def test_event_lock_stale_binding_rejected_without_rebind(self):
        import ledger as _ledger
        from contract import Rejected as _Rejected
        req,_=b.prepare(self.args)
        root=Path(self.args.ledger)/'.wechat-messaging'
        edir=root/'events'/_ledger.event_key(req);edir.mkdir(parents=True,exist_ok=True)
        atomic_json(edir/'binding.json',{'digest':'0'*64})
        with self.assertRaisesRegex(_Rejected,'event-payload-conflict'):
            with _ledger.event_lock(root,req):
                pass
    def test_freeze_item_refreeze_only_when_never_sent(self):
        # 第四层：事件从未发出但早前失败档留下旧冻结字节 → 重冻结；attempted 档保持钉死
        import executor as _executor
        newfile=self.root/'new.xlsx';newfile.write_bytes(b'new-bytes')
        item={'type':'file','itemId':'0','name':'a.xlsx','path':str(newfile),
              'sha256':hashlib.sha256(b'new-bytes').hexdigest(),'size':9}
        work=self.root/'work';(work/'payload').mkdir(parents=True)
        stale=work/'payload'/'a.xlsx';stale.write_bytes(b'old-bytes');stale.chmod(0o400)
        frozen=_executor.freeze_item(item,work,allow_refreeze=True)
        self.assertEqual(stale.read_bytes(),b'new-bytes')
        self.assertEqual(stale.stat().st_mode & 0o777,0o400)
        stale.chmod(0o600);stale.write_bytes(b'old-bytes');stale.chmod(0o400)
        with self.assertRaisesRegex(Rejected,'frozen-payload-mismatch'):
            _executor.freeze_item(item,work)
    def test_old_verified_content_conflict(self):
        self.old(state='verified',verified=True);self.args.item=['changed']
        with self.assertRaisesRegex(Rejected,'binding-mismatch'):self.run_bridge()
    def test_wrong_group(self):
        self.args.group='臻肆测试群'
        with self.assertRaisesRegex(Rejected,'target'):self.run_bridge()
    def test_wrong_authorization(self):
        self.args.authorization='test-authorized'
        with self.assertRaisesRegex(Rejected,'authorization'):self.run_bridge()
    def test_wrong_ledger(self):
        self.args.ledger=str(self.root/'other')
        with self.assertRaisesRegex(Rejected,'ledger'):self.run_bridge()
    def test_path_traversal(self):
        self.args.marker_name='../event.json'
        with self.assertRaisesRegex(Rejected,'marker'):self.run_bridge()
    def test_unknown_blocks_replay(self):
        f=Fake(['unknown']);self.assertFalse(self.run_bridge(f)['ok']);second=self.run_bridge(f)
        self.assertFalse(second['ok']);self.assertEqual(second['newSendAttempts'],0);self.assertEqual(f.calls,1)
    def test_crash_blocks_replay(self):
        f=Fake(['crash']);self.assertFalse(self.run_bridge(f)['ok']);second=self.run_bridge(f)
        self.assertFalse(second['ok']);self.assertEqual(second['newSendAttempts'],0);self.assertEqual(f.calls,1)
    def test_confirmed_zero_attempt_can_retry_with_fresh_lookup(self):
        f=Fake(['blocked','verified']);self.assertFalse(self.run_bridge(f)['ok']);self.assertTrue(self.run_bridge(f)['ok']);self.assertEqual(f.lookups,2)
    def test_no_execute_rejects(self):
        self.args.execute=False
        with self.assertRaisesRegex(Rejected,'execute-required'):self.run_bridge()
    def test_dependency_failure_before_ui(self):
        f=Fake()
        with patch.object(b,'verify_dependencies',side_effect=Rejected('dependency-drift:scripts/example.py')):
            with self.assertRaises(b.PreDispatchDependencyFailure) as caught:self.run_bridge(f)
        receipt=b.exception_receipt(caught.exception)
        self.assertEqual(receipt['sendAttempts'],0)
        self.assertEqual(receipt['stage'],'dependency_integrity_preflight')
        self.assertEqual(receipt['items'],[])
        self.assertFalse((self.root/'ledger').exists())
        self.assertEqual(f.lookups,0)
        self.assertEqual(f.calls,0)

    def test_non_dependency_pre_dispatch_failure_is_not_zero(self):
        with patch.object(b,'verify_dependencies',side_effect=RuntimeError('unexpected')):
            with self.assertRaises(RuntimeError) as caught:self.run_bridge(Fake())
        receipt=b.exception_receipt(caught.exception)
        self.assertIsNone(receipt['sendAttempts'])
        self.assertNotIn('stage',receipt)

    def test_other_dependency_rejection_is_not_classified_as_zero(self):
        with patch.object(b,'verify_dependencies',side_effect=Rejected('authorization-drift')):
            with self.assertRaises(Rejected) as caught:self.run_bridge(Fake())
        receipt=b.exception_receipt(caught.exception)
        self.assertIsNone(receipt['sendAttempts'])
    def test_partial_batch_no_resend(self):
        paths=[]
        for n in (1,2):
            p=self.root/f'{n}.xlsx';p.write_bytes(b'bytes');paths.append(str(p))
        self.args.workflow_id='jinsha-reports';self.args.group=b.JINSHA_GROUP;self.args.payload_type='file';self.args.item=paths;self.args.authorization=b.REGISTRY['jinsha-reports'][3]
        with patch.dict(b.REGISTRY,{'jinsha-reports':(b.JINSHA_GROUP,'file',2,self.args.authorization,Path(self.args.ledger))}):
            f=Fake(['verified','unknown']);r=self.run_bridge(f);self.assertEqual(r['state'],'partial');self.assertFalse(r['verified']);self.assertFalse(self.run_bridge(f)['ok']);self.assertEqual(f.calls,2)
    def test_legacy_payload_type_cannot_change(self):
        self.old(state='verified',verified=True,payloadType='file')
        with self.assertRaisesRegex(Rejected,'type-mismatch'):self.run_bridge()
    def test_evidence_authorization_uses_resolved_tmp_path(self):
        from PIL import Image
        from datetime import datetime,timedelta
        from zoneinfo import ZoneInfo
        day=(datetime.now(ZoneInfo('Asia/Shanghai'))-timedelta(days=1)).strftime('%Y-%m-%d')
        evidence=self.root/'evidence';directory=evidence/(day+'-50459ecd-01cb-452a-9e9f-f78588871317');directory.mkdir(parents=True)
        paths=[directory/name for name in ['jinsha-store-final.png','jinsha-review-final.png']]
        for p in paths:Image.new('RGB',(20,20),'blue').save(p)
        self.args.workflow_id='taobao-evidence';self.args.group=b.GROUP;self.args.payload_type='image';self.args.item=list(map(str,paths))
        self.args.authorization='\n'.join([f'确认发送两张截图到 {b.GROUP}',f'业务日期 {day}']+[f'{p.name} {hashlib.sha256(p.read_bytes()).hexdigest()}' for p in paths])
        with patch.object(b,'EVIDENCE_ROOT',evidence),patch.dict(b.REGISTRY,{'taobao-evidence':(b.GROUP,'image',2,None,Path(self.args.ledger))}):
            f=Fake();self.assertTrue(self.run_bridge(f)['ok']);self.assertEqual(f.calls,2)
            self.args.item.reverse()
            with self.assertRaisesRegex(Rejected,'order-mismatch'):self.run_bridge(f)

    def test_evidence_single_image_partial_resend(self):
        # 2026-10-03 受控维护（大同授权「方案 B：开搞」）：taobao-evidence 允许 1..2 张，
        # 单张=当日只补缺失图的保序子集；授权话术按实际张数生成。
        from PIL import Image
        from datetime import datetime,timedelta
        from zoneinfo import ZoneInfo
        day=(datetime.now(ZoneInfo('Asia/Shanghai'))-timedelta(days=1)).strftime('%Y-%m-%d')
        evidence=self.root/'evidence2';directory=evidence/(day+'-50459ecd-01cb-452a-9e9f-f78588871317');directory.mkdir(parents=True)
        paths=[directory/name for name in ['jinsha-store-final.png','jinsha-review-final.png']]
        for p in paths:Image.new('RGB',(20,20),'red').save(p)
        self.args.workflow_id='taobao-evidence';self.args.group=b.GROUP;self.args.payload_type='image'
        self.args.item=[str(paths[1])]
        self.args.authorization='\n'.join([f'确认发送一张截图到 {b.GROUP}',f'业务日期 {day}']+[f'{paths[1].name} {hashlib.sha256(paths[1].read_bytes()).hexdigest()}'])
        with patch.object(b,'EVIDENCE_ROOT',evidence),patch.dict(b.REGISTRY,{'taobao-evidence':(b.GROUP,'image',(1,2),None,Path(self.args.ledger))}):
            f=Fake();self.assertTrue(self.run_bridge(f)['ok']);self.assertEqual(f.calls,1)
        # 零张不在 (1,2) 区间 → payload-mismatch
        bad=SimpleNamespace(**{**self.args.__dict__,'item':[]})
        with patch.object(b,'EVIDENCE_ROOT',evidence),patch.dict(b.REGISTRY,{'taobao-evidence':(b.GROUP,'image',(1,2),None,Path(self.args.ledger))}):
            with self.assertRaisesRegex(Rejected,'payload-mismatch'):b.prepare(bad)
        # 整对乱序仍被拒（order-mismatch 先于授权校验）
        self.args.item=[str(paths[1]),str(paths[0])]
        self.args.authorization='\n'.join([f'确认发送两张截图到 {b.GROUP}',f'业务日期 {day}']+[f'{p.name} {hashlib.sha256(p.read_bytes()).hexdigest()}' for p in [paths[1],paths[0]]])
        with patch.object(b,'EVIDENCE_ROOT',evidence),patch.dict(b.REGISTRY,{'taobao-evidence':(b.GROUP,'image',(1,2),None,Path(self.args.ledger))}):
            with self.assertRaisesRegex(Rejected,'order-mismatch'):b.prepare(self.args)
    def test_review_reports_failed_proof(self):
        r=self.run_bridge(Fake(['unknown']))
        row=next(x for x in r['sendReview'] if x['stage']=='send:0')
        self.assertEqual(row['status'],'failed');self.assertIsInstance(row['pitfalls'][0],dict)
        self.assertEqual(r['reviewSummary']['result'],'failed')
    def test_racing_old_claim_cannot_be_overwritten(self):
        real_open=Path.open;marker=(Path(self.args.ledger)/self.args.marker_name).resolve()
        def racing(path,*args,**kwargs):
            if path==marker and args and args[0]=='x':
                with real_open(path,'w') as out:out.write('{"state":"attempted"}')
            return real_open(path,*args,**kwargs)
        fake=Fake()
        with patch.object(Path,'open',racing):
            with self.assertRaises(FileExistsError):self.run_bridge(fake)
        self.assertEqual(fake.calls,0);self.assertEqual(fake.lookups,0)
        self.assertEqual(json.loads(marker.read_text()),{'state':'attempted'})
    def test_preflight_reuses_current_verified_group_without_search(self):
        from desktop_adapter import DesktopAdapter
        from unittest.mock import Mock
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.wd=Mock()
        adapter.sender=Mock()
        adapter.sender.focused_text_value.return_value=''
        adapter.wd.wechat_ax_state.return_value={'window':{'x':0,'y':0},'texts':[{'text':'臻肆测试群(3)','x':500,'y':30}]}
        adapter.preflight_module=Mock()
        adapter.preflight_module.run_exact_group_preflight.return_value={'ok':True}
        import time
        request={'groupName':'臻肆测试群','context':{'deadlineAt':time.time()+30}}
        self.assertTrue(adapter.preflight(request,self.root)['ok'])
        adapter.preflight_module.run_exact_group_preflight.assert_not_called()
    def test_media_failure_preserves_known_physical_attempt(self):
        from desktop_adapter import DesktopAdapter
        from unittest.mock import Mock
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.cleanup_owned_preview=Mock()
        adapter.sender=Mock()
        raw={'sendAttempts':1,'groupName':'臻肆测试群'}
        adapter.sender._send_locked.return_value=raw
        adapter.wait_media=Mock(side_effect=RuntimeError('capture-failed'))
        value=adapter.send_one({'groupName':'臻肆测试群'},{'type':'file','path':'/tmp/a'},self.root,{'authorizationRef':'test'},9999999999)
        self.assertEqual(value['status'],'unknown');self.assertEqual(value['sendAttempts'],1);self.assertIs(value['transport'],raw)
    def test_verified_file_transport_is_inherited_without_extra_page_probe(self):
        from desktop_adapter import DesktopAdapter
        from unittest.mock import Mock
        adapter=DesktopAdapter.__new__(DesktopAdapter);adapter.cleanup_owned_preview=Mock();adapter.sender=Mock();adapter.wait_media=Mock()
        adapter.wd=Mock();adapter.wd.exact_group_text.return_value=True
        raw={'ok':True,'verified':True,'state':'verified','sendAttempts':1,'groupName':'目标群',
             'postSendInputCleared':[True,True],'payloads':[{'sha256':'abc'}],
             'stage':'completed','groupPreflight':{'ok':True,'group':'目标群','header':'目标群','note':'exact-group-section-text-row'}}
        adapter.sender._send_locked.return_value=raw
        value=adapter.send_one({'groupName':'目标群'},{'type':'file','path':'/tmp/a','sha256':'abc'},self.root,{'authorizationRef':'test'},9999999999)
        self.assertEqual(value['status'],'verified');self.assertEqual(value['verificationLevel'],'file-name-size-ui')
        adapter.wait_media.assert_not_called()
    def test_verified_file_transport_reconcile_is_read_only(self):
        from desktop_adapter import DesktopAdapter
        from unittest.mock import Mock
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.wd=Mock();adapter.wd.exact_group_text.return_value=True;adapter.wd.ax_confirms_raw_group_header.return_value=True
        raw={'ok':True,'verified':True,'state':'verified','sendAttempts':1,'groupName':'目标群',
             'postSendInputCleared':[True,True],'payloads':[{'sha256':'abc'}],
             'groupPreflight':{'ok':True,'group':'目标群','header':'目标群','note':'exact-group-section-text-row'}}
        value=adapter.reconcile({'groupName':'目标群'},{'type':'file','sha256':'abc'},self.root,{'transport':raw})
        self.assertEqual(value['status'],'verified');self.assertEqual(value['sendAttempts'],0);self.assertTrue(value['reconciled'])
        with self.assertRaisesRegex(Rejected,'reconcile-binding-mismatch'):
            adapter.reconcile({'groupName':'其他群'},{'type':'file','sha256':'abc'},self.root,{'transport':raw})
    def test_verified_file_transport_reconcile_accepts_ax_current_group_with_member_count(self):
        from desktop_adapter import DesktopAdapter
        from unittest.mock import Mock
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.wd=Mock();adapter.wd.exact_group_text.return_value=True;adapter.wd.ax_confirms_raw_group_header.return_value=True
        raw={'ok':True,'verified':True,'state':'verified','sendAttempts':1,'groupName':'目标群',
             'postSendInputCleared':[True,True],'payloads':[{'sha256':'abc'}],
             'groupPreflight':{'ok':True,'group':'目标群','header':'目标群(81)','note':'ax-current-group-fast-path'}}
        value=adapter.reconcile({'groupName':'目标群'},{'type':'file','sha256':'abc'},self.root,{'transport':raw})
        self.assertEqual(value['status'],'verified');self.assertEqual(value['sendAttempts'],0);self.assertTrue(value['reconciled'])
    def test_text_reconcile_accepts_exact_native_copy_without_resend_baseline(self):
        from desktop_adapter import DesktopAdapter
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        text='测试正文\n第二行';sha=hashlib.sha256(text.encode()).hexdigest()
        request={'groupName':'臻肆测试群'};item={'type':'text','text':text,'sha256':sha}
        raw={'sendAttempts':1,'groupName':'臻肆测试群','payloads':[{'sha256':sha}],
             'postSendInputCleared':[True,True]}
        proof={'ok':True,'composerEmpty':True,'copyMenuCount':1,'copiedTextSha256':sha,
               'bubblePositions':[[100,200],[101,201]]}
        with patch('desktop_adapter._copy_exact_bubble',return_value=proof), \
             patch.object(adapter,'text_newness',side_effect=AssertionError('reconcile must not require send baseline')):
            value=adapter.reconcile(request,item,self.root,{'transport':raw})
        self.assertEqual(value['status'],'verified');self.assertEqual(value['sendAttempts'],0)
    def test_text_reconcile_rejects_wrong_native_copy_hash(self):
        from desktop_adapter import DesktopAdapter
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        text='测试正文\n第二行';sha=hashlib.sha256(text.encode()).hexdigest()
        request={'groupName':'臻肆测试群'};item={'type':'text','text':text,'sha256':sha}
        raw={'sendAttempts':1,'groupName':'臻肆测试群','payloads':[{'sha256':sha}],
             'postSendInputCleared':[True,True]}
        proof={'ok':True,'composerEmpty':True,'copyMenuCount':1,'copiedTextSha256':'wrong',
               'bubblePositions':[[100,200],[100,200]]}
        with patch('desktop_adapter._copy_exact_bubble',return_value=proof):
            value=adapter.reconcile(request,item,self.root,{'transport':raw})
        self.assertEqual(value['status'],'unknown');self.assertEqual(value['sendAttempts'],0)
    def test_all_production_bindings(self):
        # 2026-10-24 补同步：10-23 大同 11:41 授权的单件修复通道 jinsha-reports-taobao-repair-20261023
        # 已进 _BUILTIN_ROUTES（带独立授权/防重台账），当时漏更新本期望集导致离线测试红。
        self.assertEqual(set(b.REGISTRY),{'merchants','top10','taobao-evidence','jinsha-reports','jinsha-reports-taobao-repair-20260917','jinsha-reports-taobao-repair-20261023','negative-reviews','negative-reviews-summary','taobao-flash-appeals','meituan-waimai-appeals','taobao-flash-appeals-summary','meituan-waimai-appeals-summary','meituan-customer-reply-daily','negative-feedback-appeals'})
        self.assertNotIn('臻肆测试群',{v[0] for v in b.REGISTRY.values()})
    def test_appeals_go_to_operations_group_and_summary_card_is_image(self):
        # 2026-10-22 大同指定：两条申诉流的 Excel 结果表 + 汇总台账截图一律发运营群（原发员工群）。
        for wid in ('taobao-flash-appeals','meituan-waimai-appeals'):
            self.assertEqual(b.REGISTRY[wid][0],b.JINSHA_GROUP)
            self.assertEqual(b.REGISTRY[wid][1],'file')
        for wid in ('taobao-flash-appeals-summary','meituan-waimai-appeals-summary'):
            self.assertEqual(b.REGISTRY[wid][0],b.JINSHA_GROUP)
            self.assertEqual(b.REGISTRY[wid][1],'image')
            self.assertEqual(b.REGISTRY[wid][2],1)
    def test_negative_review_summary_is_image_to_operations_group(self):
        # 2026-10-22 大同要求：差评分析 Excel 发群后补发整表长图，独立 image 通道进同一运营群。
        group,kind,count,authorization,ledger=b.REGISTRY['negative-reviews-summary']
        self.assertEqual(group,b.JINSHA_GROUP)
        self.assertEqual(kind,'image')
        self.assertEqual(count,1)
        self.assertTrue(authorization.startswith('zhensi-negative-review-summary-'))
        self.assertNotEqual(authorization,b.REGISTRY['negative-reviews'][3])
        self.assertNotEqual(ledger,b.REGISTRY['negative-reviews'][4])
    def test_appeals_summary_card_binds_business_date_path_and_marker(self):
        for wid,prefix,flow_dir,day,run_key in (
                ('taobao-flash-appeals-summary','淘宝闪购差评申诉台账','taobao-flash-sale-negative-review-appeals','2026-09-21','20260922'),
                ('meituan-waimai-appeals-summary','美团外卖差评申诉台账','meituan-waimai-negative-review-appeals','2026-09-22','20260923')):
            group,kind,count,authorization,ledger=b.REGISTRY[wid]
            name=f'{prefix}-{day}.png'
            expected=b.PROJECT/'outputs'/f'{flow_dir}-{run_key}'/name
            expected.parent.mkdir(parents=True,exist_ok=True)
            created=not expected.exists()
            if created:
                from PIL import Image as _Image
                _Image.new('RGB',(8,8),(255,255,255)).save(expected,format='PNG')
            marker=f"{wid}-{day}.json"
            args=SimpleNamespace(workflow_id=wid,group=group,payload_type=kind,item=[str(expected)],
                authorization=authorization,ledger=str(ledger),marker_name=marker,
                output_dir=str(self.root/'out'),execute=True,reconcile=False,deadline_unix=None,
                correction_v1=False)
            scope=('taobao_flash_appeals_scope' if wid.startswith('taobao') else 'meituan_waimai_appeals_scope')
            try:
                with patch.object(b,scope,return_value=(day,run_key)):
                    request,_=b.prepare(args)
                    self.assertEqual(request['items'][0]['name'],name)
                    self.assertEqual(request['items'][0]['type'],'image')
                    wrong=self.root/name
                    from PIL import Image as _Image2
                    _Image2.new('RGB',(8,8),(255,255,255)).save(wrong,format='PNG')
                    args.item=[str(wrong)]
                    with self.assertRaisesRegex(Rejected,'appeals-summary-path-mismatch'):b.prepare(args)
                    args.item=[str(expected)];args.payload_type='file'
                    with self.assertRaisesRegex(Rejected,'target-or-payload-mismatch'):b.prepare(args)
                    args.payload_type='image';args.marker_name=f'{wid}-2026-09-20.json'
                    with self.assertRaisesRegex(Rejected,'appeals-summary-marker-mismatch'):b.prepare(args)
            finally:
                if created:expected.unlink()
    def test_each_active_workflow_routes_common(self):
        entries={'daily-agent-new-merchants-to-wechat':'desktop_wechat_sender.py','daily-top10-to-wechat-group':'workflow_executor.py','daily-taobao-download-to-jinsha':'desktop_wechat_evidence_sender.mjs','daily-jinsha-reports-to-business-wechat':'business_desktop_wechat_file_sender.py'}
        for skill,name in entries.items():
            # 2026-10-05：部分技能包已迁入 skills/workflows/（多一层），按两处位置择一解析。
            direct=b.SKILLS/skill/'scripts'/name
            source=((b.SKILLS/'workflows'/skill/'scripts'/name) if not direct.exists() else direct).read_text()
            # 2026-09-30：桌面微信停用后统一走 Windows 驱动传输。两者是同一 REGISTRY
            # 合同的唯一统一桥（workflow_bridge 的 Windows 变体），仍不接受私有发送链路。
            self.assertTrue(
                'wechat-messaging/scripts/workflow_bridge.py' in source
                or 'wechat-messaging/scripts/workflow_bridge_windows.py' in source,
                f'{skill}/{name} 未路由到统一微信桥')
            self.assertNotIn('wechat-desktop-control/scripts/desktop_sender.py',source)
    def test_legacy_reconcile_requires_strong_copy(self):
        req,_=b.prepare(self.args);prior=self.old(stage='post_send_verify');self.args.reconcile=True
        proof={'ok':True,'composerEmpty':True,'copyMenuCount':1,'copiedTextSha256':req['items'][0]['sha256'],'bubblePositions':[[1,2],[1,2]]}
        with patch('desktop_text_readback._copy_exact_bubble',return_value=proof):
            f=Fake();r=self.run_bridge(f);self.assertTrue(r['verified']);self.assertEqual(f.calls,0)
    def test_legacy_reconcile_bad_hash_not_verified(self):
        self.old(stage='post_send_verify');self.args.reconcile=True
        with patch('desktop_text_readback._copy_exact_bubble',return_value={'ok':True}):
            f=Fake();self.assertFalse(self.run_bridge(f)['verified']);self.assertEqual(f.calls,0)

    def test_legacy_reconcile_accepts_completed_unknown_wrapper(self):
        req,_=b.prepare(self.args);self.old(stage='completed', commonReceipt={'status':'unknown'});self.args.reconcile=True
        proof={'ok':True,'composerEmpty':True,'copyMenuCount':1,
               'copiedTextSha256':req['items'][0]['sha256'],'bubblePositions':[[1,2],[1,2]],
               'frameAnchors':[{'ok':True},{'ok':True}]}
        with patch('desktop_text_readback._copy_exact_bubble',return_value=proof):
            f=Fake();r=self.run_bridge(f)
        self.assertTrue(r['verified']);self.assertTrue(r['reconciledWithoutSend']);self.assertEqual(f.calls,0)

    def test_null_attempt_quartz_unknown_reconcile_is_read_only_and_preserves_unknown_count(self):
        req,_=b.prepare(self.args)
        reason='wechat-window-capture-failed:could not create image from window:quartz-window-capture-invalid'
        common={'status':'unknown','channel':'desktop','groupName':req['groupName'],
                'items':[{'status':'unknown','type':'text','sendAttempts':None,
                          'sha256':req['items'][0]['sha256']}],
                'review':[{'stage':'send:0','status':'failed','pitfalls':[reason]}]}
        self.old(bridgeVersion=1,stage='completed',sendAttempts=None,physicalSendAttempts=None,
                 reason=reason,commonReceipt=common)
        self.args.reconcile=True
        proof={'ok':True,'composerEmpty':True,'copyMenuCount':1,
               'copiedTextSha256':req['items'][0]['sha256'],'bubblePositions':[[1,2],[1,2]],
               'frameAnchors':[{'ok':True},{'ok':True}]}
        with patch('desktop_text_readback._copy_exact_bubble',return_value=proof):
            f=Fake();r=self.run_bridge(f)
        self.assertTrue(r['verified']);self.assertTrue(r['reconciledWithoutSend'])
        self.assertIsNone(r['sendAttempts']);self.assertIsNone(r['physicalSendAttempts'])
        self.assertEqual(f.calls,0);self.assertEqual(f.lookups,1)

    def test_null_attempt_unknown_requires_exact_failure_evidence(self):
        reason='wechat-window-capture-failed:could not create image from window:quartz-window-capture-invalid'
        req,_=b.prepare(self.args)
        common={'status':'unknown','channel':'desktop','groupName':req['groupName'],
                'items':[{'status':'unknown','type':'text','sendAttempts':None,
                          'sha256':req['items'][0]['sha256']}],
                'review':[{'stage':'send:0','status':'failed','pitfalls':['different-error']}]}
        self.old(bridgeVersion=1,stage='completed',sendAttempts=None,physicalSendAttempts=None,
                 reason=reason,commonReceipt=common)
        self.args.reconcile=True
        f=Fake();r=self.run_bridge(f)
        self.assertFalse(r['verified']);self.assertEqual(r['reason'],'legacy-attempt-reconcile-only')
        self.assertEqual(f.calls,0);self.assertEqual(f.lookups,0)

if __name__=='__main__':unittest.main()
