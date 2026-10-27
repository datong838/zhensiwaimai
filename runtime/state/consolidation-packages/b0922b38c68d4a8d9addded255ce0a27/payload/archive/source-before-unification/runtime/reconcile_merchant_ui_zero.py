"""Conclude the bounded merchant UI refusal as zero-send, preserving old facts."""
import fcntl
import hashlib
import json
import sys
import time
from contextlib import ExitStack
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/wechat-messaging/scripts'))
from contract import event_key,content_binding,digest
from ledger import atomic_json
from wecom_ui_queue import QUEUE

def reconcile(folder, apply=False):
    folder=Path(folder).resolve()
    if folder.parent != QUEUE.resolve():raise ValueError('task-root-invalid')
    task=json.loads((folder/'task.json').read_text());raw={k:v for k,v in task.items() if k!='binding'}
    if hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=task['binding']:raise ValueError('binding-invalid')
    reply=json.loads((folder/'response.json').read_text());result=reply['result'];request=task['request'];context=request['context'];marker=Path(context['eventId']).resolve()
    if task['stage']!='send' or reply['taskId']!=task['taskId'] or reply['binding']!=task['binding']:raise ValueError('response-binding-invalid')
    if (context['workflowId']!='merchants' or request['groupName']!='电销+直播攻坚组'
        or task['item'].get('text')!='当前无新增意向商家'
        or marker.parent!=ROOT/'state/taobao-agent-new-merchants/send-attempts'
        or not marker.name.startswith('empty-') or len(request['items'])!=1):raise ValueError('scope-invalid')
    if ((folder/'send-intent.json').exists() or not (folder/'claim.json').exists()
        or result.get('status')!='blocked' or type(result.get('sendAttempts')) is not int
        or result['sendAttempts']!=0 or result.get('reason')!='less-than-60-seconds-before-send'):raise ValueError('zero-not-proven')
    event=marker.parent/'.wechat-messaging/events'/event_key(request)
    if json.loads((event/'binding.json').read_text())!={'digest':digest(content_binding(request))}:raise ValueError('event-binding-invalid')
    deliveries=list(event.glob('*/delivery.json'))
    if len(deliveries)!=1:raise ValueError('delivery-count-invalid')
    with ExitStack() as stack:
        for path in [marker.with_suffix('.bridge.lock'),event/'.lock']:
            h=stack.enter_context(path.open('a+'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
        prior=json.loads(marker.read_text());delivery=json.loads(deliveries[0].read_text())
        if (prior.get('state')!='unknown' or prior.get('reason')!='ui-post-response-target-mismatch'
            or prior.get('sendAttempts') is not None or delivery.get('status')!='unknown'
            or delivery.get('sha256')!=task['item']['sha256']):raise ValueError('original-state-invalid')
        review=prior.get('commonReceipt',{}).get('review',[])
        if not any(x.get('stage')=='preflight' and x.get('status')=='completed' for x in review):raise ValueError('preflight-not-proven')
        proof={'ok':True,'taskId':task['taskId'],'sendAttempts':0,'applied':apply,'reason':'ui-post-confirmed-zero-send'}
        if apply:
            audit=marker.parent/'ui-post-reconciliation'/task['taskId'];audit.mkdir(parents=True,mode=0o700)
            for source in [marker,deliveries[0],folder/'task.json',folder/'response.json']:
                target=audit/(('delivery-' if source==deliveries[0] else '')+source.name)
                if target.exists():raise ValueError('audit-already-exists')
                target.write_bytes(source.read_bytes())
            atomic_json(audit/'proof.json',proof)
            delivery.update(status='blocked',sendAttempts=0,reason=proof['reason'],transport={'sent':False,'sendAttempts':0})
            atomic_json(deliveries[0],delivery)
            prior.update(state='blocked',sendAttempts=0,newSendAttempts=0,reason=proof['reason'],uiPostReconciliation=str(audit/'proof.json'))
            common=prior['commonReceipt'];common.update(status='blocked',reason=proof['reason'])
            for item in common.get('items',[]):item.update(status='blocked',sendAttempts=0,reason=proof['reason'])
            atomic_json(marker,prior)
        return proof
if __name__=='__main__':print(json.dumps(reconcile(sys.argv[1],'--apply' in sys.argv[2:]),ensure_ascii=False))
