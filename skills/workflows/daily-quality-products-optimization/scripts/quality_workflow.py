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

def notice(count):return f'淘宝闪购 优质商品率低 店铺全部店铺优化完成 （今日执行了 {count} 家）'

def integrity():
    policy=json.loads((BASE/'runtime-policy.json').read_text())
    if (policy.get('workflowId')!=FLOW or policy.get('browserPort')!=9231 or policy.get('accountName')!='zhangyanru188'
            or policy.get('groupName')!=GROUP or set(policy.get('files',{}))!={'scripts/quality_core.mjs','scripts/quality_optimizer.mjs','scripts/quality_workflow.py'}):
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


def completion(day,folder,result):
    source=folder/'state.json';state=json.loads(source.read_text());stores=state.get('stores',[])
    if not (state.get('day')==day and state.get('workflowId')==FLOW and state.get('snapshotComplete') is True
            and state.get('finalReconciled') is True and state.get('accountLabel')=='zhangyanru188:全部门店'
            and type(state.get('total')) is int and state['total']==len(stores)
            and all(s.get('state')=='completed' and str(s.get('shopId','')).isdigit() for s in stores)
            and len({s['shopId'] for s in stores})==len(stores)
            and result.get('ok') is True and result.get('summary',{}).get('completed')==len(stores)):
        raise ValueError('quality-all-stores-completion-not-proven')
    for store in stores:
        before=store.get('before',{});after=store.get('after',{})
        if not ((before.get('total')==0 and before.get('products')==[])
                or ((store.get('submission',{}).get('state')=='observed' or (store.get('reconciliation',{}).get('mode')=='read-only' and store.get('reconciliation',{}).get('state')=='completed' and store.get('reconciliation',{}).get('submissionKey')==store.get('submission',{}).get('key'))) and after.get('total')==0 and after.get('products')==[])):
            raise ValueError('quality-remaining-product-problems')
    payload={'day':day,'workflowId':FLOW,'accountName':'zhangyanru188','groupName':GROUP,'completed':len(stores),
             'stateSha256':hashlib.sha256(source.read_bytes()).hexdigest(),'completedShopIds':[s['shopId'] for s in stores],
             'text':notice(len(stores)),'observedAt':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()}
    target=folder/'completion.json'
    if target.exists():
        saved=json.loads(target.read_text())
        if any(saved.get(k)!=v for k,v in payload.items() if k!='observedAt'):raise ValueError('quality-completion-binding-changed')
        return saved
    atomic_json(target,payload);return payload


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


def run(*,execute=False,optimizer=optimize,adapter=None,session=immediate_ui_session):
    integrity();day=day_now();folder=STATE/'days'/day;folder.mkdir(parents=True,exist_ok=True,mode=0o700)
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
        if proof['completed']==0:return {'ok':True,'status':'no-unfinished-stores','sendAttempts':0,'runtimeModelDecisions':0}
        text=proof['text'];item={'itemId':'quality-optimization-completed','type':'text','text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()}
        deadline=int(time.time())+180
        request={'schemaVersion':1,'groupName':GROUP,'items':[item],'context':{'workflowId':FLOW,'eventId':day+'-quality-optimization-completed','accountAlias':'main-wechat','channel':'desktop','deadlineAt':deadline}}
        atomic_json(folder/'request.json',request);transport=adapter or WeComAdapter()
        try:
            with session():
                preflight=transport.preflight(request,folder/'preflight')
                if not target_preflight_verified(preflight,GROUP):return {'ok':False,'stage':'preflight','reason':preflight.get('reason','quality-target-not-verified'),'sendAttempts':0}
                atomic_json(marker,{'state':'attempted','eventId':request['context']['eventId'],'sha256':item['sha256'],'sendAttempts':None})
                grant={'schemaVersion':1,'accountAlias':'main-wechat','groupName':GROUP,'channel':'desktop','expiresAt':deadline,'authorizationRef':'user-20261026-quality-products-all-stores-optimization-and-notice'}
                try:receipt=transport.send_one(request,item,folder/'send',grant,deadline)
                except BaseException as error:
                    atomic_json(marker,{'state':'unknown','eventId':request['context']['eventId'],'sha256':item['sha256'],'sendAttempts':None,'reason':str(error)});raise
        except BlockingIOError:return {'ok':False,'stage':'preflight','reason':'quality-ui-post-busy','sendAttempts':0}
        verified=receipt.get('status')=='verified'
        atomic_json(marker,{'state':'verified' if verified else 'unknown','eventId':request['context']['eventId'],'sha256':item['sha256'],'sendAttempts':receipt.get('sendAttempts'),'receipt':receipt})
        return {'ok':verified,'stage':'notification','summary':result['summary'],'delivery':receipt,'sendAttempts':receipt.get('sendAttempts'),'runtimeModelDecisions':0}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    try:result=run(execute=args.execute)
    except Exception as error:result={'ok':False,'stage':'stopped','reason':str(error),'sendAttempts':0}
    print(json.dumps(result,ensure_ascii=False));return 0 if result.get('ok') else 1
if __name__=='__main__':raise SystemExit(main())
