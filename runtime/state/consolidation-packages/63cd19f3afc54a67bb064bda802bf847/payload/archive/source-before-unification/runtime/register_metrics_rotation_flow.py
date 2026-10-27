#!/usr/bin/env python3
"""Register the task in a disabled pending state. No daemon restart or external effect."""
import argparse,json,shutil,time
from pathlib import Path
from metrics_rotation_registration import register,FLOW
ROOT=Path(__file__).resolve().parent

def main(argv=None):
 p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');p.add_argument('--manifest',type=Path,default=ROOT/'skills_manifest.json');p.add_argument('--posts',type=Path,default=ROOT/'posts.json');a=p.parse_args(argv)
 originals=[json.loads(f.read_text()) for f in [a.manifest,a.posts]];updated=register(*originals)
 changed=[str(f) for f,old,new in zip([a.manifest,a.posts],originals,updated) if old!=new]
 if a.apply:
  from contextlib import ExitStack
  import fcntl,os,uuid
  with ExitStack() as stack:
   # Serialise this registration tool; compare source bytes immediately before writing.
   for f in [a.manifest,a.posts]:
    h=stack.enter_context(f.with_suffix(f.suffix+'.registration.lock').open('a+'));fcntl.flock(h,fcntl.LOCK_EX)
   if any(json.loads(f.read_text())!=old for f,old in zip([a.manifest,a.posts],originals)):raise ValueError('registration-source-changed')
   for f,old,new in zip([a.manifest,a.posts],originals,updated):
    if old==new:continue
    shutil.copy2(f,f.with_name(f.name+'.bak-metrics-'+time.strftime('%Y%m%d-%H%M%S')))
    tmp=f.with_name(f.name+'.'+uuid.uuid4().hex+'.tmp');tmp.write_text(json.dumps(new,ensure_ascii=False,indent=2)+'\n');os.replace(tmp,f)
 print(json.dumps({'ok':True,'workflowId':FLOW,'applied':a.apply,'changed':changed,'enabled':next(x for x in updated[0]['skills'] if x['name']==FLOW)['enabled'],'daemonReloaded':False},ensure_ascii=False));return 0
if __name__=='__main__':raise SystemExit(main())
