---
name: daily-store-task-completion-ops-to-wechat
description: 服务商平台取全量「运营效果分析」+「门店分配」两份表，按门店ID关联运营人出明细 Excel，再按运营负责人统计「经营任务完成率」均值发白底彩色图到运营群。
---

# 淘宝闪购 门店经营任务完成率按小组统计

与 `daily-new-stores-not-nourished-ops-to-wechat` **同发一个群**（「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」）、**同占用 9231 服务商岗**，但业务逻辑不同：本流不按「问题类型」筛子集，取的是**全量运营效果**（含全部门店的经营任务完成率），产出「明细 + 小组均值图」两件。

## 业务口径（大同 2026-10-13 需求）

1. 服务商平台 → 代运营 → **运营效果分析** → 直接点「**数据下载**」（**不加任何筛选**，全量；数据量大，导出可能数分钟）。结果含 `门店ID`、`经营任务完成率`。
2. 服务商平台 → **门店分配** → 外卖店 tab → **已分配门店** → 选公司级**根角色** → 点「下载数据」。结果含 `门店ID`、`运营人`。
3. 以「**门店ID**」为键 vlookup，把「**运营人**」并入步骤1 的一份 → `<日期>运营-店铺经营任务完成率明细.xlsx`（**先发这个**）。
4. 在明细里按「**运营人**」分组，对「**经营任务完成率**」列求 `avg` → 白底加粗彩色图（**后发这个**）：`<90%` 红字、`>95%` 绿字、`90%~95%` 黑字，降序排列。
5. **图尾提示行**（大同 10-13 口径）：门店分配里挂着、运营效果导出里却没有的运营人，在图尾以小一号灰字逐行提示「`<原始运营人> N 家无数据未计入`」——**整组缺席的人绝不静默消失**（雷洁老师 23 家是典型案例）。提示行用**原始运营人**而非清洗名，避免和图里「雷洁2」这类近似名混淆。

## 运行入口

```sh
PY=/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python
DIR=/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-store-task-completion-ops-to-wechat

# 只采集 + 关联 + 生成明细/统计图（不发群，dry run 用这个）
$PY $DIR/scripts/task_daily.py

# 采集 + 生成 + 发群（先明细、后统计图；受发送闸约束）
$PY $DIR/scripts/task_daily.py --execute

# 补发：不重新采集，直接用某次 run 目录里的明细+统计图发群
#（大同过目后补发用；run 目录名须以 yyyy-mm-dd 开头；确定性重建，同输入同输出）
$PY $DIR/scripts/task_daily.py --deliver-run $DIR/.runtime/taskrate/runs/<day>-<ns>

# 发送闸：默认【放行】；--disarm 制动；--arm 解除
$PY $DIR/scripts/task_daily.py --disarm
```

> **★ 闸门状态（2026-10-13 收口）：已放行（armed）**。当日数据经大同过目后已由 `--deliver-run` 补发入群（明细+统计图双 `verified`，marker 落账 `events/2026-10-13-taobao-store-task-{detail,stats}.json`）。**10-14 daemon 首跑前需重载 careloop**（manifest 不热加载，见文末）。

- `scripts/task_collector.mjs`：连 9231，导「运营效果（全量·不加筛选）」+「门店分配（根角色全量）」两份原始表，收尾复位 home，`flushExit` 保证锁必释放。
- `scripts/task_workflow.py`：`collect()` → `read_effect`（CSV 多编码 utf-8-sig/gbk/utf-16；xlsx/zip 同兜）/`read_alloc`（openpyxl 读 `门店绑定信息` sheet）→ `build_report()`（vlookup 运营人 + 分组 avg + 渲染图）→ `deliver()`（明细先、图后，两份独立 marker）。
- `scripts/stats_card.py`：组名清洗 + 分组均值 + 白底加粗彩色渲染。
- 产物：`<run>/.runtime/taskrate/runs/<day>-<ns>/`（`<day>运营-店铺经营任务完成率明细.xlsx` + `<day>运营-店铺经营任务完成率.png`）。

## 关键陷阱（实测/已知，勿再犯）

