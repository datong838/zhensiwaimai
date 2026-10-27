---
name: control-background-dedicated-chrome
description: Launch and control a persistent, task-dedicated Chrome on macOS that can be manually logged in once and later run headlessly through localhost CDP without touching the user's daily Chrome, windows, tabs, keyboard, mouse, or focus. Use for authenticated background browser operations that must not interrupt the user.
---

# 后台专用 Chrome 控制

## 目的

让用户继续使用日常 Chrome，同时让自动化使用完全独立的持久 Chrome profile。支持两条显式流程：原有站点使用人工登录后无头启动；美团和金鲨可使用 `login-handoff`，在同一可见进程内完成人工登录确认、接管验收和登录窗口释放。该流程保留工作窗口与进程，不等于无头。

实施细节和验收依据见 [实施方案](references/implementation-plan.md)。每次真实操作前必须先按 [运行与故障手册](references/operations-runbook.md) 完成前置门禁；不得边操作边猜测恢复方式。

## 不干扰合同

- 不读取、复制或连接日常 Chrome profile、Cookie、密码、标签页和调试接口。
- 不使用 macOS 全局键盘鼠标、辅助功能点击或窗口激活完成后台操作。
- 每个 profile 使用独立目录、端口、PID和任务标签；端口或 profile 已被占用时失败关闭。
- 无头运行不会创建可见 Chrome 窗口。人工登录及显式选择的美团交接流程可使用独立可见窗口；新任务窗口通过 CDP background 方式创建，不调用系统键鼠或窗口激活。
- 绝不自动从后台专用浏览器降级到日常 Chrome。

## 固定入口

使用 `scripts/background_chrome.mjs`：

```bash
node scripts/background_chrome.mjs init --profile taobao-brand
node scripts/background_chrome.mjs login --profile taobao-brand --url 'https://melody.shop.ele.me/'
node scripts/background_chrome.mjs start --profile taobao-brand --port 9230 --url 'https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard'
node scripts/background_chrome.mjs probe --profile taobao-brand --port 9230 --expected-url-prefix 'https://melody.shop.ele.me/'
node scripts/background_chrome.mjs stop --profile taobao-brand
```

默认 profile 根目录为 `~/Library/Application Support/AOS Background Chrome`。测试时可显式传 `--profile-root /tmp/...`。禁止把 profile 指向 `~/Library/Application Support/Google/Chrome` 或其子目录。

## 原有模式首次登录（非美团原进程交接）

1. 执行 `init`。
2. 用户明确要求开始首次登录后执行 `login`；该命令只启动普通 Chrome，不开放 CDP、不连接 Playwright、不读取页面、不截图。该专用窗口可能取得焦点，这是唯一允许的可见阶段。
3. 用户本人处理账号、密码、扫码、验证码、Passkey、CAPTCHA和风险校验。
4. 登录完成与否只接受用户本人确认；自动化不在登录阶段验证页面。用户关闭专用 Chrome 并明确说“登录好了”后才能继续。
5. 执行 `start` 切换到无头后台模式，再首次连接 CDP 并验证登录结果。可见登录进程仍占用 profile 时，`start` 必须拒绝。

## 美团与金鲨原进程交接（新模式）

先阅读 [交接方案](references/login-handoff-plan.md)。固定 `meituan-merchant:9233` 或 `jinsha-business:9232`，其他站点保持原流程。当前已经用旧 `login` 打开的窗口没有 CDP，禁止直接停止重开来迁移；必须保留会话并报告 `legacy-visible-no-control-interface`。

1. 仅在用户明确要求启动新模式、且该 profile 没有运行实例时执行 `login-handoff`。它预先开放回环端口，但不做任何 HTTP/CDP/Playwright 连接、页面读取或截图。
2. 用户本人登录并确认后，使用本次启动返回的 instanceId 执行 `confirm-login --user-confirmed`。这不是自动推断；不得把之前启动实例的确认用于新实例。
3. 执行 `takeover`。同一站点候选页面必须唯一，两次实际页面结构检查之间断开并重新连接，成功后状态为 TAKEOVER_VERIFIED。
4. 用户已授权接管后关窗时执行 `release-login-window`。先验证同进程独立工作窗口，再关闭唯一已标记登录页；进程保持运行，工作窗口保留。失败保留窗口，不重启或复制存储。
5. 之后 `run_task.mjs inspect` 可复核；新模式禁止通过旧 open/close 绕过专用入口。该版本仅提供交接与只读复核，具体业务动作另行开发和授权。

