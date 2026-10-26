"""Original-director entry: bounded optimization segments, then one native UI notice."""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
BASE=Path(__file__).resolve().parents[1]
ROOT=BASE.parents[2]
STATE=BASE/'.runtime'
FLOW='daily-quality-products-optimization'
GROUP='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
NODE=os.environ.get('ZENSI_NODE','/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
sys.path.insert(0,str(ROOT/'skills/wechat-messaging/scripts'))
from ledger import atomic_json
from wecom_adapter import WeComAdapter,target_preflight_verified,LOCK_PATH,ui_tree_only_required


def day_now():return datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')

def notice(count,unconfirmed=0):
    return (f'淘宝闪购 优质商品率低 门店整改流程已按顺序执行完毕（今日执行了 {count} 家；其中 {unconfirmed} 家结果未确认，详见Excel）' if unconfirmed else f'淘宝闪购 优质商品率低 店铺全部店铺优化完成 （今日执行了 {count} 家）')

def integrity():
    policy=json.loads((BASE/'runtime-policy.json').read_text())
    if (policy.get('workflowId')!=FLOW or policy.get('browserPort')!=9231 or policy.get('accountName')!='zhangyanru188'
            or policy.get('groupName')!=GROUP or set(policy.get('files',{}))!={'scripts/quality_core.mjs','scripts/quality_optimizer.mjs','scripts/quality_workflow.py','scripts/quality_report.mjs'}):
        raise ValueError('quality-policy-scope-invalid')
    for name,sha in policy['files'].items():
        if hashlib.sha256((BASE/name).read_bytes()).hexdigest()!=sha:raise ValueError('quality-code-integrity-drift:'+name)
    from workflow_preflight import verify_dependencies
    verify_dependencies()


def optimize(execute):
    process=subprocess.run([NODE,str(BASE/'scripts/quality_optimizer.mjs'),'--execute' if execute else '--inspect'],capture_output=True,text=True)
    lines=[x for x in process.stdout.splitlines() if x.startswith('{')]
    if not lines:raise ValueError('quality-segment-no-receipt')
    return json.loads(lines[-1])


@contextlib.contextmanager
def immediate_ui_session():
    """Same original transport lock, nonblocking; UI ownership remains in original queue."""
    if not ui_tree_only_required():raise ValueError('quality-native-ui-only-required')
    LOCK_PATH.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    with LOCK_PATH.open('a+') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def recorded_unknown(store,day,folder):
    try:
        sub=store['submission'];rec=store['reconciliation'];fact=store['executionRecord']
        canonical=lambda value:hashlib.sha256(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        if not (store['state']=='unknown' and store.get('executionRecorded') is True and fact['day']==day and fact['kind']=='attempted-unconfirmed'
                and str(store['shopId']).isdigit() and sub['day']==day and sub['shopId']==store['shopId'] and sub['eventId']==day+'-quality-'+store['shopId']
                and fact['submissionSha256']==canonical(sub)==rec['submissionSha256'] and rec['mode']=='read-only' and fact['readonlyObservedAt']==rec['observedAt']
                and type(rec['currentTotal']) is int and rec['currentTotal']>=0):return False
        raw=(folder/'intents'/(store['shopId']+'.json')).read_bytes()
        return hashlib.sha256(raw).hexdigest()==fact['intentSha256'] and canonical(json.loads(raw))==canonical(sub)
    except (OSError,KeyError,TypeError,ValueError):return False


SINGLE_PASS='single-pass-per-day-v1'


def single_pass_notice(handled,unconfirmed=0,failed=0,row_errors=0):
    if failed or row_errors:return f'淘宝闪购 优质商品率低 门店整改流程已按顺序执行完毕（今日记录了 {handled} 家门店；{failed} 家未能执行，{unconfirmed} 家结果未确认，另有 {row_errors} 条访问异常，详见Excel）'
    return notice(handled,unconfirmed)


def real_daily_intent(store,day,folder):
    try:
        sub=store['submission'];shop=str(store['shopId'])
        if not (shop.isdigit() and sub['day']==day and sub['shopId']==shop and sub['eventId']==day+'-quality-'+shop):return False
        return json.loads((folder/'intents'/(shop+'.json')).read_text())==sub
    except (OSError,ValueError,KeyError,TypeError):return False


def single_pass_records(state,day,folder):
    records=[];optimized=[];checked=[];unconfirmed=[];failed=[]
    for store in state.get('stores',[]):
        if store.get('state')=='completed' and all(store.get('operation',{}).get(k) is True for k in ['confirmed','popoverClosed','uiStable']):
            optimized.append(store);label='已优化类目详情'
        elif store.get('state')=='checked_no_action':checked.append(store);label='已检查，无可优化项目'
        elif store.get('state') in ('unknown','attempted') and real_daily_intent(store,day,folder):unconfirmed.append(store);label='已发起优化，结果未确认；今日未重复提交'
        else:
            failed.append(store);label=('商品整改页面未能加载，未执行优化' if 'loading-timeout' in store.get('reason','') else '本次操作未能完成，今日未重复尝试')
        if store.get('operationError'):label+='；平台提示：'+'；'.join(str(x).strip() for x in store['operationError'])[:200]
        if store.get('skipCount') and store not in unconfirmed:label+='；当日重复记录已跳过'
        records.append({'shopId':store.get('shopId'),'name':store.get('name') or '门店名称未读取','execution':label})
    for error in state.get('rowErrors',[]):
        records.append({'shopId':None,'name':error.get('name') or f"门店名称未读取（第{error.get('page','?')}页第{error.get('row',0)+1}行）",'execution':'未能打开商品整改页面，未执行优化；今日未重复尝试'})
    return records,optimized,checked,unconfirmed,failed


def single_pass_completion(day,folder,result,state):
    basis=state.get('scopeFinishBasis',{});stores=state.get('stores',[])
    if not (state.get('day')==day and state.get('workflowId')==FLOW and state.get('executionPolicy')==SINGLE_PASS and state.get('scopeFinished') is True
            and state.get('accountLabel')=='zhangyanru188:全部门店' and state.get('cursor',{}).get('round')==1
            and basis.get('kind')=='single-sequential-pass-reached-last-page' and basis.get('round')==1 and basis.get('fromPage')==1 and basis.get('lastPage')==state['cursor']['page'] and basis.get('lastPageHasNext') is False
            and len({s['shopId'] for s in stores})==len(stores) and all(str(s['shopId']).isdigit() for s in stores) and result.get('ok') is True):raise ValueError('quality-single-pass-not-at-last-page')
    records,optimized,checked,unconfirmed,failed=single_pass_records(state,day,folder)
    payload={'executionPolicy':SINGLE_PASS,'day':day,'workflowId':FLOW,'accountName':'zhangyanru188','groupName':GROUP,'completed':len(optimized),'optimized':len(optimized),
             'checkedNoAction':len(checked),'attemptedUnconfirmed':len(unconfirmed),'failed':len(failed),'rowErrorCount':len(state.get('rowErrors',[])),
             'handled':len(stores),'recordRows':len(records),'stateSha256':hashlib.sha256((folder/'state.json').read_bytes()).hexdigest(),
             'completedShopIds':[s['shopId'] for s in optimized],'handledShopIds':[s['shopId'] for s in stores],'records':records,
             'text':single_pass_notice(len(stores),len(unconfirmed),len(failed),len(state.get('rowErrors',[]))),'observedAt':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
    target=folder/'completion.json'
    if target.exists():
        saved=json.loads(target.read_text())
        if any(saved.get(k)!=v for k,v in payload.items() if k!='observedAt'):raise ValueError('quality-completion-binding-changed')
        return saved
    atomic_json(target,payload);return payload


def completion(day,folder,result):
    source=folder/'state.json';state=json.loads(source.read_text());stores=state.get('stores',[])
    if state.get('executionPolicy')==SINGLE_PASS:return single_pass_completion(day,folder,result,state)
    optimized=[s for s in stores if s.get('state')=='completed'];checked=[s for s in stores if s.get('state')=='checked_no_action'];unconfirmed=[s for s in stores if recorded_unknown(s,day,folder)]
    if not (state.get('day')==day and state.get('workflowId')==FLOW and state.get('scopeFinished') is True
            and state.get('accountLabel')=='zhangyanru188:全部门店'
            and all((s.get('state') in ('completed','checked_no_action') or recorded_unknown(s,day,folder)) and str(s.get('shopId','')).isdigit() for s in stores)
            and len({s['shopId'] for s in stores})==len(stores)
            and result.get('ok') is True and result.get('summary',{}).get('completed')==len(optimized)):
        raise ValueError('quality-daily-execution-not-complete')
    records=[]
    for store in stores:
        if store['state']=='completed' and not all(store.get('operation',{}).get(k) is True for k in ['confirmed','popoverClosed','uiStable']):raise ValueError('quality-normal-operation-not-observed')
        label='已优化类目详情' if store['state']=='completed' else '已检查，无可优化项目'
        if store['state']=='unknown':
            if not recorded_unknown(store,day,folder):raise ValueError('quality-unconfirmed-execution-binding-invalid')
            label='已发起优化，结果未确认；今日未重复提交'
        elif store.get('technicalStatusPreserved')=='unknown':
            reconciliation=store.get('reconciliation',{});expected=hashlib.sha256(json.dumps(store.get('submission'),ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
            if not (reconciliation.get('mode')=='read-only' and reconciliation.get('resolved') is True and reconciliation.get('submissionSha256')==expected):raise ValueError('quality-read-only-reconciliation-binding-invalid')
            label='已只读核对，当前无可优化项；原提交结果未确认'
        if store['state']!='unknown' and store.get('skipCount',0):label+='；当日已执行，后续已跳过'
        records.append({'shopId':store['shopId'],'name':store['name'],'execution':label})
    payload={'day':day,'workflowId':FLOW,'accountName':'zhangyanru188','groupName':GROUP,'completed':len(optimized),'optimized':len(optimized),'checkedNoAction':len(checked),'attemptedUnconfirmed':len(unconfirmed),'handled':len(stores),
             'stateSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'completedShopIds':[s['shopId'] for s in optimized],
             'handledShopIds':[s['shopId'] for s in stores],'records':records,'text':notice(len(stores),len(unconfirmed)),'observedAt':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
    target=folder/'completion.json'
    if target.exists():
        saved=json.loads(target.read_text())
        if any(saved.get(k)!=v for k,v in payload.items() if k!='observedAt'):raise ValueError('quality-completion-binding-changed')
        return saved
    atomic_json(target,payload);return payload


def build_report(folder,proof):
    destination=folder/'report.json';target=folder/(proof['day']+'淘宝闪购商品整改执行台账.xlsx')
    if destination.exists():
        saved=json.loads(destination.read_text())
        if (Path(saved['file']).resolve()!=target.resolve() or saved['sourceSha256']!=hashlib.sha256((folder/'completion.json').read_bytes()).hexdigest()
                or saved['sha256']!=hashlib.sha256(target.read_bytes()).hexdigest() or saved['size']!=target.stat().st_size):raise ValueError('quality-frozen-report-binding-invalid')
        return saved
    node='/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
    process=subprocess.run([node,str(BASE/'scripts/quality_report.mjs'),'--proof',str(folder/'completion.json'),'--output',str(folder)],capture_output=True,text=True,check=False)
    lines=[x for x in process.stdout.splitlines() if x.startswith('{')]
    if not lines:raise ValueError('quality-report-no-receipt')
    result=json.loads(lines[-1])
    if process.returncode or result.get('ok') is not True:raise ValueError(result.get('reason','quality-report-failed'))
    return result


def schedule_continuation(result,now=None):
    """Program appends only itself to original control; never directly invokes a flow."""
    now=now or datetime.now(ZoneInfo('Asia/Shanghai'))
    if not (result.get('continuation') is True and result.get('summary',{}).get('pending',0)>0
            and result.get('reason') not in ('quality-yield-to-fixed-duty','quality-post-busy')
            and now.hour>=17):return False
    seconds_to_boundary=(30-now.minute%30)*60-now.second
    if seconds_to_boundary<75 or (now.hour==18 and 30<=now.minute<35):return False
    control=ROOT/'runtime/state/control.json';control.parent.mkdir(parents=True,exist_ok=True)
    before=control.read_text() if control.exists() else None
    try:data=json.loads(before) if before is not None else {}
    except ValueError:return False
    if not isinstance(data,dict):return False
    raw=data.get('force_run_now',[])
    names=[raw] if isinstance(raw,str) else raw
    if not isinstance(names,list) or any(not isinstance(n,str) for n in names):return False
    data['force_run_now']=list(dict.fromkeys(names+[FLOW]))
    # Parent director waits for this child, so its next control consumption is after return.
    # Decline a concurrent external edit; the scheduled 5-minute wake remains available.
    if (control.read_text() if control.exists() else None)!=before:return False
    atomic_json(control,data);return True


def run(*,execute=False,optimizer=optimize,adapter=None,session=immediate_ui_session,exporter=build_report):
    day=day_now();folder=STATE/'days'/day
    early_marker=folder/'delivery.json'
    if early_marker.exists():
        prior=json.loads(early_marker.read_text())
        if prior.get('state')=='verified':return {'ok':True,'status':'already_verified','newSendAttempts':0,'sendAttempts':0}
    integrity();folder.mkdir(parents=True,exist_ok=True,mode=0o700)
    with (folder/'run.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        marker=folder/'delivery.json'
        if marker.exists():
            old=json.loads(marker.read_text());ok=old.get('state')=='verified'
            return {'ok':ok,'status':'already_verified' if ok else 'unknown','reason':None if ok else 'prior-notification-requires-read-only-reconciliation','newSendAttempts':0,'sendAttempts':0}
        result=optimizer(execute)
        if not execute:return result
        if result.get('ok') is not True:
            result['continuationScheduled']=schedule_continuation(result)
            return result
        proof=completion(day,folder,result)
        report=exporter(folder,proof)
        text=proof['text'];caption={'itemId':'quality-optimization-completed','type':'text','text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
        item={'itemId':'quality-execution-ledger','type':'file','path':report['file'],'name':report['name'],'size':report['size'],'sha256':report['sha256']}
        deadline=int(time.time())+180
        request={'schemaVersion':1,'groupName':GROUP,'items':[item,caption],'context':{'workflowId':FLOW,'eventId':day+'-quality-optimization-completed','accountAlias':'main-wechat','channel':'desktop','deadlineAt':deadline}}
        atomic_json(folder/'request.json',request);transport=adapter or WeComAdapter();deliveries=[]
        try:
            with session():
                preflight=transport.preflight(request,folder/'preflight')
                if not target_preflight_verified(preflight,GROUP):return {'ok':False,'stage':'preflight','reason':preflight.get('reason','quality-target-not-verified'),'sendAttempts':0}
                grant={'schemaVersion':1,'accountAlias':'main-wechat','groupName':GROUP,'channel':'desktop','expiresAt':deadline,'authorizationRef':'user-20261026-quality-products-all-stores-optimization-and-notice'}
                for index,payload in enumerate(request['items']):
                    atomic_json(marker,{'state':'attempted','eventId':request['context']['eventId'],'currentItem':payload['itemId'],'deliveries':deliveries,'sendAttempts':None})
                    try:receipt=transport.send_one(request,payload,folder/('send-'+str(index)),grant,deadline)
                    except BaseException as error:
                        atomic_json(marker,{'state':'unknown','eventId':request['context']['eventId'],'currentItem':payload['itemId'],'deliveries':deliveries,'sendAttempts':None,'reason':str(error)});raise
                    deliveries.append({'itemId':payload['itemId'],'receipt':receipt})
                    if receipt.get('status')!='verified':break
        except BlockingIOError:return {'ok':False,'stage':'preflight','reason':'quality-ui-post-busy','sendAttempts':0}
        verified=len(deliveries)==2 and all(d['receipt'].get('status')=='verified' for d in deliveries);attempts=sum(d['receipt'].get('sendAttempts') or 0 for d in deliveries)
        atomic_json(marker,{'state':'verified' if verified else 'unknown','eventId':request['context']['eventId'],'deliveries':deliveries,'sendAttempts':attempts})
        return {'ok':verified,'stage':'notification','summary':result['summary'],'businessNote':(f"{proof.get('failed',0)}家未能执行，{proof['attemptedUnconfirmed']}家结果未确认，{proof.get('rowErrorCount',0)}条访问异常，详见执行台账" if proof['attemptedUnconfirmed'] or proof.get('failed') or proof.get('rowErrorCount') else '当日执行完成'),'deliveries':deliveries,'sendAttempts':attempts,'runtimeModelDecisions':0}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    try:result=run(execute=args.execute)
    except Exception as error:result={'ok':False,'stage':'stopped','reason':str(error),'sendAttempts':0}
    print(json.dumps(result,ensure_ascii=False));return 0 if result.get('ok') else 1
if __name__=='__main__':raise SystemExit(main())
