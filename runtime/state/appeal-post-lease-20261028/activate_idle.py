"""One original-service idle reload; never repairs locks or starts business jobs."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[3]
EVIDENCE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'runtime'))
import run_all

EXPECTED_PID = 55035
SERVICE = 'gui/501/com.zhensi.waimai.careloop'

def read(path):
    return json.loads(path.read_text())

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=15, check=True).stdout

def chrome_pids():
    return {str(port): command('/usr/sbin/lsof', '-nP', '-t', '-iTCP:'+str(port), '-sTCP:LISTEN').strip()
            for port in range(9230,9234)}

def snapshot():
    now = dt.datetime.now(ZoneInfo('Asia/Shanghai'))
    assert now.date().isoformat() == '2026-10-28' and now.hour == 9 and 40 <= now.minute < 55, 'outside-reviewed-window'
    daemon = read(ROOT/'runtime/state/daemon.json')
    assert daemon['pid'] == EXPECTED_PID and daemon['status'] == 'running', 'director-changed'
    info = command('/bin/launchctl','print',SERVICE)
    assert '\tpid = '+str(EXPECTED_PID)+'\n' in info and '\tstate = running\n' in info
    live = list((ROOT/'runtime/state/live_steps').iterdir())
    assert not live, 'live-step-registration-present'
    assert not list((ROOT/'runtime/state/locks').glob('*.lock')), 'group-owner-present'
    physical = [Path('/tmp/zhensi-post-'+str(p)+'.lock') for p in (9230,9231,9233)]
    physical.append(Path('/tmp/zhensi-jinsha-cua-exam.lock'))
    assert all(not p.exists() and not p.is_symlink() for p in physical), 'physical-owner-present'
    processes = command('/bin/ps','-axo','pid=,ppid=,comm=').splitlines()
    children = [line.strip() for line in processes if len(line.split()) >= 3 and line.split()[1] == str(EXPECTED_PID)]
    assert all(line.split()[-1].endswith('caffeinate') for line in children), 'director-child-executor'
    control_path = ROOT/'runtime/state/control.json'
    control = read(control_path)
    assert not any(control.get(k) for k in ('force_run','force_run_now','reset_circuit')), 'control-request-present'
    manifest = read(ROOT/'runtime/skills_manifest.json')
    gates = {s['name']: run_all._cadence_gate(s, now.replace(tzinfo=None))
             for s in manifest['skills'] if s.get('enabled')}
    allowed_readbacks = {'daily-meituan-income-top10-to-wechat', 'daily-negative-reviews', 'contract-termination-applications-screenshot'}
    assert {name for name, gate in gates.items() if not gate[0]} == allowed_readbacks, 'unexpected-business-could-start'
    mt = read(ROOT/'skills/workflows/daily-meituan-income-top10-to-wechat/.runtime/days/2026-10-28/delivery.json')
    ct = read(ROOT/'skills/workflows/contract-termination-applications-screenshot/.runtime/contract-termination/events/2026-10-28-contract-termination-ops.json')
    nr = read(ROOT/'.local/runs/daily-negative-reviews/20261027/workflow-state.json')
    assert mt['state']=='unknown' and mt['sendAttempts']==2
    assert ct['state']=='unknown' and ct['sendAttempts']==1 and ct['executionComplete'] is True
    assert nr['phase']=='sent' and nr['reason']=='image-submission-awaits-read-only-verification'
    # These exact original paths return existing attempts before collection or sending.
    # No force request; all other original business gates are skipped/not due.
    protected = [ROOT/'runtime/skills_manifest.json', ROOT/'runtime/state/control.json', ROOT/'runtime/posts.json']
    for post in ('taobao-brand-post','taobao-svc-post','jinsha-post','meituan-post'):
        protected.append(ROOT/'skills/posts'/post/'dependencies.json')
    return {'at':now.isoformat(),'daemon':daemon,'children':children,'gates':gates,
            'chromePids':chrome_pids(), 'protected':{str(p.relative_to(ROOT)):digest(p) for p in protected},
            'source':{str(p.relative_to(ROOT)):digest(p) for p in
                      [ROOT/'runtime/run_all.py',ROOT/'runtime/post_group_lease.py',ROOT/'runtime/post_lease_file.py']},
            'launchctl': info,
            'runHistoryNames': sorted(p.name for p in (ROOT/'runtime/run_history/2026-10-28').glob('*')),
            'pendingReadbackOnly': sorted(allowed_readbacks), 'queueTasks': sorted(str(p.relative_to(ROOT)) for p in (ROOT/'skills/wechat-messaging/.runtime/ui-post-queue').glob('*/task.json'))}

assert not (EVIDENCE/'activation-result.json').exists(), 'activation-already-attempted'
before = snapshot()
(EVIDENCE/'activation-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
second = snapshot()
assert second['source'] == before['source'] and second['protected'] == before['protected']
(EVIDENCE/'activation-attempt.json').write_text(json.dumps({'at':dt.datetime.now().isoformat(),'oldPid':EXPECTED_PID}))
# The existing original launchd service is the only process manager used.
result = subprocess.run(['/bin/launchctl','kickstart','-k',SERVICE],capture_output=True,text=True,timeout=20)
(EVIDENCE/'activation-result.json').write_text(json.dumps({'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr},indent=2))
assert result.returncode == 0, 'original-service-reload-failed'
for _ in range(25):
    time.sleep(1)
    daemon = read(ROOT/'runtime/state/daemon.json')
    if daemon['pid'] != EXPECTED_PID and daemon['status'] == 'running':
        break
else:
    raise RuntimeError('new-heartbeat-not-observed-no-retry')
info = command('/bin/launchctl','print',SERVICE)
assert '\tpid = '+str(daemon['pid'])+'\n' in info and '\tstate = running\n' in info
os.kill(daemon['pid'],0)
assert before['chromePids'] == chrome_pids(), 'business-browser-pid-changed'
assert all(digest(ROOT/p)==sha for p,sha in before['protected'].items()), 'protected-file-changed'
assert all(digest(ROOT/p)==sha for p,sha in before['source'].items()), 'tested-source-changed'
assert not list((ROOT/'runtime/state/live_steps').iterdir()), 'unexpected-live-step'
assert before['queueTasks'] == sorted(str(p.relative_to(ROOT)) for p in (ROOT/'skills/wechat-messaging/.runtime/ui-post-queue').glob('*/task.json'))
after = {'at':dt.datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'daemon':daemon,
         'launchctl':info,'chromePids':chrome_pids(),'protectedUnchanged':True,'testedSourceUnchanged':True,
         'newQueueTasks':0,'liveSteps':0,'reloadCount':1,'productionJobsRequested':0,'pendingReadbackOnly':before['pendingReadbackOnly'],
         'newDirectorCommand':command('/bin/ps','-p',str(daemon['pid']),'-o','pid=,ppid=,lstart=,command=')}
(EVIDENCE/'activation-after.json').write_text(json.dumps(after,ensure_ascii=False,indent=2))
print(json.dumps({'oldPid':EXPECTED_PID,'newPid':daemon['pid'],'chromeUnchanged':True,'reloadCount':1}))
