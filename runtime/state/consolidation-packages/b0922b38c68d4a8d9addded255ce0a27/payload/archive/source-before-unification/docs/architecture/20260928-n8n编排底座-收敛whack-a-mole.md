# 收敛 whack-a-mole：用 n8n 编排底座替掉自研心跳/恢复逻辑

> 对象：`zhensi_waimai` 任务流稳定性
> 边界：**本轮只读分析，未修改任何代码**。新增文档仅作决策依据。
> 衔接：`docs/产品探索/n8n/n8n深度解析-复杂工作流改进.md`（已结论 A 做了 / B·C·D 待做）、`docs/产品探索/n8n/聊天资料.md`（外部专家同频建议）、`docs/20260928-任务流稳定性诊断与加固分析.md`（前一份根因诊断）。

---

## 0. 一句话结论

那些 `plan-2026-09-*` / `*-维护方案.md` / `heartbeat_recovery.py` **不是方案，是病历**——每篇都是「某次 run 出现某个瞬态故障，加一个最小补丁处理它」，根架构一次没动。正确做法是**停下来别再写补丁文档**，把 n8n 从「方案 A 纯观测」推进到「方案 B 调度+失败接管」，用它的原生重试/队列/错误工作流/观测**一次性替代**这套手搓的 heartbeat/recovery。

---

## 1. 病历证据：逐症状打补丁的反模式

| 文档（路径节选） | 日期 | 它"补"的瞬态症状 |
|---|---|---|
| `daily-agent-new-merchants/references/plan-2026-09-04-stability-loop.md` | 09-04 | 首个稳定性循环补丁 |
| `daily-top10/references/plan-2026-09-04-executor-stability.md` | 09-04 | 执行器稳定性 |
| `daily-top10/references/plan-2026-09-09-background-browser-migration.md` | 09-09 | 后台浏览器迁移 |
| `daily-jinsha/references/20260908-动态定位与断点恢复维护方案.md` | 09-08 | 动态定位 + 断点恢复 |
| `daily-jinsha/references/20260910-金鲨后台浏览器优先方案.md` | 09-10 | 后台浏览器优先 |
| `daily-agent-new-merchants/references/plan-2026-09-10-background-dedicated-chrome.md` | 09-10 | 专用 Chrome |
| `daily-jinsha/references/20260919-background-process-pid维护方案.md` | 09-19 | 状态 PID 陈旧（41925 已退出）误报 `jinsha-background-process-not-alive` 阻断 |
| `daily-agent-new-merchants/references/plan-2026-09-19-undersized-main-window-recovery.md` | 09-19 | 主窗口过小恢复 |
| `daily-agent-new-merchants/references/plan-2026-09-20-bounded-wechat-contention.md` | 09-20 | 有界微信争用 |
| `daily-jinsha/references/20260920-heartbeat维护方案.md` | 09-20→09-24 | OCR 唯一行点击未稳定切换、30s 导航超时三次重开临时页、窗口释放但结构未加载、专用实例 TAKEVER 但窗口未释放（含 09-21 交接 / 09-24 导航超时补丁） |
| `wechat-messaging/references/recovery.md` + `heartbeat_recovery.py` | 持续 | 瞬态（焦点/搜索区/零标题）每 2s 观察；截图硬失败不换方式；attempted 后全 unknown；环境故障只重启应用不换通道 |

**共同特征（来自实读三篇）**：每篇开头都是「run Y 出现瞬态故障 Z（陈旧 PID / 窗口尺寸 / 导航超时 / OCR 噪声前缀 / 窗口未释放 / 授权窗口过期），加最小补丁处理 Z，不得放宽门禁」。
**根架构零改变**： hourly 外部 cron 仍派生全新进程 → 每次重连 ADB/微信/浏览器 → 瞬态抖动被 fail-closed → 人读 plan 文档 → `--resume` 人工复跑。

