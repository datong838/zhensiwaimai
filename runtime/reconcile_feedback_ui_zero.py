"""Bound read-only conclusion of an unconsumed feedback send task; never sends."""
import fcntl, hashlib, json, sys, time
from pathlib import Path
from contextlib import ExitStack
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'skills/wechat-messaging/scripts'))
from contract import event_key,content_binding,digest
from ledger import atomic_json
from wecom_ui_queue import QUEUE,validate_response
GROUP='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
LEDGER=ROOT.parent/'state/negative-feedback-list-appeals/wechat-attempts'

def check_zero_evidence(task,reply,*,claimed,intent):
 raw={k:v for k,v in task.items() if k!='binding'}
 if hashlib.sha256(json.dumps(raw,sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=task['binding']:raise ValueError('task-binding-invalid')
 result=validate_response(task,reply);request=task['request'];context=request['context']
 if (task['stage']!='send' or context.get('workflowId')!='negative-feedback-appeals' or request.get('groupName')!=GROUP
     or len(request['items'])!=2 or any(i.get('type')!='file' or not i.get('name','').endswith('.xlsx') for i in request['items'])
     or any(task['item'].get(k)!=request['items'][0].get(k) for k in ['itemId','type','name','size','sha256'])):raise ValueError('scope-invalid')
 if (claimed or intent or result.get('status')!='blocked' or type(result.get('sendAttempts')) is not int or result['sendAttempts']!=0
     or result.get('reason')!='task-expired-before-consumption' or result.get('intentExists') is not False
     or type(result.get('actualSendActions')) is not int or result['actualSendActions']!=0 or result.get('inputEmpty') is not True):raise ValueError('zero-not-proven')
 return True

def reconcile(folder,apply=False):
 folder=Path(folder).resolve()
 if folder.parent!=QUEUE.resolve():raise ValueError('task-root-invalid')
 task=json.loads((folder/'task.json').read_text());reply=json.loads((folder/'response.json').read_text())
 check_zero_evidence(task,reply,claimed=(folder/'claim.json').exists(),intent=(folder/'send-intent.json').exists())
 request=task['request'];marker=Path(request['context']['eventId']).resolve()
 if marker.parent!=LEDGER.resolve() or marker.suffix!='.json':raise ValueError('marker-scope-invalid')
 event=marker.parent/'.wechat-messaging/events'/event_key(request)
 if json.loads((event/'binding.json').read_text())!={'digest':digest(content_binding(request))}:raise ValueError('event-binding-invalid')
 files=list(event.glob('*/delivery.json'))
 if len(files)!=1:raise ValueError('delivery-count-invalid')
 with ExitStack() as stack:
  for p in [marker.with_suffix('.bridge.lock'),event/'.lock']:
   h=stack.enter_context(p.open('a+'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
  prior=json.loads(marker.read_text());delivery=json.loads(files[0].read_text())
  if (prior.get('state')!='unknown' or prior.get('reason')!='ui-post-result-timeout' or prior.get('sendAttempts')!=1
      or delivery.get('status')!='unknown' or delivery.get('reason')!='ui-post-result-timeout' or delivery.get('sha256')!=task['item']['sha256']):raise ValueError('original-state-invalid')
  if not any(x.get('stage')=='preflight' and x.get('status')=='completed' for x in prior.get('commonReceipt',{}).get('review',[])):raise ValueError('preflight-not-proven')
  for item in request['items']+[task['item']]:
   if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('source-changed')
  proof={'ok':True,'taskId':task['taskId'],'applied':apply,'sendAttempts':0,'newSendAttempts':0,'reason':'ui-post-confirmed-zero-send'}
  if apply:
   audit=marker.parent/'ui-post-reconciliation'/str(time.time_ns());audit.mkdir(parents=True,mode=0o700)
   for name,p in [('marker',marker),('delivery',files[0]),('task',folder/'task.json'),('response',folder/'response.json')]: (audit/(name+'.json')).write_bytes(p.read_bytes())
   atomic_json(audit/'proof.json',proof)
   delivery.update(status='blocked',sendAttempts=0,reason=proof['reason'],transport={'sent':False,'sendAttempts':0});atomic_json(files[0],delivery)
   prior.update(state='blocked',sendAttempts=0,newSendAttempts=0,reason=proof['reason'],uiPostReconciliation=str(audit/'proof.json'))
   prior['commonReceipt'].update(status='blocked',ok=False,reason=proof['reason'])
   for item in prior['commonReceipt'].get('items',[]):item.update(status='blocked',sendAttempts=0,reason=proof['reason'])
   atomic_json(marker,prior)
  return proof
if __name__=='__main__':print(json.dumps(reconcile(sys.argv[1],'--apply' in sys.argv[2:]),ensure_ascii=False))
