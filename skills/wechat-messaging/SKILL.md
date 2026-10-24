---
name: wechat-messaging
description: 统一普通微信群的微信收发能力。当前优先处理已授权的文字、图片和文件发送，封装精确群定位、桌面预检、内容复核、防重和只读对账。适用于业务任务将已准备对象交付到指定群；不用于视频号发布、营销群发或全量聊天记录采集。2026-10-23 起增设企业微信桌面 UI 自动化通道（仅限已审批的运营群外发场景，见下文专节）。
---

# 微信收发

> **2026-10-24 当前用户约束（覆盖下方历史通道操作说明）**：企业微信必须依据 UI 树定位真实控件，再执行可见界面操作。禁止自行调用 Quartz/CGEvent、直接写控件值或其他底层输入脚本；不得用接口、请求或隐藏通道替代。用户观察到左上角图标变化，作为异常线索记录，不据此推断已确认风控，也不试探绕过。旧发送器由 `.runtime/UI_TREE_ONLY.json` 制动，移除该文件不能视为已获恢复授权。UI 工具不可用时保留待交付对象，不改走旧注入入口。已发/未知事件防重规则继续有效。


用户只需提供**完整群名 + 要发送的文字/图片/文件**。业务调用补充稳定事件标识、账号、通道和授权，所有微信执行细节交由本技能。

图片以正常查看时内容清晰可辨为准，不设高分辨率、DPI或总像素要求，不因尺寸小而强制放大或重制。报表图片重点看文字、数字是否可读；源图质量与发送成功的证据核验分别处理，详见输入与结果合同。

先读 [输入与结果合同](references/contract.md)、[恢复规则](references/recovery.md)；维护或迁移时另读 [能力来源与迁移](references/integration.md)。禁止运行中学习、临时改通道或让模型判断是否重发。

## 当前能力

运行 `scripts/executor.py capabilities` 查看机器可读状态。桌面文字/图片/文件已通过臻肆测试群的本机真实发送与回读验收，四条桌面业务已完成代码接入，生产整链验收单独记录；真实验收结果见 [验收报告](references/acceptance.md)。手机主微信文字/图片/文件已完成HLK-AL00（1080×2340）的真实验收，见[手机验收报告](references/mobile-acceptance.md)；其他机型与分身未验收。原生视频、自动重启、接收仍返回 unsupported。MP4 当文件附件与原生视频不同，不能静默互换。

本技能源目录就是当前目录。四条桌面业务通过 workflow_bridge.py 接入；原来源、游标、群名、授权和封板门禁继续生效。迁移详情见 references/integration.md。

## Windows 网关通道（生产主用，2026-10 起）

生产发送走 **Windows 网关通道**，入口 `scripts/workflow_bridge_windows.py`：与 `workflow_bridge.py` **同一 CLI、同一 REGISTRY 授权、同一账本与标记**，唯一差别是适配器换成 `scripts/windows_adapter.py`（物理 UI 自动化跑在 Windows 10 主机，不是本机 Mac）。账本按事件身份共享，任一通道 verified 都会挡住另一通道的重复发送（跨通道免费防重）。**Mac 桌面微信自 2026-10-05 起不再用于生产发送。**

- **传输链**：本机 → `HTTP <Windows 主机>:8731` → Windows 10 微信 3.9.x UI 自动化驱动。`channel` 仍记 `desktop`（同一 `main-wechat` 账号的另一台客户端），故原有授权/防重模型原样复用，每条收据记 `transport='windows-driver'`。
- **证据等级（诚实状态，不美化）**：文字 = 发送后目标会话**末条消息**精确全文锚 + 标题交叉核对 ⇒ `verified`，否则 `unknown`；文件/图片 = 末条消息文件名锚 + 标题交叉核对 ⇒ `verified`；确定性业务错误（HTTP 已返回状态）⇒ `blocked` 且 `sendAttempts=0`；传输异常（断连/超时）⇒ `unknown` 且 `sendAttempts=attempts`（消息可能已发也可能未发）。
- **已知限制**：封印桥内的文字对账 `legacy_text_reconcile` 依赖 Mac 原生复制回读，经本通道无法执行，会**诚实地判 not-verified**（不会假绿）。新发送与文件/图片对账完全支持。
- **出站闸门** `scripts/egress_policy.py`：fail-closed，**测试载荷一律拒发线上群**（大同 2026-09-30 铁律的代码化）；拒绝时返回明确 `reason`，绝不改投测试群、绝不降级。
- **落群路由外置** `config/registry-routing.json`（仅 `group`/`kind`/`count`；授权串与防重台账路径留在封印代码 `workflow_bridge.py` 内，绝不外置）。

