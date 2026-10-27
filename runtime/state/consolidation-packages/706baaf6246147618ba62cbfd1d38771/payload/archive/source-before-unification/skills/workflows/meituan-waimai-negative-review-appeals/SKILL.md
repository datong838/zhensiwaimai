---
name: meituan-waimai-negative-review-appeals
description: 金鲨岗位美团外卖差评申诉，固定13:00/15:00/17:00执行，18:30查漏后汇总Excel与台账图。复用原确认、权威回读和unknown防重，不用于负反馈列表、其他平台或任意群发送。
---

# 美团外卖差评申诉（金鲨岗位）

## 2026-10-24生效规则（覆盖下文历史排班）

每日13:00、15:00、17:00、18:30四档。前三档仅执行申诉，18:30查漏后汇总Excel及台账图发运营群。原`-11`条目承载四档，`-1425`合并停用，原脚本和账本保留。车间主任调用`runtime/appeal_shift.mjs --platform meituan --execute`；入口拒绝上午及19点后执行。上午已发保留，不创建新事件重发。

先完整阅读[历史方案与固定投递登记](references/20260923-美团外卖单次差评申诉汇总方案.md)。

## 边界与归属

- 归属**金鲨岗位**（9232，`posts/jinsha-post`）：本工作流只调岗位，不自己连浏览器。入口门禁用 `posts/jinsha-post/scripts/auth.mjs` 的 `assertJinshaEntry`（origin=`https://data.guoshuyufen.com/`，页面 `#/negativeAnalyse`）。
- 页面域是**差评列表** `#/negativeAnalyse`。**负反馈列表** `#/evaluationManagement/feedback` 是另一个 DOM 契约，归在建工作流 `negative-feedback-list-appeals`，两页选择器互不复用。
- 不引用、不修改 taobao 系工作流；代码独立、契约与商家后台同源。

## 申诉契约（每条目状态机）

```
prepared → ready_for_confirmation → submitted_once → 点击确认
  → 权威回读（该条目从列表移除 且 未申诉总数减少）
```

- **权威回读失败 ⇒ 标 `unknown` 并停止整个批次（防重）**，绝不重发。
- 回退申诉内容兜底：`骑手送餐慢`。

## 排班与交付

- 每日四档：**13:00 / 15:00 / 17:00 / 18:30**；原`-11`主条目承载四档，`-1425`合并停用。前三档执行，18:30查漏后汇总交付。
- 申诉明细写当日临时记录：`records/meituan-waimai-negative-review-appeals/<业务日期>/`。
- 全批完成后汇总 `美团外卖差评申诉汇总-YYYY-MM-DD.xlsx`（含 `verified_submitted` / `blocked` / `unknown` 终态），经固定投递器发群 `上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰`（**运营群**；员工群“FEIBING NEO AI数字员工”不再接收本流结果表，大同 2026-10-22 指定）（workflow-id `meituan-waimai-appeals`，单附件、业务日期=上海时区昨日、独立事件账本，见 references 登记节）。
- 发送复用 `workflow_bridge.py` 桌面通道；**0 条/空表不外发**。
- **每日必发（大同 2026-10-22 指令）**：汇总表与台账截图每天固定发运营群，判据是「汇总表实际数据行数 > 0」，**不是**「当日是否有新发起申诉」。原判据看 `records/<业务日期>/*.md` 是否存在，业务日期当天没有新申诉时目录为空 ⇒ 整批被跳过（10-22 实测：汇总表 61 条却被 `no-candidate-records` 挡下，运营群当天没收到表）。现由 `deliver_batch.mjs` 读回 xlsx（第 8 行起 A 列非空行数）判定，0 行仍一律 exit 1 拒发。
- Excel 返回 `verified` 后**必须再补发一张「汇总台账」截图**到同一运营群：`runtime/appeals_summary_card.py --flow meituan ...` 渲染 PNG，再经 `--workflow-id meituan-waimai-appeals-summary`（kind=image，独立 marker `meituan-waimai-appeals-summary-<业务日>.json`）投递。两段投递互相独立：Excel 已 verified 而截图为空时只补图，绝不重发 Excel。截图数字只取 records 事实源与汇总表平台统计行。

## 安全纪律

- 「发起申诉」与「发送微信群」均为外部写操作：人工/agent 直接调起本技能时，每次实际执行前须有对当次范围的明确授权；排班自动执行按既定排班授权范围。
- 只复用已登录的浏览器与微信，不索取、复制或重新登录凭据。
- 页面、回读或发送结果不明时保留阻断与证据，不把未知写成已申诉或已发送。
