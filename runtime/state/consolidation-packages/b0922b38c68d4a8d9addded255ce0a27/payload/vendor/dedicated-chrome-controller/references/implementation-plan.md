# 后台专用 Chrome 技能实施方案

## 2026-09-13 方案修订状态

美团新增流程以 [人工登录后原进程接管方案](login-handoff-plan.md) 为拟实施规范：人工登录期间不连接自动化，用户确认后接管并完成验收，再评估关闭登录窗口。该修订已进入代码实现与隔离测试；真实美团接管必须独立验收。不得依据代码或本机模拟测试关闭当前旧模式已登录窗口或宣称接管完成。以下内容保留为现有实现基线，其他三个站点的既有流程保持不变。

人工登录阶段只启动独立普通 Chrome，不启用 CDP、Playwright、截图或页面探测；用户关闭该窗口并确认登录完成后，才允许后台阶段连接 CDP。

## 2026-09-15 金鲨同进程交接修订

金鲨实测存在进程级会话：可见登录成功后关闭该进程，再以同一 Profile 启动无头 Chrome，会回到 `#/login`。用户已授权将 `login-handoff` 最小扩展到 `jinsha-business:9232`。人工登录时执行器不连接页面；用户确认后按金鲨强前缀和业务结构完成两次接管验证，释放登录窗口并最小化同进程工作窗口。业务读取只使用状态中绑定的目标 ID、marker 和站点前缀；美团及其他三个既有流程不改变。

## 目标

实现“用户使用日常 Chrome，自动化使用独立后台 Chrome”，两者不共用 profile、窗口、标签、端口、键盘鼠标或焦点。

## 生命周期

1. `init`：创建技能专属持久 profile 和运行元数据；不读取或复制日常 Chrome 数据。
2. `login`：仅首次登录时启动该 profile 的可见 Chrome，由用户本人完成账号、验证码和风控操作。
3. `start`：确认可见登录 Chrome 已退出后，以 `--headless=new`、专属 profile、仅回环 CDP 端口启动后台 Chrome。
4. `probe`：通过 CDP 读取任务目标 URL、标题和结构判定；收据不保存页面原文，不输出 Cookie、Token、Local Storage、WebSocket URL或其他标签信息。
5. `run`：通过 Playwright `connectOverCDP` 操作任务自己创建且写有唯一 `task-id` 的标签页，不使用全局输入事件；恢复旧标签再多也不得改变选择结果。
6. `stop`：只根据技能私有 PID/进程启动时间关闭本技能启动的进程，不影响任何其他 Chrome。

## 默认隔离资源

- Profile：`~/Library/Application Support/AOS Background Chrome/<profile-name>`
- CDP：`127.0.0.1:9230` 起，由调用者显式指定；端口占用时拒绝启动。
- 元数据：profile 下 `.aos-background-chrome/`，包含 PID、端口、启动模式和非敏感收据。

## 安全与稳定性

- 禁止 profile 路径位于日常 Chrome 数据目录。
- 禁止复制 Cookie、密码、Local Storage 或现有 profile。
- CDP 只能绑定 localhost；禁止输出 debugger WebSocket 地址。
- 同一 profile 同时只能有一个 Chrome 进程；可见登录和无头运行不可并存。
- 对使用会话级登录的站点，调用者可在 `login` 显式传 `--disable-background-mode`，确保用户关闭最后一个专用窗口后进程自然退出；在随后 `start` 显式传 `--restore-last-session`。两个开关都只作用于调用者指定的专用 Profile，不改变默认行为，也不允许在人工登录阶段启用 CDP。
- 启动前验证端口空闲，启动后验证 PID、CDP、本地绑定和 profile 一致。
- 所有页面动作都通过 CDP 完成，不激活 Chrome、不发送系统键鼠事件。
- CAPTCHA、重新登录、账号风险提示只报告并停止，不规避。

## 验收

1. 静态校验：技能结构、参数、路径和端口拒绝规则。
2. 隔离测试：拒绝默认 Chrome profile；两个测试 profile 的状态互不相通。
3. 无焦点测试：记录前台 App，启动并探测无头 Chrome，前台 App 不变。
4. 生命周期测试：启动、CDP 探测、任务标签访问、停止后端口关闭。
5. 淘宝试验：空测试 profile 只能看到登录页；专用 profile 人工登录后，后台启动应能读取品牌商首页关键结构。

## 实操迭代记录

| 发现 | 固化措施 | 验收口径 |
|---|---|---|
| 临时无头上下文无法继承日常 Chrome 登录态 | 使用独立持久 profile，首次只允许人工登录 | 重启无头后仍能识别商家首页 |
| 日常 Chrome 未开放可复用 CDP | 专用 localhost 端口和专用 profile | 端口、进程、profile 三者一致 |
| 人工登录期间自动连接可能触发风控 | `login` 阶段不启用 CDP、Playwright、截图或页面读取 | 收据明确 `automationAttached=false` |
| 用户关窗后专用 Chrome 可能仍有后台进程 | `start` 失败关闭；只核验并停止本 profile 所属 PID | 不终止日常 Chrome，随后可切换无头 |
| Chrome 恢复旧标签导致多个 URL 命中 | 新标签写入唯一 `task-id`，检查和关闭只认该标记 | 0 个或多个命中均失败关闭 |
| 页面包含多个 frame/body | 分 frame 读取并去重，不使用严格单 body 定位 | 能稳定提取首页结构 |
| “建议绑定手机号”被误认为掉线 | 登录判断只用完整登录页标志，并要求至少 3 个商家首页标志 | 绑定提醒存在时仍判定已登录 |
| 截图和页面读取可能干扰办公 | 只经无头 CDP，不调用系统键鼠或激活窗口 | 前台 App、日常 Chrome 窗口数不变 |
| URL 前缀曾写错 | 固定使用 `https://melody.shop.ele.me/` 强前缀 | 前缀不符立即失败 |
| 金鲨登录依赖浏览器会话，关窗后后台驻留再被 SIGTERM 会丢登录态 | 金鲨专用 Profile 登录时禁用后台驻留，后台启动显式恢复上一会话 | 用户正常关窗后进程自然退出；无头任务不跳转 `#/login` |

完整检测、恢复和禁止动作见 [运行与故障手册](operations-runbook.md)。

## 本轮写入边界

只在 `plugins/browser/control-background-dedicated-chrome/` 新增或修改文件。测试 profile 与收据使用 `/tmp`，不修改仓库其他目录。
