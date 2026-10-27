# Phase 3 · 诊断目标对齐与运行时加固方案（先方案再编码）

> ⚠️ **历史快照状态头（2026-10-18 加，大同授权）**：本文为 dated 方案，**设计与结论保留有效**；文中「14 流程/14 条目」为 2026-09-28 当日真实口径，**不作现状**——现役 **20 条 enabled 值班流**（skills 共 23 = 20 + 2 blocked + 1 共享库），权威口径见 `runtime/skills_manifest.json`。

> 工作目录：`zhensi_waimai_back/`
> 本文是 Phase 3 的**改造方案**，落地前需用户 approve。
> 触发原因：用户质询「Phase 2 能否实现两份诊断文档的分析目标、有无看漏」。
> 审计结论：**Phase 1/2 只实现了两份诊断里"代码卫生"维度的少数点，诊断的主体目标（运行时工程化加固）大部分未覆盖**；且文档2（n8n 路线）被搁置，属路线分歧，需用户拍板。

---

## 0. 覆盖率审计矩阵（逐条对齐，含核实证据）

### 0.1 文档1《稳定性诊断与加固分析》—— 6 类根因 + 8 条加固建议

| 诊断条目 | 分析目标 | Phase 1/2 落地 | 覆盖判定 | 核实证据 |
|---|---|---|---|---|
| 根因1 会话冷启动（最致命） | 常驻守护持有会话 | **P3-1B 进行中**（launchd KeepAlive 常驻 + `preflight_warmup` 主动重连） | 🟡 | 本次落地：`run_all.py --daemon` + `com.zhensi.waimai.careloop.plist` 常驻守护；daemon 持环境不退出，根治冷启动 |
| 根因2 抖动当失败→thrashing | 失败分类+抖动预算 | Phase 1 `classify_failure` + 重试预算（连错3/5min冷却） | 🟡 部分 | skill_runner.py:198-206；但分类维度是"退出码/needs_login"，非"窗口/截图/激活瞬态"细粒度 |
| 根因3 单Mac单手机多技能争用 | 执行槽位串行化/机器独占 | Phase 1 全局锁 `.runner.lock` + 单一看护入口串行 | 🟡 部分 | skill_runner.py:32/99-118；"机器独占/专用机"未做 |
| 根因4 睡眠/ADB掉线级联 | `caffeinate` 防睡 + 超时 | **P3-2 已做**（run_all 看护入口 `ensure_caffeinate`，仅 macOS 生效） | 🟡 | `ensure_caffeinate()` 已落 run_all.py:281；非 macOS 安全跳过；真机 caffeinate 生效待用户验收 |
| 根因5 授权过期单点 | 自动化续期 + 到期告警 | **未覆盖** | ❌ | 仅 fail-closed；无续期/告警代码（grep 仅命中 references/tests） |
| 根因6 恢复覆盖面窄 | 步骤级 checkpoint + Error Workflow | 部分 skill 已有 checkpoint 但未对齐 | 🟡 部分 | `resume_flow.py`(daily-jinsha-core)、`lib/checkpoint.py`(daily-wechat-video) 存在 |

| 文档1 加固建议（★） | 目标 | 落地 | 判定 |
|---|---|---|---|
| ★常驻守护+请求 | 持有会话常驻 | 未覆盖 | ❌ |
| ★失败分类器+抖动预算 | 瞬态/永久分类+重试预算+冷却 | Phase 1 有雏形 | 🟡 |
| ★执行槽位串行化/机器独占 | 串行化（已有）/独占（无） | 🟡 |
| ★授权续期+到期告警 | 过期前告警/自动续 | 未覆盖 | ❌ |
| ★Preflight 硬门+短回路 | 不通过立即短路 | preflight 普遍有，硬门短回路未强化 | 🟡 |
| ★步骤级 checkpoint | 断点续跑 | 部分 skill 已有 | 🟡 |
| ★静默告警看板 | 上次成功时间+N小时无成功即报 | 仅有当日台账，无看门狗 | ❌ |
| ★保留安全门（不动） | EXTERNAL_EFFECT/ActionResult/逐字授权 | Phase 2 §1 明确"不动项"保护 | ✅ |

