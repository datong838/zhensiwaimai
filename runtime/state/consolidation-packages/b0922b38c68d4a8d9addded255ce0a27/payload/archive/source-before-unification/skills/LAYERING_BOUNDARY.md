# 岗位角色 ↔ 工作流 边界治理（物理分层收口文档）

> 适用仓库：`zhensi_waimai_back/skills/`
> 治理原则（大同 2026-10-05 拍板）：**任何「操作某域工位/浏览器」的逻辑，归该域岗位；边界按「在哪个域做」划分。**
> 五域岗位：淘宝闪购品牌商(9230) · 淘宝闪购服务商(9231) · 金鲨(9232) · 美团外卖(9233) · 微信。

---

## 1. 四层模式与两类技能

```
监理 ── 车间主任 ── 岗位角色（垂直域技能，posts/）  ↔  工作流（业务流程技能，workflows/）
```

- `skills/posts/`：岗位角色（专人专岗，独占一个 Chrome 端口 + 一块浏览器身份）。
- `skills/workflows/`：工作流（编排某业务的端到端流程，只调岗位，不自己连接浏览器）。
- 微信岗 `wechat-messaging`：按规划应归入 `posts/`（仍留在 `skills/` 顶层，见 §5 封印遗留）。

## 2. 岗位「强 / 弱」诊断（用户原问：各角色写得太弱？）

**根因**：`meituan-post` / `taobao-brand-post` / `taobao-svc-post` 的 SKILL.md 主动把
「登录态校验 / 遮罩处理 / 分页核对」推给工作流，岗位只剩 `connect` + `lease` → 工作流各自重写同一套域逻辑，
既重复又无单一真相。

**对照强角色 `jinsha-post`**：它拥有 `connect` + `lease` + `auth`(登录态) + `overlay`(遮罩/抽屉/公告) + `pagination`(分页) 五件套，
工作流只调不写。

**本轮已做的强化（2026-10-05）**：为三个弱岗位补齐域原语 `auth.mjs`（origin 断言 + 登录态判定），
`taobao-brand-post` 另抽 `channel.mjs`（固定通道契约 9230）。岗位 SKILL.md 已改声明「拥有登录态校验」，
`dependencies.json` 已受控重算（verify 全 clean）。

## 3. 五域岗位职责边界表

| 域 | 端口 | 岗位目录 | 岗位拥有（通用） | 工作流拥有（专属） |
|---|---|---|---|---|
| 金鲨 | 9232 | `posts/jinsha-post` | connect·lease·auth·overlay·pagination·appeal_collector | 日报下载/差评提取/新店识别业务 |
| 美团外卖 | 9233 | `posts/meituan-post` | connect·lease·**auth**(origin+登录态) | IM 队列/筛选/回复、工作台路径校验 |
| 淘宝品牌商 | 9230 | `posts/taobao-brand-post` | connect·lease·**channel**(固定通道)·**auth**(origin+登录态) | 店铺选择/活动核验/报表下载、认证锚点恢复、冷启动预算 |
| 淘宝服务商 | 9231 | `posts/taobao-svc-post` | connect·lease·**auth**(origin+登录态) | 意向商户游标采集/核对、菜单路径校验 |
| 微信 | — | `posts/wechat-messaging`(待搬) | 微信桌面发送桥 | 群发编排、文本/图片封装 |

> 说明：美团 IM 工作台是「队列」不是「列表」，无分页、无抽屉遮罩，故 `meituan-post` 不需要 `pagination/overlay`。
> 淘宝品牌商/服务商的「遮罩 / 分页」仍在工作流内（业务耦合 + 部分在封印包），本轮未抽，列入 §4 待办。

## 4. 工作流内嵌「本属岗位」的逻辑清单（迁移映射）

分类：**✅ 已迁移** · **🟡 待迁移（未封印，可直接做）** · **🔴 待迁移（封印包，需受控重封印）**

### 4.1 金鲨域（9232）
- 🔴 `daily-negative-reviews/scripts/browser_collect.mjs`：重写 jinsha 登录态/遮罩/分页 → 应改调 `jinsha-post` 的 `assertAuthenticated`/`closeDrawer`/`dismissAnnouncement`/`waitPaginationStable`。包已用**相对自钉**（搬目录安全），仍属封印包，改完需走受控重封印。
- 🟡 `daily-new-stores-opening-to-wechat/scripts/collector.mjs:16,332`：直连 9232、重写公告白名单 → 应改调 `jinsha-post`。该工作流**未封印**，可直接迁移。
- 🟡 `daily-jinsha-reports-to-business-wechat/scripts/business_jinsha_browser_exam.mjs:229`：直连 9232 → 可改调 `jinsha-post/connect.mjs` 的 `connectJinsha`。
- ✅ `taobao-flash-sale-negative-review-appeals/scripts/full_appeal_report_builder.mjs`：已改指 `jinsha-post/scripts/appeal_collector.mjs`（早前合并 negative-review-appeal-reporting 时完成）。

