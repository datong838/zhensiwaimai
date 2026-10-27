---
name: daily-jinsha-reports-to-business-wechat
description: 通过固定生产执行器，从金鲨后台专用浏览器导出昨日美团外卖和淘宝闪购多店数据，生成两份真实业务日报并发送到桌面微信群“上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰”。用于该唯一生产流程；不用于测试群、企业微信共享空间、手机微信、其他浏览器或临时文件。
---

# 金鲨昨日双平台日报 → 桌面微信群

## 权威边界

- 本文只说明流程，不授予运行时继续执行的权限。所有通道、目标、文件、阶段、重试、恢复和完成判定均由 `scripts/business_workflow_policy.mjs` 与 `scripts/business_workflow_executor.mjs` 强制执行。
- 唯一生产入口是 `scripts/business_workflow_executor.mjs`。禁止直接调用分阶段管线、下载器或任一发送器；这些入口均有内部调用凭证检查。
- 金鲨通道固定为 `control-background-dedicated-chrome` 的 `jinsha-business:9232`，禁止切换到日常 Chrome、其他 Profile/端口或桌面金鲨。
- 发送通道固定为桌面微信，唯一完整群名为“上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰”，2026-09-17重新授权后的固定授权为 `zhensi-business-main-wechat-shanghai-zhensi-operations-ding-fandang-daily-v2-reauthorized-20260917`。用户指定的核心文字为“上海臻肆外卖运营-盯个盯-饭敢当”；搜群只使用文字唯一命中，不比较头像。企业微信、手机微信及自动选通道不属于本生产入口。
- 桌面微信登录预检和精确群定位只调用统一 `wechat-messaging/scripts/workflow_preflight.py`；本流程不得复制 stderr、OCR、AX 或搜索分区判断。实际文件发送仍只调用统一 `workflow_bridge.py`。
- 业务日期由生产执行器按运行日自动计算为昨日；成品固定命名为 `美团外卖日报_YYYY-MM-DD.xlsx` 和 `淘宝闪购日报_YYYY-MM-DD.xlsx`。调用方不得传入日期、群名、通道、发送器、文件名或输出目录。
- 独立发送账本，不读取或写入测试群账本。每平台下载一次、每文件发送一次；一旦出现 attempted 或结果未知，只允许只读复核，禁止再次发送。
- 隐藏内部底座 `../.daily-jinsha-reports-core/` 的 18 个封板文件在每次生产执行前由代码校验 SHA-256；任一漂移立即失败关闭。
- 2026-09-07 用户授予的持续执行权，仅适用于上述固定浏览器、固定桌面微信群、当日自动推导的昨日日期和两份已校验日报。任一边界不匹配时，代码拒绝继续。

## 使用方式

执行前完整读取[真实业务群日报执行方案](references/20260907-真实业务群日报执行方案.md)、[动态定位与断点恢复维护方案](references/20260908-动态定位与断点恢复维护方案.md)、[桌面微信优先方案](references/20260910-桌面微信优先方案.md)、[金鲨后台浏览器优先方案](references/20260910-金鲨后台浏览器优先方案.md)、[金鲨方案列表延迟加载稳定性维护方案](references/20260911-金鲨方案列表延迟加载稳定性维护方案.md)、[生产工作流代码强制门禁方案](references/20260911-生产工作流代码强制门禁方案.md)、[visible-handoff 兼容维护方案](references/20260915-visible-handoff兼容维护方案.md)、[运营群切换方案](references/20260917-运营群切换方案.md)，以及隐藏底座的工作流合同与第14轮封板方案。2026-09-17起目标群、授权和账本以运营群切换方案为当前权威；旧方案中的旧群仅保留为历史证据。

金鲨专用浏览器允许两种由代码严格校验的稳态：历史 `headless`，或已完成人工确认、结构认证、窗口释放和任务绑定的 `visible-handoff / WINDOW_RELEASED`。后者仍是同进程交接模式，不得表述为 headless，也不得放宽 Profile、端口、站点、实例、确认和目标绑定门禁。

生产执行只有以下命令：

```bash
/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/business_workflow_executor.mjs --execute
```

中断后只允许由同一执行器恢复既有运行目录：

```bash
/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/business_workflow_executor.mjs --resume <run-dir>
```

无副作用自检：

```bash
/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node scripts/business_workflow_executor.mjs --self-test
```

执行器创建并绑定生产配置、运行目录和状态文件，严格按 `created → downloaded → prepared → sent → verified → complete` 推进。调用方和大模型不能跳过阶段、修改生产参数、选择备用通道或自行决定补发。下载、发送与回读的重试次数、等待时间和可恢复条件均由代码分类；无法证明安全时进入 blocked，不能继续猜测。

只有状态文件达到 `complete`，且下载收据、成品哈希、发送 attempted/confirmed 证据、业务账本和最终只读回读全部通过，才算本轮完成。耗时和踩坑从执行器事件与状态文件汇总，不以模型文字判断代替。

每次成功完成时，执行器CLI必须直接输出代码生成的 `completionReview`，同时写入 `workflow-summary.json`：`codeEnforced=true`、总耗时、逐节点名称/尝试次数/耗时/完成状态/踩坑数组及全局踩坑列表。调用方只能展示该对象，不得由提示词或模型补写虚构节点；缺少该对象不能报告“已完成复盘”。

## 2026-09-16 统一微信技能接入

桌面微信预检、精确查群、文字/图片/文件发送与回读统一由 [wechat-messaging](../../wechat-messaging/SKILL.md) 执行。当前工作流只负责业务来源、日期、对象、既定线上群及原授权，禁止改成臻肆测试群。入口参数、旧发送标记、成功历史和业务状态提交合同保持不变。

桥接代码保留旧marker：旧verified按完整内容绑定复用；旧attempted/unknown只能只读复核；部分成功不算整批完成。仅新桥证明零次发送的blocked可重走查群流程。迁移离线回归不代表本业务新的真实非空验收，已有封板状态不会自动提升。详见[迁移合同](../../wechat-messaging/references/integration.md)。
