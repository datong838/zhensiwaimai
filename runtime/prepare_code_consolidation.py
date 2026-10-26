"""Prepare local originals, path/pin candidates and Git history without activating code.
No default writes, no business execution; signed/shared seals are never rewritten here.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from business_storage import internal_path
from migrate_business_storage import atomic_json, assert_idle, maintenance_lock, file_sha
from audit_source_consolidation import git

SELF=Path(__file__).resolve().parent
PATCH_FILES=[
 'skills/wechat-messaging/dependencies.json','skills/wechat-messaging/scripts/desktop_text_readback.py',
 'skills/wechat-messaging/scripts/windows_adapter.py',
 'skills/workflows/daily-agent-new-merchants-to-wechat/executor-lock.json',
 'skills/workflows/daily-agent-new-merchants-to-wechat/scripts/executor_integrity.py',
 'skills/workflows/daily-top10-to-wechat-group/runtime-policy.json',
 'skills/workflows/daily-top10-to-wechat-group/scripts/runtime_guard.py',
 'skills/workflows/daily-top10-to-wechat-group/scripts/workflow_executor.py',
 'skills/workflows/daily-wechat-video-publish/scripts/lib/wechat_bridge.py',
 'skills/workflows/daily-wechat-video-publish/scripts/douyin_chrome_bridge.py',
 'skills/workflows/daily-wechat-video-publish/scripts/lib/chrome_common.py',
 'skills/workflows/daily-jinsha-reports-to-business-wechat/scripts/wecom_shared_space.py',
 'skills/workflows/daily-taobao-download-to-jinsha/scripts/background_browser_executor.mjs',
 'skills/workflows/daily-taobao-download-to-jinsha/scripts/entrypoint.mjs',
 'runtime/backfill_new_merchants_via_gateway.py','runtime/send_ledger_now.py',
 'runtime/manual_run_once.py','runtime/wechat_ax_onspace.py','runtime/wechat_contention_diag.py','runtime/wechat_focus_check.py',
]
SKIP_DIRS={'node_modules','__pycache__','.pytest_cache'}
CODE_SKIP_DIRS=SKIP_DIRS|{'.git','.runtime','state','run_history','outputs','records','work','artifacts','coverage','coverage_html'}
CODE_SUFFIXES={'.py','.mjs','.js','.sh','.json'}
FROZEN_PREFIX='skills/.daily-jinsha-reports-core/'
WRAPPER_FILE='skills/workflows/daily-jinsha-reports-to-business-wechat/scripts/business_exam_pipeline.mjs'
MAINTENANCE_CATALOGS={'runtime/business_storage_catalog.json','runtime/code_consolidation_catalog.json'}


def snapshot(root):
    root=Path(root)
    if root.is_symlink() or not root.is_dir():raise ValueError('consolidation-source-directory-required')
    files=[];links=[];dirs=[]
    for base,children,names in os.walk(root,followlinks=False):
        for name in list(children):
            item=Path(base)/name
            if name in SKIP_DIRS:children.remove(name);continue
            if item.is_symlink():links.append({'path':str(item.relative_to(root)),'target':os.readlink(item)});children.remove(name)
            else:dirs.append(str(item.relative_to(root)))
        for name in names:
            item=Path(base)/name
            if item.is_symlink():links.append({'path':str(item.relative_to(root)),'target':os.readlink(item)});continue
            if not item.is_file():raise ValueError('consolidation-nonregular-source')
            before=item.stat();sha=file_sha(item);after=item.stat()
            if (before.st_mtime_ns,before.st_size,before.st_ino)!=(after.st_mtime_ns,after.st_size,after.st_ino):raise ValueError('consolidation-source-changing')
            files.append({'path':str(item.relative_to(root)),'sha256':sha,'size':after.st_size})
    return {'files':sorted(files,key=lambda x:x['path']),'links':sorted(links,key=lambda x:x['path']),'directories':sorted(dirs)}


def load_catalog():
    data=json.loads((SELF/'code_consolidation_catalog.json').read_text())
    if data.get('schemaVersion')!=1:raise ValueError('consolidation-catalog-invalid')
    return data


def scan_code_coverage(root,config):
    root=Path(root);files=[];audit=[];opaque=[];frozen={};core_callers=[]
    for top in ('runtime','skills'):
        base_root=root/top
        if not base_root.exists():continue
        for base,children,names in os.walk(base_root,followlinks=False):
            children[:]=sorted(n for n in children if n not in CODE_SKIP_DIRS and not (Path(base)/n).is_symlink())
            for name in sorted(names):
                file=Path(base)/name
                relative=str(file.relative_to(root))
                if relative.startswith(FROZEN_PREFIX) and file.is_file() and not file.is_symlink():frozen[relative]=file_sha(file)
                if file.suffix not in CODE_SUFFIXES:continue
                if file.is_symlink():opaque.append({'path':relative,'reason':'code-symlink-not-followed'});continue
                try:raw=file.read_bytes();text=raw.decode()
                except (OSError,UnicodeError):continue
                is_frozen=relative.startswith(FROZEN_PREFIX)
                is_test='/tests/' in relative or '/examples/' in relative or name.startswith(('test_','test-','selftest_'))
                category='frozen-read-only' if is_frozen else 'test-example' if is_test else 'legacy-runtime-artifact' if '/runtime/' in relative and not relative.startswith('runtime/') else 'migration-original-path-catalog' if relative in MAINTENANCE_CATALOGS else 'runtime-code'
                if category=='runtime-code' and file.suffix in ('.mjs','.js') and re.search(r'^import\s*\{[^}]*\brunBuildReports\b[^}]*\}\s*from',text,flags=re.M):core_callers.append(relative)
                bound=any(prefix in text for prefix in config['bindings'])
                current_manifest=False
                if file.suffix=='.json' and not is_frozen and not is_test and relative not in MAINTENANCE_CATALOGS:
                    try:current_manifest=isinstance(json.loads(text).get('files'),dict)
                    except (ValueError,AttributeError):pass
                if category=='runtime-code' and (bound or current_manifest or relative==WRAPPER_FILE):files.append(relative)
                current_json_files=None
                if file.suffix=='.json':
                    try:
                        data=json.loads(text)
                        if isinstance(data.get('files'),dict):current_json_files=json.dumps(data['files'],ensure_ascii=False)
                    except (ValueError,AttributeError):pass
                for number,line in enumerate(text.splitlines(),1):
                    matched=[prefix for prefix in config['bindings'] if prefix in line]
                    for prefix in matched:
                        kind='historical-json-metadata' if current_json_files is not None and prefix not in current_json_files else category
                        audit.append({'path':relative,'line':number,'reference':prefix,'category':kind,'covered':kind=='runtime-code'})
                    if not is_frozen:
                        for match in re.finditer(r'/Users/ddt/[^\s\"\'`]+',line):
                            reference=match.group()
                            if reference==str(root) or reference.startswith(str(root)+'/'):continue
                            host=any(v in reference for v in ('/.venvs/','/node_modules/','/.codex-runtimes/','/.cache/codex-runtimes/','/.workbuddy/binaries/','/.nvm/','/Library/Application'))
                            historical=current_json_files is not None and reference not in current_json_files
                            kind='host-runtime' if host else 'historical-json-metadata' if historical else category
                            bound_ref=any(reference.startswith(prefix) or prefix.startswith(reference) for prefix in config['bindings'])
                            if category=='runtime-code' and not historical and not host and not bound_ref:
                                if '/work/projects/ai_agent/state/' in reference or '/work/臻肆/' in reference:kind='unmapped-active-business-data'
                                elif '/work/projects/ai_agent/' in reference:kind='unmapped-active-project-reference'
                            audit.append({'path':relative,'line':number,'reference':reference,'category':kind,'covered':host or (bound_ref and kind=='runtime-code')})
                    if is_frozen:
                        for match in re.finditer(r'/Users/ddt/[^\s\"\'`]+',line):
                            reference=match.group()
                            if reference==str(root) or reference.startswith(str(root)+'/'):continue
                            host=any(p in reference for p in ('/.venvs/','/node_modules/','/.codex-runtimes/','/.cache/codex-runtimes/','/Library/Application Support/'))
                            audit.append({'path':relative,'line':number,'reference':reference,'category':'host-runtime' if host else 'frozen-opaque-default','covered':host,'resolution':'wrapper-injection-required' if not host else 'host-resource'})
    # Known anchors remain inputs even when their only dependency is another changed digest.
    files.extend(n for n in PATCH_FILES if (root/n).is_file() and not n.startswith(FROZEN_PREFIX))
    return {'candidateFiles':sorted(set(files)),'references':audit,'opaque':opaque,'frozenHashes':frozen,'coreBuildCallers':sorted(core_callers)}


def render_wrapper_injection(name,text):
    if name!=WRAPPER_FILE:return text
    start="import { assertFrozenCoreHashes, assertInternalInvocation, assertProductionConfig, assertStagePermission } from './business_workflow_policy.mjs';"
    updated="import { FIXED, assertFrozenCoreHashes, assertInternalInvocation, assertProductionConfig, assertStagePermission } from './business_workflow_policy.mjs';"
    call="runBuildReports({receipt:c.downloadReceipt,buildReceipt:c.buildReceipt,outputDir:c.outputDir,filenameSuffix:'',titleSuffix:''})"
    injected="runBuildReports({receipt:c.downloadReceipt,buildReceipt:c.buildReceipt,outputDir:c.outputDir,customer:path.join(FIXED.outputRoot,'客户表最新.xlsx'),meituanReference:path.join(FIXED.outputRoot,'美团全部_2026-08-25至2026-08-25.xlsx'),taobaoTemplate:path.join(FIXED.outputRoot,'淘宝闪购_模版2026-08-24至2026-08-24.xlsx'),filenameSuffix:'',titleSuffix:''})"
    if start not in text or call not in text:raise ValueError('consolidation-frozen-wrapper-shape-unverified')
    return text.replace(start,updated,1).replace(call,injected,1)


def plan(root,source,*,catalog=None):
    root=Path(root).resolve();source=Path(source).resolve();config=catalog or load_catalog()
    if root==source or root.is_relative_to(source):raise ValueError('consolidation-target-inside-source')
    if Path(git(source,'rev-parse','--show-toplevel').decode().strip()).resolve()!=source:raise ValueError('consolidation-source-not-git-root')
    assets={}
    for key,item in config['assets'].items():
        internal_path(root,item['target']);src=Path(item['source'])
        if root==src.resolve() or root.is_relative_to(src.resolve()):raise ValueError('consolidation-recursive-source')
        assets[key]=dict(item,inventory=snapshot(src))
    coverage=scan_code_coverage(root,config)
    baseline={name:file_sha(root/name) for name in coverage['candidateFiles']}
    return {'schemaVersion':1,'mode':'read-only','id':uuid.uuid4().hex,'root':str(root),'source':str(source),
            'sourceHead':git(source,'rev-parse','HEAD').decode().strip(),
            'sourceRefs':git(source,'for-each-ref','--format=%(refname):%(objectname)').decode().splitlines(),
            'sourceInventory':snapshot(source),'coverage':coverage,'assets':assets,'bindings':config['bindings'],'baseline':baseline,
            'requiresSharedSealMaintenance':True,'productionModified':False}


def validate(p):
    root=Path(p['root']);source=Path(p['source']);config=load_catalog()
    if set(p.get('assets',{}))!=set(config['assets']) or p.get('bindings')!=config['bindings']:
        raise ValueError('consolidation-catalog-scope-invalid')
    for key,item in p['assets'].items():
        if any(item.get(field)!=value for field,value in config['assets'][key].items()):raise ValueError('consolidation-asset-scope-invalid')
    coverage=scan_code_coverage(root,config)
    if p.get('coverage')!=coverage:raise ValueError('consolidation-code-coverage-changed')
    expected_baseline={name:file_sha(root/name) for name in coverage['candidateFiles']}
    if p['baseline']!=expected_baseline:raise ValueError('consolidation-runtime-baseline-changed')
    if p.get('schemaVersion')!=1 or len(p['id'])!=32 or any(c not in '0123456789abcdef' for c in p['id']):raise ValueError('consolidation-plan-invalid')
    if root==source or root.is_relative_to(source):raise ValueError('consolidation-recursive-source')
    if git(source,'rev-parse','HEAD').decode().strip()!=p['sourceHead']:raise ValueError('consolidation-git-head-changed')
    if git(source,'for-each-ref','--format=%(refname):%(objectname)').decode().splitlines()!=p['sourceRefs']:raise ValueError('consolidation-git-refs-changed')
    if snapshot(source)!=p['sourceInventory']:raise ValueError('consolidation-source-changed')
    for item in p['assets'].values():
        internal_path(root,item['target'])
        if snapshot(Path(item['source']))!=item['inventory']:raise ValueError('consolidation-asset-changed')
    for name,sha in p['baseline'].items():
        if name not in coverage['candidateFiles'] or file_sha(root/name)!=sha:raise ValueError('consolidation-runtime-baseline-changed')


def copy_snapshot(source,target,expected):
    if target.exists():raise ValueError('consolidation-target-collision')
    if expected['links'] and any(f['path']=='.consolidation-symlinks.json' for f in expected['files']):raise ValueError('consolidation-reserved-archive-name')
    target.mkdir(parents=True,mode=0o700)
    for name in expected['directories']:(target/name).mkdir(parents=True,exist_ok=True)
    for item in expected['files']:
        src=Path(source)/item['path'];dst=target/item['path'];dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(src,dst)
        if file_sha(dst)!=item['sha256']:raise ValueError('consolidation-copy-hash-mismatch')
    # Archives never follow links to third-party runtimes or account profiles.
    if expected['links']:atomic_json(target/'.consolidation-symlinks.json',expected['links'])


def replace_paths(text,p):
    for old,target in sorted(p['bindings'].items(),key=lambda x:-len(x[0])):
        text=text.replace(old,str(internal_path(p['root'],target)))
    return text


def hash_of(raw):return hashlib.sha256(raw).hexdigest()


def replace_pin_tree(value,p,hashes):
    if isinstance(value,dict):return {replace_paths(k,p):replace_pin_tree(v,p,hashes) for k,v in value.items()}
    if isinstance(value,list):return [replace_pin_tree(v,p,hashes) for v in value]
    if isinstance(value,str):return hashes.get(value,replace_paths(value,p))
    return value


def candidate_patches(p,payload):
    root=Path(p['root']);originals={name:(root/name).read_bytes() for name in p['baseline']}
    # Adapt only active vendor code; immutable originals are separately archived.
    vendor_edges={}
    for item in p['assets'].values():
        if not item.get('originalArchive'):continue
        for entry in item['inventory']['files']:
            file=payload/item['target']/entry['path']
            if file.suffix not in ('.py','.mjs','.js','.sh','.json','.swift'):continue
            raw=file.read_bytes()
            try:
                if file.suffix=='.json':
                    value=json.loads(raw)
                    if isinstance(value.get('files'),dict):
                        old_files=value['files'];value['files']=replace_pin_tree(old_files,p,{})
                        text=(json.dumps(value,ensure_ascii=False,indent=2)+'\n') if value['files']!=old_files else raw.decode()
                    else:text=raw.decode()
                else:text=replace_paths(raw.decode(),p)
                # This host-wide lock is relative to the original shared library.
                # Preserve its exact coordination domain when code moves.
                if file.name=='wechat_interaction_lock.py' and 'LOCK_PATH = Path(__file__).resolve().parents[1]' in raw.decode():
                    lock=(Path(item['source'])/entry['path']).parents[1]/'.runtime/wechat-ui-interaction.lock'
                    text=re.sub(r'^LOCK_PATH = .*$', 'LOCK_PATH = Path('+repr(str(lock))+')',text,flags=re.M)
                new=text.encode()
            except UnicodeError:continue
            if new!=raw:file.write_bytes(new);vendor_edges[hash_of(raw)]=hash_of(new)
    current={};hashes=dict(vendor_edges)
    for _ in range(15):
        next_values={}
        for name,raw in originals.items():
            if name.endswith('.json'):
                value=json.loads(raw)
                # Only current file pins; old acceptance and rebindHistory remain immutable values.
                old_files=value.get('files')
                if isinstance(old_files,dict):value['files']=replace_pin_tree(old_files,p,hashes)
                new=(json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode() if value.get('files')!=old_files else raw
            else:
                new=render_wrapper_injection(name,replace_paths(raw.decode(),p))
                for old,updated in hashes.items():new=new.replace("'"+old+"'","'"+updated+"'").replace('"'+old+'"','"'+updated+'"')
                new=new.encode()
            next_values[name]=new
        next_hashes=dict(vendor_edges)
        for name,new in next_values.items():
            old=hash_of(originals[name]);sha=hash_of(new)
            if old!=sha:
                if old in next_hashes and next_hashes[old]!=sha:raise ValueError('consolidation-pin-rebind-ambiguous')
                next_hashes[old]=sha
        if next_values==current:break
        current=next_values;hashes=next_hashes
    else:raise ValueError('consolidation-pin-graph-not-stable')
    result={name:raw for name,raw in current.items() if raw!=originals[name]}
    # Internal install mirror preserves the existing canonical/mirror equality contract.
    mirror=payload/'vendor/installed-taobao-skill'
    source_asset=next((v for v in p['assets'].values() if v['target']=='archive/installed-skill'),None)
    if source_asset:
        shutil.copytree(payload/source_asset['target'],mirror)
        for name,relative in [('SKILL.md','skills/workflows/daily-taobao-download-to-jinsha/SKILL.md'),('scripts/entrypoint.mjs','skills/workflows/daily-taobao-download-to-jinsha/scripts/entrypoint.mjs')]:
            target=mirror/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(result.get(relative,(root/relative).read_bytes()))
    return result


def prepare(p,*,idle_check=assert_idle):
    root=Path(p['root']);source=Path(p['source'])
    with maintenance_lock(root):
        idle_check(root);validate(p)
        if git(source,'status','--porcelain').strip():raise ValueError('consolidation-source-worktree-not-frozen')
        package=internal_path(root,'runtime/state/consolidation-packages/'+p['id'])
        if package.exists():raise ValueError('consolidation-package-collision')
        package.mkdir(parents=True,mode=0o700);atomic_json(package/'plan.json',p);payload=package/'payload';payload.mkdir()
        for key,item in p['assets'].items():
            copy_snapshot(item['source'],payload/item['target'],item['inventory'])
            if item.get('originalArchive'):copy_snapshot(item['source'],payload/item['originalArchive'],item['inventory'])
        copy_snapshot(source,payload/'archive/source-before-unification',p['sourceInventory'])
        (package/'original-code').mkdir()
        for name in p['baseline']:
            original=package/'original-code'/name;original.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(root/name,original)
        patches=candidate_patches(p,payload)
        changed=[]
        for name,raw in patches.items():
            dest=package/'patches'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw);dest.chmod(0o600)
            changed.append({'path':name,'oldSha256':p['baseline'][name],'newSha256':hash_of(raw),'candidateOnly':True})
        # Build a full local history copy; no checkout, no shared/hardlinked object files.
        mirror=package/'git-history.git'
        subprocess.run(['git','clone','--mirror','--no-hardlinks',str(source),str(mirror)],check=True,capture_output=True)
        refs=git(mirror,'for-each-ref','--format=%(refname):%(objectname)').decode().splitlines()
        if refs!=p['sourceRefs']:raise ValueError('consolidation-git-mirror-refs-mismatch')
        subprocess.run(['git','--git-dir',str(mirror),'fsck','--connectivity-only','--no-reflogs'],check=True,capture_output=True)
        for args in [('config','core.bare','false'),('config','--unset','remote.origin.mirror'),('config','remote.origin.fetch','+refs/heads/*:refs/remotes/origin/*')]:
            subprocess.run(['git','--git-dir',str(mirror),*args],check=True,capture_output=True)
        remote=subprocess.run(['git','-C',str(source),'remote','get-url','origin'],capture_output=True,text=True)
        url=remote.stdout.strip() if remote.returncode==0 else None
        if url:subprocess.run(['git','--git-dir',str(mirror),'remote','set-url','origin',url],check=True,capture_output=True)
        else:subprocess.run(['git','--git-dir',str(mirror),'remote','remove','origin'],check=True,capture_output=True)
        validate(p);idle_check(root)
        shim=package/'installation-shim';(shim/'scripts').mkdir(parents=True)
        canonical=root/'skills/workflows/daily-taobao-download-to-jinsha/scripts/entrypoint.mjs'
        (shim/'scripts/entrypoint.mjs').write_text('export * from '+json.dumps(canonical.as_uri())+';\n')
        (shim/'SKILL.md').write_text('---\nname: daily-taobao-download-to-jinsha\ndescription: 业务逻辑已统一归位，先完整阅读下列仓内权威Skill再按其原入口执行。\n---\n\n权威规则：'+str(root/'skills/workflows/daily-taobao-download-to-jinsha/SKILL.md')+'\n')
        request={'phase':'prepared-not-activated','id':p['id'],'root':str(root),'sourceHead':p['sourceHead'],
                 'patches':changed,'sharedSealRebindingRequired':True,'productionCodeModified':False,
                 'payloadInventory':snapshot(payload),'originalCodeInventory':snapshot(package/'original-code'),'shimInventory':snapshot(shim),'gitRefs':refs,'gitHead':git(mirror,'rev-parse','HEAD').decode().strip()}
        ignore=source/'.gitignore'
        if ignore.exists():shutil.copy2(ignore,package/'gitignore.candidate')
        atomic_json(package/'prepared.json',request);return package


def verify_package(package,root):
    package=Path(package).resolve();root=Path(root).resolve()
    if package.parent!=(root/'runtime/state/consolidation-packages').resolve():raise ValueError('consolidation-package-out-of-scope')
    p=json.loads((package/'plan.json').read_text());proof=json.loads((package/'prepared.json').read_text())
    if p['root']!=str(root) or proof['root']!=str(root) or package.name!=p['id'] or proof['id']!=p['id']:raise ValueError('consolidation-package-binding-invalid')
    if snapshot(package/'payload')!=proof['payloadInventory']:raise ValueError('consolidation-package-payload-changed')
    if snapshot(package/'original-code')!=proof['originalCodeInventory']:raise ValueError('consolidation-original-code-changed')
    if snapshot(package/'installation-shim')!=proof['shimInventory']:raise ValueError('consolidation-installation-shim-changed')
    for item in proof['patches']:
        if item['path'] not in p['baseline'] or file_sha(package/'patches'/item['path'])!=item['newSha256']:raise ValueError('consolidation-candidate-patch-changed')
    return p,proof


def materialize_assets(package,*,root,idle_check=assert_idle):
    root=Path(root).resolve()
    with maintenance_lock(root):
        idle_check(root);p,proof=verify_package(package,root);payload=Path(package)/'payload'
        # Only vendor/archive roots; existing runtime logic and states are never overwritten.
        for kind in ('vendor','archive'):
            if not (payload/kind).exists():continue
            for child in (payload/kind).iterdir():
                relative=kind+'/'+child.name
                if kind=='archive' and child.name in ('source-before-unification','external-code-originals','installed-skill'):relative+='/'+p['id']
                target=internal_path(root,relative)
                if target.exists():raise ValueError('consolidation-asset-target-collision')
        for kind in ('vendor','archive'):
            if not (payload/kind).exists():continue
            for child in (payload/kind).iterdir():
                relative=kind+'/'+child.name
                if kind=='archive' and child.name in ('source-before-unification','external-code-originals','installed-skill'):relative+='/'+p['id']
                target=internal_path(root,relative);target.parent.mkdir(parents=True,exist_ok=True)
                if kind=='archive':target.parent.chmod(0o700)
                stage=target.with_name('.'+target.name+'.stage-'+p['id'])
                shutil.copytree(child,stage)
                if snapshot(stage)!=snapshot(child):raise ValueError('consolidation-asset-copy-mismatch')
                stage.rename(target)
        atomic_json(Path(package)/'materialized.json',{'phase':'assets-copied-code-not-activated','productionCodeModified':False})
        return {'ok':True,'phase':'assets-copied-code-not-activated','sharedSealMaintenanceStillRequired':True}


def adopt_git(package,*,root,idle_check=assert_idle):
    root=Path(root).resolve()
    with maintenance_lock(root):
        idle_check(root);p,proof=verify_package(package,root)
        if (root/'.git').exists() or (root/'.git').is_symlink():raise ValueError('consolidation-runtime-already-has-git')
        required={'state/','runtime/state/','**/.runtime/','outputs/','records/','work/','data/','archive/','.env'}
        if not (root/'.gitignore').is_file() or not required.issubset(set((root/'.gitignore').read_text().splitlines())):raise ValueError('consolidation-gitignore-not-protecting-data')
        if git(Path(p['source']),'rev-parse','HEAD').decode().strip()!=p['sourceHead'] or git(Path(p['source']),'status','--porcelain').strip():raise ValueError('consolidation-source-not-frozen')
        mirror=Path(package)/'git-history.git'
        if git(mirror,'for-each-ref','--format=%(refname):%(objectname)').decode().splitlines()!=proof['gitRefs']:raise ValueError('consolidation-history-changed')
        # Moving metadata and read-tree write only Git metadata/index, never a working-tree file.
        mirror.rename(root/'.git')
        subprocess.run(['git','--git-dir',str(root/'.git'),'--work-tree',str(root),'read-tree','HEAD'],check=True,capture_output=True)
        atomic_json(Path(package)/'git-adoption.json',{'phase':'history-adopted-index-only','head':proof['gitHead'],'workingTreeOverwritten':False})
        return {'ok':True,'phase':'history-adopted-index-only','workingTreeOverwritten':False}


def install_skill_shim(package,*,root,idle_check=assert_idle):
    root=Path(root).resolve()
    with maintenance_lock(root):
        idle_check(root);p,proof=verify_package(package,root)
        item=p['assets']['installed-skill'];original=Path(item['source'])
        if snapshot(original)!=item['inventory']:raise ValueError('consolidation-installed-skill-changed')
        entry='skills/workflows/daily-taobao-download-to-jinsha/scripts/entrypoint.mjs'
        expected=next((i['newSha256'] for i in proof['patches'] if i['path']==entry),None)
        if not expected or file_sha(root/entry)!=expected:raise ValueError('consolidation-canonical-code-not-reviewed-or-activated')
        mirrored=root/'vendor/installed-taobao-skill/scripts/entrypoint.mjs'
        if not mirrored.is_file() or file_sha(mirrored)!=expected:raise ValueError('consolidation-internal-install-mirror-missing')
        saved=internal_path(root,'archive/installed-skill-original-'+p['id'])
        if saved.exists():raise ValueError('consolidation-original-archive-collision')
        saved.parent.mkdir(parents=True,exist_ok=True);saved.parent.chmod(0o700)
        original.rename(saved)
        try:shutil.copytree(Path(package)/'installation-shim',original)
        except BaseException:
            if original.exists():original.rename(root/'archive'/('incomplete-shim-'+p['id']))
            saved.rename(original);raise
        atomic_json(Path(package)/'skill-shim.json',{'phase':'installed-thin-shim','originalArchive':str(saved),'originalRetained':True})
        return {'ok':True,'phase':'installed-thin-shim','originalRetained':True}


def undo_skill_shim(package,*,root,idle_check=assert_idle):
    root=Path(root).resolve()
    with maintenance_lock(root):
        idle_check(root);p,proof=verify_package(package,root)
        item=p['assets']['installed-skill'];original=Path(item['source']);saved=root/('archive/installed-skill-original-'+p['id'])
        if snapshot(original)!=proof['shimInventory'] or snapshot(saved)!=item['inventory']:raise ValueError('consolidation-shim-or-original-has-new-writes')
        current=root/('archive/skill-shim-after-rollback-'+p['id'])
        if current.exists():raise ValueError('consolidation-shim-rollback-collision')
        original.rename(current);saved.rename(original)
        atomic_json(Path(package)/'skill-shim-rollback.json',{'phase':'old-installation-restored','shimRetained':True})
        return {'ok':True,'phase':'old-installation-restored','shimRetained':True}


def undo_git_adoption(package,*,root,idle_check=assert_idle):
    root=Path(root).resolve()
    with maintenance_lock(root):
        idle_check(root);p,proof=verify_package(package,root)
        if (root/'.git').is_symlink() or not (root/'.git').is_dir():raise ValueError('consolidation-owned-git-missing')
        if git(root,'rev-parse','HEAD').decode().strip()!=proof['gitHead'] or git(root,'for-each-ref','--format=%(refname):%(objectname)').decode().splitlines()!=proof['gitRefs']:raise ValueError('consolidation-git-has-new-history')
        destination=Path(package)/'git-history.git'
        if destination.exists():raise ValueError('consolidation-git-rollback-collision')
        (root/'.git').rename(destination)
        atomic_json(Path(package)/'git-rollback.json',{'phase':'git-metadata-restored-to-package','workingTreeOverwritten':False})
        return {'ok':True,'phase':'git-metadata-restored-to-package','workingTreeOverwritten':False}


def installed_coverage(root):
    root=Path(root);coverage=scan_code_coverage(root,load_catalog())
    active=[r for r in coverage['references'] if r['category']=='runtime-code' and any(prefix in r['reference'] for prefix in load_catalog()['bindings'])]
    unresolved=[r for r in coverage['references'] if r['category'] in ('unmapped-active-project-reference','unmapped-active-business-data')]
    frozen=[r for r in coverage['references'] if r['category']=='frozen-opaque-default']
    wrapper=root/WRAPPER_FILE;text=wrapper.read_text() if wrapper.is_file() else ''
    unexpected_callers=[n for n in coverage['coreBuildCallers'] if n!=WRAPPER_FILE]
    override=not unexpected_callers and all(token in text for token in ("customer:path.join(FIXED.outputRoot,", "meituanReference:path.join(FIXED.outputRoot,", "taobaoTemplate:path.join(FIXED.outputRoot,"))
    for ref in frozen:
        known=ref['path']==FROZEN_PREFIX+'scripts/build_reports.mjs' and ref['reference'].startswith('/Users/ddt/work/臻肆/报表')
        ref['covered']=known and override
        ref['resolution']='active-wrapper-options-override' if ref['covered'] else 'unresolved-opaque-reference'
    return {'ok':not active and not unresolved and not coverage['opaque'] and not unexpected_callers and all(r['covered'] for r in frozen),
            'activeExternalReferences':active,'unmappedReferences':unresolved,'opaqueCode':coverage['opaque'],
            'frozenReferences':frozen,'unexpectedCoreBuildCallers':unexpected_callers,'frozenResolutionScope':'current-business-wrapper-only; legacy direct core CLI is not activated','frozenFileCount':len(coverage['frozenHashes'])}


def verify_active(root,*,python=sys.executable,node=None,merchant_authorization=None,runner=subprocess.run,expected_frozen=None):
    """Actual read-only guards against the installed tree, never static candidate success."""
    root=Path(root).resolve();node=node or os.environ.get('ZENSI_NODE','/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
    shared=root/'skills/wechat-messaging/scripts';merchant=root/'skills/workflows/daily-agent-new-merchants-to-wechat/scripts';top=root/'skills/workflows/daily-top10-to-wechat-group/scripts';negative=root/'skills/workflows/daily-negative-reviews/scripts'
    inspect_code='import sys,json;sys.path.insert(0,'+repr(str(shared))+');import dependency_maintenance as d;r=d.inspect();print(json.dumps(r));sys.exit(0 if r.get("status")=="clean" else 1)'
    merchant_code='import sys,json;sys.path.insert(0,'+repr(str(merchant))+');import executor_integrity as e;r=e.verify_for_run('+repr(merchant_authorization)+');print(json.dumps(r));sys.exit(0 if r.get("ok") is True else 1)'
    top_code='import sys,json;sys.path.insert(0,'+repr(str(top))+');import runtime_guard as g;r=g.validate_runtime_policy();print(json.dumps({"ok":bool(r.get("validatedFiles")),"validatedFiles":len(r.get("validatedFiles",{}))}));sys.exit(0 if r.get("validatedFiles") else 1)'
    negative_code='import {selfTest} from '+json.dumps((negative/'workflow_executor.mjs').as_uri())+';import {assertReleasePolicy,buildConfig} from '+json.dumps((negative/'workflow_policy.mjs').as_uri())+';const r=await selfTest();const p=await assertReleasePolicy(buildConfig());console.log(JSON.stringify({...r,releaseStatus:p.status}));'
    data_code='import sys,json;from pathlib import Path;sys.path.insert(0,'+repr(str(root/'runtime'))+');import business_storage as b;root=Path('+repr(str(root))+').resolve();r={k:b.business_path(k,root=root).resolve().is_relative_to(root) for k in b.catalog(root)};print(json.dumps({"ok":bool(r) and all(r.values()),"rootsInternal":r}));sys.exit(0 if r and all(r.values()) else 1)'
    commands={'shared-inspect':[python,'-B','-c',inspect_code],'merchant-policy':[python,'-B','-c',merchant_code],'top10-policy':[python,'-B','-c',top_code],'negative-policy':[node,'--input-type=module','-e',negative_code],'business-data-roots':[python,'-B','-c',data_code]}
    env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1',ZHS_TEST_MODE='1');env.pop('NODE_V8_COVERAGE',None)
    results={}
    for name,command in commands.items():
        try:
            process=runner(command,cwd=str(root),env=env,capture_output=True,text=True,timeout=180)
            value=None
            for line in (process.stdout or '').splitlines():
                try:value=json.loads(line)
                except ValueError:pass
            okay=process.returncode==0 and isinstance(value,dict) and (value.get('status')=='clean' if name=='shared-inspect' else value.get('ok') is True)
            results[name]={'ok':okay,'returncode':process.returncode,'status':value.get('status') if isinstance(value,dict) else None,'reason':value.get('reason') if isinstance(value,dict) else None,'stderr':(process.stderr or '')[-1200:] if not okay else ''}
        except (OSError,subprocess.TimeoutExpired) as error:results[name]={'ok':False,'reason':str(error)}
    coverage=installed_coverage(root)
    if expected_frozen is not None:
        current=scan_code_coverage(root,load_catalog())['frozenHashes']
        coverage['frozenBytesUnchanged']=current==expected_frozen
        coverage['ok']=coverage['ok'] and coverage['frozenBytesUnchanged']
    return {'ok':all(v['ok'] for v in results.values()) and coverage['ok'],'phase':'actual-installed-guards','checks':results,'coverage':coverage,'sendAttempts':0,'productionModified':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--source',type=Path)
    parser.add_argument('--prepare',action='store_true');parser.add_argument('--plan',type=Path)
    parser.add_argument('--materialize-assets',type=Path);parser.add_argument('--adopt-git',type=Path);parser.add_argument('--undo-git-adoption',type=Path);parser.add_argument('--install-skill-shim',type=Path);parser.add_argument('--undo-skill-shim',type=Path);parser.add_argument('--verify-active',action='store_true');parser.add_argument('--merchant-authorization');args=parser.parse_args()
    try:
        if sum([args.prepare,bool(args.materialize_assets),bool(args.adopt_git),bool(args.undo_git_adoption),bool(args.install_skill_shim),bool(args.undo_skill_shim),args.verify_active])>1:raise ValueError('consolidation-one-action-required')
        if args.verify_active:
            expected=None
            if args.plan:
                planned=json.loads(args.plan.read_text())
                if Path(planned['root']).resolve()!=args.root.resolve():raise ValueError('consolidation-cli-root-plan-mismatch')
                expected=planned['coverage']['frozenHashes']
            value=verify_active(args.root,merchant_authorization=args.merchant_authorization,expected_frozen=expected)
        elif args.materialize_assets:value=materialize_assets(args.materialize_assets,root=args.root)
        elif args.adopt_git:value=adopt_git(args.adopt_git,root=args.root)
        elif args.undo_git_adoption:value=undo_git_adoption(args.undo_git_adoption,root=args.root)
        elif args.install_skill_shim:value=install_skill_shim(args.install_skill_shim,root=args.root)
        elif args.undo_skill_shim:value=undo_skill_shim(args.undo_skill_shim,root=args.root)
        else:
            p=json.loads(args.plan.read_text()) if args.plan else plan(args.root,args.source or Path.cwd())
            if Path(p['root']).resolve()!=args.root.resolve():raise ValueError('consolidation-cli-root-plan-mismatch')
            value={'ok':True,'phase':'prepared-not-activated','package':str(prepare(p))} if args.prepare else p
        print(json.dumps(value,ensure_ascii=False));return 0 if value.get('ok',True) else 1
    except Exception as error:print(json.dumps({'ok':False,'reason':str(error)},ensure_ascii=False));return 1
if __name__=='__main__':sys.exit(main())
