# Top10 代码强制运行时约束方案（2026-09-11）

## 目标

把“昨日门店 Top10 → 微信群”流程的关键安全与稳定约束从 Markdown 提示迁移到可测试的运行时代码。Markdown 只解释合同；执行器代码独立决定是否允许进入下一节点。正常路径不得依赖大模型选择浏览器、端口、微信通道、目标群、选择器、重试方式或发送条件。

## 当前缺口

1. `workflow_executor.py` 暴露 `--browser-profile`、`--browser-port` 和 `--wechat-channel`，真实执行可被调用方改写。
2. `desktop_background_executor.mjs` 只校验“传入参数与状态文件一致”，没有强制品牌商固定值 `taobao-brand:9230`。
3. 关键执行文件没有 Top10 自己的运行时完整性清单；MD 更新不能证明实际加载的执行器仍是验收版本。
4. 微信被其他已知自动化进程占用时，本流程缺少代码级串行门禁和等待证据。
5. 失败收据没有统一区分“代码策略拒绝、外部硬阻塞、可等待的微信抢占、发送后未知”。

## 代码强制合同

### 1. 不可覆盖的固定身份

真实执行必须同时满足：

- 浏览器 Profile 严格等于 `taobao-brand`；
- CDP 严格等于 `127.0.0.1:9230`；
- 浏览器状态严格为 `headless`，PID 存活；
- 微信通道严格等于 `desktop`；
- 目标群由代码常量提供，严格等于 `FEIBING NEO AI数字员工`；
- 站立授权严格等于当前 Top10 授权常量；
- 正常路径 `runtimeModelDecisions=0`。

CLI 可以保留兼容参数，但任何非固定值都由代码返回稳定错误码，不能进入页面动作。调度提示不能覆盖这些值。

### 2. 运行时策略清单

新增 `runtime-policy.json`，由代码校验固定 Profile、端口、通道、目标群、策略版本，以及关键执行文件 SHA-256。清单至少绑定：

- `desktop_background_executor.mjs`；
- 共享 `desktop_sender.py`；
- 共享 `wechat_desktop.py`。

清单缺失、字段漂移或文件哈希不一致时，在任何 Chrome/微信动作前失败关闭，错误码为 `runtime-policy-*`。清单更新必须伴随方案、测试和重新验收，不能由运行时自动改写。

### 3. 微信跨进程互斥

新增 Top10 运行时门禁模块，使用固定共享锁文件和操作系统 `flock`：

- 抢不到锁时每个等待周期不超过 60 秒，持续等待，不创建发送账本；
- 锁由 OS 绑定文件描述符，进程退出自动释放，不删除他人锁文件；
- 获锁后再检查已知微信自动化进程，连续两个周期均无竞争者才放行；
- 本流程从桌面微信预检开始持锁，经过浏览器采集和单次发送，最终在 `finally` 中释放；
- 锁等待耗时、轮次、取得和释放状态进入工作流收据；
- 外部未遵循共享锁的任务仍由现有群标题、空输入区、载荷预览、发送前 attempted 和发送后双帧门禁拦截，不把单帧稳定当作发送许可。

不修改共享 `desktop_sender.py`，因为它被“新增商家”封存清单绑定；直接改动会使既有封存验收失效。后续若要让所有微信流程共同遵循同一锁，必须单独升级共享控制层并重新验收所有受影响流程。

### 4. 稳定失败分类

代码返回以下类别，不让模型临场解释后继续：

- `runtime-policy-*`：代码或配置漂移，禁止业务动作；
- `wechat-contention-*`：等待型状态，未产生发送尝试；
- `blocked-login` / CAPTCHA / 风险验证：必须人工处理；
- `desktop-send-already-attempted`：防重拒绝；
- `desktop-post-send-verification-unknown`：发送后未知，禁止重发；
- 其他确定性节点失败：保存收据，交给计时外开发修复，禁止运行时切换选择器或通道。

## 修改文件

- `skills/daily-top10-to-wechat-group/references/plan-2026-09-11-code-enforced-runtime-guardrails.md`：本方案。
- `skills/daily-top10-to-wechat-group/runtime-policy.json`：机器可读固定策略与文件哈希。
- `skills/daily-top10-to-wechat-group/scripts/runtime_guard.py`：策略校验、文件完整性、微信互斥和已知竞争进程检测。
- `skills/daily-top10-to-wechat-group/scripts/workflow_executor.py`：在任何业务动作前执行策略与互斥门禁，固定桌面通道并写入收据。
- `skills/daily-top10-to-wechat-group/scripts/desktop_background_executor.mjs`：拒绝任何非 `taobao-brand:9230` 参数。
- `skills/daily-top10-to-wechat-group/scripts/test_runtime_guard.py`：策略漂移、哈希漂移、锁等待和安全释放测试。
- `skills/daily-top10-to-wechat-group/scripts/test_background_desktop.mjs`：固定浏览器身份测试。
- `skills/daily-top10-to-wechat-group/references/deterministic-executor-contract.md`、`SKILL.md`：只说明代码已经实施的合同和入口，不再充当放行逻辑。

