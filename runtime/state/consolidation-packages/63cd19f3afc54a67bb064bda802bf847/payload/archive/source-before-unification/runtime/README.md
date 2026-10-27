> 当前生效规范：[机制运行与客户迁移交接](../docs/operations/20261024-机制运行规范与客户迁移交接.md)。下文历史通道、群名、排班与职责若有冲突，以该规范为准；纯调度脚本不代表UI岗位已可无人值守。

# zhensi_waimai · 统一调度薄包裹层（runtime/）

> 工作目录：`zhensi_waimai_back/`（原 `zhensi_waimai` 已废弃）
> 本层是 **Phase 1 统一调度**：单入口 launcher + **任何 agent（WorkBuddy / Cursor / 豆包 等）看护**，**零碰 skill 内部逻辑**。

## 1. 定位与铁律

- **只包裹、不改写**：本层按 `skills_manifest.json` 以命令行方式调用各 skill **现有入口**，不感知/不绕过 skill 内部任何安全门。
- **安全门零改动**（保护项）：各 skill 的 `EXTERNAL_EFFECT fail-closed` / 防重账本(`atomic_json`) / 逐字授权 / `ActionResult` 收据 / `policy sha256 fail-closed` / `UNSEALED_ACCEPTANCE` 一律不动。
- **看护模型（P3-1B 已升级为常驻守护）**：`run_all.py --daemon` 由 launchd KeepAlive 常驻运行，按 manifest 的 `order`/`cadence_hours`/`earliest_hour` **统一编排**（agent 掌握），持有真机/微信/浏览器会话不退出，根治诊断根因1（会话冷启动）。`--daemon` 之外仍保留一次性看护（跑全部 enabled）与 `--once` 手动触发。
- **fail-closed 语义**：适配未完成的 skill 会 `enabled:false`，相关台账行记「否」，发送门不全绿、不自动发群。历史上 #6（daily-taobao-download-to-jinsha）与 #9（meituan-intelligent-customer-service）曾因此暂禁，**两者均已于 2026-10-02 前完成适配并转 active**（runScheduled 适配层 / ensure_unanswered_queue CLI）；当前 `enabled:false` 的仅剩 2 条 blocked（视频发布、巡店）。
- **看护者中立（agent-agnostic）**：本层只依赖 `python3` + PATH 上的 `node` + 各 skill **现有入口脚本**；**不依赖 codex 或任何特定 agent 运行时**。历史上 `codex` 只是一种触发方式（其 `~/.codex/skills` 软链/注册桩指向本仓库 `skills/`），WorkBuddy / Cursor / 豆包 等任意能执行 `python3 runtime/run_all.py` 的 agent 都能看护。唯一外部库依赖是 `aos-platform/plugins/browser/` 下的两个 Playwright 插件（`headless-playwright` / `isolated-persistent-playwright`，各 skill `require` 其 `playwright-core`）——与本仓库业务逻辑无关，不在本层改动范围内。

## 2. 文件结构

| 文件 | 职责 |
|---|---|
| `skills_manifest.json` | 23 skill 调用声明 + interpreters 占位 + 台账 26 行模板（2026-10-18 口径；初建为 14 skill/17 行）（**配置，唯一需随 skill 演进维护的文件**） |
| `skill_runner.py` | 薄包裹层库：失败分类 / flock 互斥 / 每步看门狗 / 重试预算 / run prune / interpreters 解析 / 当日汇总 / `last_success` 持久状态 |
| `run_all.py` | 入口 + 看护遍历 + 台账生成 + 发送门 + **常驻守护(`--daemon`)/cadence 编排/错误工作流告警/状态文件** |
| `state/` | 常驻守护状态：`daemon.json`(心跳) / `last_cycle.json`(每轮汇总) / `alerts.jsonl`(告警流) / `control.json`(强制跑请求) / `sent_today.json`(发送去重) / `last_success.json`(cadence 依据) |
| `com.zhensi.waimai.careloop.plist` | launchd LaunchAgent（用户会话级）：`RunAtLoad`+`KeepAlive` 崩溃自启，常驻持有会话（P3-1B） |
| `run_history/` | 运行记录（每日子目录 `YYYY-MM-DD/`，含每步日志 + record.json）；prune 保留 14 天 |

## 3. 用法

