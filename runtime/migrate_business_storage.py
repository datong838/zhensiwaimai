"""Copy business-owned data only during an unloaded, idle maintenance window.
Default CLI is a read-only hash plan. No deletion, business replay or marker rewrite.
"""
import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from business_storage import REPO_ROOT, LAYOUT, business_path, catalog, internal_path


# Only these verified entry -> real-directory aliases may be followed, exactly one hop.
APPROVED_SOURCE_LINKS = {
    'jinsha-reports': ('/Users/ddt/work/臻肆/报表', '/Volumes/NVME2T/work/臻肆/报表'),
    'video-assets': ('/Users/ddt/work/臻肆/视频', '/Volumes/NVME2T/work/臻肆/视频'),
}


def source_location(key, item):
    entry = Path(item['legacy'])
    if not entry.is_symlink():
        return entry, None
    approved = APPROVED_SOURCE_LINKS.get(key)
    if approved is None or entry != Path(approved[0]):
        raise ValueError('storage-source-link-not-approved:' + key)
    real = Path(approved[1])
    link_text = os.readlink(entry)
    direct = Path(link_text) if Path(link_text).is_absolute() else entry.parent/link_text
    if Path(os.path.abspath(direct)) != real:
        raise ValueError('storage-source-link-target-mismatch:' + key)
    try:
        if real.is_symlink() or not real.is_dir() or real.resolve(strict=True) != real or entry.resolve(strict=True) != real:
            raise ValueError('storage-approved-source-not-canonical-directory:' + key)
        alias_stat = entry.lstat(); source_stat = real.stat()
    except OSError as error:
        raise ValueError('storage-approved-source-unavailable:' + key) from error
    binding = {'entry': str(entry), 'linkTarget': link_text, 'resolvedSource': str(real),
               'entryIdentity': {'device': alias_stat.st_dev, 'inode': alias_stat.st_ino},
               'sourceIdentity': {'device': source_stat.st_dev, 'inode': source_stat.st_ino}}
    return real, binding


def validated_source(key, item):
    source, binding = source_location(key, item)
    if binding != item.get('sourceBinding'):
        raise ValueError('storage-source-binding-changed:' + key)
    return source


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
    with temporary.open('xb') as stream:
        stream.write(encoded(value)); stream.flush(); os.fsync(stream.fileno())
    temporary.chmod(0o600)
    temporary.replace(path)


def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): digest.update(block)
    return digest.hexdigest()


def inventory(folder):
    folder = Path(folder)
    if folder.is_symlink() or not folder.is_dir(): raise ValueError('storage-source-not-regular-directory')
    files, dirs = [], []
    for base, children, names in os.walk(folder, followlinks=False):
        for name in sorted(children):
            p = Path(base)/name
            if p.is_symlink(): raise ValueError('storage-symlink-rejected')
            dirs.append(str(p.relative_to(folder)))
        for name in sorted(names):
            p = Path(base)/name
            if not stat.S_ISREG(p.lstat().st_mode): raise ValueError('storage-nonregular-file-rejected')
            before = p.stat(); sha = file_sha(p); after = p.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError('storage-source-changing')
            files.append({'path': str(p.relative_to(folder)), 'size': after.st_size, 'sha256': sha, 'mtimeNs': after.st_mtime_ns})
    return {'directories': sorted(dirs), 'files': sorted(files, key=lambda f: f['path'])}


def assert_idle(root):
    """Never stop writers here; caller must unload them before a real migration."""
    service = subprocess.run(['launchctl','print',f'gui/{os.getuid()}/com.zhensi.waimai.careloop'],capture_output=True)
    if service.returncode == 0: raise ValueError('storage-director-must-be-unloaded')
    if list((root/'runtime/state/live_steps').glob('*.json')): raise ValueError('storage-live-steps-present')
    if list((root/'runtime/state/locks').glob('*.lock')): raise ValueError('storage-post-group-lease-present')
    if any(Path(f'/tmp/zhensi-post-{port}.lock').exists() for port in (9230,9231,9232,9233)):
        raise ValueError('storage-post-lease-present')
    process_list = subprocess.check_output(['/bin/ps','-axo','pid=,command='], text=True)
    needles = [str(root/'runtime/run_all.py'),str(root/'skills/.daily-jinsha-reports-core'),
               *[item['legacy'] for item in catalog(root).values()],
               *[real for key,(entry,real) in APPROVED_SOURCE_LINKS.items()
                 if catalog(root).get(key,{}).get('legacy') == entry],
               *[str(root/'skills/workflows'/name) for name in (
        'meituan-waimai-negative-review-appeals','taobao-flash-sale-negative-review-appeals',
        'negative-feedback-list-appeals','daily-jinsha-reports-to-business-wechat','daily-wechat-video-publish')]]
    for line in process_list.splitlines():
        if any(needle in line for needle in needles): raise ValueError('storage-writer-process-present')