## 测试与验收

1. 非 `taobao-brand`、非 `9230`、真实执行选择手机通道均在业务动作前被代码拒绝。
2. 策略字段或任一关键文件哈希漂移时，业务动作前被代码拒绝。
3. 两个进程竞争微信锁时，第二个等待；第一个释放后第二个取得锁。
4. 异常路径也释放本任务文件描述符，不删除锁文件，不释放他人锁。
5. 后台执行器自测和现有 Top10/共享微信发送器测试全部通过。
6. 静态检查确认唯一正式入口没有运行时模型回调、模糊选择器降级或手机自动切换。
7. 2026-09-12 固定入口真实运行已端到端完成并由收据验证；代码测试通过不冒充真实发送完成。

## 风险与兼容

- 新门禁会把过去可传入的浏览器/端口覆盖变成明确拒绝，这是有意的安全收紧。
- 共享发送器保持不变，避免破坏其他已封存流程；因此跨流程完全互斥需要其他流程后续采用同一锁。Top10 本身会等待已知竞争进程，并继续依赖发送器现有的逐节点复核防止误发。
- 等待没有业务层总超时，但每个轮询周期有界；进程被系统终止时 OS 自动释放锁。
- 任何发送后未知仍优先于“必须做完”：代码禁止自动重发，避免重复消息。

## 2026-09-11 实施验证

- 代码门禁已实现，非 `taobao-brand`、非 `9230`、mobile 和 transport file 均在业务动作前返回稳定 `runtime-policy-*`。
- `runtime-policy.json` 已绑定后台执行器、共享桌面发送器和共享群定位器的绝对路径与 SHA-256；字段或哈希漂移测试通过。
- 微信互斥锁竞争、等待后取得、连续两次空闲检查、异常释放和锁文件保留测试通过；浏览器采集后、发送器启动前会再次检查竞争进程。
- Top10 Python 测试 22 项通过；后台 Node 测试 12 项与自测 7 项通过；未修改的共享桌面微信发送器回归测试 27 项通过。
- 2026-09-12 已完成真实 08:00 场景端到端运行，`last_verified` 更新为 2026-09-12。

## 2026-09-12 实操收据

- 收据：`.runtime/workflow-runs/3574e943-ca99-4060-acaf-b396577ef388/workflow_receipt.json`。
- 结果：`ok=true`，固定 `taobao-brand:9230`，桌面微信精确群命中，发送 `sendAttempts=1`，发送后双帧验证 `verified=true`，`runtimeModelDecisions=0`。
- 节点耗时：预检 1,447 ms；后台预检 121 ms；打开首页 1,595 ms；进入门店分析 906 ms；选择昨日 274 ms；排序校验 319 ms；截图自检 981 ms；定位群 350 ms；准备载荷 8,772 ms；声明并发送 3,780 ms；发送后验证 15,635 ms；端到端 37,829 ms；总墙钟 44,617 ms。
- 踩坑与修复：共享发送器哈希漂移先被策略门禁拦截；父流程与共享预检共用锁导致一次自锁，已改为预检自持锁、浏览器阶段持锁、启动发送器前释放；中文门店名 OCR 偶发误报已改为 DOM 行校验加表头 OCR。修复均已写入执行器代码及机器策略。

## 2026-09-12 共享控制层对齐修复方案

定时运行前发现共享微信发送器已由其他已授权变更升级：新增 `desktop_preflight.py`、`wechat_interaction_lock.py` 并纳入共享封存清单；其共享锁实际路径为 `wechat-desktop-control/.runtime/wechat-ui-interaction.lock`，而 Top10 门禁仍指向历史锁名，且运行策略中的发送器哈希落后于当前已封存文件。处理规则如下：

