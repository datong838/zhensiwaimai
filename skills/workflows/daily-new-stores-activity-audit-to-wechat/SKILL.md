---
name: daily-new-stores-activity-audit-to-wechat
description: 读取当天完整的新店机器收据，仅对淘宝新店逐店核验三项活动，缺项向指定群提醒。
---

# 淘宝新店活动缺项巡检与提醒

## 2026-10-28瞬态恢复与完成判定

明确搜索超时仅在原采集阶段重试一次（独立search-retry-1目录保留证据），不重试发送；持续超时记retry-required并继续独立店，整流不算完成。岗位忙记skipped-busy，不抢锁、不重试、不复位、不算完成；登录/验证码/风险不重试或复位。普通skipped完成仅限明确暂停营业/已下线，其他未知前缀不冒充成功。明确查无店铺仍按下文用户授权提示真实送达结束；原unknown不重发。完整待恢复名单包含未尝试店。方案见仓内docs/solutions/20261028-活动装修巡检瞬态恢复与完成判定.md。

本 Skill 是 `daily-new-stores-to-wechat` 拆出的**独立工作流**（与 `daily-new-stores-opening-to-wechat` 开业通知流并列，非同一任务）。它读取开业流当天产出的新店机器收据，仅对其中淘宝新店逐店核验三项活动，缺项时向「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」发送提醒。执行前阅读统一 [wechat-messaging](../../wechat-messaging/SKILL.md) 的输入/恢复合同。

## 运行入口

```sh
# 每日 11:00 全量巡检（无当天完整收据时自动先跑一次开业流的 --collect-only 刷新名单）
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python \
  /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-new-stores-activity-audit-to-wechat/scripts/activity_daily.py --execute

# 单店只读采集（不发送）
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python \
  /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-new-stores-activity-audit-to-wechat/scripts/activity_workflow.py --shop-name <完整店名>
# 单店按完整收据发送缺项提醒（加 --execute）
```

## 三项活动阶段

淘宝品牌商 `taobao-brand:9230` 的活动阶段通过 `scripts/activity_daily.py` 读取当天完整的新店机器收据，仅对其中淘宝新店逐店核验；若当天无完整收据，先运行开业流的 `workflow.py --collect-only` 一次，只读刷新新店名单，不发送开业天数通知。`scripts/activity_workflow.py --shop-name <完整店名>` 可单店只读采集，加 `--execute` 才允许按完整收据向「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」发送缺项提醒。

逐项精确核对「减配送费」「新阶梯红包」「店铺满减」；「阶梯爆涨红包」不自动等同于「新阶梯红包」。页面登录、门店身份、清单状态、总数、分页、名称和门店绑定有歧义时阻断。

## 与开业流的关系与数据复用

- 本流**不重新采集**新店名单：直接读开业流 `daily-new-stores-opening-to-wechat/scripts/workflow.py` 产出的当天新店机器收据（跨目录复用其 collection 结果）。`activity_daily.py` 通过把开业流 `scripts/` 加入 `sys.path` 后 `import workflow as new_stores` 读取，并在缺收据时以子进程调用其 `--collect-only`。
- 本流只检查淘宝新店的活动配置，不代替每日 10:00 的开业通知任务。

## 活动提醒去重台账（自包含）

活动提醒「同一事件最多发一次」的 canonical ledger 位于**本技能目录内** `.runtime/activity/events/`（由 `activity_workflow.py` 的 `EVENTS = RUNTIME / "events"` 推导），不再跨仓读 `zhensi_waimai`。同一业务日同一店铺的活动提醒事件已 `verified` 时再次调用返回 `already_verified`、新增发送 0 次。该目录缺失时 `deliver()` 返回 `blocked`（reason: canonical-activity-ledger-unavailable）。

## 完成与停止

- 每日入口只使用同业务日完整的新店收据；无收据、淘宝品牌商未登录或目标歧义时为 `unknown`、零发送。
- 页面登录失效、验证码、账号风险、门店身份或清单状态歧义、总数/分页/名称持续变化、字段缺失：保留阻断，不推断无店、不发送。
- Windows 网关或目标群预检失败：保留当日记录与零发送事实；发送已 `attempted`、`unknown` 或次数不明时，保留原事件并只读对账，绝不改事件、切通道或重复发送。
- 共享微信技能的发送逻辑、策略、依赖摘要及防重账本不能通过修改 Markdown 放行。若需修复，先更新阶段方案，最小改动并通过针对性自测，再由其受控维护入口处理。

## 2026-10-27用户明确的查无店铺完成方式

当日完整新店来源中的淘宝店，在原品牌商主账号返回明确“未搜索到店铺”时，原daily入口发送本流查无店铺提示，包含完整店名及原开业天数；记录固定“店铺在主账号查不到未能检查”。提示经原队列真实verified/already_verified后可作为本任务成功结束；不声称实际检查了活动或装修。搜索超时、岗位忙、登录失败不转换为查无店铺；unknown不重发。原普通缺项逻辑、制动、授权与防重保留。