```bash
cd <本仓库根目录>          # 即包含 runtime/ 的那一层（可随意改名，脚本按自身位置推导，不从目录名硬编码）
python3 runtime/run_all.py --list        # 列出 23 条目与 enabled 状态（20 值班 + 2 blocked + 1 共享库）
python3 runtime/run_all.py --dry-run     # 打印将执行计划（不真跑、不生成台账）
python3 runtime/run_all.py --selftest     # 调度层纯逻辑自测（分类/锁/prune/manifest）
python3 runtime/run_all.py --status      # 当天各 skill 状态快照
python3 runtime/run_all.py --once <name> # 手动触发单个（含 oneshot meituan-waimai）
python3 runtime/run_all.py               # 真实看护一轮（强制全部 enabled）
python3 runtime/run_all.py --send        # 真实看护一轮 + active 全绿时经微信发群（需登录态）
python3 runtime/run_all.py --cycle-once  # 跑一个 daemon 周期（按 cadence 门控，跑完即退，测试用）
python3 runtime/run_all.py --daemon      # 常驻守护：按 cadence 循环编排，由 launchd KeepAlive 崩溃自启
```

### 常驻守护安装（P3-1B · 根治根因1）

```bash
# 1) 放到用户 LaunchAgents（必须用户会话级，因需 USB 真机/桌面微信/浏览器 GUI）（⚠️ Mac 桌面微信已于 2026-09-30 停用，此处「桌面微信」指代过时；看护所需 GUI 会话仅指浏览器 Chrome profile 与 USB 真机，微信发送改走 Windows 网关/手机微信）
#    用 install 脚本生成（按当前绝对路径注入，重命名项目目录后重跑即可，不写死目录名）：
bash runtime/install_daemon.sh

# 2) 加载（RunAtLoad + KeepAlive 生效；崩溃自动重启，等价 n8n restart:unless-stopped）
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.zhensi.waimai.careloop.plist
launchctl kickstart -k gui/$(id -u)/com.zhensi.waimai.careloop

# 3) 查看 / 停止
launchctl print gui/$(id -u)/com.zhensi.waimai.careloop
launchctl bootout gui/$(id -u)/com.zhensi.waimai.careloop   # 卸载（会终止进程）

# 4) 日志
tail -f runtime/state/daemon.out.log
```

> 注意：plist 里 `ProgramArguments` 的 python 路径用的是 managed 3.13.12；若本机用其它解释器，改 plist 路径或设 `ZENSI_*` 环境变量覆盖 manifest 的 interpreters。

### agent 看护接口（常驻期间跟进进度）

常驻守护把状态落到 `runtime/state/`，代理（WorkBuddy）读这些文件即可在看护期间跟进，无需打断 daemon：

| 文件 | 内容 |
|---|---|
| `state/daemon.json` | 心跳：pid / started_at / last_cycle_at / next_cycle_at / status |
| `state/last_cycle.json` | 每轮汇总：各 skill 状态/成功时间/本轮是否全绿 |
| `state/alerts.jsonl` | 错误工作流告警流（NEEDS_LOGIN/UNKNOWN + 日志路径） |
| `state/control.json` | 写 `{"force_run":"<name>"}`（或数组）让 daemon 下轮强制跑该技能（避免与全局锁冲突） |

`run_all.py --status` 一屏汇总当天 record + daemon 心跳。

### 授权到期看门狗（P3-3 · 治根因5）

`runtime/auth_watch.py` 只读扫描 `skills/**/{executor-lock.json,runtime-policy.json}`，抽取 `expiresAt`（兼容 ISO 字符串与 Unix epoch 整数），对「距到期 ≤ 阈值(默认24h)」的项写 `state/alerts.jsonl` 告警（抄 n8n Error Workflow 的"异常触发告警流"语义），24h 内同键去重避免每周期刷屏。

**安全门零改动铁律**：重封（reseal）只在「本轮真实非空商家发送通过」时由 skill 内部 `executor_integrity` 原子完成，**看护进程绝不代劳**——否则会放宽 `UNSEALED_ACCEPTANCE` 安全门。因此本模块只读不改任何锁/策略文件（`--auth-watch` 与 daemon 每周期都会跑，但只产生告警事件）。

```bash
python3 runtime/run_all.py --auth-watch   # 手动触发一次扫描+告警（daemon 每周期也会自动跑）
```

## 4. 解释器配置（interpreters）

manifest 顶层 `interpreters` 默认用 PATH 上的 `node` + 项目 venv python，**不绑定任何特定 agent 运行时（含 codex）**。**可用环境变量覆盖**（避免硬编码绑定某机）：