### 0.2 文档2《n8n 编排底座》—— 核心主张

| 文档2 主张 | 落地 | 判定 | 说明 |
|---|---|---|---|
| 停写 plan 补丁文档 | 已停（Phase 2 改架构改造，性质不同） | ✅ | 但新增了 Phase2/路线图等方案文档，属"真架构方案"非"病历补丁" |
| 推 n8n plan B 调度接管 | **不采用（已拍板）** | ✅(路线决议) | 用户 09-28 拍板：继续自研 skill_runner 到底，仅**抄 n8n 机制**（retry/error-workflow/keepalive 代码对照），不引入 n8n runtime |
| 失败分类 POST → Error Workflow 三分类 | 未做（Phase 1 仅本地 classify） | ❌ | 路线分歧点 |
| 浏览器常驻服务+中央任务队列 | 未做 | ❌ | 治根因1+3 真解 |
| 授权过期→Error Workflow 告警 | 未做 | ❌ | 同根因5 |

> **路线决议（2026-09-28 已拍板）**：用户确认**继续自研 skill_runner 到底**，不引入 n8n runtime；但实现过程中**可抄 n8n 代码机制**作为对照（已对照：retryOnFail/maxTries/waitBetweenTries 重试循环；Error Workflow 失败触发告警；KeepAlive 常驻）。详见 §6 P3-1B。

---

## 1. 架构图（分层：已实现 vs 诊断目标缺口）

下图把 Phase 1/2/3 与两份诊断的六类根因对齐。**实线框 = 已实现，❌/虚线框 = Phase 3 待做**（即诊断指出的"运行时钟固"主体目标，Phase 2 漏接）。

```
┌──────────────────────────────────────────────────────────────────┐
│ ① 外部触发层                                                       │
│    codex 定时 heartbeat  ──或待裁决──▶  n8n Schedule Trigger        │
│    （文档2 主张 n8n plan B 接管；当前走自研，属路线分歧）              │
└───────────────────────────────┬──────────────────────────────────┘
                                 │ 单次执行请求（非每小时冷启动全新进程）
┌───────────────────────────────┴──────────────────────────────────┐
│ ② 调度看护层  ★Phase 1 已实现（薄包裹层，零碰 skill 内部）           │
│    runtime/run_all.py  —— 一键启动 + 看护遍历 enabled skill          │
│    runtime/skill_runner.py                                       │
│      • 全局锁 .runner.lock（跨技能串行，治根因3·部分）               │
│      • classify_failure（recoverable/needs_login/unknown）         │
│      • 重试预算（连错3次 / 5min冷却，治根因2·雏形）                  │
│      • SIGALRM 每步看门狗 + run prune                              │
│    runtime/skills_manifest.json（14条目+台账模板）                  │
└───────────────────────────────┬──────────────────────────────────┘
                                 │ 调 14 skill（enabled 7）
┌───────────────────────────────┴──────────────────────────────────┐
│ ③ 执行器层  ★Phase 2 已做"代码卫生"（去脆弱）                      │
│    A 合并 fork 执行器 → runtime/executor_common/（待做）            │
│    B+C 解路径硬编码 + sha256 自锁（#6/#13，待做）                   │
│    D subprocess 超时（已做 ✅）  E 删漂移副本（待做）                │
│    ── 安全门（保留不动）──                                        │
│    EXTERNAL_EFFECT fail-closed / ActionResult 收据 / 逐字授权       │
│    防重账本(attempted/verified/unknown) / policy sha256 /          │
│    UNSEALED_ACCEPTANCE                                           │
└──────────────────────────────────────────────────────────────────┘

╔══════════════════════════════════════════════════════════════════╗
║ ④ 运行时加固层  ★Phase 3 进行中 —— 即诊断"主体目标"，Phase 2 漏接    ║
║  P3-1B launchd KeepAlive 常驻守护(持有会话/统一编排) ← 根因1（进行中）║
║  P3-2 caffeinate -ism 防睡               ← 根因4（✅ 已做）         ║
║  P3-3 auth_watch 授权续期+到期告警        ← 根因5（待做）            ║
║  P3-4 watchdog 静默告警(上次成功+N小时)   ← 文档1★（随 daemon 落地）  ║
║  P3-5 Preflight 硬门短回路               ← 文档1★（待做）          ║
║  P3-6 步骤级 checkpoint 对齐             ← 根因6（待做）            ║
╚══════════════════════════════════════════════════════════════════╝
```

