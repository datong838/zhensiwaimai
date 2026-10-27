import collections, hashlib, json, re, zipfile
from pathlib import Path
import openpyxl

ROOT=Path(__file__).resolve().parent
FIELDS=['店铺名称','总分','评价日期','店铺类型','差评内容','点踩商品','评论订单详情']
RAW=ROOT/'raw/差评分析数据_2026-09-14_2026-09-14.xlsx'

def norm(v): return '' if v is None else str(v).replace('\r\n','\n').replace('\r','\n').strip()
def compact(v): return re.sub(r'\s+',' ',norm(v))
def raw_key(r): return (norm(r['店铺名称']),str(r['总分']),norm(r['评价日期'])[:10],norm(r['店铺类型']),compact(r['差评内容']))
def ui_key(r): return (norm(r['store']),norm(r['score']).replace('总分',''),norm(r['date'])[:10],norm(r['platform']),compact(r['comment']))

def read_raw():
    wb=openpyxl.load_workbook(RAW,data_only=True);ws=wb.active
    rows=list(ws.iter_rows(values_only=True));header=list(rows[2]);data=[]
    for row in rows[3:]:
        if not any(norm(v) for v in row): continue
        item={name:row[i] for i,name in enumerate(header) if name}
        data.append({f:item.get(f) for f in FIELDS})
    return data,ws.title

def main():
    raw,sheet=read_raw();ui=json.loads((ROOT/'ui-status.json').read_text())
    assert sheet=='差评分析数据' and len(raw)==132 and len(ui['rows'])==132
    assert all(norm(r['评价日期']).startswith('2026-09-14') for r in raw)
    assert collections.Counter(raw_key(r) for r in raw)==collections.Counter(ui_key(r) for r in ui['rows'])
    pools=collections.defaultdict(list)
    for row in ui['rows']: pools[ui_key(row)].append(row)
    output=[];supplemented=[]
    for row in raw:
        match=pools[raw_key(row)].pop()
        status=norm(match.get('status'))
        item={f:row.get(f) for f in FIELDS}
        if not norm(item['差评内容']) and status:
            item['差评内容']=status;supplemented.append({'店铺名称':norm(item['店铺名称']),'平台':norm(item['店铺类型']),'总分':item['总分'],'提示':status})
        output.append(item)
    assert all(not values for values in pools.values())
    profile={'records':len(output),'platforms':dict(collections.Counter(norm(r['店铺类型']) for r in output)),'scores':dict(collections.Counter(str(r['总分']) for r in output)),'scoresAbove3':sum(float(r['总分'])>3 for r in output),'blankBefore':sum(not norm(r['差评内容']) for r in raw),'supplementedFromUi':len(supplemented),'blankAfter':sum(not norm(r['差评内容']) for r in output),'stores':len(set((norm(r['店铺类型']),norm(r['店铺名称'])) for r in output))}
    result={'ok':True,'date':'2026-09-14','fields':FIELDS,'profile':profile,'uiCounts':ui['counts'],'rawSha256':hashlib.sha256(RAW.read_bytes()).hexdigest(),'supplemented':supplemented,'contextWarning':['授权失败']}
    (ROOT/'final-data.json').write_text(json.dumps(output,ensure_ascii=False,indent=2,default=str))
    (ROOT/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__': main()
