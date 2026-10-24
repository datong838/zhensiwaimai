#!/usr/bin/env python3
"""Official task entry. Defaults to an offline plan, never an implicit send."""
from __future__ import annotations
import argparse
import contextlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from rotation_workflow import Workflow, WorkflowError, select_metrics
import ledger_ops

HERE=Path(__file__).resolve().parent;WF=HERE.parent;REPO=WF.parents[2]
FLOW='daily-store-metrics-rotation-to-wechat'

def run_json(argv,timeout,allow_status=False):
 try:r=subprocess.run([str(x) for x in argv],capture_output=True,text=True,timeout=timeout,env={k:v for k,v in os.environ.items() if k!='PYTHONPATH'})
 except subprocess.TimeoutExpired:raise WorkflowError('subprocess-timeout')
 parsed=None
 for line in reversed(r.stdout.splitlines()):
  try:parsed=json.loads(line);break
  except ValueError:pass
 if r.returncode:
  if allow_status and isinstance(parsed,dict) and parsed.get('status') in {'blocked','unknown','verified','already_verified','conflict'}:return parsed
  reason=parsed.get('reason','') if isinstance(parsed,dict) else ''
  raise WorkflowError(reason if isinstance(reason,str) and __import__('re').fullmatch('[a-z0-9-]+',reason) else 'brand-login-required' if any(k in (r.stdout+r.stderr).lower() for k in ['login-required','captcha','security']) else 'subprocess-failed')
 if parsed is not None:return parsed
 raise WorkflowError('subprocess-receipt-missing')

def renew_post_lease(path,pid):
 from rotation_workflow import atomic
 try:
  current=json.loads(path.read_text())
  if current.get('runId')!=FLOW or current.get('pid')!=pid:return False
  current['acquiredAt']=datetime.now().isoformat();atomic(path,current);return True
 except (OSError,ValueError):return False

@contextlib.contextmanager
def brand_lease():
 sys.path.insert(0,str(REPO/'runtime'))
 import run_all
 path=run_all.POST_GROUP_LOCK_DIR/'taobao-brand-9230.lock'
 inherited=False
 if path.exists():
  try:
   owner=json.loads(path.read_text());inherited=owner.get('runId')==FLOW and owner.get('pid')==os.getppid()
  except ValueError:raise WorkflowError('post-lease-invalid')
 lease=None if inherited else run_all.acquire_post_group_lock('taobao-brand-9230',FLOW)
 if not inherited and lease is None:raise WorkflowError('post-lease-busy')
 owner_pid=os.getppid() if inherited else os.getpid()
 stop=threading.Event();lost=threading.Event()
 def renew():
  while not stop.wait(20):
   if not renew_post_lease(path,owner_pid):lost.set();return
 def check():
  if lost.is_set():raise WorkflowError('post-lease-lost')
 thread=threading.Thread(target=renew,daemon=True);thread.start()
 try:yield check
 finally:
  stop.set();thread.join(timeout=1)
  if lease:run_all.release_post_group_lock(lease)

def main(argv=None):
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--mode',choices=['plan','capture','execute'],default='plan');ap.add_argument('--execute',action='store_true')
 ap.add_argument('--metrics',help='comma separated registered metric ids; absent means configured rotation')
 ap.add_argument('--date',default=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat());ap.add_argument('--ledger',type=Path)
 ap.add_argument('--config',type=Path,default=WF/'config/workflow.json');ap.add_argument('--runtime-dir',type=Path,default=WF/'.runtime')
 ap.add_argument('--group-map',type=Path);ap.add_argument('--output',type=Path);ap.add_argument('--limit',type=int)
 ap.add_argument('--authorization-ref',default='');ap.add_argument('--node',default=os.environ.get('ZENSI_NODE','/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'))
 ap.add_argument('--disarm',action='store_true');ap.add_argument('--arm',action='store_true')
 a=ap.parse_args(argv)
 from rotation_workflow import atomic
 if a.disarm or a.arm:
  if a.disarm and a.arm:raise WorkflowError('gate-arguments-conflict')
  atomic(a.runtime_dir/'send_gate.json',{'armed':not a.disarm});print(json.dumps({'armed':not a.disarm}));return 0
 mode='execute' if a.execute else a.mode
 if os.environ.get('ZHS_TEST_MODE')=='1' and mode!='plan':raise WorkflowError('test-live-boundary-forbidden')
 cfg=json.loads(a.config.read_text());day=datetime.strptime(a.date,'%Y-%m-%d').date();metrics=select_metrics(day,cfg,a.metrics.split(',') if a.metrics else None)
 p=a.ledger or ledger_ops.default_ledger()
 if '模板' in p.name:raise WorkflowError('template-ledger-forbidden')
 if p.name.startswith('全店铺运营指标商家反馈台账_') and day.strftime('%Y-%m') not in p.name:raise WorkflowError('ledger-month-mismatch')
 gm=a.group_map or a.runtime_dir/'group_map.json';mapping=None
 if gm.exists():
  doc=json.loads(gm.read_text());mapping=doc.get('map');
  if not isinstance(mapping,dict):raise WorkflowError('group-map-invalid')
 def probe(expect_chain=True):
  r=run_json([a.node,HERE/'brand_probe.mjs']+(['--expect-chain'] if expect_chain else []),20)
  if not r.get('ok'):raise WorkflowError('brand-login-required')
  return True
 check_lease=lambda:None
 def capture(shop,mid,out):
  check_lease()
  receipt=out/'capture-receipt.json'
  r=run_json([a.node,HERE/'capture_for_metric.mjs','--shop-id',shop['id'],'--shop-name',shop['name'],'--metric',mid,'--out',out,'--receipt',receipt],cfg['capture_timeout_seconds'])
  if not receipt.exists():raise WorkflowError('capture-receipt-missing')
  return json.loads(receipt.read_text())
 def send(shop,mid,image,d,auth):
  check_lease()
  return run_json([sys.executable,HERE/'deliver_metric.py','--runtime-dir',a.runtime_dir,'--ledger',p,'--shop-id',shop['id'],'--shop-name',shop['name'],'--metric',mid,'--image',image,'--group',shop['group'],'--date',d.isoformat(),'--commit','--authorization-ref',auth],cfg['delivery_timeout_seconds'],allow_status=True)
 w=Workflow(root=a.runtime_dir,ledger=p,day=day,metrics=metrics,group_map=mapping,capture=capture,send=send,probe=probe,throttle=cfg['throttle_seconds'],max_age=cfg['pool_max_age_days'])
 pool_total=len(w.pool)
 if a.limit is not None:
  if a.limit<1:raise WorkflowError('invalid-limit')
  w.pool=w.pool[:a.limit]
 if mode=='plan':result=w.run(mode)
 else:
  with brand_lease() as check_lease:
   probe(False);result=w.run(mode,a.authorization_ref)
 import hashlib
 baseline_files=[HERE/'rotation_workflow.py',HERE/'capture_for_metric.mjs',HERE/'capture_receipt.mjs',WF/'docs/metrics_catalog.json']
 result['executorBaselineHash']=hashlib.sha256(b''.join(f.read_bytes() for f in baseline_files)).hexdigest()
 result['sourcePoolTotal']=pool_total;result['scopeLimited']=len(w.pool)!=pool_total
 if a.output:atomic(a.output,result)
 print(json.dumps(result,ensure_ascii=False))
 return 0 if result['ok'] else 3

if __name__=='__main__':
 try:raise SystemExit(main())
 except WorkflowError as exc:print(json.dumps({'ok':False,'stage':str(exc),'reason':str(exc)},ensure_ascii=False));raise SystemExit(3)