1. 先复核共享封存清单和共享发送器回归测试，不直接改哈希放行。
2. 将 Top10 策略哈希对齐到已验证的当前五个关键文件（后台执行器、发送器、预检、共享锁、群定位器）。
3. Top10 门禁改用共享锁路径；浏览器采集结束后释放父锁，再由共享发送器获取同一锁，避免父子进程自锁。
4. 发送器返回等待型 `resource_wait` 时只由代码继续等待/重试；未知发送结果、已尝试发送或确定性失败均不重发。
5. 截图自检不再用 OCR 逐字复核中文门店名：门店名、营业额、订单数由已通过的 DOM 表格节点提供；截图 OCR 仅复核关键表头与隐私禁词，避免中文 OCR 偶发误报导致流程中断。
6. 2026-09-13 共享发送器再次发生外部变更；其 40 项回归测试通过后，Top10 策略绑定当前 SHA-256。不得修改另一流程的封存清单，若该清单仍漂移只报告其独立状态。
7. 2026-09-16 共享群定位器再次发生外部变更；Python 编译及桌面预检/发送回归测试通过后，Top10 策略绑定当前 SHA-256，仍不修改其他流程封存清单。
8. 2026-09-16 复盘确认发送器在 `prepare_payload` 像素阈值误报时未清理未提交预览。修复为：未领取 attempted 的失败路径执行代码化预览取消并写入清理结果；图片预览证据不再代表清晰度，改为相对变化下限、预览区域非空与原图载荷哈希绑定，避免渲染差异误判清晰图片。
9. 修复已写入共享 `desktop_sender.py`、Top10 `runtime-policy.json` 和测试；共享发送器回归测试 48 项通过。共享“新增商家”封存清单需其所属流程单独重新验收，本次未擅自修改。
10. 预览证据范围已从“固定像素阈值”收紧误报风险改为“相对变化比例 + 最低存在性变化”：不再把阈值描述为清晰度判断；本次图片清晰度仍由原始 PNG、截图自检和发送后双帧验证负责。
11. 2026-09-17 共享发送器发生外部哈希漂移；当前版本回归测试 48 项通过，Top10 策略仅对齐该已验证版本，未修改共享封存清单。
12. 2026-09-18 微信消息桥接器及依赖再次发生外部变更；当前桥接器测试 111 项通过，Top10 策略对齐已验证哈希后再运行。
13. 2026-09-19 固定入口在业务动作前检测到 `wechat-messaging/scripts/workflow_bridge.py` 策略哈希漂移并 fail-closed，`sendAttempts=0`，未触发浏览器或微信动作。已复核桥接器及依赖测试 128 项通过；仅对齐当前已验证桥接器与依赖哈希，随后重新执行固定入口。该变更不放宽浏览器、群组、通道、发送或防重约束。
14. 2026-09-19 继续执行前再次检测到 `wechat-messaging/dependencies.json` 哈希漂移并 fail-closed，`sendAttempts=0`，未触发业务动作；当前统一微信回归测试 128 项通过。仅更新该依赖摘要的机器可读绑定，保持运行时约束不变。
15. 2026-09-20 固定入口检测到 `wechat-messaging/scripts/workflow_bridge.py` 哈希漂移并 fail-closed，`sendAttempts=0`，未触发业务动作；统一微信回归测试 140 项通过。按同一心跳维护合同对齐桥接器与依赖摘要，未放宽固定通道、目标群或防重约束。
16. 2026-09-20 用户完成商家登录后切换无头并探测通过；固定入口再次检测到桥接器哈希漂移，`sendAttempts=0`。当前统一微信回归测试 146 项通过；按受控维护合同更新桥接器与依赖摘要后进行最终复跑。
17. 2026-09-22 固定入口在业务动作前检测到桥接器哈希漂移，`sendAttempts=0`，未触发浏览器或微信业务动作；统一微信回归测试 146 项通过。按同一心跳维护合同更新桥接器与依赖摘要并最终复跑，运行约束保持不变。
18. 2026-09-23 固定入口在业务动作前检测到桥接器哈希漂移，`sendAttempts=0`，未触发业务动作；统一微信回归测试 156 项通过。按同一心跳维护合同更新桥接器与依赖摘要并执行最终复跑，未放宽任何运行约束。
19. 2026-09-24 固定入口在业务动作前检测到桥接器哈希漂移，`sendAttempts=0`，未触发业务动作；统一微信回归测试 162 项通过。按同一心跳维护合同更新桥接器与依赖摘要并执行最终复跑，未放宽任何运行约束。
20. 2026-09-25 固定入口在业务动作前检测到 `desktop_sender` 摘要漂移，`sendAttempts=0`；统一微信回归测试 163 项通过。受控维护仅重绑已验证桥接器与依赖 SHA-256，再执行无副作用策略校验和一次最终复跑。
21. 2026-09-25 最终复跑暴露共享桌面预检对 `wechat-search-region-contended` 只尝试一次的问题，收据证明 `sendAttempts=0`。修复方案：总执行器仅针对该精确可恢复原因持续等待 5 秒并重做只读预检；其他失败及 hardGate 原样失败关闭。记录每次尝试次数和累计耗时；测试覆盖竞争后成功与非竞争错误不重试，随后更新执行器策略哈希并重新跑固定入口。

