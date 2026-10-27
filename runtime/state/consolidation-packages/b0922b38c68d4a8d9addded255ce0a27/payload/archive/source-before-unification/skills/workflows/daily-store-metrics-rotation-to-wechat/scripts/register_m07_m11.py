#!/usr/bin/env python3
"""登记 M07–M11（数据中心 > 经营分析，规则 7–11，大同 2026-10-20 20:40 发）"""
import json, pathlib

p = pathlib.Path(__file__).resolve().parent.parent / 'docs' / 'metrics_catalog.json'
d = json.loads(p.read_text(encoding='utf-8'))

OUTER = 'https://melody.shop.ele.me/app/shop/<shopId>/stats__center#app.shop.stats.center'
INNER = 'melody-stats-next.ele.me/new/#/single/business-analysis?otherParams=&subTab=&tab=<TAB>&'

new = [
    {
        'id': 'M07',
        'name': '历史数据概览',
        'menu_path': '数据中心 > 经营分析 > 总览',
        'tab': '总览（tab=overview）',
        'route': OUTER,
        'route_note': '权威源 getMenuTree: sref=app.shop.stats.center / short=stats__center；iframe 与顾客分析共用 melody-stats-next，靠 hash 里的 tab 区分',
        'form': '一页多模块（总览 tab 内）',
        'shot': '模块截图（历史数据概览整块）',
        'time_range': '**近30日**（该模块自带 昨日|近7日|近30日|自定义 单选，默认「昨日 10-19 周一」）',
        'sub_indicators': [
            '时间单选：昨日 / 近7日 / 近30日 / 自定义',
            '已选时间标签（如「已选时间：10-19 周一」）',
            '对比基准：比上周一（另一处是「比上周二同时段」，属今日实时区）',
            '订单分析：收入 / 营业额 / 支出 / 有效订单 / 单均实付 / 活动补贴',
            '流量分析：曝光人数 / 进店转化率 / 下单转化率',
            '顾客分析：下单老客 等',
        ],
        'key_numbers': ['营业额', '有效订单', '单均实付'],
        'capture_notes': [
            '★该模块在「总览」tab；页面还有「今日实时数据」区（比上周二同时段），那是实时口径，不属本指标，不要一起截。',
            '★时间单选必须切到 **近30日** 并回读「已选时间：…(30日)」文本，不能只看点中态。',
        ],
    },
    {
        'id': 'M08',
        'name': '流量转化',
        'menu_path': '数据中心 > 经营分析 > 流量',
        'tab': '流量（tab=flowmeter）',
        'route': OUTER,
        'route_note': 'tab 值实测为 flowmeter（不是 flow）',
        'form': '一页多模块（流量 tab 内）',
        'shot': '模块截图（流量转化整块）',
        'time_range': '**近30日**（顶部 今日实时|昨日|近7日|近30日|自定义 + 按周|按月）',
        'sub_indicators': [
            '曝光人数 / 进店人数 / 下单人数 / 进店转化率 / 下单转化率',
            '漏斗（曝光→进店→下单）',
            '店内流量分布（页内 y≈1681，另属一模块）',
        ],
        'key_numbers': ['曝光人数', '进店转化率', '下单转化率'],
        'capture_notes': [
            '★★tab 开关在 iframe 内（不是 .ant-tabs-tab），坐标点法：x≈310,y≈87（1440 宽下），点完读 hash 里 tab= 是否变 flowmeter 才算成功。',
            '★页面另有「资源位」「平台渠道」两个筛选下拉，属分布维度，不要当时间控件切。',
        ],
    },
    {
        'id': 'M09',
        'name': '自然流量来源',
        'menu_path': '数据中心 > 经营分析 > 流量',
        'tab': '流量（tab=flowmeter）',
        'route': OUTER,
        'route_note': '同 M08 同 tab，属该 tab 下部模块',
        'form': '一页多模块（流量 tab 内的来源拆分模块）',
        'shot': '模块截图（自然流量来源整块）',
        'time_range': '**近30日**（同 M08 的顶部单选，切一次两边共享）',
        'sub_indicators': ['自然流量来源构成（各来源名称 + 人数/占比）'],
        'key_numbers': ['自然流量来源 Top1'],
        'capture_notes': [
            '★★与 M08 同一 tab、同一时间控件：切一次 30 日，两块都生效；但**截图要分两张**（不同日期发不同张）。',
            '★待补：该模块精确标题在页面实测中未落在我的标题过滤器内（含数字/长文本），需在下一轮用「自然流量」关键字定位并固化锚点。',
        ],
    },
    {
        'id': 'M10',
        'name': '销售情况',
        'menu_path': '数据中心 > 经营分析 > 商品',
        'tab': '商品（tab=goods）',
        'route': OUTER,
        'route_note': 'tab 值实测为 goods',
        'form': '一页多模块（商品 tab 内）',
        'shot': '模块截图（销售情况整块）',
        'time_range': '**近30日**（今日实时|昨日|近7日|近30日|自定义）',
        'sub_indicators': ['销售额（卡）', '销量（卡）', '商品明细/排行（随 tab 展开）'],
        'key_numbers': ['销售额', '销量'],
        'capture_notes': [
            '★商品 tab 页高仅 1409（一屏），模块少；切 30 日后等数字刷新再截。',
            '★tab 坐标 x≈490,y≈87（1440 宽）。',
        ],
    },
    {
        'id': 'M11',
        'name': '服务数据（数据概览 + 营业分析 + 出餐时效）',
        'menu_path': '数据中心 > 经营分析 > 服务',
        'tab': '服务（tab=service）',
        'route': OUTER,
        'route_note': 'tab 值实测为 service',
        'form': '一页多模块（服务 tab 内，**三个独立时间口径**）',
        'shot': '模块截图 ×3（数据概览 / 营业分析 / 出餐时效）',
        'time_range': '★例外：**数据概览选「本周」**（大同规则 11 明确指定）；**营业分析、出餐时效 各选「近30日」**',
        'sub_indicators': [
            '数据概览：订单服务 / 服务异常率 / 出餐上报率',
            '营业分析：日均营业时长 / 日均高峰营业时长',
            '出餐时效：平均出餐时长 / 出餐超时预定单 / 出餐超时即时单 / 出餐超时率',
            '（同 tab 另有 纠纷单分析 / 出餐上报 / 接单分析 / 取消单，本指标不截）',
        ],
        'key_numbers': ['服务异常率', '日均营业时长', '平均出餐时长'],
        'capture_notes': [
            '★★★这是全套 20 项里**唯一**与「全部近30日」冲突的指标：数据概览必须「本周」。不要盲目全切 30 日。',
            '★★三个模块各有独立时间控件（本周|近7日|近30日|自定义），必须分别设置并分别回读。',
            '★tab 坐标 x≈550,y≈87（1440 宽）。',
        ],
    },
]