> 读图要点：Phase 1/2 覆盖了 **②调度看护 + ③执行器代码卫生 + 安全门**；诊断最想要的**运行时钟固（④常驻/防睡/授权续期/静默看门狗/checkpoint）是缺口**，即 Phase 3。Phase 2 起草时从"14流程依赖清单"出发做代码卫生，漏接了诊断的运行时工程化主体目标。

## 2. 明确看漏清单（Phase 2 起草时漏掉的）

1. **根因1/4 会话保活与防睡**：Phase 2 从「14流程依赖清单」出发做代码卫生，**完全没接"常驻守护持有会话"和 `caffeinate` 防睡**——这正是诊断判定"最致命"的根因。
2. **根因5 授权续期告警**：诊断明确"几天一次过期对应时不时中断"，Phase 2 零涉及。
3. **文档1 ★静默告警看板**：Phase 1 只出了"当日台账"，没有"每技能上次成功时间 + N 小时无成功即报"的看门狗——诊断要的是"关注没成功而非又跑了一次"。
4. **文档1 ★Preflight 硬门短回路**：preflight 机制普遍存在于各 skill（grep 命中 14+ 处），但"不通过立即短路、不进发送流程"的强化未做。
5. **文档1 ★步骤级 checkpoint**：`resume_flow.py`/`checkpoint.py` 已存在于部分 skill，但 Phase 2 未评估"是否全量 skill 都有、是否真步骤级而非整 run 级"。
6. **文档2 n8n 路线**：被搁置，未向用户显式对齐。

---

## 2. Phase 3 运行时加固改造项（目标：落实诊断主体目标）

### P3-1 看护模型升级：会话常驻 / 防睡（治根因1、4，最高杠杆）

> **2026-09-28 拍板（P3-1B，根治）**：升级为 **launchd KeepAlive 常驻守护**。用户原话：「升级为 launchd KeepAlive 常驻守护（根治根因1），它常驻守护你也好看护跟进它们的进度，你来统一安排他们的执行」。n8n 路线不采用，但实现可抄 n8n 机制。

#### 抄 n8n 的机制对照（已核实 n8n 源码）

| n8n 机制 | n8n 实现位置 | 我们对应落地 |
|---|---|---|
| 重试循环 `retryOnFail`+`maxTries`+`waitBetweenTries` | `workflow-execute.ts:1799-1816, 2304-2349`（for 循环 + sleep 间隔 + 首轮不 sleep） | `skill_runner.run_skill`：`max_retries` + `cooldown_seconds`（同构：仅 RECOVERABLE 重试、首轮不冷却）✅ 已在 Phase 1 |
| Error Workflow（失败触发独立工作流告警） | n8n `errorWorkflow` 设置 + Error Trigger 节点 | daemon 把 `NEEDS_LOGIN`/`UNKNOWN` 写 `state/alerts.jsonl`（等价"失败触发告警流"），具备环境时经 wechat-messaging 发 AI 员工群 |
| 常驻执行 + `restart: unless-stopped` | n8n 容器 `restart: unless-stopped` / queue mode | `launchd KeepAlive=true` 崩溃自启（等价 restart:unless-stopped） |
| EXECUTIONS_DATA_PRUNE（执行数据清理） | n8n `EXECUTIONS_DATA_PRUNE` | `skill_runner.prune_history`（已做 ✅） |

