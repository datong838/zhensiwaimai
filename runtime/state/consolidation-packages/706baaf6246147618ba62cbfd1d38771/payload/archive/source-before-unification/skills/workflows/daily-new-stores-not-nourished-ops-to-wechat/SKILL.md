---
name: daily-new-stores-not-nourished-ops-to-wechat
description: 服务商平台取「新店未养活」运营效果数据 + 门店分配（根角色全量）两份表，按门店ID关联运营人，生成 Excel 发运营群。
---

# 淘宝新店未养活运营分配

本 Skill 是「新店」三兄弟（开业识别 / 活动缺项 / 装修缺失）之后的第 4 条独立工作流。它与 `daily-new-stores-activity-audit-to-wechat` **同发一个群**（「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」），但**数据源、岗位、逻辑完全不同**：本流在**服务商平台 `open.shop.ele.me`（岗 9231 taobao-svc-post）**，把两份站点导出表按「门店ID」关联合并成一份 Excel 外发。

## 业务口径（大同 2026-10-12 需求）

1. 服务商平台 → **代运营 → 运营效果分析**：问题类型选「**新店未养活**」→ 点「数据下载」→ 得运营效果数据（**实际为 CSV**，首列「门店ID」，含「新店是否养活」列）。
2. 服务商平台 → **门店分配**：外卖店 tab → **已分配门店** → 点「下载数据」→ 得 Excel（列含 `门店名称/门店ID/绑定时间/运营人`）。
3. 以「**门店ID**」为键，把步骤2 的「**运营人**」并入步骤1（等价 vlookup），生成一份 Excel 发运营群。

## 运行入口

```sh
# 只采集 + 关联 + 生成 Excel（不发群）
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python \
  /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-new-stores-not-nourished-ops-to-wechat/scripts/nourish_daily.py

# 采集 + 生成 + 发运营群（受发送闸约束）
... nourish_daily.py --execute

# 发送闸：默认【放行】；--disarm 制动写 SEND_DISARMED.json；--arm 解除
... nourish_daily.py --disarm
... nourish_daily.py --arm
```

- `scripts/nourish_collector.mjs`：连 9231，导航两页并触发站点自身下载（不新建标签页，收尾复位 home；`flushExit` 保证进程退出、锁必释放）。
- `scripts/nourish_workflow.py`：`collect()` → `read_effect`（CSV 多编码 utf-8-sig/gbk/utf-16）/`read_alloc`（openpyxl 读 `门店绑定信息` sheet）→ `build_report()`（按门店ID插入「运营人」列，蓝底表头+冻结首行）→ `deliver()`（marker 去重 + WindowsAdapter 直连发 file）。
- 产物：`<run>/.runtime/nourish/runs/<day>-<ns>/新店未养活运营分配_<day>.xlsx`。

## 关键陷阱（已实测踩过，勿再犯）

- **服务商平台登录态在 9231，不在 9230**。9230=淘宝品牌商版（melody.shop.ele.me），本流的两页都在 `open.shop.ele.me`＝服务商平台＝9231。
- **门店分配必须选「根角色」**：页面默认选中某个运营人角色（如「张燕茹发数据」，只得其名下门店、运营人一栏全是她）。必须点公司级根节点「**上海臻肆文化传播有限公司(930家)**」才能拿到全量已分配门店（实测 921 条）。`nourish_collector.mjs` 用 `ROOT_ROLE_PREFIX` 定位根节点，并在条数 `<2` 时阻断。
- **「数据下载」得到的是 CSV 而非 xlsx**（大同口头说 Excel，实际站点给 CSV），读取按 CSV 多编码兜底。
- **门店ID 必须归一化**（去空格/去引号）再关联，否则数字串两侧空白会导致漏配。

## 关联判据

- 「门店ID」列在两个来源都必须存在，否则 `effect-missing-shop-id-column` / `alloc-missing-required-columns` 阻断。
- 关联不上的行「运营人」填「未分配」，并在 result 里回传 `unmatchedShops`（前 20）。**不因个别未匹配而整体失败**；但 0 行不产表、不发群（`no-report`）。

## 完成与停止

- 每日入口只发当天新生成的那一份 Excel；Excel 行数为 0 时 `no-report`、零发送。
- 登录失效（`service-login-required`）、岗位被占（`post-lease-busy`）、目标群预检失败：保留阻断，零发送；已 `attempted` 不明时只读对账，绝不重复发送。
- 发送闸默认放行（与装修流一致，防「每日 arm」噪音）；临时需要静默时 `--disarm`。
- 共享微信技能（`wechat-messaging`）的发送逻辑/策略/依赖摘要/防重账本不能靠改 Markdown 放行；如需修复走其受控再封印入口。

## 值班登记

- `runtime/skills_manifest.json`：`skills[]` 条目 `enabled=true`、`order=10`、`earliest_hour=11`、`latest_hour=18`、`timeout_seconds=360`；`ledger_template` **row 18**（原「新店养活」占位）已转 `active`。
- `runtime/posts.json`：`taobao-agent-service(9231).usedBy` 已加入本流名，使 daemon 取得互斥组 `taobao-svc-9231`（与 `daily-agent-new-merchants-to-wechat` 互斥，防同端口并发）。
- 改 manifest 后必须 `launchctl kickstart -k gui/$(id -u)/com.zhensi.waimai.careloop` 重载（manifest 不热加载）。