ids = {m['id'] for m in d['metrics']}
for m in new:
    if m['id'] in ids:
        d['metrics'] = [x if x['id'] != m['id'] else m for x in d['metrics']]
    else:
        d['metrics'].append(m)
d['metrics'].sort(key=lambda x: x['id'])
d['total_metrics'] = 20
d['recorded_at'] = '2026-10-20T20:45:00+08:00'

rules = d['global_rules']
add = [
    '★★【2026-10-20 20:45 规则7–11】数据中心 › 经营分析是**另一个页面**：外层 `#app.shop.stats.center`（路由 short=`stats__center`），'
    'iframe 仍是 melody-stats-next，但 hash 是 `#/single/business-analysis?...&tab=<TAB>`；tab 实测值：overview/flowmeter/goods/service。'
    'tab 栏在 **iframe 内**（不是 .ant-tabs-tab），只能按坐标点（1440 宽：总览46 流量310 商品490 服务550，y≈87），点完必须回读 hash 里 tab= 已变。',
    '★★【服务 tab 例外】规则 11 要求：数据概览选「本周」，营业分析/出餐时效各选「近30日」⇒ 采集器必须支持**分模块设定时间**，'
    '不能沿用「整页一律 30 日」的粗暴逻辑。',
]
for a in add:
    if not any(a[:24] in r for r in rules):
        rules.append(a)

p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
print('ok total=', len(d['metrics']), [m['id'] for m in d['metrics']])
