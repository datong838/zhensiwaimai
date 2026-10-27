---
name: daily-store-basic-diagnosis-to-wechat
description: 服务商平台取「基础诊断」14 个指标的未完成任务商户列表（含门店ID）+ 门店分配（根角色全量）两份数据，按门店ID关联运营人，生成一个按指标分 sheet 的 Excel 发运营群。
---

# 淘宝门店基础项诊断 · 运营问题分析

本 Skill 是「新店」系列之外的第 2 条「服务商平台两表关联」工作流。它与 `daily-new-stores-not-nourished-ops-to-wechat` **同发一个群**（「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」），岗位同为 **9231 taobao-svc-post**，但**业务对象与数据源不同**：本流取「**经营任务 → 基础诊断**」的 14 个指标商户清单。

## 业务口径（大同 2026-10-13 需求）

1. 服务商平台 → **经营任务 → 基础诊断**：14 个指标（每次单选一个），各取「**任务状态=未完成**」的任务商户列表，字段需含 **门店ID / 门店名称 / 问题分析 / 当前值 / 建议值**。
2. 服务商平台 → **门店分配**：外卖店 tab → **已分配门店** → 点「下载数据」→ 得 Excel（列 `门店名称/门店ID/绑定时间/运营人`）。
3. 以「**门店ID**」为键，把步骤2 的「**运营人**」并入步骤1（等价 vlookup），产出一个 Excel。
4. 发运营群（同上）。

**产物形态（大同 2026-10-13 拍板）**：**一个** Excel，文件名 `yyyy-mm-dd基础诊断-运营问题分析.xlsx`，**每个有数据的指标一个 sheet**（sheet 名=指标名，0 行指标不出 sheet）；每个 sheet 列 = `门店ID / 门店名称 / 问题分析 / 当前值 / 建议值 / 运营人`。发群只发这一个文件。

## 14 个指标（agent_code ↔ 名称）

| 分组 | 指标名 | agent_code |
|---|---|---|
| 门店基础 | 服务功能丰富度不足 | material_service_set_cnt |
| 门店基础 | 店装丰富度不足 | material_shop_set_cnt |
| 门店基础 | 高峰营业时长低 | material_peak_open_duration_7d |
| 门店基础 | 营业时长低 | material_open_time_avg_7d |
| 门店基础 | 最低起送价高 | material_base_delivery_price |
| 服务履约 | 出餐完成上报率低 | material_cooking_over_click_rate_7d |
| 服务履约 | 送达准时率低 | material_ontime_delivery_rate_7d |
| 服务履约 | 商责取消率高 | material_shop_responsibility_cancel_rate_7d |
| 用户管理 | 差评回复率低 | material_negative_reply_rate_7d |
| 用户管理 | 在线联系回复率低 | material_im_reply_5min_rate_7d |
| 用户管理 | 顾客评分低 | material_shop_rating |
| 营销推广 | 有效活动丰富度不足 | material_market_set_cnt |
| 商品管理 | 菜单丰富度不足 | material_item_set_cnt |
| 商品管理 | 优质商品率低 | material_quality_entree_proportion_rate |

## 运行入口

```sh
# 只采集 + 关联 + 生成 Excel（不发群）
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python \
  /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-store-basic-diagnosis-to-wechat/scripts/basic_diag_daily.py

# 采集 + 生成 + 发运营群（受发送闸约束）
... basic_diag_daily.py --execute

# 发送闸：默认【放行】；--disarm 制动写 SEND_DISARMED.json；--arm 解除
... basic_diag_daily.py --disarm
... basic_diag_daily.py --arm
```

- `scripts/basic_diag_collector.mjs`：连 9231 → 打开基础诊断页 → **一次加载拿凭证** → 换 `agentCode` 批量拉 14 指标全量 → 下载门店分配表；收尾复位 home（`flushExit` 防句柄挂起、锁必释放）。
- `scripts/basic_diag_workflow.py`：`collect()` → `read_alloc()`（openpyxl 读 `门店绑定信息` sheet）→ `build_report()`（按指标建 sheet，插「运营人」列，蓝底表头+冻结首行）→ `deliver()`（marker 去重 + WindowsAdapter 直连发 file）。
- 产物：`<run>/.runtime/basic-diag/runs/<day>-<ns>/<day>基础诊断-运营问题分析.xlsx`。
- **★ 解释器与 sys.path**（2026-10-13 手工跑通的组合，沙箱内可用）：需 `openpyxl`，用 `/Users/ddt/.workbuddy/binaries/python/envs/default/bin/python`（**并 `env -u PYTHONPATH` 防沙箱注入**）；发送链路 `windows_adapter` 会 `import client` / `import wxsend`，这两个模块在 `/Users/ddt/work/projects/ai_agent/wechat-windows-driver/`，**手工调用时必须先把它加进 `sys.path`**（daemon 由自身 PYTHONPATH 提供）。裸 python 跑全量测试会因缺 PIL 假报错，非代码回归。