| 占位 | 默认 | 覆盖变量 |
|---|---|---|
| `{node}` | PATH 上的 `node`（不再硬编码 codex runtime） | `ZENSI_NODE` |
| `{python}` | `/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python` | `ZENSI_PYTHON` |
| `{python3}` | `python3` | `ZENSI_PYTHON3` |

例：`ZENSI_NODE=/usr/local/bin/node python3 runtime/run_all.py --dry-run`

## 5. 失败分类与看护动作

| 分类 | 含义 | 看护动作 |
|---|---|---|
| `SUCCESS` | 全部步 exit=0 | 记「是」 |
| `RECOVERABLE` | 瞬态（超时/连接失败/设备离线） | 预算内自动重试（max_retries + cooldown）；耗尽后代理读日志决定再等冷却重跑或跳过 |
| `NEEDS_LOGIN` | 登录态失效（命中「扫码/未登录」等） | 写 `state/alerts.jsonl`（错误工作流告警流，抄 n8n Error Workflow），代理 @人告警，人工恢复后重跑 |
| `UNKNOWN` | 真故障 | 写 `state/alerts.jsonl`，代理读日志定位根因后升级 |

## 6. 台账体系（两类）

- **客户版**：`work/YYYY-MM-DD臻肆工作台账.xlsx`（复刻深蓝表头/绿「是」/COUNTIFS 汇总）。26 行规划+执行一体（2026-10-18 口径；初版 17 行），**不含单次任务**。完成口径＝当日任意一轮成功即「是」。**发送门＝active 20 行全绿才发 AI 员工群（这是给老板看的每日汇总，非逐工作流投递）**；有失败先处理并告警，不发群，全绿后补发。
- **各工作流落群是异构的（已核实，不在 run_all 控制内）**：逐工作流的消息发送 100% 在 skill 内部、由 `wechat-messaging/scripts/workflow_bridge.py` 的 `REGISTRY` 决定落群，manifest 每个 skill 已记 `target_group` 权威字段。**现行 20 值班流落群全景以 `docs/operations/工作流-落群对照表.md` 为唯一权威**（2026-10-18 已按 manifest 重导；四大固定群：员工群 `FEIBING NEO AI数字员工` / 运营群 `上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰` / `电销+直播攻坚组` / 品牌唯一匹配群异构多群，另有门店视频群异构·blocked）。**run_all 从不代发任何工作流消息**，只在一天结束时把「汇总台账」发到员工群（老板看）。
- **内部版**：`run_history/` + `--status` 快照，供代理看护决策（含重试/分类/日志路径、可含单次任务）。

## 7. Phase 2 执行器/共享库改造（待做，每项带测试）

详见 `docs/architecture/流程执行器依赖与共享库清单.md` §五（2026-10-18 改名去数量前缀，条目已重导为 23 条）：

- **A** 合并 fork 执行器（`workflow_executor`/`runtime_contract`/`executor_integrity`/`runtime_guard`）为单一真源
- **B** 修 `.codex/skills/...` 硬编码 → canonical `skills/...` ⇒ **已决议跳过（2026-09-28）**：实读代码 + sha256 验证确认 `.codex` 软链/注册桩是刻意安全架构且当前健康，去硬编码会削弱生产安全门，违背 P3-3「安全门零改动」铁律。
- **C** 解 #6 sha256 自锁 + 动态 import ⇒ **已决议跳过（同上）**：自锁当前与 canonical 源文件哈希精确一致、`preflight` 比对通过，是 fail-closed 保险；保留不动。
- **D** 补 subprocess timeout（多处 `osascript`/`screencapture`/依赖维护）
- **E** 删 `maintenance/candidate` 漂移副本

适配待办：**#6** 写 `node -e` 包裹 `runScheduled`；**#9** 写 CDP `driver` 注入薄包装。两者 manifest 已标 `needs_adapter:true, enabled:false`。

## 8. 依赖

- 生成 xlsx 需 `openpyxl`（`pip install openpyxl`）；缺失时 `run_all` 自动降级 csv 并告警。
- 调度层纯逻辑（分类/锁/prune/manifest/dry-run）仅用标准库。

项目级文件与图片大小约束：复用docs/operations/文件与图片大小统一约束.md及file_size_policy.py；显示取整保留一个显示精度单位余量，真实上传上限预留至少5%，禁止把88K/89K显示值硬编码成上传门槛。