#### P3-1B 设计（本次落地）

**1. 看护哲学升级**：从「一键启动看护跑完即退」→「launchd KeepAlive 常驻守护，会话常驻持有」。

**2. 形态**
- `runtime/run_all.py --daemon`：常驻循环。启动 `ensure_caffeinate()`（P3-2 已做）+ `fcntl` 全局锁 + heartbeat。
- `runtime/com.zhensi.waimai.careloop.plist`：launchd **LaunchAgent**（用户会话级，因需 USB 真机/桌面微信/浏览器 GUI）→ `RunAtLoad=true` + `KeepAlive=true`，崩溃自动重启（等价 n8n `restart: unless-stopped`）。
- **会话保活（治根因1）**：daemon 常驻持有环境（Mac 不睡、ADB server 不灭）；每轮 `preflight_warmup()` 主动 `adb connect`/校验微信/浏览器，避免冷启动重连。

**3. 统一编排（agent 掌握，用户授权"你来统一安排"）**
- manifest 每 skill 加三字段（我排定，用户可改）：
  - `order`：整数执行序号（原序线索：08:00 Top10 → 09:00 差评 → 09:40 品牌申诉 → 11:00 金鲨日报 → 13:00 淘宝下载 → 每小时增量/美团 → 每2h+20:40 闪购申诉；我据此排并保数据依赖：下载在日报前、增量/美团每小时、闪购每2h）。
  - `cadence_hours`：默认 24（日流程）；每小时类=1；闪购=2。
  - `earliest_hour`：窗口起点（保"昨日"数据正确，如 Top10=8、差评=9、金鲨=11、淘宝下载=13；每小时类=0）。
- daemon 每 `cycle_interval_seconds`（默认 1800s=30min）扫一遍：对每个 enabled skill，若 `earliest_hour<=当前小时` 且 `now - last_success >= cadence_hours` → 跑（含重试预算）；否则跳过（窗口内已成功）。
- **完成口径**：`state/last_success.json` 落"任意一轮成功=是"，与台账口径一致。

**4. 错误工作流（n8n Error Workflow 等价）**
- 每 skill 跑完，若 `category ∈ {NEEDS_LOGIN, UNKNOWN}` → 追加 `state/alerts.jsonl`（技能/时间/分类/日志路径）；具备真实环境时经 wechat-messaging 发 AI 员工群（与台账发送同门，受 `--send`/环境约束）。

**5. agent 看护接口（用户："常驻守护你也好看护跟进进度"）**
- `state/daemon.json`：pid / started_at / last_cycle_at / next_cycle_at / status / running_skill。
- `state/last_cycle.json`：每轮汇总（各 skill 状态/成功时间/本轮是否全绿）。
- `state/alerts.jsonl`：告警事件流（agent 跟进出错项）。
- `state/control.json`：`{"force_run":"<skill>"}` 让 daemon 下轮强制跑某技能（避免与全局锁冲突；`--once` 在 daemon 持锁时提示改用 control 文件）。
- 既有一键 `run_all.py --status` / `--once <name>` 仍可用（acquire 同锁）。

**6. 发送门（沿用）**：每轮写台账 xlsx；当日 active 全绿且未发过 → 发 AI 员工群（去重 `state/sent_today`）。

**7. 安全门零改动（铁律）**：daemon 只按 manifest 命令行包裹，不碰 skill 内部 EXTERNAL_EFFECT/ActionResult/逐字授权/防重账本。

- **测试前提**：本机 `launchctl bootstrap` 后跨天长跑；Mac 合盖/睡眠 30min 后 ADB 不掉；某 skill 故意失败验证 `alerts.jsonl` 写入与全绿发送去重。沙箱无法闭环，需用户真机验收。