- **服务商平台登录态在 9231**，不在 9230（9230 是淘宝品牌商版 melody.shop.ele.me）。本流两页都在 `open.shop.ele.me`。
- **全量导出慢**：参考流筛「问题类型=新店未养活」只有 8 行，本流是全量（921 门店量级），「数据下载」的 download 事件可能数分钟后才触发 ⇒ 采集器 `EFFECT_DOWNLOAD_TIMEOUT_MS=300000`，python 侧 `timeout=720`，manifest `timeout_seconds=900`。**别把超时改回参考流的 60/240s**。
- **门店分配必须选「根角色」**（公司级「上海臻肆文化传播有限公司(930家)」），否则只得默认角色（如「张燕茹发数据」）名下门店，统计会整体失真。
- **「数据下载」实际给 CSV**（大同口头说 Excel），且大数据量时可能给 zip；读取层三种格式都兜住，`_rate_scale` 还会在小数值 `0.8333` 与百分数 `83.33` 之间按整列最大值自动定标（**定标结果回传在 `summary.json.rateScale`**，出怪数先查它）。
- **门店ID 必须归一化**（去空格/去引号）再关联，否则漏配。
- **统计值必须是图片**：驱动逐字键盘注入敲不进 `\n`，`read_messages` 又把一条消息里的换行整体删除（见 `wechat-messaging/scripts/windows_adapter.py` 顶部注释），多行文本外发后回读锚点必不过、判 `unknown`。这是大同要求做图的**技术根因**，别改回文本。
- **组名清洗只动展示层，绝不用于分组**：分组键永远是门店分配表里的**原始「运营人」**。清洗表 `stats_card.DISPLAY_OVERRIDES` + 前后缀剥离只改显示名（`盯个盯徐从众→徐从众`、`上海青辅咨询→青辅`、`张燕茹发数据→张燕茹`）。原始键回传在 `summary.json.stats[].raw`。
  - ★ **两个不同运营人清洗后撞成同一展示名时，一律退回原始值显示、各自独立成行，绝不合并均值**（`王森` vs `王森组长号` 就是这种）。单测 `test_collision_falls_back_to_raw_name` 钉住这条。
  - ★ **10-13 真实事故（已修）**：清洗表曾把 `雷洁老师` 与 `雷洁2` 都映射成「雷洁」，而 `compute_stats` 又按**展示名**当分组键 ⇒ 两条混算成一条「雷洁 95.33」，那 5 家全是雷洁2 的，**雷洁老师的 23 家贡献 0 家且静默消失**。教训：**别名不得互相合并成同一展示名**；防回归单测 `test_distinct_owners_never_merge_even_with_same_display_name`。
- **★ 覆盖盲区（10-13 实测踩到，查数字先看它）**：`雷洁老师` 名下 23 家门店**在运营效果导出里一条都不存在**（门店ID 全表搜不到 ⇒ 不是匹配 bug；全是重庆门店，疑因合同非「生效中」被站点筛掉），于是这个人**不会出现在图里**。这类组不参与 avg，也**不能当「没问题」**处理——已显式回传 `summary.json.coverage.allocOnlyGroups`（raw/display/shops），并由 `stats_card.coverage_notes()` 生成**图尾提示行**（`summary.json.notes`）。当天实测：alloc 922 家，effect 891 家，差 31 家，分布在 6 个运营人名下（雷洁老师 23 + 四个 1~2 家小缺口 + 王森组长号 1）。
- **events 目录首跑不存在是正常现象**：`deliver()` 会 `mkdir(parents=True, exist_ok=True)` 自动补建（曾在此误闸 `canonical-taskrate-ledger-unavailable`，daemon 首跑必栽，10-13 已修，单测 `test_missing_events_dir_is_auto_created` 钉住）。
- **明细 Excel 的 `经营任务完成率` 列本来就在**（站点导出自带，是汇总的源头列，大同 10-13 确认）——保持站点原样的小数值，**不另加百分数列**；图上是换算后的百分数，两者对不上是预期，不是 bug。

## 关联与统计判据

