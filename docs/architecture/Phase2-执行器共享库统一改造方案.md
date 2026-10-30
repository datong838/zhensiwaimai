# Phase 2 · 执行器/共享库统一改造方案（先方案再编码）

> ⚠️ **历史快照状态头（2026-10-18 加，大同授权）**：本文为 dated 方案，**设计与结论保留有效**；文中「14 流程」为 2026-09-28 当日真实口径，**不作现状**——现役 **20 条 enabled 值班流**（skills 共 23 = 20 + 2 blocked + 1 共享库），权威口径见 `runtime/skills_manifest.json`。

> 工作目录：`zhensi_waimai_back/`（原 `zhensi_waimai` 已废弃）
> 本文是 Phase 2 的**改造方案**，落地前需用户 approve；每项改造须带测试（单元 + 一次真实跑通）后才并入主线。
> 前置：Phase 1 调度层已完成（`runtime/`），本阶段才动 skill 内部执行器/共享库。
> **2026-09-28 更新 · B+C 已决议跳过**：实读 `entrypoint.mjs` + `sha256sum` 验证确认 `.codex` 软链/注册桩为刻意安全架构且健康，去自锁会削弱生产安全门（违背 P3-3「安全门零改动」铁律）；详见路线图 §3。A/E/#6/#9 仍按原计划推进。

---

## 0. 前置关键发现（2026-09-28 核实，影响 B/C 范围）

读 `skills/daily-taobao-download-to-jinsha/scripts/entrypoint.mjs:1–14` 发现：

1. **硬编码不止 `.codex`，还有原目录**：`SOURCE`(行5)/`CANONICAL_ENTRYPOINT`(行6)/`CANONICAL_SKILL`(行8)/`WECHAT_SOURCE`(行11)/`RECOVERY_SOURCE`(行13) 全部指向 **`zhensi_waimai_back/...`**（原目录，非 `_back`）。即复制到 `_back` 后这些路径仍读已废弃的原目录——语义错误。
2. **sha256 自锁强约束**：`EXECUTOR_SHA256`(行10)/`WECHAT_SHA256`(行12)/`RECOVERY_SHA256`(行14) 是文件内容哈希；`executor()`/`wechatSender()`/`evidenceRecovery()`(行75–94) 读文件算哈希比对，不符即抛 `*-code-drift`。**任何改动 #6 文件都会触发自锁失败**，须同步更新哈希或解自锁。
3. `INSTALLED_*`(行7/9) 指向 `.codex/skills/...`，`preflight()`(行114–127) 校验 `canonical == installed` 哈希一致；codex 已非触发器，该基准需重定（保留校验语义但基准随仓库走，或移除）。

**推论**：
- B 项扩展为「全仓硬编码路径（`.codex/skills/...` **与** `zhensi_waimai/...` 原目录）→ `zhensi_waimai_back/` 或相对/canonical」。
- C 项（解 #6 自锁）与 B **强联动**：改路径必改哈希，故 B+C 合并为同一改动批次，不可拆分。

---

## 1. 改造总目标

去脆弱（fork 多份 → 单一真源）+ 补超时 + 解路径硬编码 + 修漂移副本 + 适配 #6/#9，使 14 流程在 `_back` 上稳定、可统一看护。

**不动项（保护）**：`mobile_runtime/`、`skills/.daily-jinsha-reports-core/`（封板）、各 skill 安全门（`EXTERNAL_EFFECT fail-closed` / 防重账本 / 逐字授权 / `ActionResult` 收据 / `policy sha256 fail-closed` / `UNSEALED_ACCEPTANCE`）。

---

## 2. 改造项（含具体文件:行证据）

### A. 合并 fork 执行器为单一真源（风险中）
- **范围**（来自 `流程执行器依赖与共享库清单.md` §2.4，2026-10-18 改名；原引 `14流程执行器依赖与共享库清单.md`）：`workflow_executor` / `runtime_contract` / `executor_integrity` / `runtime_guard` 在 `daily-agent-new-merchants-to-wechat`、`daily-top10-to-wechat-group`、`maintenance/merchant-20260916-production-guard/candidate/scripts/` 等多处各存独立一份（无单一真源）。
- **做法**：抽到 `runtime/executor_common/`（注意：与 Phase 1 `skill_runner` 调度层区分——这是执行器共享逻辑，非调度）。各 skill 改为 `import` 该共享模块；删除本地副本。
- **测试前提**：每个受影响的 skill 跑一次真实流程，输出与改动前逐字节一致（用 `ActionResult` 收据比对）。
- **回退**：单文件独立 commit，失败即 revert。

### B + C. 解路径硬编码 + sha256 自锁（合并批次，风险中）
- **B 路径硬编码**：
  - `#6 entrypoint.mjs` 行5/6/8/9/11/13：`zhensi_waimai` → `zhensi_waimai_back`；行7/9 `INSTALLED_*` 的 `.codex` 基准 → 重定为 `_back` 对应路径（或移除该基准校验，改由 git/文件权限保证完整性）。
  - `#13 deliver_batch.mjs:8`：`.codex/skills/wechat-messaging/scripts/workflow_bridge.py` → canonical `skills/wechat-messaging/scripts/workflow_bridge.py`（与 #10 meituan-waimai 的 canonical 写法对齐）。
  - 全仓扫：Grep 全 `skills/` + `maintenance/` 的 `.codex` 与 `zhensi_waimai` 字面量，逐一改。