### 4.2 美团域（9233）
- ✅ `meituan-intelligent-customer-service/scripts/ensure_unanswered_queue.mjs`：原 `assertWorkbenchUrl` 内联 host 判定 → 已改调 `meituan-post/auth.mjs` 的 `assertOrigin`（host 校验），路径校验仍留工作流（业务专属）。
- 🟡 `store-inspection/runtime/meituan-silent-probe-2026-09-14/probe.mjs:30`：重复美团登录态判定（扫码/二维码/手机号登录/请登录）→ 可改调 `meituan-post/auth.mjs` 的 `assertAuthenticated`。（probe 脚本，非主链路。）

### 4.3 淘宝品牌商域（9230）
- ✅ `daily-new-stores-activity-audit-to-wechat/scripts/activity_collector.mjs:13`：原 `brand-login-required` 内联 → 已改调 `taobao-brand-post/auth.mjs` 的 `assertAuthenticated`（保留错误码）。
- 🔴 `daily-taobao-download-to-jinsha/scripts/background_browser_executor.mjs`（1500+ 行）：taobao-brand 固定通道策略、认证锚点恢复、冷启动预算、遮罩 OCR 关闭 → 域身份（`channel.mjs`）已抽出；**认证锚点恢复 / 冷启动预算是业务耦合逻辑，按治理原则仍留工作流**，不在岗位原语内。包**未封印**，但若要把其通道常量改用 `channel.mjs` 需小幅重构。
- 🔴 `daily-top10-to-wechat-group`：复用 9230，含登录检测 → **封印包（绝对自钉 + 下游 Top10 runtime-policy 重绑）**，需授权重封印后再迁移（见 §5）。

### 4.4 淘宝服务商域（9231）
- 🔴 `daily-agent-new-merchants-to-wechat/scripts/background_merchant_collector.mjs:16,18,71,73,74`：重写 `PREFIX` origin + `LOGIN_MARKERS` 登录态 → 域原语已就位（`taobao-svc-post/auth.mjs` 的 `assertOrigin`/`assertAuthenticated`），工作流仍是旧副本。**封印包（绝对自钉 + D11 门禁）**，需授权重封印 + 扩门禁后再迁移（见 §5）。

## 5. 封印遗留（物理分层未完成项，需大同授权）

仅 4 个目录有封印文件。本轮已安全搬完 11 个工作流 + 合并 negative-review-appeal-reporting；
以下 3 个因「绝对自钉 / D11 门禁」未单方面搬，需授权重封印：

| 包 | 应去位置 | 障碍 | 处理 |
|---|---|---|---|
| `skills/wechat-messaging` | `skills/posts/wechat-messaging` | D11 门禁 + 绝对自钉（31~32 文件） | 需授权重封印 |
| `skills/daily-top10-to-wechat-group` | `skills/workflows/` | 绝对自钉 + 下游 Top10 runtime-policy 重绑 | 需授权重封印 |
| `skills/daily-agent-new-merchants-to-wechat` | `skills/workflows/` | 绝对自钉 + **D11 门禁未扩**（历史不可修） | 需授权扩门禁 + 重封印 |

> 规则：封印用**相对路径**自钉（如 `daily-negative-reviews`）搬目录不破钉；用**绝对路径**自钉 + 有 D11 门禁的，不能单方搬。

### 5.1 交叉钉值图（2026-10-05 实测）——这 3 个包**互相钉死**，必须一起搬 + 一起重签

| 钉值文件 | 钉了谁 | 路径形态 |
|---|---|---|
| `wechat-messaging/dependencies.json` | 自己 31 项（相对） + `daily-top10/scripts/ocr_vision`（绝对） + `daily-agent-new-merchants/.runtime/ocr_control_label`（绝对） + app-controler 5 文件（绝对·项目外） | 混合 |
| `daily-top10-to-wechat-group/runtime-policy.json` | 自己 3 脚本（绝对） + `wechat-messaging/scripts/workflow_bridge_windows.py`（绝对） + `wechat-messaging/scripts/workflow_preflight.py`（绝对） + `wechat-messaging/dependencies.json`（绝对） | 全绝对 |
| `daily-agent-new-merchants-to-wechat/executor-lock.json` | SEALED 态 + D11 死结（`UNSEALED_ACCEPTANCE` 已过期 + 4 项摘要漂移，现有门禁下无合法 refresh 路径） | 锁 |

