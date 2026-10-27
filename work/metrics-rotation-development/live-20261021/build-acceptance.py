import json,pathlib,hashlib
repo=pathlib.Path.cwd();wf=repo/'skills/workflows/daily-store-metrics-rotation-to-wechat';root=repo/'work/metrics-rotation-development/live-20261021'
runs=sorted((root/'state/runs').glob('*/receipt.json'),key=lambda p:p.stat().st_mtime)
allruns=[json.loads(p.read_text()) for p in runs]
chosen={}
for d in allruns:
 for r in d['rows']:
  if r['status']=='captured':chosen[r['metric']]={**r,'runId':d['runId'],'executorBaselineHash':d.get('executorBaselineHash')}
notes={
'M01':'评分4.4；质量4.5；服务4.4；6行明细。首图被手机号提醒遮挡，已拒收并重采。',
'M02':'概览5卡为--/暂无；下单顾客趋势有折线。仅部分数据可用，未确认缺失原因。',
'M03':'近30日下单频次表明确显示暂无数据。',
'M04':'近30日下单时段明确显示暂无数据。',
'M05':'近30日热门街区TOP10暂无数据；地图正常显示。',
'M06':'互动行为近7日有值（评分4.7/评价6/未评价77/差评1）；画像近30日暂无数据。',
'M07':'近30日历史概览多项--，不可当作0或完整数据。',
'M08':'近30日漏斗本店和同行均显示0，未独立验证是否为真实零值。',
'M09':'自然流量来源明确显示暂无数据。',
'M10':'近30日商品明细暂无数据；原时间坐标范围漏掉下移控件，已改唯一语义组定位并重采。',
'M11':'三图无损合成；概览本周服务异常率9.1%、出餐上报100%；营业/出餐近30日多项--。日期输入框由页面自身横向压缩，但已激活近30日。'}
rows=[]
for mid,r in sorted(chosen.items()):
 attempts=[{'runId':d['runId'],'status':x['status'],'elapsedMs':x['elapsedMs'],'pitfalls':x['pitfalls']} for d in allruns for x in d['rows'] if x['metric']==mid]
 r['attempts']=attempts;r['attemptElapsedMs']=sum(x['elapsedMs'] for x in attempts);r['visualReview']='unobstructed-region-reviewed';r['dataObservation']=notes[mid];r['sha256']=hashlib.sha256((repo/r['image']).read_bytes()).hexdigest();rows.append(r)