## 2026-09-26 桌面发送器摘要漂移受控恢复

### 证据与边界

- 固定总入口首次运行在 runtime-policy 门禁立即拒绝，收据 `b1cfd95a-b464-4277-b244-600a79dd5e2` 记录 `sendAttempts=0`、`runtimeModelDecisions=0`、`preflightMs=0`，原因是 `runtime-policy-file-digest-mismatch:desktop_sender`；未启动浏览器或微信业务动作。
- 当前 Top10 策略登记的 `desktop_sender` 摘要与共享 `wechat-messaging/scripts/workflow_bridge.py` 实际字节不一致；修正后无副作用策略校验又发现 `messaging_dependencies` 本地摘要也滞后。共享 `wechat-messaging/dependencies.json` 的整体哈希当前为 `8f2dc613…e36cdeb`，其内部登记的桥接器摘要与实际字节一致，且共享 172 项回归通过；证据指向 Top10 两个本地摘要绑定滞后，不是共享依赖内容待改。

### 修复步骤与放行条件

1. 运行共享微信桥接器专项测试，并用共享执行器依赖校验确认完整依赖清单一致；不得为了消除错误直接重写共享清单。
2. 专项测试和依赖校验通过后，仅将 Top10 `runtime-policy.json` 中 `desktop_sender` 与 `messaging_dependencies` 的 SHA-256 对齐到已验证文件当前摘要；不改业务执行器、群、通道、Profile、重试、防重或发送约束。
3. 运行 Top10 全量测试、共享微信回归及 runtime-policy 无副作用校验；全部通过且原收据仍确认 `sendAttempts=0` 后，只从固定总入口进行一次最终复跑。
4. 若门禁显示 attempted、unknown 或发送边界不明，禁止复跑并转只读对账。

### 2026-09-26 修复与执行结果

- 已对齐 Top10 `runtime-policy.json` 的 `desktop_sender` 与 `messaging_dependencies` 两个摘要；共享代码和共享依赖清单均未修改。
- 验证通过：共享微信 Python 回归 172 项；Top10 Python 回归 27 项；后台执行器 Node 测试 12 项；桌面就绪 Node 测试 4 项；`validate_runtime_policy()` 校验全部 6 个绑定文件及共享传递依赖通过。
- 固定总入口最终复跑成功，收据 `.runtime/workflow-runs/83df97f8-3fc3-497c-a690-6de401c5cd0d/workflow_receipt.json`：`sendAttempts=1`，`runtimeModelDecisions=0`，固定 `taobao-brand:9230` + desktop + `FEIBING NEO AI数字员工`；昨日 PNG 自检通过，截图 `2240×1764`，发送后双帧内容校验通过。实际业务执行器未修改；这是经测试后的策略摘要同步，不记作新执行器逻辑沉淀。

## 2026-09-27 桌面桥接器策略摘要再次漂移