这就是前诊断里的根因 1（会话冷启动）+ 根因 2（抖动当失败→无限续跑）的**换皮重现**。每加一篇 plan 文档，只是把同一类根因换个外壳又来一次。

---

## 2. 根因没变，只是换了马甲（呼应前诊断 6 类）

| 前诊断根因 | 病历里的对应表现 |
|---|---|
| ① 会话冷启动 | 每 hour 派生新进程重连微信/Chrome；`TAKEOVER_VERIFIED` 但窗口未释放、`WINDOW_RELEASED` 但结构未加载 |
| ② 抖动当失败→thrashing | `preflight` 跑满 60s 超时、`contentionRetries=63` 等锁 5 分钟、导航超时才重开临时页 |
| ③ 资源争用 | 9231/9232 专用 Chrome 被多工作流抢；`bounded-wechat-contention` 补丁本身就是证据 |
| ④ 睡眠/掉线级联 | Mac 睡眠掐断 ADB/微信会话，无超时调用挂起后级联 |
| ⑤ 授权过期单点 | `runtime-policy.json.expiresAt` + `UNSEALED_ACCEPTANCE` 过期→整链 fail-closed，需人工续章（几天一次） |
| ⑥ 恢复覆盖面窄 | `heartbeat_recovery.py` 只认代码类失败，环境故障不真修复只甩人工 |

---

## 3. n8n 已经在场，且原生就有你要的"加固"

`n8n深度解析` 已定论：**A（纯观测）09-20 已落地，B（调度接管）/C（契约升级）待做，D（执行迁移）永不**。
**关键事实**：`docker ps` 实测 **`n8n-obs` 当前未运行**（restart=unless-stopped 但此刻不在）——连已落地的方案 A 观测都因"缺乏常驻纪律"而休眠。这恰好反证「常驻编排层」的必要性。

逐根因对照——**前诊断手搓的建议，n8n 原生就有等价品，且零代码**：

| 根因 | 前诊断手搓建议 | n8n 原生等价（源码实证） | 谁更省 |
|---|---|---|---|
| ① 冷启动 | launchd KeepAlive 常驻守护持有会话 | n8n 常驻 main 进程 + `EXECUTIONS_MODE=queue`；浏览器升为**常驻 worker 服务 + 中央任务队列**（聊天资料「中央浏览器任务队列」） | n8n：调度常驻 + 观测 UI 白送 |
| ② 抖动当失败 | 失败分类器 + 抖动预算（连错 3 次/5min 不再派生新 run） | 节点 `retryOnFail` + `maxTries`(默认3) + `waitBetweenTries`；`onError=continueErrorOutput` 红色分支 = 我们的 `recoverable/needs_login` | **n8n 不用写一行 Python** |
| ③ 争用 | 槽位串行化 / 机器独占 | `EXECUTIONS_MODE=queue` + 单浏览器 worker 消费中央任务表（聊天资料） | n8n：自带队列，免自研锁 |
| ④ 掉线级联 | 守护进程不随 Mac 睡 | n8n 跑 Docker `restart=unless-stopped`，main 进程常驻，调度不受单次 cron 派生影响 | n8n：容器级自愈 |
| ⑤ 授权过期 | 到期前告警 + 自动续期 | `Credentials` 集中加密管理 + 一个 preflight 检测过期→`Error Workflow` 告警（**不静默 fail-closed**） | 各擅：授权票据语义仍在 executor，n8n 只管"过期即告警" |
| ⑥ 恢复窄 | 步骤级 checkpoint | `Error Workflow` 真实处理路径（告警+路由+可选自动修复）；`Wait`/`$execution.resumeUrl` 断点续跑 | n8n：错误是一等公民 |

> 外部验证：`聊天资料.md` 专家原话——「n8n 不建议当浏览器执行器用，正确姿势是 n8n 编排 + 独立浏览器/反检测层 + 视觉模型 + 企微分发」「调度、分支、重试、入库、通知、人工兜底交给 n8n」。与本项目结论完全一致。

