"""Scoped review/apply for the four physical-lease pins; never touches live leases."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import os

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=ROOT/'runtime/state/post-lease-process-ownership-20261028'
POSTS=('taobao-brand-post','taobao-svc-post','jinsha-post','meituan-post')
ADDITIONS={'../shared/lease_core.mjs':'skills/posts/shared/lease_core.mjs',
           '../../../runtime/post_lease_file.py':'runtime/post_lease_file.py'}
CONTRACT='skills/workflows/contract-termination-applications-screenshot/scripts/contract_termination_shot.mjs'


def sha(data):return hashlib.sha256(data).hexdigest()


def atomic(path,data):
    temporary=path.with_name('.'+path.name+f'.{os.getpid()}.lease-maintenance')
    with temporary.open('xb') as stream:
        stream.write(data);stream.flush();os.fsync(stream.fileno())
    temporary.replace(path)


def prepare():
    baseline=json.loads((EVIDENCE/'before-install.json').read_text())
    indexed={item['post']:item for item in baseline['posts']}
    staged={CONTRACT:sha((ROOT/CONTRACT).read_bytes())}
    staged.update({p:sha((ROOT/p).read_bytes()) for p in ADDITIONS.values()})
    changes=[]
    for post in POSTS:
        folder=ROOT/'skills/posts'/post
        original=(EVIDENCE/'originals/skills/posts'/post/'dependencies.json').read_bytes()
        current=(folder/'dependencies.json').read_bytes()
        if current!=original or sha(original)!=indexed[post]['originalManifestSha256']:
            raise ValueError('post-maintenance-original-manifest-changed:'+post)
        manifest=json.loads(original)
        for name,expected in manifest['files'].items():
            file=folder/name
            if name!='scripts/lease.mjs' and sha(file.read_bytes())!=expected:
                raise ValueError('post-maintenance-unrelated-drift:'+post+':'+name)
        old_source=(EVIDENCE/'originals/skills/posts'/post/'scripts/lease.mjs').read_bytes()
        if sha(old_source)!=manifest['files']['scripts/lease.mjs']:
            raise ValueError('post-maintenance-backup-invalid:'+post)
        source=f'skills/posts/{post}/scripts/lease.mjs'
        staged[source]=sha((ROOT/source).read_bytes())
        manifest['files']['scripts/lease.mjs']=staged[source]
        for entry,file in ADDITIONS.items():
            if entry in manifest['files']:raise ValueError('post-maintenance-addition-already-present')
            manifest['files'][entry]=staged[file]
        candidate=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode()
        changes.append({'post':post,'path':str((folder/'dependencies.json').relative_to(ROOT)),
                        'originalSha256':sha(original),'candidateSha256':sha(candidate),
                        'candidate':manifest})
    return {'scope':'four physical lease files and two explicitly registered common files only',
            'humanInstruction':'只要不是登录问题 任何阻拦 都要你立即解决 然后 安排主任执行',
            'sourceDigests':staged,'manifestChanges':changes,
            'liveLeaseMutations':0,'productionActions':0}


def apply_reviewed(node):
    review=json.loads((EVIDENCE/'review.json').read_text())
    plan=prepare()
    if plan!=review:raise ValueError('post-maintenance-review-no-longer-matches')
    tested=json.loads((EVIDENCE/'preinstall-tests.json').read_text())
    if tested.get('ok') is not True or tested.get('sourceDigests')!=plan['sourceDigests']:
        raise ValueError('post-maintenance-tested-source-mismatch')
    from post_lease_file import alive,read_owner
    live=ROOT/'runtime/state/live_steps'
    if any(live.glob('*.json')):raise ValueError('original-director-has-live-steps')
    for name in ['/tmp/zhensi-post-9230.lock','/tmp/zhensi-post-9231.lock',
                 '/tmp/zhensi-jinsha-cua-exam.lock','/tmp/zhensi-post-9233.lock']:
        owner=read_owner(Path(name))
        if owner is not None and alive(owner.get('pid')) is not False:
            raise ValueError('post-maintenance-active-or-unconfirmed-owner')
    written=[]
    try:
        for change in plan['manifestChanges']:
            path=ROOT/change['path']
            if sha(path.read_bytes())!=change['originalSha256']:raise ValueError('manifest-race')
            data=(json.dumps(change['candidate'],ensure_ascii=False,indent=2)+'\n').encode()
            atomic(path,data);written.append(change)
        gates=[]
        for post in POSTS:
            result=subprocess.run([node,str(ROOT/'skills/posts'/post/'scripts/verify_dependencies.mjs')],
                                  capture_output=True,text=True,timeout=15)
            gates.append({'post':post,'exitCode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})
            if result.returncode:raise ValueError('original-post-gate-failed:'+post)
        if any(sha((ROOT/p).read_bytes())!=expected for p,expected in plan['sourceDigests'].items()):
            raise ValueError('source-changed-during-install')
        result={'ok':True,'originalGates':gates,'sourceDigests':plan['sourceDigests'],
                'changes':[{k:v for k,v in c.items() if k!='candidate'} for c in written],
                'liveLeaseMutations':0,'productionActions':0}
        atomic(EVIDENCE/'install-receipt.json',(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode())
        return result
    except Exception:
        for change in reversed(written):
            path=ROOT/change['path']
            if sha(path.read_bytes())==change['candidateSha256']:
                atomic(path,(EVIDENCE/'originals'/change['path']).read_bytes())
        for p,expected in plan['sourceDigests'].items():
            backup=EVIDENCE/'originals'/p
            if backup.is_file() and sha((ROOT/p).read_bytes())==expected:atomic(ROOT/p,backup.read_bytes())
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['prepare','apply-reviewed'])
    parser.add_argument('--node',required=True);args=parser.parse_args()
    with (EVIDENCE/'maintenance.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if args.mode=='prepare':
            plan=prepare();atomic(EVIDENCE/'review.json',(json.dumps(plan,ensure_ascii=False,indent=2)+'\n').encode())
            print(json.dumps({'ok':True,'manifestChanges':len(plan['manifestChanges']),'productionActions':0}))
        else:
            result=apply_reviewed(args.node)
            print(json.dumps({'ok':result['ok'],'originalGates':len(result['originalGates']),'liveLeaseMutations':0}))
