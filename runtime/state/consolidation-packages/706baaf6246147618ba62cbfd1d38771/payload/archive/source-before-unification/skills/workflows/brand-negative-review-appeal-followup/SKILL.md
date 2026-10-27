---
name: brand-negative-review-appeal-followup
description: 按品牌表读取金鲨昨日美团外卖和淘宝闪购中差评，生成逐条申诉跟进 CSV；经单独授权后才向每个品牌唯一匹配的微信群逐条发送。用于品牌差评申诉跟进，不用于既有日报、任意群发或临时平台扩展。
---

# 品牌差评申诉跟进

先完整阅读[实施方案](references/20260918-品牌差评申诉跟进技能方案.md)。本 Skill 默认 `dry-run`：只读取金鲨并生成或校验 CSV，严禁搜索微信群、发送消息或把任何行标为“已发送”。

## 输入和采集

- 品牌表固定为 [品牌表.csv](inputs/品牌表.csv)，每行一个品牌、无表头、不得写入店铺名或群名。
- 日期固定按 `Asia/Shanghai` 计算昨日；平台只选“美团外卖”“淘宝闪购”；评分只采集 1–3 星。
- 每个品牌、每个平台都必须回读品牌搜索值、平台选中值和昨日日期范围；每一页都读取，不能用卡片计数或截图代替完整列表。
- 每条 CSV 必须包含记录键、品牌、平台、门店、评价时间、评价等级、申诉结果、评价内容、通知正文、群检索结果、发送状态、备注。通知正文一条评价一条消息，使用方案中的固定格式。
- 通知正文的申诉结果固定为 `申诉结果：---状态---`；状态为“未申诉”“未申诉（已开启自动申诉）”“申诉中”“申诉成功”或“差评免责”。“差评免责”仅在页面明确显示平台已拦截评分／免责、不计入评分时使用。“未申诉（已开启自动申诉）”仅在页面显示未申诉、且卡片明确显示“自动申诉已开启”时使用（2026-10-06 大同指令）；二者同一判定，不得互相替代。

## 发送前的强制门禁

只有用户对当次业务日期、品牌、目标群和逐条正文明确授权，才可从 `dry-run` 切换到发送准备。切换后，先阅读 [统一微信收发 Skill](../../wechat-messaging/SKILL.md)、其[输入与结果合同](../../wechat-messaging/references/contract.md)和[恢复规则](../../wechat-messaging/references/recovery.md)。

- 每个品牌仅以品牌核心词检索一次，并只接受经原生完整标题与群类型核验后的唯一群。
- 候选群数量不是 1 时跳过该品牌；不能凭头像、联系人、聊天记录或网络结果选择群。
- 同一品牌每条消息单独建立稳定事件与 itemId，顺序以 CSV 记录键为准；禁止合并、多发或重发。
- 只有统一执行器返回 `verified` 或 `already_verified` 时，才把对应行的发送状态更新为“已发送”。未知、失败或被阻断均保留原状态和证据，不自动补发。

## 完成与报告

`dry-run` 完成条件是 CSV 列顺序正确、记录键不重复、每条通知正文与字段相符，且所有行的发送状态仍为“未发送”。

发送模式完成条件还包括：每个处理品牌有唯一群核验结果、每项有发送回执、CSV 的“已发送”行逐项可回读。报告必须区分已发送、跳过、阻断和未知；不得把 CSV 生成成功表述为消息已送达。

## 固定发送编排器

每日采集入口 `scripts/daily_executor.mjs` 只读取金鲨并生成 CSV，不发送微信。定时任务先执行：

```sh
/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node \
  /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/brand-negative-review-appeal-followup/scripts/daily_executor.mjs
```

采集成功后，发送和恢复唯一业务入口为：

```sh
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python \
  /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/brand-negative-review-appeal-followup/scripts/delivery_executor.py
```

该编排器只负责回执归并、精确请求策略登记、调用 `wechat-messaging/scripts/heartbeat_recovery.py`、安全续发规划及回执到 CSV 的本地投影。所有微信定位、发送、逐字原文回读仍且只能由统一 `executor.py` 完成。它按稳定记录键/itemId 与执行器底层账本关联，不根据 CSV 行号或截图决定是否发送。

- 发现既有 `attempted`/`unknown` 时，必须先在原请求授权摘要下执行只读 reconcile；机器确认 verified 后才可登记后续新事件。授权/摘要不匹配时先精确回登原请求策略并只读对账，不把新事件策略用于旧事件。
- 续发事件只包含账本证明从未尝试的条目，使用确定性事件身份；相同计划复用冻结请求。任何 unknown、缺失/非零 attempt 证明、partial、摘要冲突均禁止续发。
- 若用户明确逐条确认一条 `unknown`/`partial` 已送达，可通过固定入口提交确切 itemId 与用户证据文件引用；代码必须核验关联事件、群、请求/正文摘要、attempt marker 和 transport `sendAttempts=1`，并私有留存证据哈希与审计记录。此人工状态只排除重发，不伪造机器 `verified`，CSV 仍标“核验未知”；仅底层证明 untouched 的其它条目可续发。证据不符或仍有其它未解决项时阻断。
- 仅 verified/already_verified 投影为“已发送”；attempted/unknown 保持“核验未知”；blocked/未尝试保持“未发送”。投影采用原子替换并回读 CSV，保留正文、记录键与顺序。
- 仅对明确零发送的 `current-group-composer-not-empty` 允许同一会话一次只读复采样；完整群标题、群类型及空框证明缺一仍阻断。不得重复搜索或切群；人工证据只能用于排除已确认送达的 unknown，不可授权新的发送或绕过发送前门禁。
- 子进程退出状态与结构化 JSON 均纳入结果；空输出、无效 JSON、缺少发送次数视为未知/阻断，不能默认为零发送或完成。
- 自动摘要以 `completionReview.codeEnforced=true` 为完成必要条件；执行入口不得将评价正文写入公共复盘日志。
