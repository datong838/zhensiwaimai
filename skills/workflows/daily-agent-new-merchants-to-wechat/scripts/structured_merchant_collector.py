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

STATE=Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/state/taobao-agent-new-merchants')
PRODUCTION_GROUP='电销+直播攻坚组'
PRODUCTION_CURSOR=STATE/'cursor.json'
CORE_COLLECTION_STAGES=('background_preflight','task_page','navigation','date_filter')

def today():return datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
def digest(value):return hashlib.sha256(value.encode()).hexdigest()
def private_json(path, value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())

def collection_stage_label(stage,receipt):
    labels={'background_preflight':'后台浏览器预检','task_page':'建立独立任务页','navigation':'进入意向商户列表',
            'date_filter':'日期设置与双帧回读'}
    if stage in labels:return labels[stage]
    page=re.fullmatch(r'page_(\d+)_(read|next)',stage)
    if page:return f"第{page[1]}页"+('采集与稳定核验' if page[2]=='read' else '翻页')
    if stage=='selection_audit':
        audit=receipt.get('selectionAudit') or {}
        if audit:
            return ('选择审计（总{totalRows}/游标及以前{excludedAtOrBeforeCursor}/'
                    '游标后非待处理{excludedAfterCursorNotPending}/待发{targetCount}）').format(**audit)
        return '选择审计'
    if stage.startswith('detail_'):return '商家详情核验 '+stage[7:]
    return stage

def build_collection_review(receipt):
    rows=[];stage_ms=receipt.get('stageMs') or {};stage_results=receipt.get('stageResults') or {}
    order=list(CORE_COLLECTION_STAGES)
    for stage in stage_ms:
        if stage not in order:order.append(stage)
    if 'selection_audit' not in order:order.append('selection_audit')
    for stage in order:
        entered=stage in stage_ms
        status=stage_results.get(stage,'SKIPPED' if not entered else 'FAIL')
        pitfalls=[receipt.get('error','collection-failed')] if status=='FAIL' else []
        rows.append({'item':len(rows)+1,'stage':stage,'label':collection_stage_label(stage,receipt),
                     'elapsedMs':stage_ms.get(stage),'status':status,'pitfalls':pitfalls})
    if receipt.get('ok') is not True and not any(row['status']=='FAIL' for row in rows):
        rows.append({'item':len(rows)+1,'stage':'collector','label':'采集器前置门禁','elapsedMs':None,
                     'status':'FAIL','pitfalls':[receipt.get('error','collection-failed')]})
    rows.append({'item':len(rows)+1,'stage':'total','label':'只读采集总耗时（含子阶段，不重复相加）',
                 'elapsedMs':receipt.get('elapsedMs'),'status':'PASS' if receipt.get('ok') is True else 'FAIL',
                 'pitfalls':[] if receipt.get('ok') is True else [receipt.get('error','collection-failed')]})
    return {'schemaVersion':1,'ok':receipt.get('ok') is True,'targetCount':receipt.get('targetCount'),
            'totalRows':receipt.get('totalRows'),'pendingRows':receipt.get('pendingRows'),'rows':rows}

def render_collection_review(review):
    labels={'PASS':'通过','FAIL':'失败','SKIPPED':'未执行'}
    def safe(value):return str(value).replace('|','\\|').replace('\n',' ')
    lines=['# 只读采集复盘','','| 项目 | 耗时 | 结果 | 踩坑点 |','|---|---:|---|---|']
    for row in review['rows']:
        elapsed='—' if row['elapsedMs'] is None else ('<0.001秒' if row['elapsedMs']==0 else f"{row['elapsedMs']/1000:.3f}秒")
        pitfalls='；'.join(row['pitfalls']) or ('前置门禁未通过' if row['status']=='SKIPPED' else '无')
        lines.append(f"| {safe(row['label'])} | {elapsed} | {labels[row['status']]} | {safe(pitfalls)} |")
    lines+=['','父阶段包含子阶段耗时，不能把所有行重复相加。']
    return '\n'.join(lines)+'\n'