@contextlib.contextmanager
def maintenance_lock(root):
    path = root/'runtime/state/storage-migration.lock'; path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def make_plan(root=REPO_ROOT, keys=None):
    root = Path(root).resolve(); objects = catalog(root); keys = list(keys or objects)
    if len(set(keys)) != len(keys) or any(k not in objects for k in keys): raise ValueError('storage-keys-invalid')
    plan = {'schemaVersion':1, 'id':uuid.uuid4().hex, 'root':str(root),
            'createdAt':datetime.now(timezone.utc).isoformat(), 'objects':{}}
    for key in keys:
        item = objects[key]; target = internal_path(root,item['target'])
        if target.exists(): raise ValueError('storage-target-collision:'+key)
        if business_path(key,root=root) != Path(item['legacy']): raise ValueError('storage-already-active:'+key)
        source, binding = source_location(key, item)
        if target == source or target.is_relative_to(source): raise ValueError('storage-source-contains-target:' + key)
        snapshot = inventory(source)
        plan['objects'][key] = dict(item, inventory=snapshot)
        if binding is not None: plan['objects'][key]['sourceBinding'] = binding
    return plan


def validate_plan(root, plan):
    if plan.get('schemaVersion') != 1 or plan.get('root') != str(root) or not plan.get('objects'):
        raise ValueError('storage-plan-invalid')
    if len(plan.get('id','')) != 32 or any(c not in '0123456789abcdef' for c in plan['id']): raise ValueError('storage-id-invalid')
    objects = catalog(root)
    for key, item in plan['objects'].items():
        if key not in objects or any(item.get(k) != objects[key][k] for k in ('legacy','target')):
            raise ValueError('storage-plan-scope-invalid')
        target = internal_path(root,item['target'])
        source = validated_source(key,item)
        if target == source or target.is_relative_to(source): raise ValueError('storage-source-contains-target:' + key)
        if inventory(source) != item['inventory']: raise ValueError('storage-source-changed:'+key)


