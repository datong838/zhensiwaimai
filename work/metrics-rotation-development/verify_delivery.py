import hashlib,json,subprocess,time,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
PY='/Users/ddt/.workbuddy/binaries/python/envs/default/bin/python';NODE='/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
WF=ROOT/'skills/workflows/daily-store-metrics-rotation-to-wechat'
production=[WF/'docs/全店铺运营指标商家反馈台账_2026-10.xlsx',WF/'docs/全店铺运营指标商家反馈台账_模板.xlsx',WF/'docs/店铺群映射_待填_2026-10.xlsx']
before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in production}
commands=[('python-regression',[PY,'-m','pytest',str(WF/'tests'),str(WF/'scripts/test_deliver_metric.py'),'-q','--basetemp',str(Path(tempfile.mkdtemp(prefix='metrics-final-'))/'pytest')]),('eleven-capture-contracts',[NODE,'--test',str(WF/'scripts/capture_receipt.test.mjs')]),('flow-order',['python3','runtime/assert_flow_order.py']),('registration-idempotence',[PY,'runtime/register_metrics_rotation_flow.py','--apply']),('skill-structure',[PY,'/Users/ddt/.codex/skills/.system/skill-creator/scripts/quick_validate.py',str(WF)])]
results=[]
for name,argv in commands:
 t=time.perf_counter();p=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=120);elapsed=round((time.perf_counter()-t)*1000)
 (OUT/(name+'.log')).write_text(p.stdout+p.stderr)
 results.append({'name':name,'exitCode':p.returncode,'elapsedMs':elapsed});print(name,p.returncode,elapsed)
 if p.returncode:break
after={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in production}
m0=json.loads((OUT/'baseline/skills_manifest.json').read_text());m1=json.loads((ROOT/'runtime/skills_manifest.json').read_text());p0=json.loads((OUT/'baseline/posts.json').read_text());p1=json.loads((ROOT/'runtime/posts.json').read_text())
existing_preserved=all(next(s for s in m1['skills'] if s['name']==x['name'])==x for x in m0['skills']) and all(x in m1['ledger_template'] for x in m0['ledger_template'])
registration=next(s for s in m1['skills'] if s['name']=='daily-store-metrics-rotation-to-wechat')
result={'ok':all(r['exitCode']==0 for r in results) and before==after and existing_preserved,'checks':results,'productionWorkbookHashesUnchanged':before==after,'productionWorkbookHashes':after,'existingTasksUnchanged':existing_preserved,'newTaskEnabled':registration['enabled'],'newTaskState':registration['dev_state'],'realSendPerformed':False,'realBrowserCapturePerformed':False}
(OUT/'acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='productionWorkbookHashes'},ensure_ascii=False))
raise SystemExit(0 if result['ok'] else 1)