- **C sha256 自锁**（与 B 同批）：
  - 现状：行73–93 哈希比对 + `import(file://...?sha256=...)`。
  - 改造（二选一，建议 C2）：
    - **C1** 保留自锁：启动期计算 `_back` 下 canonical 文件哈希作基准，仍 drift 检测但基准随仓库走（需同步更新行10–14 哈希字面量）。
    - **C2** 移除自锁：依赖外部完整性（git 状态 + 文件权限 + 调度层已有的防重账本），去掉 `?sha256=` 动态 import，直接 `import(SOURCE)`。更稳、易维护，且调度层 `skill_runner` 已有看门狗兜底。
  - **测试前提**：改动后 #6 真实跑通（`runScheduled` 无参，行350–351）；且故意篡改 `background_browser_executor.mjs` 能被 C1 检测（或 C2 下由 git/CI 检测）。

### D. 补 subprocess timeout（风险低）
- **位置**（来自依赖清单 §五 D）：
  - `skills/wechat-messaging/scripts/dependency_maintenance.py:201`（`subprocess.run` 无 timeout）
  - `skills/wechat-messaging/scripts/business_desktop_wechat_file_sender.py:91`
  - `skills/daily-negative-reviews/scripts/maintenance_executor.py:283`
  - `skills/daily-wechat-video-publish/scripts/workflow_executor.py:315`
  - 多处 `osascript` / `screencapture` 调用
- **做法**：加 `timeout=`（复用各 skill 已有的 `deadline()` SIGALRM 模式或 `subprocess(timeout=)`），与 Phase 1 `skill_runner` 每步看门狗互补（内部超时优先，外层看门狗兜底）。
- **测试前提**：真实调用不超时；或超时能被看门狗接住并分类为 `RECOVERABLE`。

### E. 删 maintenance/candidate 漂移副本（风险低）
- **范围**：`maintenance/merchant-20260916-production-guard/candidate/scripts/` 中与 `daily-agent-new-merchants-to-wechat/scripts/` 重复的 6 文件（`workflow_executor.py`/`runtime_contract.py`/`executor_integrity.py`/`desktop_wechat_sender.py`/`structured_merchant_collector.py`/`background_merchant_collector.mjs`）。
- **做法**：确认 `daily-agent` 为唯一真源且 staging 不再引用副本后删除。
- **测试前提**：`daily-agent` 真实跑通；staging 流水线不报缺文件。

### 适配 #6（node -e 包 runScheduled，依赖 B+C）
- manifest 已留 steps：`["{node}", "-e", "import('./scripts/entrypoint.mjs').then(m=>m.runScheduled()).catch(e=>{console.error(e);process.exit(1)})"]`。
- `runScheduled` 无参（行351 校验 `args.length!==0` 抛错），故 `m.runScheduled()` 正确。
- **启用前提**：B+C 完成后，manifest 将 `daily-taobao-download-to-jinsha` 的 `enabled` 改 `true`、`needs_adapter` 改 `false`。

### 适配 #9（CDP driver 注入，风险高，最后做）
- `skills/meituan-intelligent-customer-service/scripts/ensure_unanswered_queue.mjs` 无 CLI，需外部 CDP `driver` 注入（`runWithUnansweredQueue(driver, scan)`）。
- **做法**：薄适配层 `runtime/adapters/meituan_ics_adapter.{py,mjs}`，由调度层注入 driver 后调用；或暂保留手工调用。
- **测试前提**：真实美团商家中心会话 + CDP driver 可达时跑通。

---

## 3. 执行顺序（风险递增，每项独立 commit）

```
D（低） → B+C（中，合并批次） → E（低） → A（中） → #6 适配（依赖 B+C） → #9 适配（高，末位）
```

建议从 **D** 起（最低风险、纯加 timeout、易验证），再 **B+C**（虽中风险但打通 #6 是「全部流程保障到位」的关键），**E** 顺手清，**A** 去根因脆弱，**#6/#9 适配**收口。

---

## 4. 测试纪律（用户铁律：改造须带测试）

- 每项：单元自测（mock/纯函数） + **一次真实跑通**（需真机 / 微信登录态 / 美团 CDP）。
- 沙箱（WorkBuddy）无法真机闭环；真机验收须用户本机跑 `python3 runtime/run_all.py --once <name>` 或真实触发。
- 改动前先 `git` 状态干净；每项独立 commit，失败即 revert 该文件。
- 全量复扫：每项改造后跑 Phase 1 `run_all --selftest` + 受影响 skill 真实一轮，确认无回归。

---

## 5. 风险与待裁决

- [!] **#6 是高危改造点**：原目录硬编码 + sha256 自锁双重约束，B+C 须同批、且真机验收前不可 `enabled`。
- [!] 全仓 `.codex`/`zhensi_waimai` 硬编码须 Grep 全量摸底（不止 #6/#13），避免漏改导致 `_back` 运行仍读原目录。
- [!] A 项改引用路径，须确认所有消费者 import 行为一致，避免「改一处漏多处」（这正是当前脆弱根因）。
- [!] #9 适配最难，若真机环境暂不具备，可暂缓并保留 `enabled:false` 手工调用，不阻塞其余流程。