- 固定入口首次运行的收据 `1918ddec-7a51-4088-adea-f2d7a630a177` 明确记录 `sendAttempts=0`、`preflightMs=0`、`runtimeModelDecisions=0`，原因 `runtime-policy-file-digest-mismatch:desktop_sender`，`wallMs=1`；没有进入浏览器或微信业务动作。
- `workflow_bridge.py` 当前 SHA-256 为 `5bd411a5a441edfa0612a1919928f768a8ba89e7a7d31c5d4242f36b5a68dfc7`，而 Top10 策略仍绑定上一已验证版本 `62e81d…027f`。共享依赖验证通过，桥接器专项测试 174 项通过；Top10 测试中仅当前策略摘要一致性测试因该漂移失败。
- 修复方案：先以共享完整回归和依赖清单校验确认当前文件；只更新 Top10 `runtime-policy.json` 的 `desktop_sender` SHA-256，保持其他文件、固定运行约束和防重逻辑不变；再跑 Top10 全量 Python/Node 测试及 runtime-policy 校验。仅当全部通过且本收据保持 `sendAttempts=0` 时，才从固定总入口进行一次最终复跑。业务执行器无代码缺陷证据，不修改共享桥接器或执行器实现。
- 第一次仅对齐 `desktop_sender` 后，Top10 测试发现 `messaging_dependencies` SHA-256 也滞后；共享依赖清单当前 SHA-256 为 `fee37703d1f6a47c7fdfb002762767997523506343db74cdc626ad4a28e28fe5`，其内部依赖校验再次通过。恢复因此还需仅对齐这个第二个摘要，再完成相同的全量回归与无副作用策略校验；在此前提达成前不最终复跑。
- 两个摘要同步后，共享微信 174 项、Top10 Python 27 项、后台执行器 12 项、桌面就绪 4 项均通过，`validate_runtime_policy()` 对 6 个绑定文件及共享传递依赖校验通过。唯一最终复跑仍在外部效果前被桌面微信预检拒绝：`ax-exact-header-count:0`，总收据 `f87a64bb-262d-4205-a969-8c41a555a647` 明确 `sendAttempts=0`、`runtimeModelDecisions=0`，未进入浏览器采集及发送节点。预检已按共享代码重试窗口运行约 29.5 秒仍未得到目标群标题证明；本轮最终复跑额度已用尽，不得再运行或换通道。当前未证实是登录/验证码问题，也没有足够证据把它归因为确定性代码缺陷，因此不改执行器代码、不放宽定位；后续需依代码的只读/安全恢复合同处理此未完成状态。
- 进一步对照只读预检截图与调用链后，确认确定性代码缺口：精确 AX 行被点击但三次短轮询仍未见标题时，底层立即返回 `ax-exact-header-count:0`，顶层无条件接受失败 AX 收据，阻断已经存在的完整群名精确搜索兜底；适配器仅重复该 AX 路径至 30 秒截止。按共享微信代码强制维护方案，最小修复是仅让这个精确零标题错误进入已有精确搜索兜底，其他失败与群身份校验保持不变；先补共享方案，再改真实定位代码和回归测试、用受控依赖维护器同步依赖，最后由总入口做一次最终复跑。当前任务未完成，`attempted` 不存在、禁止把 UI 截图本身当作已发送证据。
- 已按计划修改共享 `wechat_desktop.py`，加入“仅精确 AX 零标题可进入既有 exact OCR/search”分支；成功 AX 快路径仍不截图，多个标题等失败仍失败关闭。共享桌面专项 77 项通过；统一维护器全量测试 174 项通过，用时 3,779 ms；依赖清单 29 项回读 clean，capabilities 校验通过，维护总计 3,819 ms，`sendAttempts=0`。Top10 `runtime-policy.json` 的 `messaging_dependencies` 更新到维护后摘要；待 Top10 全量回归及无副作用策略校验通过后，才允许一次最终入口复跑。
- 本次最终复跑收据 `75f6f8a7-a7e8-4311-9edc-c9198271f68c` 再次为 `sendAttempts=0`，原因 `exact-group-header-count:0`。对其代码截图离线 OCR 后发现第二处定位逻辑缺口：完整群名会话候选位于“聊天记录”之前，而底部“搜索网络结果”行重复完整查询文本；旧 `y>=120` 条件漏掉顶部候选，误将网络查询行点击。已先更新共享搜索方案，下一最小修改是按 UI 文本分区筛选完整群名候选，明确排除聊天记录与网络搜索区，再继续标题/群类型双重验证；其它候选/发送防重合同不变。
- 搜索结果过滤方案已细化：排除聊天记录/网络搜索标题之后的文本，允许 <40px 顶部完整群名建议行；40–120px 顶带按输入回显排除。共享专项现为 79 项通过。下一步仍需受控维护器全量回归、更新 Top10 依赖摘要、Top10 测试/策略校验，随后仅一次最终复跑。
- 已按细化方案更新共享定位逻辑与 2 项分区候选测试；共享桌面专项 79 项通过，受控维护器统一微信全量回归 174 项通过（3,763 ms），依赖清单 29 项 clean、capabilities 通过，维护总计 3,799 ms、零发送。Top10 `messaging_dependencies` 已绑定新摘要 `6c10f15b…ef34c805`；待 Top10 回归与策略校验通过后再按合同进行一次最终复跑。
- 本修复最终复跑通过群预检并完成 Top10 截图，但单次图片发送回执为 `unknown`：工作流 `4292d5e1-bebf-42a8-b5e6-d5db33f1f46c`，桥接器账本 `.runtime/send-ledger/2026-09-26-main-16379fcc7508.json` 已有 `attempted`，`sendAttempts=1`，原因 `media-composer-not-empty`，发送后输入区两帧都未证明为空；聊天区变化量两帧相同，但不替代输入区门禁。当前预检标题确认为目标群(19)，发送前输入区空，固定 desktop 通道与 `runtimeModelDecisions=0`；当次 PNG `2026-09-26_top10seller.png`、2240×1770、自检 PASS、SHA-256 `70c3e846da7a5b694fbe06ca123f11c57b76555689c11fac61d1da64862c0fd2`。微信锁统计 `lockWait=0 ms/0轮`，已知进程安静检查累计 10,000 ms、4 次检查；发送节点耗时：定位 744 ms、发送前复核 1,703 ms、准备图片 1,995 ms、单次发送阶段 3,665 ms、发送后复核 7,798 ms；端到端 31,705 ms、总墙钟 52,313 ms。`sendAttempts=1` 且 `unknown` 后禁止重发、清空草稿或换通道。共享图片运输对账要求原运输 verified 及输入区双帧清空，本次不满足；工作流桥 `--reconcile` 的既有 marker 恢复仅覆盖文本，故本轮不能由代码只读合同提升图片状态，保留 unknown 并等待只读人工对账。任务不标记为已发送/已完成。