## 关键陷阱（已实测踩过，勿再犯）

- **★ 站点自带「下载」的 CSV 不含门店ID**：列只有 `门店名称/问题分析/当前值/目标值/状态`。**不能**用它做关联；必须走列表接口 `pageQueryOpenTaskMerchantList`（响应含 `shop_id`）。
- **★ 重放列表接口必须带请求头 `token`**（形如 `...=5354305340`）。缺 `token` → **HTTP 401 / code 401002**（不是签名问题，别误判）。
- **★ 签名不覆盖 `pageSize` 与 `agentCode`**：可一份凭证换 `agentCode` 批量拉 14 指标，且 `pageSize=1000` **一次取全量**（实测 731 行一次返回）。**但 `pageSize=5000` 会被服务端吞成 0 行** ⇒ 用 1000，并留分页兜底（`current++` 直至 `collected>=totalCount`）。
- **凭证来源**：基础诊断页打开时会**自动**发一次列表请求（默认指标=服务功能丰富度不足），从中取 `url/reqBody/token` 作为基凭证；若未自动触发，点一次任一指标 radio 兜底。
- **`shop_id` 是数字、分配表「门店ID」是字符串** ⇒ 两侧都必须归一化（去空格/去引号）再关联，否则漏配。
- **门店分配必须选「根角色」**：默认选中某个运营人角色（只得其名下门店）。必须点公司级根节点「上海臻肆文化传播有限公司」才拿全量（实测 922 条）。
- **服务商平台登录态在 9231，不在 9230**（9230=品牌商版 melody.shop.ele.me）。

## 关联判据

- 分配表须含「门店ID」「运营人」列，否则 `alloc-missing-required-columns` 阻断。
- 关联不上的行「运营人」填「未分配」，并在 result 回传 `unmatchedShops`（前 20）。不因个别未匹配整体失败；但 0 行不产表、不发群（`no-report`）。
- 仅保留 `task_status == "未完成"` 的行（接口已按 `taskStatus=未完成` 过滤，落盘前再校验一次）。

## 完成与停止

- 每日入口只发当天新生成的那一份 Excel；0 行 `no-report`、零发送。
- 登录失效（`service-login-required`）、岗位被占（`post-lease-busy`）、目标群预检失败：保留阻断、零发送；已 `attempted` 不明时只读对账，绝不重复发送。
- 发送闸默认放行；临时静默 `--disarm`。
- 共享微信技能（`wechat-messaging`）的发送逻辑/策略/依赖摘要/防重账本不能靠改 Markdown 放行；如需修复走其受控再封印入口。

## 值班登记（接入方式）

**接入/撤出用脚本，勿手改 manifest**：

```sh
cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back
/usr/bin/python3 runtime/enable_basic_diag_flow.py --status    # 只读看是否已接入
/usr/bin/python3 runtime/enable_basic_diag_flow.py --enable    # 接入（写 manifest+posts，校验，重载 daemon）
/usr/bin/python3 runtime/enable_basic_diag_flow.py --disable   # 撤出（恢复原状）
```

- 脚本幂等；写盘前自动备份 `<file>.bak-basicdiag-<ts>`；写盘前跑 JSON 校验 + `assert_flow_order` 断言；重载优先 `launchctl kickstart -k gui/$(id -u)/com.zhensi.waimai.careloop`，沙箱不可见时回退 `kill <pid>`（SIGTERM，靠 KeepAlive 重生）。
- 接入后三处齐备：① `skills_manifest.json` 新增条目（`enabled=true, dev_state=active, order=10, cadence_hours=24, earliest_hour=13, latest_hour=18, timeout_seconds=900`，steps=`{python} scripts/basic_diag_daily.py --execute`）；② 台账模板 **row 19** 由 `pending/门店商户运营问题诊断` 转 `active`；③ `posts.json` 的 `taobao-agent-service(9231).usedBy` 加入本流名（取互斥组 `taobao-svc-9231`）。
- **★ 接入时点很关键**：daemon 启动只 `load_manifest` 一次、不热加载，所以必须重载；且**若当天接入时已过 `latest_hour(18)`，该流会被判 `past_latest` → 台账「未全绿」且巡检每小时报 YELLOW**。故**开档（13:00）之后不要再接入**——要么赶在 13:00 前，要么次日接入。

