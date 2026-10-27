# 2026-10-22 15:53 两条积压流分工（大同裁定：都行动起来）

> **16:08 更新：两条均已由监理会话（98ed37a2）接手处理完毕，本分工单转为交接记录。**
> - ① basic-diag：已于 16:03 补发并 verified（sendAttempts=1，windows-readback-file-card）。**任何人不要再重发**。
> - ② new-merchants：封印已按 `user-20261022-cursor-watermark` 重绑（SEALED / 19 文件 / verify ok）。
>   若你（13b76155）回来继续改这 4 个执行器，**改完必须再跑一次 refresh-unsealed-acceptance 重绑**，
>   否则门禁会再次 `executor-lock-digest-mismatch` 全流堵死。当前补跑已排队（control.json force_run）。

## 我（会话 98ed37a2，15:00 档监理中接办）
**负责：`daily-store-basic-diagnosis-to-wechat`（cf=9，11:55 起死锁）**

- 根因：11:54:36 那轮 `exit=-15`(SIGTERM, 71s) 死在发送段 → marker 写成 `state=attempted / sendAttempts=null`；
  `runs/2026-10-22-1792641276937021000/windows-send/` 空目录无回执；此后每轮重产 xlsx（sha 变）
  → `same-event-payload-conflict` 硬闸，9 轮全卡。
- 出口：先只读取证 11:55 那张 `2026-10-22基础诊断-运营问题分析.xlsx` 是否入群
  → 在群：结论化 verified（不重发）；不在群：双层 void + force_run 单次补发。
- 不触碰：new-merchants 的任何脚本/封印文件。

## 他（会话 13b76155，15:25–15:27 在改执行器的那位）
**负责：`daily-agent-new-merchants-to-wechat`（cf=1，封印漂移 escalate）**

- 你 15:25–15:27 改过：`background_merchant_collector.mjs`、`structured_merchant_collector.py`、
  `test_background_merchant_collector.mjs`、`maintenance_executor.py`（含 15:22 那轮的 `same-day-cursor-not-unique` 修复）。
- 现状：`seal_drift_repair --flow daily-agent-new-merchants-to-wechat` dry-run 返回
  `state=escalate`，理由「含白名单外文件」：background_collector / background_selftest /
  maintenance_executor / structured_collector —— 正是你这 4 个文件。
- **你要做**（你是改动方，只有你知道最终版该是什么）：
  1. 把 4 个执行器改到最终态、跑通自测；
  2. 重绑封印摘要（`dependencies.json` + executor-lock），务必与已装副本同步；
  3. 重跑 `seal_drift_repair --flow … --apply` 或等 daemon 下周期 `force_run` 补跑；
  4. **不要**在没有重绑的情形下让流空转 —— 每轮都会只回 `executor-lock-digest-mismatch`，白跑。
- 不要触碰：basic-diag 的 events/marker 与 xlsx。

## 互不越界
- 我已在 15:51 复核：你自 15:27 后无新写入（24 分钟静默），故我此刻只动 basic-diag。
- 你若恢复动手改脚本，请在本文件追加一行说明，避免我们同时改同一棵树。