- `门店ID` / `经营任务完成率` 任一列缺失 ⇒ `effect-missing-shop-id-column` / `effect-missing-task-completion-column`，阻断零发送。
- alloc 缺 `门店ID`/`运营人` ⇒ `alloc-missing-required-columns`。
- 关联不上的行运营人填「未分配」，回传 `unmatchedShops`（前20）；**不因个别未匹配整体失败**。
- 完成率为空的门店不进均值（等价 AVERAGE 忽略空单元格）；某组**全部**为空则整组不进图，`summary.json` 里 `missing` 可见。
- **0 行硬闸**：明细 0 行或统计 0 组 ⇒ `no-report`，不产表不发图（与全项目铁律一致）。
- 明细 Excel 里 `经营任务完成率` 保持**站点原样的小数值**（便于溯源），统计图用的是换算后的百分数；两者对不上是预期，不是 bug。

## 完成与停止

- **投递顺序不可换**：明细 `verified` 之后才发统计图；明细卡住（blocked/unknown）就停，绝不单发图。
- **★ 防重账本分三态，别把 blocked 写成 unknown**（10-13 加固）：
  | marker state | 含义 | 下轮行为 |
  |---|---|---|
  | `verified` | 已发出且群回读锚点命中 | `already_verified`，**零再发、连预检都不打**（前置 marker 判读，不接触网关） |
  | `unknown` | 可能已发出、收据不明 | **绝不重发**，只读对账（10-08 重复外发事故的血泪规则） |
  | `blocked` | **确定没发出去**（网关确定性拒绝/闸门拦/未触驱动） | 允许安全重试 |
  把 `blocked` 混记成 `unknown` 会让一次干净失败被永久卡死；把 `unknown` 混记成 `blocked` 会导致重复外发。两者方向相反，务必分清。
- 同日 marker 里 sha 与本次产物不符 ⇒ `same-event-payload-conflict` 硬阻断，**不覆盖旧账、不发**。
- `deliver(..., adapter=...)` 供离线单测注入桩件；默认 `None` 才现场构造 `WindowsAdapter`。
- 登录失效（`service-login-required`）、岗位被占（`post-lease-busy`）、群预检失败：保留阻断，零发送。
- 发送闸默认放行；临时静默 `--disarm`。
- 共享微信技能（`wechat-messaging`）的发送逻辑/依赖封印不能靠改 Markdown 放行；需要修复走其受控再封印入口。

## 离线单测（不联网、不占岗位、不外发）

```sh
$PY -m unittest discover -s tests -v     # 在本工作流目录下，49 项
```

- `tests/test_task_report.py`：定标 fraction/percent、列缺失阻断、vlookup 插列位置、未匹配上报、空值不进均值、整组无值不出图、覆盖盲区 coverage、zip 兜底、0 行/0 组硬闸、disarm 闸、配色阈值（<90/>95/边界归黑）、数值格式、组名清洗、**同名不合并**、2→3 字对齐、白底渲染、**图尾提示行格式与墨迹断言**。
- `tests/test_delivery.py`：桩件注入，验投递编排——先明细后图、明细卡住则图零发送、预检不过零发送、`verified` 零再发且不碰网关、`unknown` 禁重发、`blocked` 可安全重试、payload 冲突硬阻断、marker 落账正确、**events 目录自动补建**。**49 项全绿，全离线、不发任何消息。**

## 值班登记

- `runtime/skills_manifest.json`：`daily-store-task-completion-ops-to-wechat`，`enabled=true`、`order=10`、`earliest_hour=12`、`latest_hour=18`、`timeout_seconds=900`。
- `runtime/skills_manifest.json.ledger_template`：**追加 row 26**「淘宝闪购门店经营任务完成率小组统计（每日12:00）」（不占用 row 19「门店商户运营问题诊断」等业务占位行）。
- `runtime/posts.json`：`taobao-agent-service(9231).usedBy` 已加本流名 → daemon 取得互斥组 `taobao-svc-9231`（与 `daily-agent-new-merchants-to-wechat`、`daily-new-stores-not-nourished-ops-to-wechat` 三方互斥）。
- 改 manifest 后必须 `launchctl kickstart -k gui/$(id -u)/com.zhensi.waimai.careloop` 重载（manifest 不热加载）。
- **★ 10-13 收口时未重载**：重载会立即跑一轮 due 的流，其中 `meituan-waimai-negative-review-appeals-1425` 与 `taobao-flash-sale-negative-review-appeals` 会**真发群**——监理不替大同触发他人生产流，重载待大同放行后一并做。