> 2026-10-13：本流当天 23 点才建成，按大同要求「当天只开发、不发送」，**当天未接入**（避免当晚台账由 19/19 变 19/20 并触发夜间巡检告警）；已改用一次性自动化 `a9630b32-1eac-4288-9288-db249b37c3e3`（2026-10-14 13:10）执行 `--enable` 接入，随后由 daemon 在 13:00 档自动跑并外发。发送闸已 `--arm`（默认放行）。
>
> **2026-10-13 23:42 首次外发（手工触发，大同当场批准「今天这个可以发群」）**：把当天试跑产物 `2026-10-13基础诊断-运营问题分析.xlsx`（2100 行 / 14 个指标 sheet / 运营人关联 2100 全中）发到「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」，`status=verified`、`sendAttempts=1`、`verificationLevel=windows-readback-file-card`（`currentTitle` 与目标群一致、`[文件]` 卡片位于末尾、marker `sha256` 与本地文件逐字节一致）。
> - **踩坑并已修**：发送前台账目录 `.runtime/basic-diag/events/` 不存在，直接撞上 `deliver()` 的 fail-closed 硬闸 `canonical-basic-diag-ledger-unavailable`（首跑必 blocked）。修法=`main()` 在正常路径上先 `EVENTS.mkdir(parents=True, exist_ok=True)`；**硬闸语义保留**（运行期目录消失仍拒发，不因修复而静默重发）。
> - 幂等已验证：同 event 复跑 `deliver()` 返回 `already_verified` 且 `sendAttempts=0`（零重发）。
> - 手工外发只调 `deliver()`，**严禁重跑 `main()`/采集**（重跑=重复外发副作用）。
>
> **2026-10-13 23:53 接入值班（大同要求「安排值班」，台账 19 → 20 个流）**：`runtime/enable_basic_diag_flow.py --enable` 已执行——manifest 新增本流条目、台账 row19 转 `active/门店商户运营问题诊断（每日13:00）`、`posts.json` 的 `taobao-agent-service(9231).usedBy` 加入本流（该岗位现共 4 个流），`launchctl kickstart -k` 重载 daemon（pid 21330）。写盘前备份 `*.bak-basicdiag-20261013-235309`，校验 + `assert_flow_order` 全过。
> - **接入后当天是 `past_latest`（已过 latest_hour=18 且当日无成功记录）→ 记 PENDING、`all_green=false`**。已用**真实外发证据**补登完成信号：`last_success.json` 写 `2026-10-13T23:42:03`（回读 `readbackAt=1791906123.6` 换算），并调用 `run_all._persist_done_today_record()` 落 `run_history` SUCCESS（记录内附 marker/sha256/verificationLevel/行数，可审计）。补登后 `_cadence_gate` 判 `done_today`、`ledger_gate` 变 `GO` 且 `C_ok=20`（本流 `runs=1`）。
> - **★ 双源必须同补**：只写 `last_success.json` 会让台账 Excel 显「已完成」而 `ledger_gate`（只读 run_history）查不到 → 重现「Excel 全绿但 gate 拦发」。补登脚本以 marker `state==verified and sendAttempts==1` 为硬前提，无证据不写。
> - **时序验证（用守护自身判据 `_cadence_gate` 复算，非推演）**：今晚 23:58 → 本流 `done_today`、`past_latest` 流数 **0**（夜间无本流告警）；10-14 00:23 → 本流 `not_due`（**不会凌晨跑、不会夜间外发**）；10-14 13:05 → 本流 `(False,'')` **真正执行**（采集+生成+外发）。
> - **夜间 YELLOW 属既有常态，勿误判为本流引入**：`supervisor_patrol` 的 `check_last_cycle` 对任何非 SUCCESS 都报；历史取证——凌晨 00–07 点 10-11 报 8 次、10-13 报 9 次 YELLOW（跨零点后所有流都是 `not_due` PENDING，与本流无关）。**不得为消音改巡检判据**（弱化监控是禁忌）。
> - 明日首发档 13:00（9231 岗位与每小时流 `daily-agent-new-merchants-to-wechat` 同互斥组，若撞车会 `SKIPPED_BUSY` 并在下周期重试，属既有排队机制）。一次性自动化 `a9630b32`（13:10 `--enable`）已无必要——接入态下它走 `[noop]` 分支、不重载 daemon，保留零风险，可随时删。
