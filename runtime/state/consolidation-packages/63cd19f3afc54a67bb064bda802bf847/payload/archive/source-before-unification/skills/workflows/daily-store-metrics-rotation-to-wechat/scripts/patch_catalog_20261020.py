#!/usr/bin/env python3
"""把 2026-10-20 20:30 的单店实测结构写回指标字典（幂等）"""
import json, pathlib

p = pathlib.Path(__file__).resolve().parent.parent / 'docs' / 'metrics_catalog.json'
d = json.loads(p.read_text(encoding='utf-8'))

rules = d['global_rules']
# 1) 替换"6 个选择器"的旧口径
for i, r in enumerate(rules):
    if '时间选择器单店页共 6 个' in r:
        rules[i] = ('★★★【2026-10-20 20:30 修正】单店顾客分析页真·时间控件只有 **5 个 antd select**：'
                    '顾客分析 / 下单时段 / 下单热门街区 / 顾客画像 / 商圈顾客动态。'
                    '「下单行为」右上那两个字是**静态标签、默认近30日**；「互动行为」右上也是静态标签、**平台固定近7日、不可切换** '
                    '⇒ 该模块只能如实交付 7 日口径，禁止冒充 30 日。切完必须**按元素（data-wb 标记）回读**，'
                    '不能按同 docY 邻近回读——「下单行为(静态30)」与「下单时段(真控件7)」在同一行，按坐标会读错。')

# 2) 追加作用域铁律（插到最前，最高优先级）
scope_rule = ('★★★【2026-10-20 20:30 实测·最高优先级】`#app.shop.customerStats` 的 iframe 有两个作用域：'
              '`/single/business-analysis`（单店，6 张卡，有下单热门街区）与 `/chain/business-analysis`'
              '（连锁汇总，4 张卡，下单顾客 95,035、门店榜单 1984 行、无热门街区）。'
              '只改 hash 的导航浏览器不重载，iframe 会沿用旧作用域 ⇒ **切店/切路由后必须 Page.reload 硬刷新**；'
              '出图前必须校验 iframe location 含 `/single/`，否则拒绝出图（exit 9）。'
              'contextId 必须按 Page.getFrameTree 的 frameId 绑定（同源有多个 about:blank 上下文，按 origin 取会拿空壳）。')
if not any('作用域' in r and '/single/business-analysis' in r for r in rules):
    rules.insert(1, scope_rule)

# 3) M02-M06 补模块锚点
anchors = {
    'M02': {'card': 'customer_analysis', 'start': None, 'end': None, 'col': 'full'},
    'M03': {'card': 'customer_distribution', 'start': '下单行为', 'end': '下单热门街区', 'col': 'left'},
    'M04': {'card': 'customer_distribution', 'start': '下单时段', 'end': '下单热门街区', 'col': 'right'},
    'M05': {'card': 'customer_distribution', 'start': '下单热门街区', 'end': None, 'col': 'full'},
    'M06': {'card': 'customer_feature', 'start': None, 'end': '商圈顾客动态', 'col': 'full'},
}
for m in d['metrics']:
    if m['id'] in anchors:
        a = anchors[m['id']]
        m['module_anchor'] = {
            'scope': 'single-only（/single/business-analysis）',
            'card_class': a['card'],
            'start_title': a['start'],
            'end_title': a['end'],
            'column': a['col'],
            'pad_top': 8 if a['start'] is None else 20,
            'capture_mode': 'module-region（按卡片/标题文档坐标裁剪，禁止整页截图）',
        }
        m['time_control'] = {
            'M02': 'antd select（select_date）→ 切 近30日',
            'M03': '静态标签，默认近30日，不可切',
            'M04': 'antd select → 切 近30日',
            'M05': 'antd select（filter）→ 切 近30日',
            'M06': '互动行为=静态固定近7日（不可切）；顾客画像=antd select（time_select）→ 切 近30日',
        }[m['id']]

d['verification_20261020_2030'] = {
    'purpose': '大同要求「切换一个店铺试试」——验证换店后整条采集链路仍成立',
    'shop': {'shopId': '694471', 'name': '李当家汉派猪蹄饭(一清路店)', 'from_scope': '爱鱼爱虾（小连锁）连锁根'},
    'steps': [
        'switch_shop.mjs --shop-id 694471 --expect-name … → exit 0，iframe 作用域 /single/business-analysis',
        'set_all_30.mjs → exit 0，5 个 antd 控件全部近30日；statics=[互动行为 近7日]',
        'capture_metric.mjs --metric M02..M06 → 5/5 exit 0，truncated=false',
    ],
    'artifacts': '.runtime/captures/M0*_shop694471_*.png',
    'visual_check': 'M02 下单顾客248 / M03 1单81.9%203人 / M04 午餐60.1% / M05 东和颐园32 / M06 评分4.7·会员13.0%，数据属该店、口径近30日',
    'open': 'M01 顾客评价在 comments 路由，本轮未跑',
}

p.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding='utf-8')
print('ok metrics=', len(d['metrics']), 'rules=', len(rules))
