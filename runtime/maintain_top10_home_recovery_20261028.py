"""Scoped, reviewed installation of two pre-send navigation repairs; no business run."""
import argparse
from contextlib import ExitStack
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent.parent
EVIDENCE=ROOT/'runtime/state/top10-home-recovery-20261028'
BASE_REV='4275b1e6'
SPECS={
 'taobao':('skills/workflows/daily-top10-to-wechat-group','scripts/desktop_background_executor.mjs','background_executor','taobao-brand-9230','/tmp/zhensi-post-9230.lock'),
 'meituan':('skills/workflows/daily-meituan-income-top10-to-wechat','scripts/income_collector.mjs','scripts/income_collector.mjs','meituan-9233','/tmp/zhensi-post-9233.lock'),
}
NODE='/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'

def sha(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(path.read_text())
def write(path,value):path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def original_bytes(relative):return subprocess.check_output(['git','show',BASE_REV+':'+relative],cwd=ROOT)
def paths(role):
 base,source,*_=SPECS[role]
 return ROOT/base/source,ROOT/base/'runtime-policy.json'
def pin(policy,role):
 value=policy['files'][SPECS[role][2]]
 return value['sha256'] if role=='taobao' else value

def validate_originals():
 result={}
 for role in SPECS:
  source,policy=paths(role);back=EVIDENCE/'originals'
  for target,backup in [(source,back/(role+'.mjs')),(policy,back/(role+'-policy.json'))]:
   expected=original_bytes(str(target.relative_to(ROOT)))
   if target.read_bytes()!=expected or backup.read_bytes()!=expected:raise ValueError('original-drift:'+str(target))
  value=read(policy)
  for key,entry in value['files'].items():
   if role=='taobao':target=Path(entry['path']);expected=entry['sha256']
   else:target=ROOT/SPECS[role][0]/key;expected=entry
   if sha(target.read_bytes())!=expected:raise ValueError('original-pin-drift:'+key)
  result[role]={'source':sha(source.read_bytes()),'policy':sha(policy.read_bytes()),'candidate':sha((EVIDENCE/'candidates'/(role+'.mjs')).read_bytes())}
 return result

def prepare():
 review={'scope':validate_originals(),'baseRevision':BASE_REV,'authorization':'user-current-goal-repair-recoverable-before-next-duty','plan':'docs/solutions/20261028-双Top10首页连接关闭一次恢复.md','effects':'two source files and their existing source pins only; no send or business evidence mutation'}
 write(EVIDENCE/'review.json',review);return review

def candidate_binding():
 result={role:sha((EVIDENCE/'candidates'/(role+'.mjs')).read_bytes()) for role in SPECS}
 for name in ['runtime/maintain_top10_home_recovery_20261028.py','runtime/tests/top10_home_recovery.test.mjs','runtime/tests/test_top10_home_recovery_maintenance.py']:
  result[name]=sha((ROOT/name).read_bytes())
 return result

def prepare_shadow():
 shadow=EVIDENCE/'isolated-candidates'
 tests=[]
 for role in SPECS:
  source,_=paths(role);directory=shadow/role/'scripts';directory.mkdir(parents=True,exist_ok=True)
  for actual in source.parent.iterdir():
   target=directory/actual.name
   if target.exists() or target.is_symlink():continue
   target.symlink_to(actual)
  target=directory/source.name
  if target.is_symlink():target.unlink()
  target.write_bytes((EVIDENCE/'candidates'/(role+'.mjs')).read_bytes())
  names=['test_background_desktop.mjs','test_income_sort.mjs','test_task_page_cleanup.mjs'] if role=='taobao' else ['test_income_collector.mjs']
  for name in names:
   actual=source.parent/name if role=='taobao' else source.parent.parent/'tests'/name
   target=directory/name if role=='taobao' else shadow/role/'tests'/name
   target.parent.mkdir(parents=True,exist_ok=True)
   if target.is_symlink():target.unlink()
   target.write_bytes(actual.read_bytes());tests.append(target)
 return tests

def test_candidates():
 env=dict(os.environ,TOP10_HOME_CANDIDATES='1',PYTHONPATH=str(ROOT/'runtime'))
 commands=[('navigation',[NODE,'--test','runtime/tests/top10_home_recovery.test.mjs']),
 ('maintenance',[sys.executable,'-m','unittest','runtime.tests.test_top10_home_recovery_maintenance','-v'])]
 commands += [('original-node-'+str(i),[NODE,str(test)]) for i,test in enumerate(prepare_shadow())]
 for name,folder,pattern in [('tao-runtime','daily-top10-to-wechat-group','test_runtime_guard.py'),('tao-label','daily-top10-to-wechat-group','test_income_label.py'),('mt-workflow','daily-meituan-income-top10-to-wechat','test_income_workflow.py')]:
  where=ROOT/'skills/workflows'/folder/('scripts' if folder.startswith('daily-top10') else 'tests')
  commands.append((name,[sys.executable,'-m','unittest','discover','-s',str(where),'-p',pattern,'-v']))
 results=[];binding=candidate_binding()
 for name,argv in commands:
  p=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
  (EVIDENCE/(name+'-tests.log')).write_text(p.stdout+p.stderr)
  results.append({'name':name,'returncode':p.returncode,'argv':argv})
  if p.returncode:raise ValueError('candidate-tests-failed:'+name)
 if binding!=candidate_binding():raise ValueError('candidate-changed-during-tests')
 value={'passed':True,'binding':binding,'results':results};write(EVIDENCE/'tests.json',value);return value

def atomic_replace(path,data):
 temp=path.with_name('.'+path.name+'.top10-maintenance-'+str(os.getpid()))
 with temp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
 os.chmod(temp,path.stat().st_mode&0o777);temp.replace(path)

def run_gates():
 code="""import sys,importlib.util,json
from pathlib import Path
root=Path(sys.argv[1]);sys.path.insert(0,str(root/'skills/workflows/daily-top10-to-wechat-group/scripts'))
from runtime_guard import validate_runtime_policy
validate_runtime_policy()
p=root/'skills/workflows/daily-meituan-income-top10-to-wechat/scripts/income_workflow.py'
spec=importlib.util.spec_from_file_location('mt_original_gate',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.integrity()
print(json.dumps({'taobaoOriginalGate':True,'meituanOriginalGate':True,'productionActions':0}))
"""
 p=subprocess.run([sys.executable,'-c',code,str(ROOT)],capture_output=True,text=True,timeout=30)
 (EVIDENCE/'original-gates.log').write_text(p.stdout+p.stderr)
 if p.returncode:raise ValueError('original-runtime-gate-failed')
 return json.loads(p.stdout)

def assert_idle():
 now=datetime.now(ZoneInfo('Asia/Shanghai'))
 if now.date().isoformat()!='2026-10-28' or not (8*60+35<=now.hour*60+now.minute<8*60+55):raise ValueError('outside-reviewed-safe-window')
 if list((ROOT/'runtime/state/live_steps').glob('*')):raise ValueError('live-steps-busy')
 control=read(ROOT/'runtime/state/control.json')
 if control.get('force_run_now') or control.get('force_run'):raise ValueError('control-request-pending')
 for *_,group,physical in SPECS.values():
  if Path(physical).exists() or Path(physical).is_symlink():raise ValueError('physical-post-busy')

def acquire_groups(stack):
 import run_all
 for *_,group,physical in SPECS.values():
  lease=run_all.acquire_post_group_lock(group,'top10-home-maintenance-20261028')
  if lease is None:raise ValueError('original-group-busy:'+group)
  stack.callback(run_all.release_post_group_lock,lease)

def apply_reviewed():
 review=read(EVIDENCE/'review.json');tests=read(EVIDENCE/'tests.json')
 if tests.get('passed') is not True or tests.get('binding')!=candidate_binding():raise ValueError('untested-candidate')
 if review.get('scope')!=validate_originals():raise ValueError('stale-review')
 assert_idle();old={};installed={}
 with ExitStack() as stack:
  acquire_groups(stack);assert_idle()
  if review['scope']!=validate_originals():raise ValueError('original-changed-after-lock')
  try:
   for role in SPECS:
    source,policy=paths(role);candidate=(EVIDENCE/'candidates'/(role+'.mjs')).read_bytes()
    current=read(policy);updated=json.loads(json.dumps(current))
    if role=='taobao':updated['files'][SPECS[role][2]]['sha256']=sha(candidate)
    else:updated['files'][SPECS[role][2]]=sha(candidate)
    policy_bytes=(json.dumps(updated,ensure_ascii=False,indent=2)+'\n').encode()
    for path,data in [(source,candidate),(policy,policy_bytes)]:
     old[path]=path.read_bytes();installed[path]=data;atomic_replace(path,data)
   gates=run_gates()
   if tests['binding']!=candidate_binding():raise ValueError('candidate-changed-during-install')
   for path,data in installed.items():
    if path.read_bytes()!=data:raise ValueError('installed-source-drift')
   receipt={'installed':True,'gates':gates,'changes':{str(p.relative_to(ROOT)):sha(data) for p,data in installed.items()},'productionActions':0,'browserRestarts':0,'directorRestarts':0,'realNextDayAcceptancePending':True}
   write(EVIDENCE/'install-receipt.json',receipt);return receipt
  except BaseException:
   restored=[];unmatched=[]
   for path,data in reversed(list(installed.items())):
    if path.read_bytes()==data:atomic_replace(path,old[path]);restored.append(str(path))
    else:unmatched.append(str(path))
   write(EVIDENCE/'rollback.json',{'restored':restored,'unmatched':unmatched,'businessDataChanged':False})
   raise

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','test','apply-reviewed']);args=p.parse_args()
 result={'prepare':prepare,'test':test_candidates,'apply-reviewed':apply_reviewed}[args.action]();print(json.dumps(result,ensure_ascii=False))
