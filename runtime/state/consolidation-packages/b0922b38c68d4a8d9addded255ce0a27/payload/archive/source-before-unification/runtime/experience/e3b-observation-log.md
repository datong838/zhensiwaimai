# E3b 认知层白名单 · 观察周记录（2026-10-06 → 2026-10-13）

> 大同 2026-10-06 17:4x 裁决：「先开 2 条最稳的，跑一周看效果再扩，其余 7 条记录好日志观察」。
> 本文件是**观察周的唯一权威记录**；一周后大同会忘，复盘由自动化提醒（一次性）触发。

## 1. 已启用（首批 2 条，2026-10-06 生效）

| 码 | 动作 | 白名单 | 理由 |
|---|---|---|---|
| `windows-driver-unreachable`（含 `windows-wechat:` 前缀变体） | **自动重试** | `autoRetryAllowlist` | Windows agent 冷启动 503 实测「重试 1–2 次即成」；升格 RECOVERABLE 后复用既有 `max_retries(2)+cooldown(300s)` 护栏，不新增风暴面 |
| `lock` | **自动静音** | `autoSilenceAllowlist` | 互斥占用天然下一轮自愈；不进 `alerts.jsonl`/聚合/看护屏，只落独立审计流 |

**机制落点**（2026-10-06 实现，daemon 重启后生效）：
- 重试臂：`receipt.py::classify_receipt` 对 `retry_allowed` 的 **UNKNOWN** 码升 RECOVERABLE（detail 带 `[policy-retry]` 标记）；绝不覆盖 NEEDS_LOGIN/幂等决策；`never-silence` 档在 `code_policy` 内恒不放行。
- 静音臂：`run_all.py::append_alert` 对 `silence_allowed` 的码不进告警主链路，只写 `runtime/state/alerts_suppressed.jsonl`（append-only 审计）；无码/判定异常 ⇒ 照常告警（fail-closed）。

## 2. 复盘时看什么（2026-10-13，一次性自动化会自动跑）

1. `runtime/state/alerts_suppressed.jsonl`：静音触发了几次、集中在哪个流——**若同一流连发 ≥3 次/日，说明「自愈」假设在退化，收回静音**。
2. `runtime/run_history/` 当周 record：grep `[policy-retry]` —— 重试臂命中几次、二次尝试是否 SUCCESS；**若重试后仍败的比例 > 50%，说明该码不是瞬态，收回重试**。
3. 有无「本该响却没响」的事故（静音掩蔽）——一条都不许有。
4. 全部干净 ⇒ 大同点头后再从 §3 候选里逐条扩。

## 3. 其余 7 条候选（观察中，未启用，禁批量）

| 码 | tier | 潜在动作 | 观察关注点 |
|---|---|---|---|
| `collection` | auto-retry-candidate | 重试 | 是竞态还是站点改版？改版时重试会浪费且掩蔽 |
| `workbench-entry-page-missing` | auto-retry-candidate | 重试 | 复位臂（post_page_reset）已在管，可能不需要重试 |
| `send-button-not-enabled` | auto-retry-candidate | 重试 | 连续出现=站点改版信号，静音危险 |
| `desktop_wechat_preflight` | auto-retry-candidate | 重试 | 前台窗口态，看复位是否已消化 |
| `windows-wechat-not-ready` | auto-retry-candidate | 重试 | 与 unreachable 同族，若本周效果好可下批一起裁 |
| `windows-driver-local-network-blocked`（含前缀变体） | auto-retry-candidate | 重试 | launchd 上下文必然被拦，重试无用（须中继），**大概率永不启用** |
| （`lock` 已启用，故候选剩 6 条 + 上述共 7 条原始候选） | | | |

## 4. 回滚

- 数据层：从 `known_codes.json` 对应数组删码（或 `rm runtime/experience/known_codes.json` 整体退回内置默认）。
- 代码层：重试臂只认白名单，名单空即失效，无需改代码。

## 5. 大同的原问（记录在案）：「观察 1 周效果好，能代替以后也效果好吗？」

**不能划等号**。一周观察验证的是「当前环境条件下」这两个码的行为稳定（网关 IP/Windows 重启节奏/站点 UI/驱动版本都不变的前提下）。环境变了，码的语义可能变——所以有四道补强：① `never-silence` 档永不放行（机制焊死）；② 静音只落审计流、随时可数；③ 重试复用既有预算+cooldown，不会风暴；④ 观察周复盘不是一次性验收，而是建立「每周可重看」的模式——复盘自动化模板可复用。详见当日监理回复。
