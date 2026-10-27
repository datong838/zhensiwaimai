"""Read-only inventory before adopting one source/runtime authority; never copies or checks out."""
import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

PROTECTED = ('.runtime/', '.local/', 'state/', 'runtime/state/', 'runtime/run_history/',
             'work/', 'outputs/', 'records/', 'artifacts/', 'node_modules/', 'data/', 'archive/')


def git(source, *args):
    env=dict(os.environ,GIT_OPTIONAL_LOCKS='0')
    return subprocess.check_output(['git','-C',str(source),*args],env=env)


def digest(file):
    before=file.stat();sha=hashlib.sha256()
    with file.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):sha.update(block)
    after=file.stat()
    if (before.st_size,before.st_mtime_ns,before.st_ino)!=(after.st_size,after.st_mtime_ns,after.st_ino):
        raise ValueError('source-consolidation-file-changing')
    return sha.hexdigest()


def protected(name):
    return (name.startswith(PROTECTED) or '/.runtime/' in name or '/node_modules/' in name
            or Path(name).name in ('dependencies.json','runtime-policy.json','registry-routing.json','native-ui-selectors.json')
            or 'authorization' in name.lower() or Path(name).name.startswith('.env') or Path(name).suffix in ('.pem','.key','.sqlite','.db'))


def external_references(source,names):
    references=[]
    for name in names:
        p=source/name
        if p.suffix not in ('.py','.mjs','.js','.sh','.json','.yaml','.toml') or '/tests/' in name or p.name.startswith('test') or not p.is_file():continue
        try:text=p.read_text()
        except UnicodeError:continue
        for match in re.finditer(r"[\"'](/Users/ddt/[^\"'\n]+)[\"']",text):
            value=match.group(1)
            if '/zhensi_waimai_back' in value:continue
            if any(v in value for v in ('/node_modules/','/.venvs/','/.cache/codex-runtimes/','/.codex-runtimes/','/.nvm/','/.workbuddy/binaries/')):kind='standard-runtime'
            elif '/Library/Application Support/AOS Background Chrome' in value:kind='browser-profile-do-not-copy'
            elif '/work/臻肆/' in value or '/ai_agent/state/' in value:kind='business-data'
            elif '/.codex/skills/' in value:kind='installed-skill-binding'
            elif '/wechat-windows-driver' in value:kind='legacy-channel-code-and-config'
            elif '/work/projects/ai_agent/' in value:kind='external-project-code-review'
            else:continue
            references.append({'source':name,'line':text.count('\n',0,match.start())+1,'path':value,'category':kind})
    return references


def audit(source, runtime):
    source=Path(source).resolve();runtime=Path(runtime).resolve()
    if source==runtime:raise ValueError('source-runtime-already-same')
    top=Path(git(source,'rev-parse','--show-toplevel').decode().strip()).resolve()
    if top!=source:raise ValueError('source-not-repository-root')
    names=[n for n in git(source,'ls-files','-z').decode().split('\0') if n]
    changes=[n for n in git(source,'diff','--name-only','-z','HEAD').decode().split('\0') if n]
    untracked=[n for n in git(source,'ls-files','--others','--exclude-standard','-z').decode().split('\0') if n]
    ignored=[n for n in git(source,'ls-files','--others','--ignored','--exclude-standard','-z').decode().split('\0') if n]
    rows=[]
    for name in names:
        if Path(name).is_absolute() or '..' in Path(name).parts:raise ValueError('source-path-invalid')
        left=source/name;right=runtime/name
        row={'path':name,'protected':protected(name),'sourceSha256':None,'runtimeSha256':None}
        if left.is_symlink() or right.is_symlink():row['status']='symlink-review'
        elif not left.is_file():row['status']='source-missing'
        else:
            row['sourceSha256']=digest(left)
            if not right.exists():row['status']='source-only'
            elif not right.is_file():row['status']='runtime-nonfile'
            else:
                row['runtimeSha256']=digest(right)
                row['status']='same' if row['sourceSha256']==row['runtimeSha256'] else 'review-difference'
        rows.append(row)
    counts={}
    for row in rows:counts[row['status']]=counts.get(row['status'],0)+1
    return {'schemaVersion':1,'mode':'read-only','source':str(source),'runtime':str(runtime),
            'head':git(source,'rev-parse','HEAD').decode().strip(),
            'refs':git(source,'for-each-ref','--format=%(refname):%(objectname)').decode().splitlines(),
            'trackedCount':len(names),'counts':counts,'rows':rows,'uncommittedTracked':changes,
            'untracked':untracked,'ignoredEntryCount':len(ignored),'runtimeHasGit':(runtime/'.git').exists(),
            'externalReferences':external_references(source,names),
            'productionFilesModified':False,'gitMetadataMoved':False}


def main():
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);a=p.parse_args()
    print(json.dumps(audit(a.source,a.runtime),ensure_ascii=False,sort_keys=True))
if __name__=='__main__':main()