## 2026-09-25 预检零结果自恢复（不转交用户清理）

### 根因与边界

一次桌面微信预检返回 `exact-group-result-count:0` 且 `sendAttempts=0`。此前把普通会话/搜索状态问题转交用户清空，打断了固定流程；但现有证据不能证明零结果一定由某一条草稿导致，也不能证明任意可见草稿都属于本工作流。共享发送器已有“仅清除本次发送器自己粘贴、且 attempted 尚未创建的预览”逻辑；共享 `normalize_empty_composer` 刻意保留非空普通草稿。不得把“自动清空任何草稿”作为修复，以免删除用户内容。

### 最小修复

- Top10 总执行器在共享只读群预检失败、且结果精确为 `exact-group-result-count:0`、`sendAttempts=0`、`hardGate` 非真时，等待 5 秒并从同一固定精确预检入口完整重做一次。总尝试最多 2 次；记录尝试次数与总耗时。
- 微信发送器仅当本轮图片粘贴失败后由自身清理预览，且收据明确 `sendAttempts=0`、`uncommittedPreviewCleanup=attempted`、`uncommittedPreviewCleared=true`、无 `attemptMarker` 时，Top10 总执行器才等待 1 秒并重跑同一发送命令一次。否则不重试。该条件保证只恢复本执行器已验证清空的预览，不接受或清空未知来源的现有草稿。
- 仅原有 `wechat-search-region-contended` 继续按既有代码合同等待；登录/CAPTCHA/风险验证、多个候选、任何 attempted/unknown 和其他失败不套用零结果重试。
- 本修复不点击发送、不清除未识别草稿、不更换会话/通道/群，也不触及防重账本。未识别且非空的用户草稿继续由共享发送器保护并失败关闭；用户协助边界仍仅用于登录/验证码，但代码不得擅自删除该草稿。

### 修改与验证

- 方案：本节先记录根因、有限重试合同及不清理未知草稿的安全边界。
- 执行器：`scripts/workflow_executor.py` 增加精确零结果的一次性只读重试与耗时证据。
- 测试：`scripts/test_runtime_guard.py` 覆盖“零结果后成功”“零结果重试上限”“attempted/unknown/login/multiple 不重试”及“本次发送器清理成功后才重试图片准备、未知残留不重试”。
- 策略：更新 `runtime-policy.json` 中 `workflow_executor` SHA-256；跑策略校验及全部 Top10/共享微信相关测试。
- 发送边界：本修复只允许 sendAttempts=0 的只读群定位重试，不改变任何发送授权。若本日已发送或 attempted 存在，不得用真实总入口作验收复跑；使用无副作用测试证明代码路径。

### 2026-09-25 实施结果

- 已实现：`workflow_executor.py` 对精确零结果做一次 5 秒后只读重试；对本轮图像准备失败，仅在发送器明确报告已尝试并验证清理成功、零发送且无 attempted marker 时重试一次。两类恢复均写入收据 `retryHistory`。
- 已更新 `runtime-policy.json` 的 `workflow_executor` SHA-256：`41c1b46314f511f0d15d116e32d0fafd0e53aeed6332b70d61a7677f9046e4e3`；策略完整性测试通过。
- Top10 Python 回归 27 项通过；后台 Node 回归 12 项通过；桌面就绪测试 4 项通过；共享微信预检/发送/锁回归 69 项通过；后台无副作用自测 7 项通过。`runtimeModelDecisions=0`。
- 今日已存在成功发送（`sendAttempts=1`），因此没有再从生产固定入口复跑，避免重复发送。恢复路径由无副作用测试验证，明日下一次日常执行才会使用新代码。

