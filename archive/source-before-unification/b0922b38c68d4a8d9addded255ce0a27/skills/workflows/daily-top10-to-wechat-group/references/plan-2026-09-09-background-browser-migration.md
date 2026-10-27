# Top10 后台专用浏览器迁移方案（2026-09-09）

## 目标

把桌面采集段从 `control-existing-chrome` 的前台窗口、AX、系统键鼠和窗口截图，迁移到 `control-background-dedicated-chrome` 的专用持久 Profile 与 localhost CDP。用户继续使用日常 Chrome 和其他桌面应用，Top10 采集不抢窗口、键盘、鼠标或焦点。

## 固定资源与边界

- Profile：`taobao-brand`
- CDP：`127.0.0.1:9230`
- 首个页面：淘宝闪购品牌商首页 `https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard`
- 每轮创建唯一 `task-id` 标签，只操作和关闭该标签；不枚举、不修改、不关闭其他标签。
- 不启动、停止或重启后台 Chrome；端口、进程、Profile 或登录态不符合即失败关闭。
- 不读取 Cookie、Local Storage、密码、浏览器历史或调试 WebSocket 地址。
- 手机微信、目标群、原图、一次发送账本和发送后大图复验合同保持不变。

## 新桌面执行器

新增 `scripts/desktop_background_executor.mjs`，由 `workflow_executor.py` 唯一调用：

1. 只读核验专用 Profile 状态文件、进程、headless 模式和 9230 端口。
2. 连接 CDP，创建带唯一 `task-id` 的新标签并固定 2200×1800 无头 viewport、2× device scale；截图直接使用设备像素，不做事后 resize。
3. 先打开品牌商首页，按完整登录页标志为 0、商家结构标志至少 3 项验证登录态。
4. 若首页出现唯一“绑定手机号提醒”弹窗，必须同时命中完整标题、说明、“跳过”和“去绑定”，只点击一次“跳过”并验证弹窗消失；其他弹窗一律停止。
5. 在所有 frame 中等待唯一可见「门店分析」站内链接并单击；不使用地址栏直达分析页。
6. 等待唯一 `storeAnalysisDetail` frame，选择「昨日」，同时验证选中 class 与 `已选时间：MM-DD`。
7. 读取表格 DOM，过滤测量行，要求恰好 10 个业务行；按固定列合同提取门店、商圈排名、营业额和有效订单。
8. 营业额已非增序则不点击；否则只点击一次唯一「营业额」表头并复核。要求分页器第 1 页、`10 条/页`。
9. 以表格容器到分页器的页面区域生成原始 PNG；要求宽度不低于 1500 px，OCR 字段、十家门店和隐私检查全部通过。
10. 写出与手机执行器兼容的桌面收据；无论成功失败，只关闭本轮 task-id 标签并断开 CDP，不关闭浏览器。

## 稳定性规则

- 首页链接短暂未加载时只读轮询最多 10 秒；0 个或多个可见候选都不点击。
- 页面点击统一使用 5 秒上限，禁止让 Playwright 默认 30 秒重试吞掉总预算。
- “昨日”已选、无加载动画、至少 6 个指标为 `--` 且出现“暂无数据”时，立即分类为 `yesterday-data-not-ready`；不重登、不刷新、不把空状态误报为解析失败。
- Playwright 对子 frame 元素返回的 `boundingBox` 已是主 frame viewport 坐标；截图裁剪直接使用表格和分页器 box，禁止再次叠加 iframe 偏移。失败收据保留非敏感几何用于复盘。
- 无头 Chrome 默认 1× 像素密度会使 1120 CSS px 业务区域低于清晰度门禁；任务页固定 2× device scale，以原始设备截图得到 2240 px，不允许事后放大。
- `connectOverCDP` 下 Playwright `page.screenshot(scale=device)` 未采用后设 device scale；当前执行器改用同一 CDP 会话的 `Page.captureScreenshot`。device scale 固定为 2、capture scale 固定为 1，避免二者叠加成 4× 大图。
- 页面出现登录、CAPTCHA、风险验证或 URL 偏离强前缀时立即停止。
- 所有页面动作由确定性 DOM 选择器和后置条件驱动，正常路径 `runtimeModelDecisions=0`。
- 每阶段只允许规定的一次动作；不使用坐标、OCR 点击、系统键鼠、窗口激活、全屏或页面缩放。
- 收据记录阶段耗时、task-id、URL、数据日期、行数、排序、图片尺寸和哈希，不保存页面原文或认证数据。
- 主微信前台门禁必须同时满足 `uiautomator2.app_current()` 为 `com.tencent.mm`，以及系统恢复任务为主空间 `u0 com.tencent.mm`；双开选择器或微信冷切换期间采用最长 12 秒的有限轮询。不得把稍后才完成的合法主微信切换误判为失败，也不得仅凭包名放行微信分身 `u128`。

## 真机回归复盘（2026-09-10）

- 现象：桌面下载、手机合同和图片推送均通过，`open_main_wechat` 在 8.279 秒时报 `wechat-not-foreground`；失败后立即只读复核时，真机画面已是微信首页，系统恢复任务为 `u0 com.tencent.mm/.ui.LauncherUI`，且发送次数仍为 0。
- 原因：旧逻辑先等待双开选择器 2 秒、再仅按包名等待 6 秒，选择器与主微信切换稍慢时会在边界先失败，随后微信才完成切换；最终主空间校验来不及执行。
- 最小修复：将“包名”和“主空间恢复任务”组合为同一确定性前台证据，启动后有限轮询 12 秒；原有进程、主空间、目标群、原图、一次发送账本和发送后复验门禁不变。
- 重试边界：本轮收据 `sendAttempts=0` 且当日账本无标记才允许重新生成桌面收据并完整重跑；成功或结果未知后禁止重发。

## 验收

1. 纯函数测试：Profile 状态、行解析、排序、task-id 和登录标志。
2. 静态测试：Node/Python 语法、原有手机安全测试、技能结构校验。
3. 只读预检：9230 存活且属于 `taobao-brand` headless 进程；手机身份、屏幕和微信依赖可用。
4. 真机全流程：唯一总入口生成昨日 Top10 原图，交给手机主微信，发送到「FEIBING NEO AI数字员工」，群内气泡及大图复验通过。
5. 记录每个桌面和手机节点耗时、是否模型介入、结果与待优化项；发送结果未知禁止补发。
