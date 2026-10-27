# 方案：回读锚点被判 unknown —— 驱动换行压平导致（D15）

- 日期：2026-09-30
- 范围：`skills/wechat-messaging/scripts/windows_adapter.py` 的**只读回读校验**路径
- 授权：`user-20260930-windows-adapter-readback-anchor-flatten-resync`

## 1. 现象

`#9 品牌差评申诉跟进`（`brand-negative-review-appeal-followup`）本次真实投递：

- 第 1 条（李老哈·东北农家小院(海上海店) / 美团）**实际已发成功**（只读 `read_messages()` 在当前会话 `李老哈（品牌）💰臻肆外卖运营对接群 (37)` 末条读到该通知全文）；
- 但 `send_one` 回读判定失败：`windows-readback-anchor-not-trailing`；
- 随后只读对账也失败：`reconcile-anchor-missing`；
- 结果被投影为 1 条「核验未知 / unresolved」+ 3 条「未发送」——**fail-closed 正确**（没有误重发），但业务日无法收口。

## 2. 根因（已取证）

`windows_adapter._verify_sent` / `reconcile` 用 `item['text']`（业务正文，**含 `\n`**）当锚点：

```python
hits = [i for i, m in enumerate(messages)
        if anchor in json.dumps(m, ensure_ascii=False, default=str)]
```

而驱动 `read_messages` 返回的条目是**把换行压平后的单行字符串**。实测同一条通知：

- 业务锚点（多行）：
  `--- 2026-09-29 差评申诉进度通知 ---\n李老哈·东北农家小院(海上海店)\n【美团】\n评价时间: 2026-09-29\n...`
- 驱动回读（单行）：
  `--- 2026-09-29 差评申诉进度通知 ---李老哈·东北农家小院(海上海店)【美团】评价时间: 2026-09-29评价等级: 2星...`

两处叠加使匹配必然失败：

1. 驱动把 `\n` 整体删除（不是替换成空格），所以真实换行在回读侧不存在；
2. `json.dumps(message)` 会把消息里**残留**的换行转义成两字符序列 `\n`（反斜杠 + n），所以即便回读侧有换行，含真实换行的锚点也不可能等于转义后的形式。

⇒ 任何**多行**载荷的回读校验都不可能通过。此路径此前从未跑到（`#9` 历史全部止步于 `wechat-search-region-contended`），所以缺陷一直被掩盖。

## 3. 修法（最小、只动校验，不动发送）

在 `windows_adapter.py` 增加一个纯函数并在锚点比较前对**双方**做同样的压平：

```python
_FLATTEN_RE = _re.compile(r'[\r\n]+|\\[rn]')

def _flatten(value):
    """压平换行：真实 \r\n 与 json.dumps 产生的转义 \n/\r 一并去掉。"""
    return _FLATTEN_RE.sub('', str(value))
```

`_anchor_newness()` 改为：

```python
needle = _flatten(anchor)
hits = [i for i, m in enumerate(messages)
        if needle in _flatten(json.dumps(m, ensure_ascii=False, default=str))]
```

保留原有的**新鲜性**规则不变（锚点最后一次出现之后只允许时间戳条目），因此判定强度不降：
仍然是「精确全文锚点 + 尾部位置」双重条件，只是把**换行差异**归一化掉。

## 4. 不动的部分（边界）

- **不改发送路径**：`_driver_search_key`（本日已封印）、`send_one` 的调用次序、重试预算、`_transport` 注入，全部保持。
- **不改判定强度**：不引入模糊匹配、不缩短锚点、不把「未找到」当通过；找不到锚点仍返回 `unknown`。
- **不改安全门**：`dependencies.json` 只做受控再封印（有回执、有回读、失败即回滚）。

## 5. 放行条件（全部满足才认为修复成立）

1. `dependency_maintenance.py inspect` 为 `clean`；
2. 统一微信完整离线测试**全绿**（基准 197 项）+ `executor.py capabilities` 通过；
3. 新增/失败用例证明：多行锚点可命中被压平的回读条目；**错锚点仍不命中**；**锚点非尾部仍不通过**；
4. 重绑受影响的下游外层摘要（`daily-top10-to-wechat-group` / `daily-negative-reviews`）；
5. 真实复跑只做**只读对账**（`reconcile`）——若能把那条已确认送达的条目从 `unresolved` 收敛为 `verified`，即证明修复有效；**禁止重发该条**（发送状态已确认送达，重发即为重复投递）。

## 6. 方案先行声明

本节在任何代码改动前记录根因、证据、修复范围与停止条件。预计只沉淀「回读锚点换行归一化」，不预设需要改动发送执行器业务逻辑；若测试暴露其它根因，另按对应方案处理。