### P3-2 `caffeinate` 防睡（治根因4，最低风险）
- **做法**：skill_runner 启动看护时执行 `subprocess.run(["caffeinate","-ism","-w",str(os.getpid())])` 子进程随看护存活防睡；或 P3-1B 在 launchd 层加 `caffeinate`。
- **测试前提**：Mac 睡眠 30min 后看护进程仍持有 ADB/微信会话。

### P3-3 授权续期 + 到期告警（治根因5）
- **做法**：新增 `runtime/auth_watch.py`，扫描 `executor-lock.json`(UNSEALED_ACCEPTANCE) 与 `runtime-policy.json`(expiresAt)，提前 N 小时（默认 24h）经 wechat-messaging 发 AI 员工群告警；能自动 reseal 的（参照 `plan-2026-09-17-noop-first-and-auto-reseal.md`）自动续，不能的提示人工盖章。
- **测试前提**：mock 一个将过期的 policy，确认告警触发；自动 reseal 路径用测试锁验证。

### P3-4 静默告警看门狗（治"堆积 146 run"，文档1 ★）
- **做法**：复用 Phase 1 history ledger，新增 `runtime/watchdog.py`：每技能读"上次成功时间"，N 小时（默认 24h）无成功即发 AI 员工群静默告警；关注"没成功"而非"又跑了一次"。
- **测试前提**：故意停某 skill 超过阈值，确认告警发出；正常时零噪声。

### P3-5 Preflight 硬门短回路（文档1 ★）
- **做法**：确认各 skill preflight 已是"硬门"（不通过立即短路返回，不进发送流程）；对未达标的补 `if not preflight(): return fail-closed`。复用已普遍存在的 `workflow_preflight.py` 等。
- **测试前提**：构造 preflight 失败场景，确认立即短路、无无效 run。

### P3-6 步骤级 checkpoint 对齐（根因6）
- **做法**：评估 `resume_flow.py`(daily-jinsha-core) / `lib/checkpoint.py`(daily-wechat-video) 的粒度（断在第 N 步续 vs 整 run 重跑）；缺步骤级回放的 skill 复用这两份真源，杜绝"掉一次线前功尽弃"。
- **测试前提**：人为中断某 skill 第 3 步，确认从第 3 步续而非重跑。

---

## 3. 执行顺序（已按拍板落地前两项）

```
P3-2（caffeinate，✅ 已落地）→ P3-1B（launchd 常驻+统一编排，✅ 本次落地，作为其余项的运行底座）
   → P3-4（静默看门狗：daemon alerts.jsonl 已落地，可再补"N小时无成功"主动巡检）
   → P3-3（授权续期+到期告警）→ P3-5（Preflight 硬门确认/强化）→ P3-6（checkpoint 步骤级对齐）
```

## 4. 测试纪律（用户铁律：改造须带测试）

- 每项：单元自测 + 一次真实跑通（需真机/微信登录态/Mac 睡眠实测）。
- 沙箱无法闭环；真机验收须用户本机跑 `python3 runtime/run_all.py --once <name>` 或真实触发。
- 每项独立验证无回归后再并下一项目。

## 5. 风险与待裁决（2026-09-28 两项已拍板闭环）

- [x] **n8n 路线分歧**：已决议——继续自研 skill_runner 到底，不引入 n8n runtime；仅抄 n8n 机制（retry/Error Workflow/KeepAlive），对照见 §6 表。
- [x] **P3-1 常驻看护**：已拍板升级为 launchd KeepAlive 常驻守护（P3-1B），本次已实现（run_all --daemon + com.zhensi.waimai.careloop.plist）。
- [!] P3-3 自动 reseal 涉及安全门（UNSEALED_ACCEPTANCE），须严格走封板，不可放宽 fail-closed。
- [!] P3-2/3/4 新增的告警发送须经 wechat-messaging 既有通道，复用不改其安全门。
- [!] **真机验收**：daemon 跨天/合盖场景需用户本机 `launchctl bootstrap` 后实测；沙箱仅验证调度层纯逻辑（已 ALL PASS）。
