---
name: daily-negative-reviews
description: 通过固定生产执行器，从金鲨9232专用浏览器提取昨日全部平台差评，逐条对账并生成固定Excel，再发送到上海臻肆外卖运营群。用于“执行昨日差评分析”及该每日自动任务；不用于临时日期、其他群、其他浏览器或人工拼接执行。
---

# 昨日差评分析 → 运营微信群

## 2026-10-24生效排班

本流由08:40提前为08:30启动，车间主任按固定时点调起。业务日期、封印、目标群和原事件防重不变；unknown只能对账，群里其他同名文件不能代替本事件验收。

## 唯一入口

本文件只说明流程。日期、端口、页面、平台、群、文件、状态转换、防重、验证、重试、停止和复盘均由代码强制。

```bash
/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/workflow_executor.mjs --execute
```

已有运行需要继续时仍调用 `--execute`；执行器按业务日期复用唯一运行状态。无副作用自检：

```bash
/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/workflow_executor.mjs --self-test
```

若自检在任何业务动作前报告公共微信 `dependencies.json` 摘要漂移，只能使用受控维护入口恢复外层摘要：

```bash
/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/maintenance_executor.mjs prepare-unsealed-acceptance user-20260920-negative-review-dependency-maintenance
```

该入口只在当前封板、公共依赖清单 `clean`、本地依赖未漂移和全量离线回归通过时，原子进入下一业务日的一次性验收态；它不打开浏览器、不生成报表、不写发送账本且 `sendAttempts=0`。验收态只能由下一次 `--execute` 的真实非空完成自动重新封板。详见[外层依赖摘要受控恢复与每日调度方案](references/20260920-外层依赖摘要受控恢复与每日调度方案.md)。

禁止绕过入口直接调用浏览器采集、对账、报表或微信发送脚本。内部脚本要求执行器凭证，调用方不能传日期、群名、端口、输出目录或发送通道。

`runtime-policy.json` 绑定依赖摘要。代码变化后只能进入指定业务日期的一次性 `UNSEALED_ACCEPTANCE`；真实非空运行全部通过后由执行器自动写回 `SEALED`。修改 Markdown、自动任务提示或依赖清单本身不能绕过该门禁。

## 完成条件

只有状态达到 `complete`，且 CLI 返回代码生成的 `completionReview` 才能报告完成。展示 `reviewItems` 中每个节点的耗时、尝试次数、状态和踩坑，以及全局 `pitfalls`；不得根据日志或提示词补写。

实现和维护前读取[代码强制执行器方案](references/20260918-代码强制执行器方案.md)。公共微信发送仍服从 [wechat-messaging](../../wechat-messaging/SKILL.md) 的防重和未知结果规则。