## 2026-09-28 固定入口桥接器摘要漂移

### 证据与边界

- 本次固定总入口收据 `7bf561b3-f8e8-4889-a612-db970c7ac6cb` 在 runtime-policy 校验立即失败：`runtime-policy-file-digest-mismatch:desktop_sender`，`sendAttempts=0`、`preflightMs=0`、`runtimeModelDecisions=0`、`wallMs=1`。没有进入浏览器、微信预检、发送或账本阶段；该零发送边界以原始收据为准，禁止改写。
- Top10 策略中 `desktop_sender` 仍绑定前一版本 SHA-256 `5bd411a5a441edfa0612a1919928f768a8ba89e7a7d31c5d4242f36b5a68dfc7`，当前固定目标路径实际 SHA-256 为 `9bdf4cd64cc76b3adb5685429585f0473dc642fd80e9d1d7a4e962700fbf07e3`。该路径经 Codex skill 符号链接解析后仍是同一份工作区文件。
- 当前统一微信 `dependencies.json` 的整体摘要为 `9f827a83b25ca5c2b974e6e0ef6731242f94a74919f397670f2223d3ddf15741`，其登记的 `scripts/workflow_bridge.py` 摘要已等于实际字节；共享依赖清单本身未显示漂移。因此现有证据指向 Top10 机器策略的 `desktop_sender` 摘要滞后，不是业务执行器/桥接器逻辑缺陷。
- 同步 `desktop_sender` 后，Top10 Python 回归与 `validate_runtime_policy()` 均进一步报告 `runtime-policy-file-digest-mismatch:messaging_dependencies`。共享只读 `dependency_maintenance.py inspect` 仍为 clean；固定策略中 `messaging_dependencies` 保存值为旧摘要 `6c10f15b9c73d140ec40de0d05415d371ce79c8aeedacebc8ce4e677ef34c805`，共享依赖清单当前摘要为 `9f827a83b25ca5c2b974e6e0ef6731242f94a74919f397670f2223d3ddf15741`。故修复范围扩展为仅同步这两个已分别核验的摘要，不修改业务执行器、桥接器、依赖清单或运行授权。

### 受控恢复步骤与放行条件

1. 按共享依赖维护方案执行只读 `dependency_maintenance.py inspect`，核对所有已登记依赖与 capabilities；运行共享微信完整回归，不在不需要时改共享依赖清单或执行器代码。
2. 以上回读和回归通过后，仅更新 Top10 `runtime-policy.json` 的 `desktop_sender` 与 `messaging_dependencies` SHA-256 到各自当前经验证字节；若任何其他绑定文件/依赖漂移，则先调查并按其对应维护方案处理，不以批量重绑放行。
3. 跑 Top10 全量 Python 与 Node 回归、策略字段/所有绑定摘要校验及无副作用 runtime-policy 校验；收据仍须为 `sendAttempts=0` 且门禁明确允许。
4. 仅从同一固定总入口进行一次最终复跑；attempted、unknown 或任何外部效果边界不明都禁止重发/换通道，改为只读对账。

### 方案先行声明

本节在修改任何运行策略前记录了根因、证据、修复范围与停止条件。预计仅沉淀机器策略摘要绑定，不预设需要改动真实执行器业务逻辑；只有测试或依赖回读暴露明确代码缺陷时才另行按对应方案修代码。

### 2026-09-28 受控恢复结果