ledger=wf/'docs/全店铺运营指标商家反馈台账_2026-10.xlsx';before=json.loads((root/'before.json').read_text());after=hashlib.sha256(ledger.read_bytes()).hexdigest()
events=list((root/'state/events').glob('*.json'));checkpoints=list((root/'state/checkpoints').glob('*.json'))
assert len(rows)==11 and all((repo/r['image']).is_file() for r in rows)
assert before['ledgerSha256']==after and not events and not checkpoints
out={'businessDate':'2026-10-21','scope':'one store × M01–M11; capture only; recovery runs retained','shopId':'694471','shopName':'李当家汉派猪蹄饭(一清路店)','sourcePoolTotal':863,'captureReviewed':11,'businessDataComplete':False,'sendRequested':False,'sendEvents':len(events),'sendCheckpoints':len(checkpoints),'ledgerUnchanged':True,'ledgerSha256':after,'measuredWorkflowElapsedMs':sum(d['elapsedMs'] for d in allruns),'rows':rows,'tests':{'python':{'passed':32,'seconds':1.25},'node':{'passed':18,'seconds':0.0556},'legacyLedgerScript':{'failed':5,'reason':'hardcoded 486 stores and former 20-slot assumptions; temporary copy only; not a pytest module'}},'productionEnabled':False}
(root/'real-acceptance.json').write_text(json.dumps(out,ensure_ascii=False,indent=2))
lines=['# 2026-10-21 真机采集验收（禁止发送）','','使用Rules：本流SKILL.md、REQUIREMENTS.md最新口径、IMPLEMENTATION.md、项目岗位互斥与测试隔离规则。只用9230既有独立品牌商浏览器；不登录、不碰其他岗位；一店11指标；不调用发送器、不写反馈成功。','','样本：694471 李当家汉派猪蹄饭(一清路店)。正式池863家，本次仅1家，不代表全量验收。正式入口capture模式，故障修复后按未完成项续跑，不是一次无故障成功。','','11项均已取得对应区域并核图；M01旧遮挡图拒收，M10旧今日实时图拒收，保留全部失败收据。截图链路完成不等于业务数据完整：本轮多处暂无/--/零值未独立核实，不能启用正式投递。','','| 项目 | 最终采集耗时 | 含失败尝试累计 | 观察及踩坑 | 证据 |','|---|---:|---:|---|---|']
for r in rows:lines.append(f"| {r['metric']} | {r['elapsedMs']/1000:.2f}秒 | {r['attemptElapsedMs']/1000:.2f}秒 | {r['dataObservation']} | [图片]({repo/r['image']}) |")
lines+=['','耗时为正式执行器各run测得的处理时间；累计保留失败/废弃图耗时，不含人工核图、排障、编码等待。完整流程run总处理时间：'+str(round(out['measuredWorkflowElapsedMs']/1000,2))+'秒。','','## 固化进代码的修复','','- capture缺群仍可采集；execute缺群继续阻断，不填假群。','- 切店前精确处理可选手机号提醒，未知/安全弹窗阻断。','- 所有Page.captureScreenshot前统一复核提醒，提醒不消失或未知弹窗不得截图；三条正负测试。','- M10使用唯一完整选项时间组定位，保留近30日激活态回读；不再依赖150–240坐标带。','- 子进程错误保留白名单FAIL代码和M10时间/区域诊断。','','变更位于本工作流scripts/rotation_workflow.py、metrics_rotation_daily.py、switch_shop.mjs、capture_for_metric.mjs、capture_biz.mjs、lib/cdp.mjs、lib/known_overlay.mjs、lib/time_controls.mjs及对应tests；不改已封印岗位和共享发送器。','','## 验证与边界','','- 正式台账sha256前后相同：`'+after+'`。独立runtime发送events/checkpoints均0；各正式run externalEffectRequested=false。','- Python32项通过（1.25秒），Node18项通过（0.056秒）。','- 旧scripts/test_ledger_ops.py用pytest收集时触发顶层sys.exit，5项过时断言失败（486家/旧20槽假设）；只操作临时副本，未修改正式台账。未隐去该失败。','- 任务仍pending/disabled；没有启用调度、没有发微信、没有写反馈成功。','- 本轮不能证明空值的业务原因；采集器尚未将这些空数据现状统一转成带证据的no-data合同，正式投递前必须完善，不把captured当可发送数据。','- 本轮各次基线不同，收据保存各run executorBaselineHash；不是最终版本一次性全11项验收，更不是封印。','- capture收据summary.remaining目前按待投递数量计算，因此capture完成时仍非0；本验收不据此声称已投递。','- 最终登录/chain复位证据见同目录final-probe.json；探针与岗位锁释放验证追加在机器证据中。','','机器证据：['+str(root/'real-acceptance.json')+']('+str(root/'real-acceptance.json')+')。']
(wf/'docs/REAL-CAPTURE-ACCEPTANCE-20261021.md').write_text('\n'.join(lines)+'\n')
p=wf/'docs/DEVELOPMENT-ACCEPTANCE.md';s=p.read_text();s+='\n\n## 2026-10-21 后续真机实操\n\n上述“没有操作真实浏览器”为开发离线阶段历史边界，现已完成1家×11项只采集演练及核图；发生故障后修复续跑，非一次全绿。页面多项无数据/空值，数据完整性和真实投递仍未验收，任务继续pending/disabled。详见[真机复盘](REAL-CAPTURE-ACCEPTANCE-20261021.md)。\n';p.write_text(s)
print(json.dumps({k:v for k,v in out.items() if k!='rows'},ensure_ascii=False))