def write_collection_review(out,receipt):
    out=Path(out);review=build_collection_review(receipt)
    json_path=out.with_name(out.stem+'.review.json');markdown_path=out.with_name(out.stem+'.review.md')
    private_json(json_path,review)
    markdown_path.write_text(render_collection_review(review),encoding='utf-8')
    return str(json_path),str(markdown_path)

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
    # 2026-10-22 修复（与 background_merchant_collector.stableIncremental 同步）：游标行可能因运营处理
    # 而移出「待处理」队列，matches 为空时降级为「严格晚于游标推荐时间」的时间水位，不阻塞当天增量；
    # 仅 matches>1（同一 merchantId+recommendTime 多行）仍视为行身份不唯一异常。
    if len(match)==0:return [r for r in ordered if r['recommendTime']>cursor['recommendTime']]
    if len(match)>1:raise UIError('same-day-cursor-not-unique')
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
            if not re.fullmatch(r'\d{6,}',data.get('商家ID','')):continue
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
        # 换行符会被 **Windows 服务网关** 弄丢（不是微信输入框），多行正文到达对端后
        # 挤成一行、字段首尾相连。2026-10-02 大同实测反馈即此问题（「淘宝新增商家增量
        # 通知」两行数据叠在一起）。按大同最终要求用「  ；  」（中文全角分号、前后各 2 空格）
        # 分隔并加字段标签，单行可读且有分割感；不依赖换行符（网关丢换行是运输层问题，正文里不能出现 \n）。
        def _flat(v):
            # 源字段值可能自带换行（如地址多行、联系人分段），Windows 服务网关会丢换行 →
            # 多行挤成一行、字段首尾相连。拼装前把所有空白（含 \n/\r/多空格）折叠为单空格，
            # 确保最终正文永不含换行符（运输层丢换行是正文本质问题，正文里不能出现 \n）。
            return ' '.join(str(v or '').split())
        lines=[f"城市：{_flat(result['city']) or '（城市字段缺失）'}",
               f"联系人：{_flat(result['contact']) or '（商家联系人字段缺失）'}",
               f"店铺：{_flat(name) or '（商家名称字段缺失）'}",
               f"地址：{_flat(result['address']) or '（商家地址字段缺失）'}",
               f"商家ID：{_flat(result['merchantId']) or '（商家ID字段缺失）'}"]
        result['text']='  ；  '.join(lines);result['sha256']=digest(result['text'])
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


def collect(group,cursor_path,out,timeout_seconds=180):
    """Default deterministic collector: isolated headless Chrome over localhost CDP."""
    out=Path(out);date=today();started=time.monotonic();completed=None
    try:
        if group!=PRODUCTION_GROUP:raise UIError('production-only-target-required')
        cursor,source=cursor_state(cursor_path,group)
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
        completed=subprocess.run([NODE,str(BACKGROUND_EXECUTOR),'--input',str(control),'--out',str(out)],capture_output=True,text=True,timeout=min(180,timeout_seconds))
        try:r=json.loads(out.read_text())
        except (OSError,json.JSONDecodeError):
            r={'ok':False,'executor':'merchant-collector','browserController':'control-background-dedicated-chrome','groupName':group,'businessDate':date,
               'runtimeModelDecisions':0,'error':'background-collector-invalid-receipt'}
    except subprocess.TimeoutExpired:
        r={'ok':False,'executor':'merchant-collector','browserController':'control-background-dedicated-chrome','groupName':group,'businessDate':date,
           'runtimeModelDecisions':0,'stageMs':{},'stageResults':{},'error':'background-collector-timeout',
           'elapsedMs':round((time.monotonic()-started)*1000)}
    except Exception as error:
        r={'ok':False,'executor':'merchant-collector','browserController':'control-background-dedicated-chrome','groupName':group,'businessDate':date,
           'runtimeModelDecisions':0,'stageMs':{},'stageResults':{},'error':str(error),
           'elapsedMs':round((time.monotonic()-started)*1000)}
    if completed is not None and completed.returncode and r.get('ok'):
        r['ok']=False;r['error']='background-collector-process-failed'
    if 'elapsedMs' not in r:r['elapsedMs']=round((time.monotonic()-started)*1000)
    private_json(out,r)
    review_json,review_markdown=write_collection_review(out,r)
    r['reviewPath']=review_json;r['reviewMarkdownPath']=review_markdown;private_json(out,r)
    return r

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--group',default=PRODUCTION_GROUP);p.add_argument('--cursor-file',default=str(PRODUCTION_CURSOR));p.add_argument('--out',required=True);a=p.parse_args()
    r=collect(a.group,Path(a.cursor_file),Path(a.out));print(json.dumps({k:v for k,v in r.items() if k not in ['messages','cursor']},ensure_ascii=False));raise SystemExit(0 if r['ok'] else 1)
