# 金鲨 visible-handoff 兼容维护方案（2026-09-15）

## 背景与证据

生产运行 `jinsha-business-production-20260915-01` 在下载前连续三次以 `jinsha-background-profile-state-mismatch` 停止，两个平台下载点击均为 0，未进入制表或微信阶段。

只读核验表明固定进程、Profile 与端口均正确：`jinsha-business:9232` 正在回环监听，控制器状态为 `visible-handoff / WINDOW_RELEASED`，当前实例已完成人工确认、双次业务结构认证、工作页绑定及最小化。日报下载器仍只接受旧 `headless` 模式，形成控制器升级后的合同错位。

## 目标与边界

1. 日报下载器同时接受原有 `headless` 稳态与金鲨专用 `visible-handoff / WINDOW_RELEASED` 稳态。
2. visible-handoff 必须严格绑定 `jinsha-business`、9232、`site=jinsha`、金鲨强前缀、当前实例、已确认状态、已附着状态、唯一活动目标与任务标记；任一缺失均失败关闭。
3. 不修改隐藏封板核心、下载业务规则、日期、方案、36项指标、文件路径、发送通道、目标群、授权、账本或 unknown 防重规则。
4. 业务运行仍创建本轮独立任务页，只关闭自己创建的页面，不关闭交接工作页或浏览器进程。

## 实施

- 在 `scripts/business_jinsha_browser_exam.mjs` 增加纯函数 `assertBrowserProfileState`，集中校验两种允许稳态。
- 在 `scripts/test_jinsha_browser_channel.mjs` 增加正反测试：旧 headless 通过、完整 visible-handoff 通过，错误阶段、站点、前缀、确认、附着和目标绑定均拒绝。
- 真实执行前先运行语法检查、浏览器通道测试、生产执行器/策略测试及无副作用 self-test。
- 由于原运行已终态且零下载零发送，修复后只通过 `business_workflow_executor.mjs --execute` 创建新运行，不手改状态、不强行 resume。

## 完成与停止条件

- 完成：新运行达到 `phase=complete`，两平台各一次下载、制表完成、桌面微信去重发送或确认、最终只读复核通过。
- 停止：登录/验证码/风险页、下载或发送 attempted 后结果 unknown、文件/群/授权/哈希不匹配；这些情况不得绕过或重发。

## 风险复核

- 放行只增加一种已经由控制器验收的金鲨稳态，不放宽站点或业务动作。
- visible-handoff 进程仍为可见同进程交接模式，不宣称 headless；业务动作继续通过本地 CDP，且不使用系统键鼠。
- 保留原 headless 路径，避免影响历史正常功能。

## 实操验收结果

- 无副作用验收：Node 语法通过；浏览器通道 47 项、生产策略 32 项、生产执行器 24 项全部通过；隐藏冻结核心 18 项 SHA-256 校验通过。
- 完整生产运行：`jinsha-business-production-20260915-02`，业务日期 `2026-09-14`，最终 `phase=complete`、`status=complete`。
- 下载：美团与淘宝各点击 1 次，均以同任务页 staging 恢复保存并通过 XLSX、大小及 SHA-256 校验；下载节点 18.427 秒。
- 制表：两份日报保存后数值、数据条、业务条件格式、正文样式和营收降序检查通过；prepare 节点 7.269 秒。
- 发送：桌面微信固定群两文件共同发送 1 次，附件对象、平台前缀、发送后输入框清空和双帧气泡复核通过；状态机 send 节点有 2 次尝试，其中首次通道选择失败发生在发送动作之前，第二次成功，未重复发送。
- 最终只读复核：0.945 秒通过；总耗时 68.459 秒，180 秒效率达标，`runtimeModelDecisions=0`，模型只在失败运行结束后参与诊断与代码维护。
- 报告观察：`workflow-summary.json` 的 `pitfalls` 未收录首次通道选择失败，但 `workflow-state.json` 与 `exam-receipt.json` 已保留对应事件。该问题不影响业务完成与防重证据；后续若修改汇总器，应另行先写方案和失败测试，不在本次成功交付后扩大改动。

## 2026-09-16 控制器字段兼容维护

- 失败证据：`jinsha-business-production-20260916-01` 在下载首节点连续三次以 `jinsha-background-profile-state-mismatch` 失败关闭，两个平台下载点击、发送和复核均为0。
- 只读诊断：固定 `jinsha-business:9232` 仍为 `visible-handoff / WINDOW_RELEASED`，Profile、端口、站点、前缀、实例确认、CDP附着和登录状态均有效；控制器当前以 `taskId/taskTargetId/taskMarker` 保存已绑定工作标签，而日报门禁只读取旧的 `activeTargetId/activeMarker`。
- 页面刷新：按状态文件中的精确 `taskTargetId` 只刷新一次，刷新后仍为金鲨实时数据页，登录有效，无验证码或风险验证。
- 最小修改：不新增浏览器、下载或发送分支，只在原 `visible-handoff` 门禁内兼容两套控制器字段。旧 `activeTargetId/activeMarker` 保持原合同；新字段必须同时具备非空 `taskId`、非空 `taskTargetId`，且 `taskMarker` 严格等于 `aos-background-task:<taskId>:work`。任一字段残缺，或两套字段同时存在但目标/标记不一致，继续失败关闭。
- 验收顺序：先完成字段正反测试、Node语法、浏览器通道、生产策略、生产执行器、冻结核心哈希和无副作用自检；全部通过后只允许唯一生产入口创建全新运行，不恢复终态 `01`。
- 无副作用验收：Node语法通过；浏览器通道54项、生产策略32项、生产执行器24项全部通过；隐藏冻结核心18项SHA-256校验通过，`runtimeModelDecisions=0`。
- 中间运行 `jinsha-business-production-20260916-02` 已完成双平台各一次下载和制表，但桌面微信输入区AX树未恢复，发送尝试为0；后续出现精确业务群独立副窗，被既有 `unexpected-secondary-window` 门禁拒绝。只关闭该精确副窗，并通过正常微信启动页复用既有账号进入微信；未强制结束进程、未输入凭据、未改发送逻辑。标准主窗恢复后，唯一大尺寸 `AXTextArea` 回归。
- 完整生产验收：`jinsha-business-production-20260916-03`（业务日2026-09-15）最终 `phase=complete`、`status=complete`。下载节点32.203秒（状态机尝试2次；首次 `date-readback-mismatch:开始日期` 在下载动作前由代码恢复，完成轮美团/淘宝各点击1次）、制表7.643秒、发送28.214秒、最终只读复核0.921秒、总计68.992秒，效率达标，`runtimeModelDecisions=0`。
- 发送验收：固定桌面群两文件共同发送尝试1次，附件对象数2、平台前缀、发送后输入区连续两帧清空及文件气泡双帧均通过；最终只读复核新增发送0。
- 代码沉淀边界：本轮只沉淀控制器任务绑定字段兼容和正反测试；微信副窗与AX恢复属于外部状态维护，没有新增发送分支、替代通道或手工发送逻辑。
