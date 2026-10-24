#!/usr/bin/env python3
import collections, hashlib, json, os, re, sys
from pathlib import Path
import openpyxl

FIELDS=['店铺名称','总分','评价日期','店铺类型','差评内容','点踩商品','评论订单详情']

def norm(value): return '' if value is None else str(value).replace('\r\n','\n').replace('\r','\n').strip()
def compact(value): return re.sub(r'\s+',' ',norm(value))
def raw_key(row): return (compact(row['店铺名称']),str(row['总分']),norm(row['评价日期'])[:10],norm(row['店铺类型']),compact(row['差评内容']))
def ui_key(row): return (compact(row['store']),norm(row['score']).replace('总分',''),norm(row['date'])[:10],norm(row['platform']),compact(row['comment']))

def read_raw(raw):
    workbook=openpyxl.load_workbook(raw,data_only=True,read_only=True)
    sheet=workbook.active;rows=list(sheet.iter_rows(values_only=True))
    if len(rows)<3: raise ValueError('raw-workbook-too-short')
    header=list(rows[2])
    if any(field not in header for field in FIELDS): raise ValueError('raw-fields-mismatch')
    data=[]
    for row in rows[3:]:
        if not any(norm(value) for value in row): continue
        item={name:row[index] for index,name in enumerate(header) if name}
        data.append({field:item.get(field) for field in FIELDS})
    return data,sheet.title

def reconcile(config):
    raw_path=Path(config['raw']);ui=json.loads(Path(config['uiStatus']).read_text())
    raw,sheet=read_raw(raw_path);date=config['businessDate']
    if sheet!='差评分析数据': raise ValueError('raw-sheet-name-mismatch')
    if len(raw)!=len(ui['rows']) or len(raw)!=sum(ui['counts'].values()): raise ValueError('record-count-mismatch')
    if any(not norm(row['评价日期']).startswith(date) for row in raw): raise ValueError('raw-date-mismatch')
    if collections.Counter(raw_key(row) for row in raw)!=collections.Counter(ui_key(row) for row in ui['rows']): raise ValueError('raw-ui-multiset-mismatch')
    pools=collections.defaultdict(list)
    for row in ui['rows']: pools[ui_key(row)].append(row)
    output=[];supplemented=[];excluded=[]
    for row in raw:
        match=pools[raw_key(row)].pop();item={field:row.get(field) for field in FIELDS}
        try: score=float(row['总分'])
        except Exception as error: raise ValueError('score-invalid') from error
        if score not in (1,2,3):
            excluded.append({'店铺名称':norm(row['店铺名称']),'平台':norm(row['店铺类型']),'总分':row['总分'],'差评内容':norm(row['差评内容'])})
            continue
        status=norm(match.get('status'))
        if not norm(item['差评内容']) and status:
            item['差评内容']=status;supplemented.append({'店铺名称':norm(item['店铺名称']),'平台':norm(item['店铺类型']),'总分':item['总分'],'提示':status})
        output.append(item)
    if any(pools.values()): raise ValueError('ui-unconsumed-rows')
    profile={'sourceRecords':len(raw),'records':len(output),'platforms':dict(collections.Counter(norm(row['店铺类型']) for row in output)),'scores':dict(collections.Counter(str(row['总分']) for row in output)),'scoresAbove3':0,'excludedAboveThree':len(excluded),'blankBefore':sum(not norm(row['差评内容']) for row in raw if float(row['总分']) in (1,2,3)),'supplementedFromUi':len(supplemented),'blankAfter':sum(not norm(row['差评内容']) for row in output),'stores':len(set((norm(row['店铺类型']),norm(row['店铺名称'])) for row in output))}
    result={'ok':True,'businessDate':date,'fields':FIELDS,'profile':profile,'uiCounts':ui['counts'],'rawSha256':hashlib.sha256(raw_path.read_bytes()).hexdigest(),'supplemented':supplemented,'sourceRows':len(raw),'excludedAboveThree':excluded,'businessWarnings':ui.get('businessWarnings',[]),'runtimeModelDecisions':0}
    Path(config['finalData']).write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str))
    Path(config['analysis']).write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    return result

def main():
    if os.environ.get('NEGATIVE_REVIEW_INTERNAL')!='daily-negative-reviews-workflow-executor-v1': raise ValueError('direct-stage-invocation-forbidden')
    config=json.loads(Path(sys.argv[1]).read_text());print(json.dumps(reconcile(config),ensure_ascii=False))

if __name__=='__main__': main()
