"""Pure registration projection; never enables a new unaccepted production sender."""
from copy import deepcopy
FLOW='daily-store-metrics-rotation-to-wechat'
ENTRY={
 'name':FLOW,'ledger_name':'20项运营指标全店铺互动反馈','target_group':'按已确认店铺群映射',
 'schedule':'待确定首发日期','dev_state':'pending','enabled':False,'order':30,'cadence_hours':24,
 'earliest_hour':10,'latest_hour':18,'cwd':f'skills/workflows/{FLOW}',
 'timeout_seconds':28800,'max_retries':0,'cooldown_seconds':300,'needs_adapter':False,
 'steps':[{'argv':['{python}','scripts/metrics_rotation_daily.py','--mode','execute']}],
 'note':'M01–M11已开发；群映射、起始日期、10店真实灰度尚未验收，默认不派班。只复用9230品牌商岗与统一微信发送岗。'
}
def register(manifest,posts):
 m,p=deepcopy(manifest),deepcopy(posts)
 entries=[s for s in m.get('skills',[]) if s.get('name')==FLOW]
 if len(entries)>1:raise ValueError('duplicate-workflow-registration')
 if not entries:m.setdefault('skills',[]).append(deepcopy(ENTRY))
 if not any(r.get('skill')==FLOW for r in m.get('ledger_template',[])):
  row=max((r['row'] for r in m.get('ledger_template',[])),default=0)+1
  m.setdefault('ledger_template',[]).append({'row':row,'ledger_name':ENTRY['ledger_name'],'schedule':ENTRY['schedule'],'dev_state':'pending','skill':FLOW})
 matches=[v for v in p.get('posts',{}).values() if v.get('port')==9230]
 if len(matches)!=1:raise ValueError('brand-post-not-unique')
 used=matches[0].setdefault('usedBy',[])
 if FLOW not in used:used.append(FLOW)
 return m,p