```bash
node scripts/background_chrome.mjs login-handoff --profile meituan-merchant --port 9233
# INSTANCE 使用刚才输出的 instanceId；TASK 使用本次唯一任务名。
node scripts/background_chrome.mjs confirm-login --profile meituan-merchant --port 9233 --instance INSTANCE --user-confirmed
node scripts/background_chrome.mjs takeover --profile meituan-merchant --port 9233 --instance INSTANCE --task-id TASK
node scripts/background_chrome.mjs release-login-window --profile meituan-merchant --port 9233 --instance INSTANCE --task-id TASK
node scripts/run_task.mjs inspect --profile meituan-merchant --port 9233 --instance INSTANCE --task-id TASK

# 金鲨使用同一组命令，profile/port 固定替换为 jinsha-business/9232。
```

MANUAL_LOGIN 时所有连接入口失败关闭。BLOCKED 默认禁止重放；仅下述明确的恢复/诊断入口可处理特定原因。PREPARING_WINDOW、CLOSING、CLOSE_OUTCOME_UNKNOWN 等非稳定状态禁止重放；锁目录残留时只读排查，不能自动删锁。`stop` 新模式要求匹配实例及 `--allow-process-exit`，且只有用户明确要求退出整个专用进程时才允许使用，不用于普通窗口交接。

## 后台任务（原有无头模式）

1. `start` 后先运行 `probe`，验证 CDP 只绑定回环地址、目标 URL 前缀正确。
2. 页面操作统一使用 `scripts/run_task.mjs`；每次运行使用调用方提供的唯一 `--task-id`，不得按标签顺序或模糊标题猜测页面。
3. 不枚举或输出其他标签页。任务页由 `open` 创建并写入任务标记；复核用 `inspect`，结束清理用 `close`，两者都只允许唯一命中该标记。
4. 登录页、CAPTCHA、账号风险或安全警告出现时停止，不绕过。
5. 写操作继续遵循对应业务技能的授权、去重和结果复核要求；浏览器隔离不等于业务授权。

```bash
node scripts/run_task.mjs open --profile taobao-brand --port 9230 --task-id daily-report-20260909 --url 'https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard' --screenshot artifacts/dashboard.png --receipt artifacts/dashboard.json
node scripts/run_task.mjs inspect --profile taobao-brand --port 9230 --task-id daily-report-20260909
node scripts/run_task.mjs close --profile taobao-brand --port 9230 --task-id daily-report-20260909
```

## 验证命令

```bash
node --test scripts/*.test.mjs
# 以下会创建临时可见 Chrome，仅本机模拟站点，不使用业务账号：
RUN_BROWSER_INTEGRATION=1 node --test scripts/*.test.mjs
node scripts/background_chrome.mjs self-test
```

`probe` 和测试收据不包含 Cookie、Token、Local Storage 或 debugger WebSocket URL。

## 美团目标歧义恢复与诊断

用户已确认当前实例登录、并授权处理多目标时：`recover-target --profile meituan-merchant --port 9233 --instance INSTANCE --task-id TASK`。仅对 BLOCKED/TARGET_AMBIGUOUS 执行一次，创建新工作窗口，按返回 targetId 与唯一 marker 验证；不猜选既有页，不重启。

恢复目标已建立但结构未通过时，`diagnose-target` 只诊断该目标，可显式传 --screenshot；不会创建页面。对于同目标的 PAGE_NOT_READY/STRUCTURE_UNVERIFIED，修复有证据的原因后可用 `verify-work-page` 作第二次验证，安全页/登录页禁止该恢复；达到上限不得重试。

工作目标验证通过后，用 `release-recovered-pages`（同 profile/port/instance/task-id）只关闭恢复前记录的美团 targetId；随后使用 run_task inspect 复核。工作页及浏览器进程继续运行，其他站点页面不在关闭范围。

2026-09-13 真实接管证据见 [恢复交付记录](references/recovery-delivery-20260913.md)。记录是该时刻的验收，后续操作仍要实时 inspect，不能直接把历史状态当作当前状态。

## 无头迁移状态

美团显式无头迁移已尝试，当前证据见 [无头迁移记录](references/headless-migration-20260913.md)。run_task 对 meituan-merchant 使用共享的美团实际结构识别器；diagnose 仅针对唯一任务目标输出框架来源、尺寸及加载元数据。空白不是登录成功或登录失败，需单独报告；历史可见模式验收不能沿用到新无头进程。

## 最小化工作窗口

用户要求不遮挡办公时，在当前实例/任务已验证后使用 `minimize-work-window --profile meituan-merchant --port 9233 --instance INSTANCE --task-id TASK`。仅允许窗口内只有绑定工作页；通过 CDP 最小化，等待窗口状态回读（最多3秒，不重复发送最小化），读取页面并断开重连，再次确认仍最小化且登录结构正常。禁止系统输入和窗口激活；不能把最小化称为无头。2026-09-13 的真实证据见 references/minimized-verification-20260913.json；实际当前状态仍需复核。
