---
name: contract-termination-applications-screenshot
description: 截取淘宝闪购服务商平台「客户管理 → 合同解约申请」任务列表原图（任务状态固定选「处理中」），落盘 PNG + JSON 收据。当需要「合同解约申请」列表截图、核对待处理解约任务数量、或按门店/状态复核解约任务时使用。
license: CC0-1.0
metadata:
  author: ops
  version: 0.1.0
  created: 2026-10-20
  target_site: https://open.shop.ele.me/manager/agent/dissolution-task
  post: taobao-agent-service / 127.0.0.1:9231
  layer: business-application
  trigger: 大同 2026-10-20「做一个合同解约申请的截图，和 top10 流程一样，菜单换掉，任务状态选处理中」
allowed-tools:
  - control-background-dedicated-chrome
  - Bash
  - Read
---

# 合同解约申请 · 任务列表截图（工位 9231）

## 一句话

复用 Top10 的「进页面 → 筛选 → 截表格原图落盘」形态，把菜单换成 **客户管理 → 合同解约申请**，
**任务状态固定选「处理中」**，截出「任务列表」表头 + 全部数据行（含操作列）的原图，并写 JSON 收据。

## 页面与固定口径

| 项 | 值 | 来源 |
|---|---|---|
| 工位 | `taobao-agent-service` / `127.0.0.1:9231` | `skills/posts/taobao-svc-post` |
| 路由 | `https://open.shop.ele.me/manager/agent/dissolution-task` | 站内菜单 客户管理 → 合同解约申请 实测跳转 |
| 菜单路径 | 代运营 → 客户管理 → 合同解约申请 | 首页左侧一级/二级菜单 |
| 筛选 | 任务状态 = 处理中（其余条件不填） | 大同 2026-10-20 口径 |
| 截图范围 | 蓝色标题条「任务列表」+ 表头 + 全部数据行 | 对齐大同给的示例图；**不含**筛选器、分页器 |
| 分页 | 默认 10 条/页；超过 1 页逐页截图并拼接记录 | 「不要漏记录」 |
| 输出 | `runtime/state/screenshots/contract-termination/<YYYY-MM-DD>/<日期>_合同解约申请_<状态>_p<N>.png` + `..._run-<HHMM>.json` | — |

## 用法

```bash
cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/contract-termination-applications-screenshot/scripts

# 判据自检（纯函数，不碰工位）：必须 13 passed, 0 failed
NODE_PATH=/Users/ddt/.workbuddy/binaries/node/workspace/node_modules \
  /Users/ddt/.workbuddy/binaries/node/versions/22.22.2-2/bin/node contract_termination_shot.mjs --self-test

# 只读结构探测（进页面读表头/行数，不筛选不截图）
... contract_termination_shot.mjs --dry-run

# 真跑：任务状态=处理中 + 截图落盘（默认）
... contract_termination_shot.mjs
# 其它状态 / 自定义输出目录
... contract_termination_shot.mjs --task-status 已完成 --out-dir /tmp/shots
```

退出码：`0` 成功（含状态一致性自检 0 异常）；`3` 登录/页面异常；`4` 工位忙跳过；`9` 其它错误。

## 硬约束（沿用本仓纪律）

1. **只连已运行的后台专用 Chrome**（9231），不启动/重启浏览器。
2. **不新开标签页**：复用 `context.pages()[0]`，站内点击 + 本站路由 `page.goto`。
3. **抢 `taobao-svc-post` 工位租约**（`/tmp/zhensi-post-9231.lock`），抢不到即 `SKIPPED_BUSY` 退出，绝不干扰采集流；**死 pid 遗留租约自动清理**（否则会白锁 30 分钟）。
4. **登录硬闸**：`assertOrigin` + `assertAuthenticated`，命中登录特征即 `service-login-required`，不截图、不猜测。
5. **只读**：不点「导出查询结果」、不碰「操作」列的「查看合同/去处理」，不提交任何写操作。
6. **收尾复位** `https://open.shop.ele.me/manager/base/home`，保持工位已知良好态。
7. **收据必落盘**：行内容、总条数/页数、状态自检结果、告警项全写 JSON，便于事后溯源。

## 实现要点（踩过的坑）

- **别用 `table.rows` 取数**：页面上第一张 `<table>` 是 antd 的定宽量测表（`table-layout: fixed` + `<colgroup>`，0 数据行）。
  必须用 `.ant-table-thead th` 取表头、`.ant-table-tbody tr.ant-table-row` 取数据行。
- **该工位窗口只有 ~1126 px 宽，而表格最小宽度 12 列 × 120 px = 1440 px** ⇒ 直接截会切掉右侧「任务状态/说明/操作」。
  做法：CDP `Emulation.setDeviceMetricsOverride` 把视口提到 1800×1200、DSF=2（原图级清晰），截完 `clearDeviceMetricsOverride`。
- **表格纵向不内滚**（`scrollHeight == clientHeight`），但要 `window.scrollTo(0,0)` + 表体 `scrollLeft=0` 后再算 clip，
  否则 `getBoundingClientRect` 为视口坐标、与 CDP 文档坐标错位，截出来是空白或错行。
- **分页器不显示「共 N 条」**（只有页码序列），总条数取不到时用 `.ant-pagination-item` 的最大页码兜底。
- **「任务状态」下拉禁按下标硬编码**：用「label 文本 → 文档顺序后第一个 `.ant-select`」定位，
  选中项用**精确文本匹配**（`处理中` 绝不能命中 `待处理中`），选完再点「查询」。
- **筛选后必做状态一致性自检**：所有行「任务状态」列必须等于目标值，否则告警（防筛选没生效就出图）。

## 值班任务流（2026-10-20 起，对齐 daily-store-basic-diagnosis 形态）

入口 `scripts/contract_termination_daily.py`（薄壳）→ `contract_termination_workflow.py`：

```bash
cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/contract-termination-applications-screenshot
python3 scripts/contract_termination_daily.py              # 只截图（不发）
python3 scripts/contract_termination_daily.py --execute    # 截图 + 发运营群（daemon 排班用）
python3 scripts/contract_termination_daily.py --deliver-run <run目录>   # 不重截，用某次 run 的图补发
python3 scripts/contract_termination_daily.py --disarm     # 制动发送；--arm 解除
```

- **排班**：`runtime/skills_manifest.json` 注册为每日 09:00（cadence 24h，latest_hour=18），daemon 派班执行 `--execute`。
- **岗位**：`runtime/posts.json` 的 `taobao-agent-service`（9231）usedBy 已登记本流；工位忙退出码 4 → `skipped-busy` 可恢复跳过，不干扰采集流。
- **发送**：经 Windows 网关发运营群「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」；多页逐张发（p1/p2…）。
- **防重**：marker = `.runtime/contract-termination/events/<YYYY-MM-DD>-contract-termination-ops.json`（state: attempted→verified；sha256 不一致 ⇒ same-event-payload-conflict 阻断，防同日重复外发）。
- **0 行不产不发**：无数据行时不发群（记 `no-report`）。
- **发送闸**：默认放行；`SEND_DISARMED.json` 存在即制动（零外发）。
