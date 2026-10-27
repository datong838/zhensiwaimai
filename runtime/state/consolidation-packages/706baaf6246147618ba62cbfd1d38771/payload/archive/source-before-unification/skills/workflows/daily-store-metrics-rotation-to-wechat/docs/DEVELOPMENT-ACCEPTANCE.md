# M01–M11工作流开发验收（2026-10-21）

状态：开发与离线验收通过，正式任务已登记；未启用、未实采、未真实投递。

## 逐项实现与测试

| 指标 | 内容 | 已接入执行路径 | 时间/截图合同 |
|---|---|---|---|
| M01 | 顾客评价（综合评分） | capture_m01.mjs → 统一收据 → 验图 → 投递/台账 | 平台评分快照；排除评价正文 |
| M02 | 顾客分析（顾客概览 + 下单顾客趋势） | capture_metric.mjs → 统一收据 → 验图 → 投递/台账 | 近30日 |
| M03 | 顾客分布 · 下单行为（下单频次） | capture_metric.mjs → 统一收据 → 验图 → 投递/台账 | 固定近30日（静态标签核验） |
| M04 | 顾客分布 · 下单时段 | capture_metric.mjs → 统一收据 → 验图 → 投递/台账 | 近30日 |
| M05 | 下单热门街区（热门地标 TOP10） | capture_metric.mjs → 统一收据 → 验图 → 投递/台账 | 近30日 |
| M06 | 顾客特征（互动行为 + 顾客画像） | capture_metric.mjs → 统一收据 → 验图 → 投递/台账 | 互动行为固定近7日＋画像近30日 |
| M07 | 历史数据概览 | capture_biz.mjs → 统一收据 → 验图 → 投递/台账 | 近30日 |
| M08 | 流量转化 | capture_biz.mjs → 统一收据 → 验图 → 投递/台账 | 近30日 |
| M09 | 自然流量来源 | capture_biz.mjs → 统一收据 → 验图 → 投递/台账 | 近30日 |
| M10 | 销售情况 | capture_biz.mjs → 统一收据 → 验图 → 投递/台账 | 近30日 |
| M11 | 服务数据（数据概览 + 营业分析 + 出餐时效） | capture_biz.mjs → 统一收据 → 验图 → 投递/台账 | 概览本周＋营业/出餐近30日；三图无损纵向合成 |

## 验收复盘（本轮命令实测耗时，不含全部开发时间）

| 检查 | 耗时 | 结果 / 踩坑点 |
|---|---:|---|
| python-regression | 1274ms | 31项通过；修复月/日幂等冲突、attempted重发、unknown误记已完成、送达后账本失败；测试解释器原先缺pytest，改用项目现有WorkBuddy解释器 |
| eleven-capture-contracts | 162ms | 14项通过；11项固定路由与截图合同；M06静态7日不可伪称30日，M11概览不可一律改30日 |
| flow-order | 32ms | 通过；新任务不改变既有先申诉后汇报顺序 |
| registration-idempotence | 22ms | 通过；再次登记changed=[]，未重启daemon |
| skill-structure | 26ms | 通过；入口及引用路径齐备 |

## 已验证的恢复与隔离

- 模拟2店×11指标=22任务单元，完整跑通截图验证、M11三图合成、假适配器送达、临时台账；同月重跑零重复投递。模拟结果仅用于开发测试。
- 发送异常按unknown，历史attempted不重发；只有同sha/同群的verified事件可对账崩溃检查点。送达后台账失败进入ledger_pending，重跑只修账。
- 月内跨日复用旧daily marker，防重范围升级到店/指标/月。明确未发送blocked可重试，带sendAttempts的blocked保守unknown。
- plan为纯本地；当前正式台账863家，11项共9493单元，因群映射为空全部blocked。此数字是计划数量，不是完成数量。
- 三份正式Excel（实盘、模板、群映射接收表）在测试前后sha256一致；既有skills及台账行逐项不变。
- 注册在runtime/skills_manifest.json、runtime/posts.json、ledger_template row28；enabled=false、dev_state=pending；没有reload daemon。
- 每项收据包含steps.elapsedMs/pitfalls；timeout与不完整批次不能被exit0误当SUCCESS。

## 尚未做，不能声称完成

- 本轮没有操作真实浏览器、没有真实发送。现有采集器历史实测证据不能替代本轮代码改动后的真实验收。
- 当前缺群映射、start_date和放量排期确认；400×3仍是提案，本版支持显式多指标输入，但不会擅自改变生产排期。
- 同店多指标当前逐指标复用既有采集入口，尚未实现“一次切店采完同页五项”的性能优化，不声称达到400×3/4.6小时。
- 现有采集器对真正空数据页未统一产no-data证明：无明确证明按采集失败保留，不把截图小或超时解释成0条。上层已具备no-data不投递与记录合同。
- 真实1店核图、10店灰度、未知结果只读对账和共享发送岗权限验证完成后，才可启用。

机器证据：`work/metrics-rotation-development/acceptance.json`；逐项日志同目录。实现方案：`docs/IMPLEMENTATION.md`。


## 2026-10-21 后续真机实操

上述“没有操作真实浏览器”为开发离线阶段历史边界，现已完成1家×11项只采集演练及核图；发生故障后修复续跑，非一次全绿。页面多项无数据/空值，数据完整性和真实投递仍未验收，任务继续pending/disabled。详见[真机复盘](REAL-CAPTURE-ACCEPTANCE-20261021.md)。