## 企业微信桌面 UI 自动化通道（2026-10-23 起，仅运营群）

目标群「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」是**微信外部群**（企业微信内可见、45 位外部联系人），官方 API 三路全堵（群机器人不接外部群、智能机器人仅内部群、客户群群发需管理员建自建应用）；外部群**无法**转为内部群（创建时定死）。几百个客户群均为企微外部群 ⇒ **UI 自动化是唯一程序化通道**。固定解释器 `/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python`。

### 任务流唯一入口（大同 2026-10-23 指令：任务流不操心通道细节）

`scripts/wecom_sender_api.py` —— 三类载荷统一函数，所有通道内部门禁/定位/防护细节（下述五层）都封装在此，任务流**只调这三个函数**：

```python
import sys; sys.path.insert(0, 'skills/wechat-messaging/scripts')
from wecom_sender_api import send_text, send_image, send_file
r = send_text(group, "文本")                      # -> {"ok": bool, "result": ..., "kind": "text", ...}
r = send_image(group, "/abs/a.png", caption="可选")
r = send_file(group, "/abs/a.xlsx", caption="可选")
```

验收状态（2026-10-23，大同确认三类通过，不再发测试数据）：text 12:43 / image 11:08 / file(+caption) 12:49 均已在目标群截图+群尾读回实证送达。业务级防重 marker 仍由调用方负责（按业务日期），本 API 只保证「单次调用=单次尝试=至多一条外发」。

### 通道内部五层防护（任务流不可见、不可绕过）

1. **主窗锁定**：永远定位尺寸最大的 AXWindow（聊天主窗 1294×781）；设置窗/浮层永不参与定位（曾致鼠标落到群名区）。
2. **导航 = 前缀搜索**（大同拍板，禁左侧列表大海捞针）：搜索框粘贴唯一前缀 → 下拉默认高亮 → Enter 打开 → 行为级确认（聊天输入框出现）+ 聊天区群名证据；0/多命中即停。注意：标题不在 AX 树；下拉浮层为 CEF 私有层读不到。
3. **点击安全区闸门 `click_checked`**：搜索框只允许点击窗口顶部条（rel_y 0-110）、输入框只允许底部区（rel_y≥550），锚点与落点双重校验，越界 fail-closed——鼠标永不接近群名/设置区（群名临时改动曾引发金鲨日报整批卡停事故；**禁止改群名**）。
4. **修饰键清理 `ensure_clean_modifiers`**：每次发送前清卡死的 Cmd/Ctrl/Shift/Alt（卡死的 Cmd 曾让全部 Enter 变 Cmd+Enter=换行，静默失败 40 分钟）。
5. **焦点闸门 `assert_focus_on`**（大同最终叮嘱）：任何键入/粘贴/回车前强制回读系统 `AXFocusedUIElement` 并与目标输入框比对，光标不在目标上立即中止——放错位置一定出错。

### 通道已知坑（复现记录，勿凭记忆覆盖）
- 发送键设置：企微「快捷键→发送消息」须为 ⏎ (Return键)；⌘↩ 模式下合成 Enter 表现为换行。
- 先写 caption 会**阻断** file-url 粘贴；AXSetValue 写文本会**顶掉** media preview ⇒ media 流固定顺序=先粘文件 → caption 用剪贴板粘贴追加。
- `AXSetValue` 直写文本可用于 text 流（回读校验）；粘贴路径（pbcopy+Cmd+V）对 CEF 状态最稳。
- 聊天区树序≠时间序（虚拟滚动坐标）；`last_message_texts` 已按聊天区 x 域过滤。
- 前置窗口期「短暂前置+发完还原」纪律不变（try/finally 还原 frontmost）。

**前置条件**：企业微信保持运行+登录；辅助功能权限授予 `harmonyos3-phone-control` venv 的 python 二进制（AXIsProcessTrusted=True 为验讫标志）。

## 固定入口

使用已验证 Python：`/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python`。

```sh
python scripts/executor.py capabilities
python scripts/executor.py validate --request /absolute/request.json
python scripts/executor.py preflight --request /absolute/request.json
python scripts/executor.py verify-existing --request /absolute/request.json
python scripts/executor.py execute --request /absolute/request.json --authorization /absolute/authorization.json
python scripts/executor.py reconcile --request /absolute/request.json --authorization /absolute/authorization.json
```

