#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出站闸门（egress policy）：禁止**测试载荷**进入线上业务群。

2026-09-30 事故动机（代码级定性，不再是推测）：
⑨ 品牌申诉工作流的**测试套件**每次运行都真往线上群
`李老哈（品牌）💰臻肆外卖运营对接群` 发 2 张夹具图
（`aaaa…(64a).png` = `render_png("正文甲")`、`bbbb…(64b).png` = `render_png("正文乙")`）。
三要素：① 夹具用真品牌名、而目标群是**模块常量**（测试只隔离了路径）；
② 测试把桩打在已废弃的 `heartbeat_recovery.run` 上，而 `run()` 真正的传输点是
`_windows_run` ⇒ 桩失效、走真通道真发；③ 通道层**没有任何出站守卫**。
技能层的三道锁已在 `tests/test_delivery_executor.py` 落地（隔离群身份 / 改桩到真缝 /
出站硬闸门）；本模块补的是**通道层**的最后一道，覆盖技能层之外的路径
（其它技能的测试、项目另一副本、直连驱动的脚本）。

为什么必须有一条**结构性**规则而不能只比文案：
image 条目的正文（`正文甲`）是**画在 PNG 里**的，闸门看不到；能看到的只有
`itemId` / `name` / `path`。所以「夹具内容是 正文甲」这件事，只有靠
**文件名/键形态**（`aaaa…`、`bbbb…` 这种单字符重复）才拦得住。

设计纪律：
- **纯函数、无 IO**（唯一的外部读取是环境变量），因此可被完整单测覆盖；
- **fail-closed**：测试群集合为空（默认）时，测试载荷**一律拒发**；
- **不降低业务判定强度**：生产载荷（当日授权群 + 真实业务载荷）行为**逐字不变**；
- **拒绝不静默**：返回明确 `reason`，由调用方写入 `egress-denied` 事件后硬失败，
  绝不"改投到测试群"、绝不降级成"发到上一个会话"。