搬迁会同时打破的**跨包引用**（改完必须一并重签）：
- `daily-jinsha-reports-to-business-wechat/scripts/business_wechat_group_locator.py:18` → `skills/daily-agent-new-merchants-to-wechat/scripts/wechat_sender_executor.py`（绝对表达式 `parents[3]/...`）
- `daily-jinsha-reports-to-business-wechat/scripts/test_business_desktop_preflight.py:14` → `skills/wechat-messaging/scripts`
- `daily-negative-reviews/dependencies.json` → `wechat-messaging/dependencies.json` + `wechat-messaging/scripts/workflow_bridge*.py`（2 条绝对钉）
- `brand-negative-review-appeal-followup`（`ROOT.parent.parent/wechat-messaging`）、`daily-negative-reviews/workflow_policy.mjs`（`PROJECT_ROOT/skills/wechat-messaging/...`）等诸多在跑工作流都按 `skills/wechat-messaging` 定位

**结论**：搬这 3 个包的收益是「目录整齐」，成本是「3 个包重签 + 4+ 处下游重绑 + 扩 D11 门禁」，功能零改善。建议**除非有明确诉求，不动封印**；若确需搬，须一次性（3 包同批）走 sealed-dependency-maintenance 6 步 + 全项目绝对路径重绑 + 扩门禁。

### 5.2 `.daily-jinsha-reports-core`（第 4 个未转正项）

金鲨岗**底座**（18 个封板文件），被 `daily-jinsha-reports-to-business-wechat` 经**相对路径** `../../../.daily-jinsha-reports-core/scripts/...` 引用（搬目录后已随之修正）。按域治理应转正并入 `posts/jinsha-post/`，但涉及 18 个封板文件移动 + 引用重写 + 重封印，属「动封印 + 改语义」重构，同样需授权。

## 6. 本轮交付小结

- ✅ 三弱岗强化：`meituan-post`·`taobao-brand-post`·`taobao-svc-post` 各补 `auth.mjs` + 契约测试；`taobao-brand-post` 加 `channel.mjs`；SKILL.md 改声明；`dependencies.json` 受控重算（verify clean）。
- ✅ 低风险迁移 2 处：美团 IC 的 origin 校验、淘宝品牌活动核验的登录校验，已改调岗位模块（self-test 通过）。
- 🟡🔴 剩余迁移与 3 个封印包搬运见 §4 / §5，按「是否封印 / 业务耦合」分类推进。
- ⏸ 统一全量验收（含此前 deferred 的 `meituan-waimai-negative-review-appeals-1425 --once` 端到端）待上述收口后执行。

## 7. 搬迁遗留缺陷修复（2026-10-05 第二轮，全部已修 + 回归通过）

首轮搬迁（11 工作流入 `workflows/`）漏改了一批**非 `posts/`/`wechat-messaging` 模式**的引用，导致 3 处包级断裂；本轮用「全量引用审计脚本」扫出并修复：

| 缺陷 | 位置 | 修复 |
|---|---|---|
| 金鲨底座引用深度少一级 | `daily-jinsha-reports.../business_exam_pipeline.mjs:7-8`、`business_jinsha_cua_exam.mjs:1` 的 `../../.daily-jinsha-reports-core/` | → `../../../.daily-jinsha-reports-core/` |
| `parents[N]` 未随搬迁 +1 | 同包 `business_wechat_file_sender.py:16,20`、`business_wecom_shared_space_sender.py:17`、`conftest.py:5`、`business_wechat_group_locator.py:18` | 各 +1（实测解析结果均 exists=True） |
| `PROJECT_ROOT` 少一层 | `daily-negative-reviews/scripts/workflow_policy.mjs:8` `'../..'` | → `'../../..'`（并重签该包封印：`workflow_policy.mjs`+`browser_collect.mjs`） |
| 7 个工作流 `conftest.py` 的 `REPO_ROOT` 少一层 | 各包 `scripts/`·`tests/conftest.py` | `parents[3]` → `parents[4]` |
| 改名后 import 未跟 | `posts/jinsha-post/scripts/test_appeal_collector.mjs:2` 指 `./all_appeals_collector.mjs` | → `./appeal_collector.mjs` |
| **`~/.codex` 镜像漂移** | 仓库 `daily-taobao-download.../entrypoint.mjs`+`SKILL.md` 与 `~/.codex/skills/...` 镜像 sha256 不等 → 运行时抛 `installed-entrypoint-drift` | 已同步镜像（差异仅 5 处文档链接字符串，无运行时路径语义） |

**回归结果**：JS 自动化测试 24/24 通过（另 2 个为需 CLI 参数的手动验收脚本）；Python 测试 17/17 通过（`reconcile` 需 openpyxl，改用 codex 运行时解释器跑 4 passed；`wechat_locator` 为顶层断言脚本，运行输出 `checks passed`）。

**审计工具**：`/tmp/audit_refs.py`（扫描 JS 相对 import + Python `parents[N]` 并做存在性校验）。如需长期保留，建议迁入 `runtime/` 作为搬迁后置检查。