---

## 4. 收敛路线图：停什么 / 推什么 / 守什么

### ⛔ 停（立即）
- **不再为单个瞬态故障写 `plan-*` / `*-维护方案.md` 补丁文档**。冷启动/抖动/争用类根因一律归入「上 n8n plan B」解决，不再新开病历。
- 瞬态失败默认走 n8n 重试 + Error Workflow，**不再**「人读 plan → `--resume` 人工复跑」。

### 🚀 推（按杠杆）
1. **固化 n8n-obs 常驻**：先确认 Docker 在跑（它现在没起），把它纳入开机/看护自启；补**成功+失败告警通道**（企微机器人，限流 20 条/分，汇总发送）。
2. **plan B 调度接管（试点）**：挑 `daily-top10-to-wechat-group`（最简单）由 n8n `Schedule Trigger` → `ExecuteCommand` 调执行器唯一入口；失败走 `Error Workflow`。执行器零改动。
3. **失败分类落地**：executor `fail()` 时 POST 标准 payload（`workflow-id/businessDate/phase/reason/needsLogin`）→ Error Workflow 三分类（needs_login @人 / recoverable 静默 n8n 自动重试 / unknown 升级）。**recoverable 类纯环境故障由 n8n `retryOnFail` 自动重试，直接进人工的只有 needs_login / unknown**。
4. **浏览器常驻化**（治 ①+③ 真解）：把 9231/9232 专用 Chrome 从「每 run 派生」改为**常驻服务 + 任务队列**，n8n 只产任务、worker 消费。直接消掉冷启动与争用。
5. **plan C 契约升级**（独立立项）：`wechat-messaging` request/authorization JSON Schema 化，新工作流接入从「读三份文档」变「看一份 schema」，走封板流程。

### 🛡 守（铁律，一行不改）
- 执行器的**安全门全部保留在 executor 层，绝不进 n8n**：
  - 防重账本（attempted/verified/unknown 不可重发）
  - `EXTERNAL_EFFECT` fail-closed
  - 逐字授权确认文本
  - `ActionResult` 收据 + 双帧截图 + 原生复制回读
- n8n 的 `retryOnFail` **只重试环境/瞬态失败，绝不重试 `attempted/unknown`**（幂等门在 executor，n8n 碰不到）。
- **永不 plan D**（推倒重来迁移执行器）——那是 tare 式错误，且会丢失防重账本这一 n8n 没有的强项。

---

## 5. 下一步清单（供登记，本次不执行）

- [ ] 确认 Docker 守护在跑，重启 `n8n-obs` 并固化常驻（launchd/Docker 开机自启 or 纳入现有看护）
- [ ] 加企微「运维告警群」机器人节点 + needs_login/recoverable/unknown 三分类模板
- [ ] plan B 试点：daily-top10-to-wechat-group 由 n8n 调度接管（ExecuteCommand 调唯一入口）
- [ ] executor `fail()` 增加 POST 标准告警 payload（接 Error Workflow）
- [ ] 评估浏览器常驻服务 + 中央任务队列（治冷启动+争用，最高杠杆之一）
- [ ] plan C：wechat-messaging request/authorization JSON Schema 化（走封板）

---

## 6. 验证深度声明

- ✅ 实读病历文档 3 篇（09-19 PID / 09-20 heartbeat / wechat-messaging recovery）+ 文件名枚举 12+ 篇 plan/维护文档
- ✅ 实读 n8n 资料：`n8n深度解析-复杂工作流改进.md`、`n8n使用说明.md`（含方案 A 实测）、`聊天资料.md`、`ops-observer/` 三件套
- ✅ 实查 `docker ps --filter name=n8n-obs`：当前无运行容器（方案 A 实例休眠）
- ✅ 未修改任何 `zhensi_waimai` / `n8n` 代码与配置，仅新增本分析文档