- 共享只读依赖检查为 `clean`，29 个候选文件、0 变更；共享能力读取未改变微信策略或外部状态。
- 更正事件测试此前失败的根因是测试夹具要求当前日期真实生产报表存在。按共享方案，仅调整共享桥接器测试文件为临时工作区夹具；更正事件专项 48 项、共享微信全量 180 项全部通过。未创建或删除真实业务报表，未修改桥接器业务逻辑和共享依赖清单。
- Top10 `runtime-policy.json` 只同步 `desktop_sender`=`9bdf4cd64cc76b3adb5685429585f0473dc642fd80e9d1d7a4e962700fbf07e3` 与 `messaging_dependencies`=`9f827a83b25ca5c2b974e6e0ef6731242f94a74919f397670f2223d3ddf15741` 两个已核实摘要。
- 回归通过：Top10 Python 27 项；后台 Node 12 项；桌面就绪 Node 4 项；后台/桌面无副作用自测 7+10 项；runtime-policy 校验 6 个绑定文件及传递依赖通过，`runtimeModelDecisions=0`。
- 唯一最终复跑收据 `.runtime/workflow-runs/2097a7e9-2c44-43d0-b6cb-1ae9b45bf02e/workflow_receipt.json`：业务日期 `2026-09-27`，固定 `taobao-brand:9230` + desktop + `FEIBING NEO AI数字员工(19)`；当次 PNG `2026-09-27_top10seller.png`，2240×1764，截图自检通过，SHA-256 `65cd4a98dda33f6eaea2abc7fae57303f7b0d27db61083f56e4c8aed73be9873`；发送 1 次，单图 image-content-match verified，发送后输入框两帧均清空且双帧验证通过；微信锁等待 0 ms/0 轮，已知进程稳定检查 10,000 ms/4 次；运行时模型决策 0。
- 节点耗时：后台预检 79 ms、打开首页 2,078 ms、关闭已知提示 455 ms、进入门店分析 823 ms、选择昨日 247 ms、排序校验 842 ms、截图自检 993 ms；微信精确群预检 11,622 ms（总桌面预检 13,158 ms）；发送定位 710 ms、群与空输入复核 1,663 ms、载荷准备 1,956 ms、领取防重并单次发送 3,539 ms、发送后双帧复核 6,168 ms；投递阶段 14,913 ms、端到端 25,560 ms、总墙钟 44,013 ms。
- 沉淀分类：执行器业务逻辑未修改；机器策略摘要修复已写入并验证；共享测试夹具隔离属于测试代码修复，不宣称为发送执行器逻辑增强。第一次零发送策略失败收据保留，不改写；最终新事件现为 verified，禁止重复运行/重发同一业务日图片。
- 从首次策略拒绝收据到唯一最终复跑完成共 915,201 ms（15 分 15.201 秒）；其中最终业务复跑墙钟 44,013 ms。回归命令耗时分别记录在上方，维护总时长含诊断、文档方案、测试修复、策略同步与最终复跑。

## 2026-09-28 运行时策略门禁代码强化

### 复盘发现

- 2026-09-28 前置拒绝先暴露 `desktop_sender` 摘要漂移；同步后全量策略测试才暴露第二个 `messaging_dependencies` 漂移，造成重复维护轮次。根因是 `validate_runtime_policy()` 遇到第一个文件摘要不符即抛错，没有汇总同一策略快照中的所有摘要差异。
- 策略虽绑定业务总入口、浏览器执行器、微信桥接/预检、依赖清单及交互锁，却没有绑定负责解释策略和作出放行判断的 `runtime_guard.py` 自身；门禁实现可在摘要列表外变化。

### 代码强化方案

1. 将 `scripts/runtime_guard.py` 作为必需文件项加入 `EXPECTED_POLICY_FILES`，机器策略必须绑定其绝对路径和 SHA-256；文件集合少项、多项或路径变化继续失败关闭。
2. 对所有路径/文件存在性合法的策略文件收集 SHA-256 差异，按策略代码固定顺序一次返回完整标签列表（如 `runtime-policy-file-digest-mismatch:desktop_sender,messaging_dependencies`）；仍在任何浏览器/微信动作前拒绝，不自动修策略、不自动放行。
3. 为门禁自身摘要绑定、双摘要汇总、稳定错误顺序和仍失败关闭补充单元测试；仅在方案、实现和测试一致后更新机器策略的 `runtime_guard` SHA-256。
4. 运行 Top10 全量 Python/Node 回归、无副作用自测、runtime-policy 校验与共享依赖只读检查。不得用生产发送作测试；既有 verified 事件仍防重命中，unknown/attempted 仍只读对账。

### 2026-09-28 实施与验证

- `scripts/runtime_guard.py` 已把自身加入 `EXPECTED_POLICY_FILES`；策略验证现一次收集合法路径文件的全部摘要差异，并按固定顺序报告，不会自动修改 SHA 或继续执行。
- `runtime-policy.json` 已加入 `runtime_guard` 文件绑定，SHA-256=`49bffc03228720bfd62c8748e17f87393f407505e2696b668e2c167ef1522d78`。
- `scripts/test_runtime_guard.py` 增加门禁自身绑定、同时存在多个摘要差异时完整且顺序稳定报告的测试；定向测试 13 项、Top10 Python 全量 28 项、后台 Node 12 项、桌面就绪 Node 4 项、自测 7+10 项通过；策略校验覆盖 7 个文件及传递依赖，`runtimeModelDecisions=0`。
- 本次仅运行无副作用验证，没有再次运行已完成的当日微信投递。固定群、desktop 通道、`taobao-brand:9230`、防重与发送合同未变。