共享依赖发生代码漂移时，不手工改 `dependencies.json`。先读
[依赖维护方案](references/plan-2026-09-18-dependency-resync.md)，再由
`scripts/dependency_maintenance.py inspect` 只读检查；只有明确维护授权下，才调用
`prepare --authorization ... --expires-at ... --output-dir ...`。该入口固定运行全量测试、
原子写入、回读和失败回滚，且 `sendAttempts=0`，不能调用微信发送。

定时任务遇到发送代码或依赖加载故障时，固定从
`scripts/heartbeat_recovery.py execute --request ... --authorization ...` 进入：它先运行一次
总执行器；**仅**在批次及每个项目都明确 `sendAttempts=0`、且故障为依赖摘要或 Python
加载/语法类错误时，才允许一次依赖维护、全量回归及一次最终复跑。业务动作仍只由
`scripts/executor.py` 完成。任一 `attempted`、`unknown`、缺失发送次数、群/页面/登录/授权
门禁失败均不恢复发送，只能对账或停止。

每日业务正文变化时，先由 `scripts/policy_registration.py prepare --request ... --authorization ... --output-dir ...`
登记该次唯一摘要、群名、账号、通道和短时到期范围。该入口不加载桌面控制、不会搜索或发送微信，且原子回读策略；不得手工编辑 `runtime-policy.json`。策略登记完成后才可调用恢复器与总执行器。

示例中的 `python` 必须换为上述完整解释器路径。validate 只读取本地对象，不接触微信。preflight 只定位群；verify-existing 只对本次明确给出的文件，在当前可见消息范围核对完整名、大小和双帧，不发送、不写投递账本。execute 在检查策略、请求授权和源文件摘要之后才加载桌面控制。runtime-policy 默认 offline；只有用户已明确授权的验收组、载荷及有效期才能登记为 acceptance，不能根据“想测试”自动选生产内容或升级到无人值守。

## 执行合同

1. 全批次核对群名、对象、类型、内容哈希和授权；同一事件换目录/通道不产生新发送许可。源文件冻结到私有快照。
2. 占用统一事件锁与公共微信交互锁；先检查已有记录。verified 返回原收据，attempted/unknown 只允许 reconcile。
3. 桌面固定走公共“当前群 → 唯一可见会话 → 完整搜索 → 标题复核”，并验证人数标题证明是群。不能唯一确认就停止。
4. 写 attempted 后才进入发送；发送键仅一次。文字 AX 写入和逐字回读；发送后原生复制全文；图片做内容比对；文件检查完整名称、大小、传输提示和新消息变化。详情和证据等级见合同。
5. 同一批逐项保留结果，中途未知立即停止。业务游标由业务层只对 verified 项更新。本技能不写商家、报表等业务状态。
6. 展示代码生成的 review：阶段、耗时、结果、踩坑。unknown 不算失败未发，更不能算完成；不删除或重置账本。再次明确测试同一内容需要独立测试事件，不改旧记录。

接收方向当前尚未开放，不以“收发”名称暗示已经能监听消息。后续接收必须指定群与时间/数量范围，不默认读取全部历史。

## 手机入口

手机发送使用同一execute入口，请求context.channel=mobile、accountAlias=main-wechat，并传`--device-serial-file /absolute/private-temporary-serial-file`。设备必须本轮发现并明确绑定；策略同时绑定deviceHash与userId=0，不记录原serial到公共文档。手机查群预检在execute内部执行，独立preflight/verify-existing入口仍仅支持桌面；当前validate输出的supported字段也仅描述桌面路径，手机能力以capabilities和手机验收报告为准。

运行前读取harmonyos3-phone-control和wechat-mobile-control规程及本技能恢复规则。业务提供群名与对象，通道内部完成主实例核验、精确定位、原文复制/大图/文件回读、输入法恢复和通知遮挡处理。移动reconcile尚未实现，不能因测试群曾允许重发就对生产unknown重发。

## 已注册业务入口

业务总入口委托 scripts/workflow_bridge.py（固定workflow-id、群、类型、数量、原授权及账本），预检委托 scripts/workflow_preflight.py。桥接门禁使用各业务已有授权，不读取臻肆测试群的验收策略；不得把它当任意群发送CLI。它调用同一deliver/desktop_adapter，不另写微信操作逻辑。原业务总入口仍是唯一运行入口，尤其商家封板和金鲨阶段权限不能跳过。
