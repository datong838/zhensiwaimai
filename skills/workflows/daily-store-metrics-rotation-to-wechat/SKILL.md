---
name: daily-store-metrics-rotation-to-wechat
description: 店铺运营16项指标商户群反馈。将淘宝闪购品牌商9230的M01–M11店铺运营指标截图按已确认店群映射轮转反馈，支持离线计划、只采集演练、月度防重、断点恢复和统一微信投递。用于本项目店铺指标轮转任务，不用于其他平台或未登记指标。
---

# 店铺运营16项指标商户群反馈

执行前读 [实施方案](docs/IMPLEMENTATION.md) 与 [需求](REQUIREMENTS.md) 最新章节。M01–M11定义来源为 `docs/metrics_catalog.json`；原话 `user_rules` 不改写。旧需求中9232名单与20项日历排期已被后续口径替代，本阶段只处理11项，自动轮转从明确配置的start_date连续计算。

只用一个正式入口 `scripts/metrics_rotation_daily.py`，默认plan纯本地、不连接浏览器或微信。采集岗固定9230，复用当前唯一品牌商页；采集后复位chain首页。运行期间持有项目品牌商岗位互斥锁。发送只复用wechat-messaging的WindowsAdapter，不另造驱动。

```sh
# 本地计划：按现有台账核对全部11项；默认不外发
python scripts/metrics_rotation_daily.py --mode plan --metrics M01,M02,M03,M04,M05,M06,M07,M08,M09,M10,M11
# 单店只采集演练：只需岗位与店铺身份可用，不依赖群映射
python scripts/metrics_rotation_daily.py --mode capture --metrics M01 --limit 1
# 显式真实投递：须任务目标和群映射已授权
python scripts/metrics_rotation_daily.py --mode execute --metrics M01 --authorization-ref '实际人类授权引用'
# 制动或恢复（没有闸文件默认放行，但默认运行模式仍是plan）
python scripts/metrics_rotation_daily.py --disarm
python scripts/metrics_rotation_daily.py --arm
```

依赖openpyxl、Pillow；本机开发测试解释器为 `/Users/ddt/.workbuddy/binaries/python/envs/default/bin/python`，带 `env -u PYTHONPATH`。Node由`--node`或ZENSI_NODE指定。

## 运行合同

- 店铺池取品牌商来源的当月台账“店铺池”，只选营业中，快照≤7天；ID唯一、全名不空。群名来自已解析group_map或台账，缺群blocked，不模糊匹配。保留池总数、限定样本数、预期/实发/待补数。
- 采集必须走切换器和原有单店作用域校验，不允许只改URL冒充切店。截图对应当前店名/ID/指标，时间回读通过、有效PNG、未截断、只取本run文件。
- M01只截评价详情评分区域，排除顾客评价正文。M02–M05近30日；M06互动行为平台固定近7日、画像近30日，必须如实标注。M07–M10近30日；M11概览本周，营业与出餐近30日，三张原图顺序无损合成一张。
- 防重键=店ID/指标/月，跨日同样阻断。verified/already_verified跳过采集和发送；attempted/unknown仅对账，不能重发。只有绑定同一图片sha和同一群的verified事件可对账崩溃检查点。
- 确认送达先落verified事实，再写台账；写台账失败标ledger_pending，重跑仅修台账。unknown不填“已完成”进度。blocked只有明确未尝试发送才可重试；sendAttempts>0保守unknown。
- 批次收据含每项每步elapsedMs/pitfalls。外层ok=false、incomplete及非零退出表示未完成；不能把子进程exit0或模拟测试当真实送达。掉登录/安全验证停批，普通单店失败记录后继续独立项。

## 注册与验收

`runtime/register_metrics_rotation_flow.py --apply`在项目manifest、岗位usedBy、待验收台账行三处幂等登记，**保持enabled=false/dev_state=pending**，不重载daemon。任务已具备调度入口；群映射、首发起始日、10店真实灰度及重跑零外发尚须验收，不能自行填假群或改为active。

离线测试加载仓库`tests/isolation_guard`，临时台账与假适配器完全隔离；运行：

```sh
python -m pytest skills/workflows/daily-store-metrics-rotation-to-wechat/tests skills/workflows/daily-store-metrics-rotation-to-wechat/scripts/test_deliver_metric.py -q
node --test skills/workflows/daily-store-metrics-rotation-to-wechat/scripts/capture_receipt.test.mjs
```

本次交付证据见 [开发验收](docs/DEVELOPMENT-ACCEPTANCE.md)。

真机采集复盘见[2026-10-21一店11项](docs/REAL-CAPTURE-ACCEPTANCE-20261021.md)。截图前统一检查已知可选提醒与未知弹窗；M10采用唯一完整时间组定位并回读。captured仅为截图合同通过，页面暂无/空值不代表数据完整或可发送；本轮不构成正式投递验收。


## 2026年10月名单与月登记

当前23家范围、全量来源、挂历与停用约束见 [本月工作登记](docs/MONTHLY-PLAN-2026-10.md)。用户明确三个流先不值班执行，名单确认不自动启用。
