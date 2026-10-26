import contextlib
import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
spec=importlib.util.spec_from_file_location('quality_workflow',Path(__file__).resolve().parents[1]/'scripts/quality_workflow.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
from registered_ui_routes import quality_optimization_allowed
class Adapter:
    def __init__(self,status='verified',ready=True):self.status=status;self.ready=ready;self.calls=[]
    def preflight(self,request,folder):return {'ok':self.ready,'resolvedGroup':w.GROUP,'inputEmpty':True,'verificationLevel':'wecom-ui-tree-target'}
    def send_one(self,request,item,*args):self.calls.append(item);return {'status':self.status,'sendAttempts':1}
class Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name);self.state=self.root/'skills/workflows/daily-quality-products-optimization/.runtime';self.folder=self.state/'days/2026-10-26';self.folder.mkdir(parents=True)
        for p in [patch.object(w,'STATE',self.state),patch.object(w,'integrity'),patch.object(w,'day_now',return_value='2026-10-26')]:p.start();self.addCleanup(p.stop)
        self.original={'day':'2026-10-26','workflowId':w.FLOW,'scopeFinished':True,'accountLabel':'zhangyanru188:全部门店','stores':[{'state':'completed','shopId':'546721968','name':'示例门店','operation':{'confirmed':True,'popoverClosed':True,'uiStable':True},'skipCount':2}]}
        self.result={'ok':True,'summary':{'ok':True,'completed':1}}
        self.optimizer=Mock(return_value=self.result)
        self.write(self.original)
    def write(self,state):self.original=state;(self.folder/'state.json').write_text(json.dumps(state,ensure_ascii=False))
    def export(self,folder,proof):
        f=folder/(proof['day']+'淘宝闪购商品整改执行台账.xlsx');f.write_bytes(b'fixture-xlsx');result={'ok':True,'file':str(f),'name':f.name,'size':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'rows':len(proof['records']),'sourceSha256':hashlib.sha256((folder/'completion.json').read_bytes()).hexdigest()};(folder/'report.json').write_text(json.dumps(result));return result
    def run_flow(self,adapter=None,session=contextlib.nullcontext):return w.run(execute=True,optimizer=self.optimizer,adapter=adapter or Adapter(),session=session,exporter=self.export)
    def test_complete_text_once_then_no_optimizer_or_resend(self):
        a=Adapter();r=self.run_flow(a);self.assertTrue(r['ok']);r=self.run_flow(a);self.assertEqual(r['status'],'already_verified');self.assertEqual(len(a.calls),2);self.assertEqual(self.optimizer.call_count,1);self.assertEqual([i['type'] for i in a.calls],['file','text']);self.assertEqual(a.calls[1]['text'],w.notice(1))
    def test_unknown_notice_never_retries(self):
        a=Adapter(status='unknown');self.assertFalse(self.run_flow(a)['ok']);self.assertEqual(self.run_flow(a)['status'],'unknown');self.assertEqual(len(a.calls),1);self.assertEqual(self.optimizer.call_count,1)
    def test_pending_segment_never_opens_notification(self):
        self.optimizer.return_value={'ok':False,'continuation':True,'summary':{'completed':0}};a=Adapter();self.assertFalse(self.run_flow(a)['ok']);self.assertEqual(a.calls,[]);self.assertFalse((self.folder/'completion.json').exists())
    def test_manual_unknown_blocked_never_full_completion(self):
        for value in ['manual_required','unknown','blocked','pending']:
            state=copy.deepcopy(self.original);state['stores'][0]['state']=value;self.write(state)
            with self.assertRaisesRegex(ValueError,'not-complete'):self.run_flow()
    def test_remaining_problems_do_not_block_normal_daily_action(self):
        state=copy.deepcopy(self.original);state['stores'][0]['after']={'total':8,'visibleProducts':8};self.write(state)
        self.assertTrue(self.run_flow()['ok'])
    def test_no_normal_confirmation_never_claims_success(self):
        state=copy.deepcopy(self.original);state['stores'][0]['operation']['confirmed']=False;self.write(state)
        with self.assertRaisesRegex(ValueError,'not-observed'):self.run_flow()
    def test_read_only_resolved_unknown_is_not_counted_as_optimized(self):
        state=copy.deepcopy(self.original);store=state['stores'][0];store['state']='checked_no_action';store['technicalStatusPreserved']='unknown';store['submission']={'day':'2026-10-26','shopId':store['shopId'],'state':'attempted'}
        sha=hashlib.sha256(json.dumps(store['submission'],ensure_ascii=False,separators=(',',':')).encode()).hexdigest();store['reconciliation']={'mode':'read-only','resolved':True,'submissionSha256':sha};self.write(state);self.optimizer.return_value={'ok':True,'summary':{'completed':0}}
        a=Adapter();self.assertTrue(self.run_flow(a)['ok']);self.assertEqual(a.calls[-1]['text'],w.notice(1));proof=json.loads((self.folder/'completion.json').read_text());self.assertIn('原提交结果未确认',proof['records'][0]['execution']);self.assertEqual(store['submission']['state'],'attempted')
    def test_notice_count_includes_optimized_and_checked_and_matches_excel_rows(self):
        state=copy.deepcopy(self.original);state['stores'].append({'state':'checked_no_action','shopId':'520411538','name':'无需优化示例门店'});self.write(state)
        a=Adapter();self.assertTrue(self.run_flow(a)['ok']);self.assertEqual(a.calls[-1]['text'],w.notice(2));proof=json.loads((self.folder/'completion.json').read_text());self.assertEqual((proof['optimized'],proof['checkedNoAction'],proof['handled']),(1,1,2));self.assertEqual(len(proof['records']),2)
    def test_unbound_read_only_fact_is_rejected(self):
        state=copy.deepcopy(self.original);state['stores'][0].update({'state':'checked_no_action','technicalStatusPreserved':'unknown','reconciliation':{'mode':'read-only','resolved':True,'submissionSha256':'wrong'}});self.write(state);self.optimizer.return_value={'ok':True,'summary':{'completed':0}}
        with self.assertRaisesRegex(ValueError,'reconciliation-binding-invalid'):self.run_flow()
    def test_preflight_zero_send_resume_same_completion(self):
        a=Adapter(ready=False);self.assertFalse(self.run_flow(a)['ok']);self.assertFalse((self.folder/'delivery.json').exists());a.ready=True;self.assertTrue(self.run_flow(a)['ok']);self.assertEqual(len(a.calls),2)
    def test_busy_ui_does_not_wait_or_send(self):
        @contextlib.contextmanager
        def busy():raise BlockingIOError();yield
        a=Adapter();r=self.run_flow(a,session=busy);self.assertEqual(r['reason'],'quality-ui-post-busy');self.assertEqual(a.calls,[]);self.assertFalse((self.folder/'delivery.json').exists())
    def request(self):
        proof=w.completion('2026-10-26',self.folder,self.result);report=self.export(self.folder,proof);text=proof['text'];return {'groupName':w.GROUP,'context':{'workflowId':w.FLOW,'eventId':'2026-10-26-quality-optimization-completed','accountAlias':'main-wechat','channel':'desktop'},'items':[{'itemId':'quality-execution-ledger','type':'file','path':report['file'],'name':report['name'],'size':report['size'],'sha256':report['sha256']},{'itemId':'quality-optimization-completed','type':'text','text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}]}
    def test_route_requires_frozen_all_completed_binding(self):
        request=self.request();self.assertTrue(quality_optimization_allowed(request,root=self.root,day='2026-10-26'))
        for bad in [request|{'groupName':'wrong'},request|{'items':[]},request|{'context':request['context']|{'eventId':'2026-10-27-quality-optimization-completed'}}]:self.assertFalse(quality_optimization_allowed(bad,root=self.root,day='2026-10-26'))
        self.assertFalse(quality_optimization_allowed(request,root=self.root,day='2026-10-27'))
        self.write(self.original|{'scopeFinished':False});self.assertFalse(quality_optimization_allowed(request,root=self.root,day='2026-10-26'))
    def test_route_does_not_trust_changed_count_or_text(self):
        request=self.request();request['items'][1]['text']=w.notice(251);self.assertFalse(quality_optimization_allowed(request,root=self.root,day='2026-10-26'))
    def test_schedule_is_customer_then_new_flow_without_success_dependency(self):
        data=json.loads((Path(__file__).resolve().parents[4]/'runtime/skills_manifest.json').read_text());skills={s['name']:s for s in data['skills']};new=skills[w.FLOW];customer=skills['meituan-intelligent-customer-service'];appeal=skills['meituan-waimai-negative-review-appeals-11']
        self.assertEqual(new['ledger_name'],'淘宝闪购低优质商品的全部门店商品整改优化');self.assertEqual(new['schedule_times'],['17:00']);self.assertLess(customer['order'],new['order']);self.assertLess(new['order'],appeal['order']);self.assertEqual(new.get('depends_on',[]),[]);self.assertEqual((new['max_retries'],new['cooldown_seconds']),(0,0));self.assertEqual(customer['max_retries'],0)
        post=data['ledger_template'][-1];self.assertEqual(post['skill'],w.FLOW);self.assertEqual(post['row'],24)
    def test_partial_main_is_nonzero_never_success(self):
        import io
        result={'ok':False,'continuation':True,'summary':{'pending':230,'completed':21}}
        with patch.object(w.sys,'argv',['quality_workflow.py','--execute']),patch.object(w,'run',return_value=result),contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(w.main(),1)

    def test_program_continuation_preserves_other_controls_and_never_launches(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        p=self.root/'runtime/state/control.json';p.parent.mkdir(parents=True)
        p.write_text(json.dumps({'force_run':['other'],'force_run_now':['already-waiting'],'reason':'keep-this'}))
        result={'continuation':True,'summary':{'pending':230}}
        with patch.object(w,'ROOT',self.root),patch.object(w.subprocess,'run') as launch:
            for _ in range(2):self.assertTrue(w.schedule_continuation(result,datetime(2026,10,26,17,5,tzinfo=ZoneInfo('Asia/Shanghai'))))
            launch.assert_not_called()
        actual=json.loads(p.read_text());self.assertEqual(actual['force_run'],['other']);self.assertEqual(actual['reason'],'keep-this');self.assertEqual(actual['force_run_now'],['already-waiting',w.FLOW])
    def test_fixed_slots_unknown_only_and_yield_never_busy_requeue(self):
        from datetime import datetime
        from zoneinfo import ZoneInfo
        with patch.object(w,'ROOT',self.root):
            for hour,minute,second in [(16,59,0),(17,29,0),(18,30,0),(18,34,0)]:
                self.assertFalse(w.schedule_continuation({'continuation':True,'summary':{'pending':3}},datetime(2026,10,26,hour,minute,second,tzinfo=ZoneInfo('Asia/Shanghai'))))
            self.assertFalse(w.schedule_continuation({'continuation':True,'summary':{'pending':0,'unknown':3}},datetime(2026,10,26,17,5,tzinfo=ZoneInfo('Asia/Shanghai'))))
            self.assertFalse(w.schedule_continuation({'continuation':True,'reason':'quality-yield-to-fixed-duty','summary':{'pending':3}},datetime(2026,10,26,17,5,tzinfo=ZoneInfo('Asia/Shanghai'))))
        self.assertFalse((self.root/'runtime/state/control.json').exists())
    def test_retry_wake_uses_existing_director_five_minute_support(self):
        import fixed_schedule
        from datetime import datetime
        data=json.loads((Path(__file__).resolve().parents[4]/'runtime/skills_manifest.json').read_text());skill=next(s for s in data['skills'] if s['name']==w.FLOW)
        self.assertEqual(fixed_schedule.next_boundary([skill],datetime(2026,10,26,17,3)),datetime(2026,10,26,17,5))
        self.assertEqual(fixed_schedule.gate(skill,datetime(2026,10,26,17,5),None),(False,''))

    def test_director_continues_to_optimizer_after_customer_failure(self):
        import run_all
        data=json.loads((Path(__file__).resolve().parents[4]/'runtime/skills_manifest.json').read_text())
        data['skills']=[s for s in data['skills'] if s['name'] in (w.FLOW,'meituan-intelligent-customer-service')]
        calls=[]
        def run(data,name,interpreters):calls.append(name);return {'category':'UNKNOWN','status':'FAILED','finished_at':'2026-10-26T17:02:00'}
        with contextlib.ExitStack() as stack:
            for name,value in [('login_health_gate',None),('merchant_priority_checkpoint',None),('write_ledger_xlsx',False),('_maybe_send_ledger',None),('write_last_cycle',None),('record_outcome',None),('build_ledger_rows',[])]:stack.enter_context(patch.object(run_all,name,return_value=value))
            stack.enter_context(patch.object(run_all,'pop_forced_runs',return_value=([],None)))
            stack.enter_context(patch.object(run_all,'_cadence_gate',return_value=(False,'')))
            stack.enter_context(patch.object(run_all,'alert_store',None))
            stack.enter_context(patch.object(run_all.aw,'run_auth_watch',return_value=[]))
            stack.enter_context(patch('group_consistency_check.check_flow',return_value=[]))
            stack.enter_context(patch('triage.run_triage'))
            stack.enter_context(patch.object(run_all,'run_one',side_effect=run))
            run_all.daemon_cycle(data,{},False)
        self.assertEqual(calls,['meituan-intelligent-customer-service',w.FLOW])

if __name__=='__main__':unittest.main()
