#!/usr/bin/env python3
"""Collect only rendered AX business rows; never use network or browser internals."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
try:
    from native_service_ui import ServiceUI, UIError, attr, intention_page, run_route
except ModuleNotFoundError as exc:
    # The default CDP collector must not require legacy macOS AX/AppKit modules.
    # Keep the historical implementation importable for contracts and cursor logic.
    if exc.name != 'AppKit':
        raise
    class UIError(RuntimeError):pass
    class ServiceUI:pass
    def _legacy_ax_unavailable(*_args, **_kwargs):raise UIError('legacy-ax-appkit-unavailable')
    attr=intention_page=run_route=_legacy_ax_unavailable

STATE=Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai/state/taobao-agent-new-merchants')

def today():return datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def private_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())

def valid_cursor(c,group):
    return isinstance(c,dict) and c.get('verified') is True and c.get('groupName')==group and all(c.get(k) is not None for k in ('merchantId','recommendTime','tableOrder')) and bool(re.fullmatch(r'\d{4}-\d\d-\d\d \d\d:\d\d:\d\d',c['recommendTime']))
def cursor_state(path,group):
    cursor=None
    try:cursor=json.loads(Path(path).read_text())
    except (OSError,ValueError):pass
    history=[]
    hp=Path(path).parent/'send-history.jsonl'
    if hp.exists():
        for line in hp.read_text().splitlines():
            c=json.loads(line)
            if valid_cursor(c,group):history.append(c)
    if history and (not valid_cursor(cursor,group) or history[-1]['recommendTime']>=cursor['recommendTime']):
        return history[-1],'verified-history'
    if not valid_cursor(cursor,group):raise UIError('cursor-unavailable-requires-group-recovery')
    return cursor,'local'

def incremental(rows,cursor,date):
    ordered=sorted(rows,key=lambda r:r['recommendTime'])
    for n,r in enumerate(ordered,1):r['tableOrder']=n
    if cursor['recommendTime'] < date+' 00:00:00':return ordered
    match=[i for i,r in enumerate(ordered) if r['merchantId']==cursor['merchantId'] and r['recommendTime']==cursor['recommendTime']]
    if len(match)!=1:raise UIError('same-day-cursor-not-unique')
    return ordered[match[0]+1:]

class Collector(ServiceUI):
    def __init__(self):super().__init__(budget=180)
    def text(self,i):return ''.join(self.nodes[j]['label'] for j in self.descendants(i) if self.nodes[j]['role']=='AXStaticText').strip()
    def rows(self):
        rows=[];headers=None
        for i,n in enumerate(self.nodes):
            if n['role']!='AXRow':continue
            cells=[j for j,x in enumerate(self.nodes) if x['parent']==i and x['role']=='AXCell']
            values=[self.text(j) for j in cells]
            if '商家ID' in values and '推荐时间' in values:headers=values;continue
            if not headers or len(values)!=len(headers):continue
            data=dict(zip(headers,values))
            if not re.fullmatch(r'\d{7,}',data.get('商家ID','')):continue
            rows.append({'merchantId':data['商家ID'],'merchantName':data['商家名称'],'recommendTime':data['推荐时间'],'city':data['城市'],'status':data['状态'],'node':i})
        if headers is None:raise UIError('table-headers-missing')
        return rows
    def pager(self):
        active=[];next_nodes=[];numbers=[]
        for i,n in enumerate(self.nodes):
            classes=list(attr(n['element'],'AXDOMClassList') or [])
            if 'ant-pagination-item' in classes:
                v=self.text(i)
                if v.isdigit():numbers.append(int(v))
            if 'ant-pagination-item-active' in classes:active.append(int(self.text(i)))
            if n['label']=='下一页':next_nodes.append(n)
        if len(active)!=1 or len(next_nodes)!=1:raise UIError('pagination-state-not-unique')
        return {'page':active[0],'lastVisiblePage':max(numbers),'nextEnabled':bool(attr(next_nodes[0]['element'],'AXEnabled'))}
    def stable_page(self,expected=None):
        previous=None
        def ready(s):
            nonlocal previous
            try:
                rows=self.rows();pager=self.pager()
                sig=(pager['page'],tuple((r['merchantId'],r['recommendTime'],r['status']) for r in rows))
                good=(expected is None or pager['page']==expected) and previous==sig
                previous=sig
                return good
            except UIError:return False
        self.wait(ready)
    def close_detail(self):
        self.snapshot()
        if '推荐商家详情' in [n['label'] for n in self.nodes]:
            self.press('Close');self.wait(intention_page)
    def filter(self,date):
        self.set_today_range(date);self.press('查询');self.stable_page(1)
        if any(attr(self.field(p)['element'],'AXValue')!=date for p in ['开始日期','结束日期']):raise UIError('date-filter-lost')
    def detail(self,row):
        self.snapshot();matches=[r for r in self.rows() if r['merchantId']==row['merchantId'] and r['merchantName']==row['merchantName']]
        if len(matches)!=1:raise UIError('detail-row-not-unique')
        buttons=[i for i in self.descendants(matches[0]['node']) if self.nodes[i]['role']=='AXButton' and self.nodes[i]['label']=='详情']
        if len(buttons)!=1:raise UIError('detail-action-not-unique')
        self.press_index(buttons[0]);self.wait(lambda s:'推荐商家详情' in s['labels'])
        fields=['商家名称','商家ID','商家地址','商家联系人','是否已告知价格','商家意愿度','意向举证','备注','推荐人']
        previous=None
        def detail_ready(state):
            nonlocal previous
            labels=tuple(n['label'].strip() for n in self.nodes if n['role']=='AXStaticText' and n['label'].strip())
            ready=all(labels.count(name)==1 for name in fields) and previous==labels
            previous=labels
            return ready
        self.wait(detail_ready)
        labels=[n['label'].strip() for n in self.nodes if n['role']=='AXStaticText' and n['label'].strip()]
        def field(name):
            starts=[i for i,x in enumerate(labels) if x==name]
            if len(starts)!=1:raise UIError('detail-label-not-unique:'+name)
            end=next((i for i in range(starts[0]+1,len(labels)) if labels[i] in fields),len(labels))
            return ''.join(labels[starts[0]+1:end])
        name=field('商家名称');mid=field('商家ID')
        if (name,mid)!=(row['merchantName'],row['merchantId']):raise UIError('detail-identity-mismatch')
        result={k:v for k,v in row.items() if k!='node'}
        result.update(contact=field('商家联系人'),address=field('商家地址'),detailVerified=True)
        lines=[result['city'] or '（城市字段缺失）',result['contact'] or '（商家联系人字段缺失）',name or '（商家名称字段缺失）',result['address'] or '（商家地址字段缺失）']
        result['text']='\n'.join(lines);result['sha256']=digest(result['text'])
        self.close_detail();return result


def collect_existing_chrome(group,cursor_path,out):
    c=Collector();date=today();r={'ok':False,'executor':'merchant-collector','groupName':group,'businessDate':date,'stageMs':c.stage_ms,'runtimeModelDecisions':0,'messages':[]}
    try:
        cursor,source=cursor_state(cursor_path,group)
        c.stage('attach',c.attach);c.stage('close_residual_detail',c.close_detail);c.stage('navigation',lambda:run_route(c))
        c.stage('date_filter',lambda:c.filter(date))
        all_rows=[];pages=[];seen=set()
        for page in range(1,51):
            c.stage(f'page_{page}_read',lambda:c.stable_page(page))
            rows=c.rows();pager=c.pager()
            if any(not re.fullmatch(date+r' \d\d:\d\d:\d\d',x['recommendTime']) for x in rows):raise UIError('non-today-row-after-filter')
            ids={x['merchantId'] for x in rows}
            if len(ids)!=len(rows) or ids & seen:raise UIError('duplicate-pagination-row')
            seen.update(ids);pages.append({**pager,'rowCount':len(rows)})
            for row in rows:row['sourcePage']=page
            all_rows.extend(rows)
            if not pager['nextEnabled']:break
            c.stage(f'page_{page}_next',lambda:c.press('下一页'))
        else:raise UIError('pagination-budget-exceeded')
        pending=[x for x in all_rows if x['status']=='待处理']
        targets=incremental(pending,cursor,date)
        for row in targets:
            page=row['sourcePage'];current=c.pager()['page']
            while current>page:c.press('上一页');current-=1;c.stable_page(current)
            while current<page:c.press('下一页');current+=1;c.stable_page(current)
            item=c.stage('detail_'+row['merchantId'],lambda row=row:c.detail(row));r['messages'].append(item)
        if today()!=date:raise UIError('business-date-changed-during-run')
        r.update(ok=True,createdAt=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),cursor=cursor,cursorSource=source,
                 dateFilter=date+'..'+date,dateFilterVerified=True,pages=pages,paginationComplete=True,totalRows=len(all_rows),pendingRows=len(pending),targetCount=len(targets),ascending=True,detailsVerified=True)
    except Exception as e:r['error']=str(e)
    r.update(elapsedMs=round((time.monotonic()-c.started)*1000),frontmostBefore=c.frontmost_before,frontmostAfter=c.frontmost())
    private_json(out,r);return r


NODE='/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'
BACKGROUND_EXECUTOR=Path(__file__).with_name('background_merchant_collector.mjs')
BACKGROUND_PROFILE='taobao-agent-service'
BACKGROUND_PORT=9231


def collect(group,cursor_path,out):
    """Default deterministic collector: isolated headless Chrome over localhost CDP."""
    out=Path(out);date=today();cursor,source=cursor_state(cursor_path,group)
    control=out.with_name(out.stem+'-browser-input.json')
    private_json(control,{
        'profile':BACKGROUND_PROFILE,
        'port':BACKGROUND_PORT,
        'taskId':'agent-merchants-'+uuid.uuid4().hex[:16],
        'group':group,
        'businessDate':date,
        'cursor':cursor,
        'cursorSource':source,
    })
    completed=subprocess.run([NODE,str(BACKGROUND_EXECUTOR),'--input',str(control),'--out',str(out)],capture_output=True,text=True,timeout=180)
    try:r=json.loads(out.read_text())
    except (OSError,json.JSONDecodeError):
        r={'ok':False,'executor':'merchant-collector','browserController':'control-background-dedicated-chrome','groupName':group,'businessDate':date,
           'runtimeModelDecisions':0,'error':'background-collector-invalid-receipt'}
        private_json(out,r)
    if completed.returncode and r.get('ok'):
        r['ok']=False;r['error']='background-collector-process-failed';private_json(out,r)
    return r

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--group',default='FEIBING NEO AI数字员工');p.add_argument('--cursor-file',default=str(STATE/'cursor.test.json'));p.add_argument('--out',required=True);a=p.parse_args()
    r=collect(a.group,Path(a.cursor_file),Path(a.out));print(json.dumps({k:v for k,v in r.items() if k not in ['messages','cursor']},ensure_ascii=False));raise SystemExit(0 if r['ok'] else 1)
