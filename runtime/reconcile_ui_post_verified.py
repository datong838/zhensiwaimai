"""Reconcile one original half-hour notice from timely UI evidence; never send."""
import sys,json,hashlib,fcntl,time,re,math
from pathlib import Path
from contextlib import ExitStack
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'skills/wechat-messaging/scripts'))
from ledger import atomic_json
from contract import event_key,content_binding,digest
from wecom_ui_queue import validate_response,QUEUE

def validate(task,reply,intent):
 original={k:v for k,v in task.items() if k!='binding'}
 if hashlib.sha256(json.dumps(original,sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=task['binding']:raise ValueError('task-binding-invalid')
 req=task['request'];ctx=req['context'];item=task['item']
 if (task['stage']!='send' or ctx['workflowId']!='merchants' or req['groupName']!='电销+直播攻坚组'
     or not re.fullmatch(r'empty-\d{12}\.json',Path(ctx['eventId']).name)
     or len(req['items'])!=1 or item.get('type')!='text' or item.get('text')!='当前无新增意向商家'
     or hashlib.sha256(item['text'].encode()).hexdigest()!=item['sha256']
     or req['items'][0]!=item):raise ValueError('scope-invalid')
 result=validate_response(task,reply)
 if result.get('status')!='verified' or result.get('sendAttempts')!=1:raise ValueError('response-not-verified')
 if any(intent.get(k)!=v for k,v in {'taskId':task['taskId'],'binding':task['binding'],'sha256':item['sha256'],'groupName':req['groupName'],'sendAttempts':1}.items()):raise ValueError('intent-binding-invalid')
 times=[intent.get('createdAt')]+[f.get('observedAt') for f in result['observations']]+[task['deadlineAt']]
 if any(type(t) not in (int,float) or not math.isfinite(t) for t in times) or not times[0]<=times[1]<times[2]<=times[3]:raise ValueError('evidence-time-invalid')
 return result

def reconcile(folder,apply=False):
 folder=Path(folder).resolve()
 if folder.parent!=QUEUE.resolve():raise ValueError('queue-root-invalid')
 task=json.loads((folder/'task.json').read_text())
 if not (folder/'claim.json').is_file():raise ValueError('claim-missing')
 proof=validate(task,json.loads((folder/'response.json').read_text()),json.loads((folder/'send-intent.json').read_text()))
 req=task['request'];item=task['item'];marker=Path(req['context']['eventId']).resolve()
 if marker.parent!=ROOT/'state/taobao-agent-new-merchants/send-attempts':raise ValueError('marker-root-invalid')
 event=marker.parent/'.wechat-messaging/events'/event_key(req)
 with ExitStack() as stack:
  for path in [marker.with_suffix('.bridge.lock'),event/'.lock']:
   h=stack.enter_context(path.open('a+'));fcntl.flock(h,fcntl.LOCK_EX|fcntl.LOCK_NB)
  if json.loads((event/'binding.json').read_text())!={'digest':digest(content_binding(req))}:raise ValueError('event-binding-invalid')
  ds=list(event.glob('*/delivery.json'))
  if len(ds)!=1:raise ValueError('delivery-count-invalid')
  prior=json.loads(marker.read_text());delivery=json.loads(ds[0].read_text());common=prior.get('commonReceipt',{})
  if (prior.get('state')!='unknown' or prior.get('sendAttempts')!=1 or prior.get('reason')!='ui-post-result-timeout'
      or prior.get('groupName')!=req['groupName'] or len(prior.get('payloads',[]))!=1
      or prior['payloads'][0].get('sha256')!=item['sha256']
      or delivery.get('status')!='unknown' or delivery.get('sendAttempts')!=1
      or delivery.get('reason')!='ui-post-result-timeout' or delivery.get('sha256')!=item['sha256']
      or common.get('eventKey')!=event_key(req) or len(common.get('items',[]))!=1
      or common['items'][0].get('sha256')!=item['sha256']
      or common['items'][0].get('status')!='unknown' or common['items'][0].get('sendAttempts')!=1):raise ValueError('prior-state-invalid')
  audit=marker.parent/'ui-post-reconciliation'/task['taskId']
  result={'ok':True,'applied':apply,'taskId':task['taskId'],'eventKey':event_key(req),'sendAttempts':1,'newSendAttempts':0,'reason':'timely-ui-evidence-returned-late','originalMarkerSha256':hashlib.sha256(marker.read_bytes()).hexdigest()}
  if apply:
   audit.mkdir(parents=True,exist_ok=False,mode=0o700)
   (audit/'original-marker.json').write_bytes(marker.read_bytes());(audit/'original-delivery.json').write_bytes(ds[0].read_bytes())
   transport=ds[0].parent/'transport/delivery-receipt.json'
   if transport.exists():(audit/'original-transport.json').write_bytes(transport.read_bytes())
   for name in ['task.json','response.json','send-intent.json']:(audit/name).write_bytes((folder/name).read_bytes())
   updated=delivery|proof|{'status':'verified','reason':None,'newSendAttempts':0,'reconciledWithoutSend':True}
   atomic_json(ds[0],updated);atomic_json(transport,proof)
   common.update(ok=True,status='verified',reason=None,items=[updated])
   prior.update(ok=True,verified=True,state='verified',reason=None,newSendAttempts=0,physicalSendAttempts=1,commonReceipt=common,copyReadback=proof['evidence'],postSendInputCleared=[True,True],reconciledWithoutSend=True,verificationMethod='wecom-ui-tree-text',uiPostReconciliation=str(audit/'proof.json'))
   atomic_json(marker,prior);atomic_json(audit/'proof.json',result)
  return result
if __name__=='__main__':print(json.dumps(reconcile(sys.argv[1],'--apply' in sys.argv[2:]),ensure_ascii=False))
