import collections
import hashlib
import json
import re
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent
DATE = '2026-09-17'
FIELDS = ['店铺名称', '总分', '评价日期', '店铺类型', '差评内容', '点踩商品', '评论订单详情']
RAW = ROOT / 'raw' / f'差评分析数据_{DATE}_{DATE}.xlsx'


def norm(value):
    return '' if value is None else str(value).replace('\r\n', '\n').replace('\r', '\n').strip()


def compact(value):
    return re.sub(r'\s+', ' ', norm(value))


def raw_key(row):
    return (compact(row['店铺名称']), str(row['总分']), norm(row['评价日期'])[:10], norm(row['店铺类型']), compact(row['差评内容']))


def ui_key(row):
    return (compact(row['store']), norm(row['score']).replace('总分', ''), norm(row['date'])[:10], norm(row['platform']), compact(row['comment']))


def read_raw():
    workbook = openpyxl.load_workbook(RAW, data_only=True)
    worksheet = workbook.active
    rows = list(worksheet.iter_rows(values_only=True))
    header = list(rows[2])
    data = []
    for row in rows[3:]:
        if not any(norm(value) for value in row):
            continue
        item = {name: row[index] for index, name in enumerate(header) if name}
        data.append({field: item.get(field) for field in FIELDS})
    return data, worksheet.title


def main():
    raw, sheet = read_raw()
    ui = json.loads((ROOT / 'ui-status.json').read_text())
    assert sheet == '差评分析数据'
    assert len(raw) == len(ui['rows']) == sum(ui['counts'].values())
    assert all(norm(row['评价日期']).startswith(DATE) for row in raw)
    assert collections.Counter(raw_key(row) for row in raw) == collections.Counter(ui_key(row) for row in ui['rows'])
    pools = collections.defaultdict(list)
    for row in ui['rows']:
        pools[ui_key(row)].append(row)
    output = []
    supplemented = []
    retained_above_three = []
    for row in raw:
        match = pools[raw_key(row)].pop()
        if float(row['总分']) > 3:
            retained_above_three.append({
                '店铺名称': norm(row['店铺名称']),
                '平台': norm(row['店铺类型']),
                '总分': row['总分'],
                '差评内容': norm(row['差评内容']),
            })
        status = norm(match.get('status'))
        item = {field: row.get(field) for field in FIELDS}
        if not norm(item['差评内容']) and status:
            item['差评内容'] = status
            supplemented.append({'店铺名称': norm(item['店铺名称']), '平台': norm(item['店铺类型']), '总分': item['总分'], '提示': status})
        output.append(item)
    assert all(not values for values in pools.values())
    profile = {
        'records': len(output),
        'platforms': dict(collections.Counter(norm(row['店铺类型']) for row in output)),
        'scores': dict(collections.Counter(str(row['总分']) for row in output)),
        'scoresAbove3': sum(float(row['总分']) > 3 for row in output),
        'blankBefore': sum(not norm(row['差评内容']) for row in raw),
        'supplementedFromUi': len(supplemented),
        'blankAfter': sum(not norm(row['差评内容']) for row in output),
        'stores': len(set((norm(row['店铺类型']), norm(row['店铺名称'])) for row in output)),
    }
    result = {
        'ok': True,
        'date': DATE,
        'fields': FIELDS,
        'profile': profile,
        'uiCounts': ui['counts'],
        'rawSha256': hashlib.sha256(RAW.read_bytes()).hexdigest(),
        'supplemented': supplemented,
        'sourceRows': len(raw),
        'retainedAboveThree': retained_above_three,
        'businessWarnings': ui.get('businessWarnings', []),
    }
    (ROOT / 'final-data.json').write_text(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    (ROOT / 'analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
