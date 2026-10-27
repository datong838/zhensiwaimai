# 2026-10-21 真机采集验收（禁止发送）

使用Rules：本流SKILL.md、REQUIREMENTS.md最新口径、IMPLEMENTATION.md、项目岗位互斥与测试隔离规则。只用9230既有独立品牌商浏览器；不登录、不碰其他岗位；一店11指标；不调用发送器、不写反馈成功。

样本：694471 李当家汉派猪蹄饭(一清路店)。正式池863家，本次仅1家，不代表全量验收。正式入口capture模式，故障修复后按未完成项续跑，不是一次无故障成功。

11项均已取得对应区域并核图；M01旧遮挡图拒收，M10旧今日实时图拒收，保留全部失败收据。截图链路完成不等于业务数据完整：本轮多处暂无/--/零值未独立核实，不能启用正式投递。

| 项目 | 最终采集耗时 | 含失败尝试累计 | 观察及踩坑 | 证据 |
|---|---:|---:|---|---|
| M01 | 32.13秒 | 64.31秒 | 评分4.4；质量4.5；服务4.4；6行明细。首图被手机号提醒遮挡，已拒收并重采。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-d44c8729bfc8/694471/M01/M01_shop694471_20261020180057.png) |
| M02 | 56.65秒 | 62.88秒 | 概览5卡为--/暂无；下单顾客趋势有折线。仅部分数据可用，未确认缺失原因。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-56f8c14db489/694471/M02/M02_shop694471_20261020175146.png) |
| M03 | 56.06秒 | 59.16秒 | 近30日下单频次表明确显示暂无数据。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-56f8c14db489/694471/M03/M03_shop694471_20261020175243.png) |
| M04 | 56.26秒 | 59.37秒 | 近30日下单时段明确显示暂无数据。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-56f8c14db489/694471/M04/M04_shop694471_20261020175339.png) |
| M05 | 56.10秒 | 59.17秒 | 近30日热门街区TOP10暂无数据；地图正常显示。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-56f8c14db489/694471/M05/M05_shop694471_20261020175435.png) |
| M06 | 56.05秒 | 59.13秒 | 互动行为近7日有值（评分4.7/评价6/未评价77/差评1）；画像近30日暂无数据。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-56f8c14db489/694471/M06/M06_shop694471_20261020175531.png) |
| M07 | 35.78秒 | 38.86秒 | 近30日历史概览多项--，不可当作0或完整数据。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-56f8c14db489/694471/M07/M07_shop694471_20261020175605.png) |
| M08 | 36.44秒 | 39.52秒 | 近30日漏斗本店和同行均显示0，未独立验证是否为真实零值。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-56f8c14db489/694471/M08/M08_shop694471_20261020175642.png) |
| M09 | 36.44秒 | 39.53秒 | 自然流量来源明确显示暂无数据。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-56f8c14db489/694471/M09/M09_shop694471_20261020175718.png) |
| M10 | 36.47秒 | 107.10秒 | 近30日商品明细暂无数据；原时间坐标范围漏掉下移控件，已改唯一语义组定位并重采。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-7b03b4535407/694471/M10/M10_shop694471_20261020180547.png) |
| M11 | 39.74秒 | 42.82秒 | 三图无损合成；概览本周服务异常率9.1%、出餐上报100%；营业/出餐近30日多项--。日期输入框由页面自身横向压缩，但已激活近30日。 | [图片](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/state/runs/2026-10-21-56f8c14db489/694471/M11/combined.png) |

耗时为正式执行器各run测得的处理时间；累计保留失败/废弃图耗时，不含人工核图、排障、编码等待。完整流程run总处理时间：631.95秒。

## 固化进代码的修复

- capture缺群仍可采集；execute缺群继续阻断，不填假群。
- 切店前精确处理可选手机号提醒，未知/安全弹窗阻断。
- 所有Page.captureScreenshot前统一复核提醒，提醒不消失或未知弹窗不得截图；三条正负测试。
- M10使用唯一完整选项时间组定位，保留近30日激活态回读；不再依赖150–240坐标带。
- 子进程错误保留白名单FAIL代码和M10时间/区域诊断。

变更位于本工作流scripts/rotation_workflow.py、metrics_rotation_daily.py、switch_shop.mjs、capture_for_metric.mjs、capture_biz.mjs、lib/cdp.mjs、lib/known_overlay.mjs、lib/time_controls.mjs及对应tests；不改已封印岗位和共享发送器。

## 验证与边界

- 正式台账sha256前后相同：`d6b4f0641ad3f382d889e100ad6ed511aae408a4aa7dbe227d10ef8cb3f6dfdb`。独立runtime发送events/checkpoints均0；各正式run externalEffectRequested=false。
- Python32项通过（1.25秒），Node18项通过（0.056秒）。
- 旧scripts/test_ledger_ops.py用pytest收集时触发顶层sys.exit，5项过时断言失败（486家/旧20槽假设）；只操作临时副本，未修改正式台账。未隐去该失败。
- 任务仍pending/disabled；没有启用调度、没有发微信、没有写反馈成功。
- 本轮不能证明空值的业务原因；采集器尚未将这些空数据现状统一转成带证据的no-data合同，正式投递前必须完善，不把captured当可发送数据。
- 本轮各次基线不同，收据保存各run executorBaselineHash；不是最终版本一次性全11项验收，更不是封印。
- capture收据summary.remaining目前按待投递数量计算，因此capture完成时仍非0；本验收不据此声称已投递。
- 最终登录/chain复位证据见同目录final-probe.json；探针与岗位锁释放验证追加在机器证据中。

机器证据：[/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/real-acceptance.json](/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/metrics-rotation-development/live-20261021/real-acceptance.json)。
