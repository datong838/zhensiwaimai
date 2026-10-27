# A2 方案：`attempted` 死结的检测与根治（封印面）

> 2026-10-06 · 监理（WorkBuddy）· 状态：**A2a 已落地 / A2b-② 已落地（大同 10-06 裁决）/ A2b-① 不做**

## 1. 问题

桥（`skills/wechat-messaging/scripts/workflow_bridge.py`）对**已存在的 marker** 只有四条出口：

| marker 状态 | 桥的行为 | 是否安全 |
|---|---|---|
| `verified` | 复用，直接返回 verified | ✅ |
| `blocked` 且 `sendAttempts == 0` | 认可"没开始发"，允许重来 | ✅ |
| 其余（**含 `attempted` 且无收据**） | `existing-attempt-reconcile-only`，**绝不重发** | ⚠ 安全但不前进 |
| 无 marker | 正常发送 | ✅ |

**死结**：上一轮"进程已发出指令、但收据丢失"（中继 8s 静默丢响应事故即此类）⇒ marker 停在
`state=attempted`、`sendAttempts=null`。桥为防重复外发**拒绝重发**（正确），
但**也无法确认是否已送达** ⇒ 该 marker 永久卡住，下游游标不推进，**后续条目全被挡住**。

**实证**：2026-10-06 旨寿司 `1332142200` 卡死，用**方案 A（人工受控结论化：把 marker 改写为
`verified`）** 解开，14:57 自愈第 1 步 + 16:01 第 2 步双双验证通过。

## 2. 现状盘点（2026-10-06 16:4x 实测）

* 全仓扫描 `state/`、`.local/state/` 下 `*attempts*` 目录：`state=attempted` 且
  `sendAttempts in (None, 0)` 的**仅 1 个**：
  `.local/state/jinsha-report-send-feibing-neo-ai.desktop-attempts/83a4804a….unknown-evidence-20260910-2219.json`
  （2026-09-10 的陈旧证据旁文件，非现役阻塞）。
* ⇒ **当前不是现役故障，是潜在风险**（一旦中继再丢响应就会复发）。
* 可用原语：`windows_adapter.reconcile(request, item, work, prior)` = 「只读 reconcile；把留存的
  传输收据与**实时读回**绑定」，以及 `_verify_sent()` 的「末条消息锚点读回」。

## 3. 两个实现变体

### A2b-① 在桥内自动复核（**❌ 不做 · 大同 2026-10-06 裁决选 ②**）

桥在遇到 `attempted` 无收据时，主动做一次实时读回，据结果自动判 verified / 允许重发。

* **硬阻断**：`workflow_bridge.py` 是封印件；`daily-agent-new-merchants-to-wechat/executor-lock.json`
  （status=**SEALED**）单独钉了 `messaging_bridge` 摘要 ⇒ 改桥立刻
  `executor-lock-digest-mismatch:messaging_bridge`，而该锁**当前无合法重签通道**
  （`refresh-unsealed-acceptance` 只认 `UNLOCKED/UNSEALED_ACCEPTANCE`）。
* 即：**改桥 = 每小时新商家流下一档必失败**，须大同先授权扩门禁（新增一条再封印授权语义，
  有 2026-10-05 先例但属**新增授权**）。
* 收益/代价：收益=自动前进；代价=动公共桥 + 连锁 3 个消费者 + 扩门禁 + 全量重绑。
  **在"当前死结数≈0"的前提下，性价比不成立。**

### A2b-② 桥外独立工具（**✅ 已落地 · 大同 2026-10-06 裁决**）

新增**未被封印**的独立工具（`runtime/` 下，零封印影响）：扫出死结 → 用适配器做**只读读回**取证
（末条锚点是否命中本载荷）→ 产出证据文件 → **仅在 `--apply` + 明确授权串**下把 marker 结论化为
`verified`（等价方案 A，但证据由机器采集）。

* 复用 `windows_adapter` 的判据原语（`_read_messages/_anchor_newness/_title_compatible`）；
  **不碰封印件**，不动公共桥，不影响任何消费者。
* 默认 `dry-run`；结论化需 `--authorize <每例唯一串>`（与方案 A 同级的人工闸门）。
* 失败开放=否：读不到证据 ⇒ 只报告，绝不改 marker。

**实现**：`runtime/conclude_attempt_deadlock.py`

| 命令 | 作用 |
|---|---|
| `--scan`（默认） | 扫全部死结 → 逐个只读读回 → 打印 `readback` 结论 + 逐例 `--apply` 命令 |
| `--marker <path>` | 单例 dry-run 取证（不写任何文件） |
| `--marker <path> --apply --authorize <token>` | **受控结论化**（备份 + 登记 + 审计 + 写后回读校验） |
| `--selftest` | hermetic 24 例（读回正负对照 / 真闸门正负对照 / 闸门与授权拒绝 / 端到端） |