def apply_plan(plan, *, root=REPO_ROOT, idle_check=assert_idle):
    root = Path(root).resolve()
    with maintenance_lock(root), contextlib.ExitStack() as source_guards:
        idle_check(root); validate_plan(root,plan)
        for key,item in plan['objects'].items():
            source = validated_source(key,item)
            for file in item['inventory']['files']:
                if file['path'].endswith('.lock'):
                    handle=source_guards.enter_context((source/file['path']).open('rb'))
                    fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        layout_path = internal_path(root,LAYOUT)
        previous_bytes = layout_path.read_bytes() if layout_path.exists() else None
        previous = json.loads(previous_bytes) if previous_bytes else {'schemaVersion':1,'root':str(root),'objects':{}}
        if previous.get('schemaVersion') != 1 or previous.get('root') != str(root): raise ValueError('storage-layout-binding-invalid')
        tx = internal_path(root,'runtime/state/storage-migrations/'+plan['id'])
        if tx.exists(): raise ValueError('storage-transaction-collision')
        tx.mkdir(parents=True); atomic_json(tx/'plan.json',plan)
        atomic_json(tx/'previous-layout.json',{'exists':previous_bytes is not None,'value':previous})
        renamed=[]
        try:
            for key,item in plan['objects'].items():
                target = internal_path(root,item['target'])
                if target.exists(): raise ValueError('storage-target-collision:'+key)
                target.parent.mkdir(parents=True,exist_ok=True)
                stage = target.with_name('.'+target.name+'.migration-'+plan['id'])
                source = validated_source(key,item)
                shutil.copytree(str(source),stage,copy_function=shutil.copy2,symlinks=True)
                if inventory(stage) != item['inventory']: raise ValueError('storage-copy-mismatch:'+key)
                idle_check(root)
                if inventory(validated_source(key,item)) != item['inventory']: raise ValueError('storage-source-changed:'+key)
                if target.exists(): raise ValueError('storage-target-collision:'+key)
                stage.rename(target); renamed.append(key)
                atomic_json(tx/'progress.json',{'phase':'copied','keys':renamed})
            idle_check(root); validate_plan(root,plan)
            for key,item in plan['objects'].items():
                if inventory(internal_path(root,item['target'])) != item['inventory']: raise ValueError('storage-copy-changed:'+key)
            if (layout_path.read_bytes() if layout_path.exists() else None) != previous_bytes:
                raise ValueError('storage-layout-changed-during-copy')
            proof={'schemaVersion':1,'phase':'activated','id':plan['id'],'root':str(root),
                   'activatedAt':datetime.now(timezone.utc).isoformat(),
                   'objects':{key:{'target':item['target'],'inventory':item['inventory'],
                                   **({'sourceBinding':item['sourceBinding']} if 'sourceBinding' in item else {})}
                              for key,item in plan['objects'].items()}}
            proof_path=tx/'activation.json'; atomic_json(proof_path,proof)
            updated=dict(previous['objects'])
            for key,item in plan['objects'].items():
                updated[key]={'target':item['target'],'migrationId':plan['id'],
                              'proof':str(proof_path.relative_to(root)),'proofSha256':file_sha(proof_path)}
            atomic_json(layout_path,{'schemaVersion':1,'root':str(root),'objects':updated})
            return {'ok':True,'phase':'activated','id':plan['id'],'objects':list(plan['objects']),'sourceDeleted':False}
        except BaseException as error:
            atomic_json(tx/'failure.json',{'phase':'not-activated','copiedKeys':renamed,'reason':str(error)})
            raise


def rollback(migration_id, *, root=REPO_ROOT, idle_check=assert_idle):
    root=Path(root).resolve()
    if len(migration_id)!=32 or any(c not in '0123456789abcdef' for c in migration_id): raise ValueError('storage-id-invalid')
    with maintenance_lock(root):
        idle_check(root)
        tx=internal_path(root,'runtime/state/storage-migrations/'+migration_id)
        proof=json.loads((tx/'activation.json').read_text()); old=json.loads((tx/'previous-layout.json').read_text())
        current=json.loads(internal_path(root,LAYOUT).read_text())
        if proof.get('root')!=str(root) or proof.get('id')!=migration_id or proof.get('phase')!='activated':
            raise ValueError('storage-rollback-proof-invalid')
        for key,item in proof['objects'].items():
            business_path(key,root=root)  # Recheck catalog, proof hash and current authority.
            if current['objects'].get(key,{}).get('migrationId')!=migration_id: raise ValueError('storage-newer-migration-present')
            if inventory(internal_path(root,item['target']))!=item['inventory']: raise ValueError('storage-target-has-new-writes')
        validate_plan(root,json.loads((tx/'plan.json').read_text()))
        # Never drop unrelated later activations: roll back only this transaction's keys.
        updated=dict(current['objects'])
        for key in proof['objects']:
            if key in old['value']['objects']:updated[key]=old['value']['objects'][key]
            else:updated.pop(key,None)
        atomic_json(internal_path(root,LAYOUT),{'schemaVersion':1,'root':str(root),'objects':updated})
        atomic_json(tx/'rollback.json',{'phase':'rolled-back','objects':list(proof['objects']),'targetsRetained':True})
        return {'ok':True,'phase':'rolled-back','targetsRetained':True}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=REPO_ROOT)
    parser.add_argument('--keys',nargs='+');parser.add_argument('--apply',type=Path);parser.add_argument('--rollback')
    args=parser.parse_args()
    if args.apply and args.rollback:parser.error('apply and rollback are exclusive')
    try:
        if args.apply:value=apply_plan(json.loads(args.apply.read_text()),root=args.root)
        elif args.rollback:value=rollback(args.rollback,root=args.root)
        else:value=make_plan(root=args.root,keys=args.keys)
        print(json.dumps(value,ensure_ascii=False,sort_keys=True));return 0
    except Exception as error:print(json.dumps({'ok':False,'reason':str(error)},ensure_ascii=False));return 1
if __name__=='__main__':sys.exit(main())
