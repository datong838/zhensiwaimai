"""Bound zero-send conclusion for the original UI-post event. No UI or sends."""
import sys,json,hashlib,fcntl,time
from pathlib import Path
from contextlib import ExitStack
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/wechat-messaging/scripts'))
from contract import event_key, content_binding, digest
from ledger import atomic_json
from wecom_ui_queue import validate_response,QUEUE

def reconcile(folder,apply=False):
 folder=Path(folder).resolve()
 if folder.parent!=QUEUE.resolve():raise ValueError('task-root-invalid')
 task=json.loads((folder/'task.json').read_text());original={k:v for k,v in task.items() if k!='binding'}
 if hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=task['binding']:raise ValueError('task-digest-invalid')
 if task['stage']!='send' or not (folder/'claim.json').exists() or (folder/'send-intent.json').exists():raise ValueError('zero-send-not-proven')
 result=validate_response(task,json.loads((folder/'response.json').read_text()))
 if result.get('status')!='blocked' or type(result.get('sendAttempts')) is not int or result['sendAttempts']!=0 or result.get('inputEmpty') is not True:raise ValueError('zero-response-invalid')
 request=task['request'];marker=Path(request['context']['eventId']).resolve()
 if not marker.is_relative_to(ROOT/'.local/state') or request['context']['workflowId']!='negative-reviews-summary':raise ValueError('scope-invalid')
 event=marker.parent/'.wechat-messaging/events'/event_key(request)
 if json.loads((event/'binding.json').read_text())!={'digest':digest(content_binding(request))}:raise ValueError('event-binding-invalid')
 deliveries=list(event.glob('*/delivery.json'))
 if len(deliveries)!=1:raise ValueError('delivery-count-invalid')
 with ExitStack() as stack:
  for lock in [marker.with_suffix('.bridge.lock'),event/'.lock']:
   h=stack.enter_context(lock.open('a+'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
  prior=json.loads(marker.read_text());delivery=json.loads(deliveries[0].read_text())
  if prior.get('state')!='attempted' or prior.get('sendAttempts') is not None or delivery.get('status')!='attempted' or delivery.get('sha256')!=task['item']['sha256']:raise ValueError('original-claim-invalid')
  if hashlib.sha256(Path(task['item']['path']).read_bytes()).hexdigest()!=task['item']['sha256']:raise ValueError('source-changed')
  proof={'ok':True,'sendAttempts':0,'applied':apply,'taskId':task['taskId'],'eventKey':event_key(request),'reason':'ui-post-confirmed-zero-send','originalMarkerSha256':hashlib.sha256(marker.read_bytes()).hexdigest()}
  if apply:
   audit=marker.parent/'ui-post-reconciliation'/str(time.time_ns());audit.mkdir(parents=True,mode=0o700)
   (audit/'original-marker.json').write_bytes(marker.read_bytes());(audit/'original-delivery.json').write_bytes(deliveries[0].read_bytes());atomic_json(audit/'proof.json',proof)
   delivery.update(status='blocked',sendAttempts=0,reason=proof['reason'],uiPostTask=task['taskId'],transport={'sent':False,'sendAttempts':0})
   atomic_json(deliveries[0],delivery)
   prior.update(state='blocked',sendAttempts=0,newSendAttempts=0,reason=proof['reason'],uiPostReconciliation=str(audit/'proof.json'))
   atomic_json(marker,prior)
  return proof
if __name__=='__main__':print(json.dumps(reconcile(sys.argv[1],'--apply' in sys.argv[2:]),ensure_ascii=False))