**安全设计**：取桥同一把 `.bridge.lock`（防并发）→ 取锁后**重读**确认 marker 未被改写 →
备份 → 原子替换 → **写后回读校验**（`verified/state` 到位且 `payloads` 逐字节不变，否则回滚）。
落盘形状与人工方案 A **逐字段一致**（`commonReceipt.items[0].verificationLevel=
windows-readback-text-anchor` + `evidence` + `sendAttempts=1` + `merchantId`/`messageSha256`），
已用 `runtime_contract.verify_delivery` **真闸门**做正负对照验证（抽掉 `anchorInTrailingPosition`
或把 `sendAttempts` 改回 null ⇒ 闸门必须拒绝）。

**★ 驱动契约所限（必须知道）**：`client.py` **没有「只打开会话不发送」的 action** ⇒ 读回只在目标群
**恰是 Windows 微信当前会话**时成立。这恰是死结事故的现场状态（进程死在「已发出」之后，Windows 侧
会话仍停在目标群）。标题不符时只做**有界轮询**（12s 等驱动落定），**绝不为了取证去打开会话**；
超时即如实报 `windows-current-session-title-mismatch`，并提示人工在 Windows 微信切到目标群后重跑。

**验收证据（2026-10-06）**：`--selftest` 24/24 ALL PASS；生产 `--scan` **CLEAN**（适配器直连可用）；
**真实闭环**（测试群 `FEIBING NEO AI数字员工` + 临时台账）：只读读回通过 → `--apply` → marker 变
`verified` → 过 `runtime_contract.verify_delivery` → 备份/登记/证据旁文件三件齐 → **生产台账零写入**；
**负例对照**：目标群≠当前会话 ⇒ 如实拒绝且零写入。

## 4. 本波已落地（A2a · 零风险）

`runtime/scan_attempt_deadlocks.py`：**只读**死结体检器。

* 扫 `state/`、`.local/state/` 下 `*attempts*` 目录，识别
  `state=attempted` 且 `sendAttempts in (None, 0)`；
* **排除证据旁文件**（文件名含 `unknown-evidence` / `-evidence-` 等），避免误报；
* 输出死结清单（路径 / 群 / 龄期）+ 推荐动作（含方案 A 的命令模板）；
* 带 `--selftest`（正负对照：真死结 / verified 不算 / blocked-zero 不算 / 证据旁文件不算）；
* 接入看护自动化，**1 小时内即可发现新死结**，不再"靠人撞见"。

## 5. 裁决结果与操作手册（2026-10-06 大同裁决）

| # | 事项 | 裁决 | 状态 |
|---|---|---|---|
| **A2b-②** | 桥外独立工具（读回取证 + 授权结论化） | **同意，选 ②** | ✅ 已落地并验收 |
| **A2b-①** | 扩门禁以允许改公共桥 | **不做** | ❌ 不实施（改桥会炸 #6 每小时流） |

### 5.1 死结复发时的处置流程（照此执行，别自由发挥）

```bash
cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back

# ① 发现（看护 G 段每小时也会跑）
PY=/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python
env -u PYTHONPATH $PY runtime/scan_attempt_deadlocks.py
#    期望末行 `attempt-deadlock-scan: CLEAN`；FOUND n ⇒ 进入 ②

# ② 只读取证（会打印 readback 结论 + 逐例唯一授权串 + --apply 命令）
env -u PYTHONPATH $PY runtime/conclude_attempt_deadlock.py --scan

# ③ 受控结论化（**逐例唯一授权串**，直接把 ② 打印的 command 粘回来）
env -u PYTHONPATH $PY runtime/conclude_attempt_deadlock.py \
    --marker <marker 路径> --authorize conclude:<12hex> --merchant-id <商家号>

# ④ 复核
env -u PYTHONPATH $PY runtime/scan_attempt_deadlocks.py        # 应回 CLEAN
```

**铁律**：`readback` 不是 ok 就**不要**加 `--apply`；`--authorize` 串**每例唯一**（换 marker/换载荷都会变），
不可跨案例复用；**不要**为了取证去手工打开会话、**不要**重发、**不要**删 marker。

### 5.2 何时会失败（预期内，不是 bug）

* `windows-current-session-title-mismatch`：目标群不是 Windows 微信**当前会话**。驱动契约没有
  「只打开会话不发送」的 action，本工具**不代开会话**。→ 请人工在 Windows 微信切到该群后重跑 ②③。
* `windows-readback-anchor-not-trailing`：载荷不在会话尾部（可能已被后来的消息顶下去，或根本没发出）。
  → **只报告**，交人判断；绝不因此放行。