"""
from __future__ import annotations

import os
import re

TEST_GROUP_ENV = 'WECHAT_TEST_GROUPS'

#: **大同铁律（2026-09-30）**：测试数据与测试脚本**永远只能发测试群**，
#: 不允许发任何线上业务群。本模块即该铁律的代码化 enforcement。
#: 注意：测试群集合**默认为空**（当前驱动通道无安全测试组，见 D17），
#: 故默认行为是「测试载荷一律拒发」——这正是铁律的最严实现。

#: 明确标记测试/夹具身份的保留字。命中即视为测试载荷。
SENTINEL = ('__TEST__', 'TEST-IMG', '正文甲', '正文乙', 'lorem ipsum', 'hello world')

#: **任意位置**出现同一字符连排 ≥20 次（`aaaa…`、`appeal-aaaa…`）。
#: 只对**标识符**（`itemId` / `name`）生效——它们是机器生成的（sha256 十六进制、
#: 日期文件名、键），现实中不会出现 20 连排同字符；而**自由正文不适用**，
#: 因为正常文案里可能出现长破折号分隔线（`----------`），会误伤。
_DEGENERATE_RE = re.compile(r'(.)\1{19,}')

_DEGENERATE_THRESHOLD = 20


def _degenerate(value) -> bool:
    """标识符是否为退化串（出现同一字符连排 ≥20 次）。

    覆盖两种形态：整体重复（`aaaa…`）与带前缀的重复（`appeal-` + 20×a，即夹具
    记录键经 `item_id()` 截断后的真实形态）。
    """
    text = str(value or '').strip()
    if not text:
        return False
    return bool(_DEGENERATE_RE.search(text))


def _sentinel(value) -> bool:
    text = str(value or '')
    if not text:
        return False
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in SENTINEL)


def test_groups() -> frozenset:
    """环境变量声明的测试群集合；默认空 ⇒ 最严（测试载荷无处可去）。

    2026-09-30 事实（D17）：驱动微信号的会话里**没有** `臻肆测试群`，
    `臻肆测试群` 属于**手机侧普通微信**通道。驱动通道当前无安全测试落点，
    故此处保持默认空。
    """
    raw = os.environ.get(TEST_GROUP_ENV) or ''
    return frozenset(part.strip() for part in raw.split(',') if part.strip())


def classify(items) -> str:
    """载荷分类：'degenerate' > 'sentinel' > 'clean'（按严重度取最重者）。

    - 退化串检测只作用于**标识符**（`itemId` / `name`）：自由正文可能出现长破折号
      分隔线（`----------`），对它做连排检测会误伤正常文案。
    - 哨兵字面量对**标识符与正文**都生效。
    """
    verdict = 'clean'
    for item in items or ():
        if not isinstance(item, dict):
            continue
        identifiers = (item.get('itemId'), item.get('name'))
        if any(_degenerate(field) for field in identifiers):
            return 'degenerate'
        if any(_sentinel(field) for field in identifiers + (item.get('text'),)):
            verdict = 'sentinel'
    return verdict


def check(*, group, resolved_group, items, test_groups=frozenset(),
          business_keys=None) -> dict:
    """返回 `{'allow': bool, 'reason': str|None, 'payload': str}`。命中任一规则即拒发。

    规则（按顺序，命中即拒）：
      R1 测试载荷只能进测试群 —— `degenerate`/`sentinel` 且目标群 ∉ 测试群。
      R2 测试群集合为空时，测试载荷**一律拒**（默认即此情形 ⇒ fail-closed）。
      R4 `business_keys` 由调用方提供时（当日业务快照允许的 itemId 集合），
         快照外的条目拒发。默认不提供 ⇒ 该规则不生效（不误伤未接入的业务）。
    """
    target = str(resolved_group or group or '').strip()
    groups = frozenset(str(name).strip() for name in (test_groups or ()))
    payload = classify(items)

    if payload != 'clean' and target not in groups:
        reason = ('egress-degenerate-payload' if payload == 'degenerate'
                  else 'egress-sentinel-payload')
        return {'allow': False, 'reason': reason, 'payload': payload,
                'detail': ('tests cannot be delivered to production groups'
                           if not groups else 'test payloads may only enter test groups')}

    if business_keys is not None:
        allowed = set(business_keys)
        for item in items or ():
            if isinstance(item, dict) and item.get('itemId') not in allowed:
                return {'allow': False, 'reason': 'egress-payload-not-in-business-snapshot',
                        'payload': payload, 'detail': str(item.get('itemId'))[:80]}

    return {'allow': True, 'reason': None, 'payload': payload}


def self_test() -> dict:
    """自证：本次事故的两个真实文件名必须被拒，真实业务载荷必须放行。"""
    incident = [
        {'itemId': 'appeal-' + 'a' * 20, 'type': 'image', 'name': 'a' * 64 + '.png'},
        {'itemId': 'appeal-' + 'b' * 20, 'type': 'image', 'name': 'b' * 64 + '.png'},
    ]
    verdict = check(group='李老哈（品牌）💰臻肆外卖运营对接群',
                    resolved_group='李老哈（品牌）💰臻肆外卖运营对接群',
                    items=incident)
    if verdict['allow']:
        raise AssertionError('egress-gate-failed-to-catch-2026-09-30-incident')
    if verdict['reason'] != 'egress-degenerate-payload':
        raise AssertionError('egress-gate-wrong-reason:' + str(verdict['reason']))

    production = [
        {'itemId': 'appeal-9a4576c4f2a1b6cc0e45', 'type': 'image',
         'name': '9a4576c4f2a1b6cc0e45e0f0a1b2c3d4e5f60718293a4b5c6d7e8f90a1b2c.png'},
        {'itemId': 'top10-2026-09-29', 'type': 'image',
         'name': '2026-09-29_top10seller.png'},
        {'itemId': 'jinsha-2026-09-29', 'type': 'file',
         'name': '2026-09-29美团外卖日报.xlsx'},
    ]
    for item in production:
        single = check(group='李老哈（品牌）💰臻肆外卖运营对接群',
                       resolved_group='李老哈（品牌）💰臻肆外卖运营对接群', items=[item])
        if not single['allow']:
            raise AssertionError('egress-gate-false-positive:' + str(item['name']))

    text_production = [{'itemId': 'appeal-x', 'type': 'text',
                        'text': '--- 通知 ---\n李老哈·东北农家小院(海上海店)\n【美团】\n'
                                '评价时间: 2026-09-29\n评价等级: 2星\n'
                                '申诉结果：---申诉中---\n评价内容: 最难吃的炖白菜'}]
    if not check(group='g', resolved_group='g', items=text_production)['allow']:
        raise AssertionError('egress-gate-false-positive-real-notice')

    return {'ok': True, 'threshold': _DEGENERATE_THRESHOLD,
            'testGroupEnv': TEST_GROUP_ENV, 'runtimeModelDecisions': 0}


if __name__ == '__main__':
    import json
    print(json.dumps(self_test(), ensure_ascii=False))
