# 2026-10-28 22:56 新机器启动前最新交接

当前接班聊天为 `01a18298-0a79-7481-b24a-0b1743a38edf`。用户已明确要求源机器完成最细交接后暂停，由新机器启动；暂停不代表 Goal complete、blocked 或被缩小。完整原 objective 保存在仓库内 `runtime/state/night-goal-handoff/20261028-evening-original-goal.json`，SHA-256 为 `dcded41ff8d12c789e34853a7261822af55e0d8f0311646e4f9b2fec1f195e30`，原件不改写。最新机器交接为 `runtime/state/night-goal-handoff/20261028-2256-new-machine-detailed-handoff.json`，最新交接词为 `docs/operations/20261028-新机器监理接续交接词.md`。

所有交接路径均从仓库根解析。不得把历史材料中的旧机器绝对路径复制到新机器。旧机 PID、锁、浏览器和登录状态只是快照，不是新机验收或所有权凭证；凭据、Cookie、localStorage、钥匙串和浏览器 profile 不迁移。

新机应使用最新已审查的 `origin/main`，并确认上述三份最新交接材料存在，不得只检出旧业务基线。2026-10-28 的24行客户台账、22:00四岗维护、企业微信UI共享依赖闭环和商品整改末档均已有原证据，禁止重复发送、重复维护或返扫旧unknown。旧机主任PID24510在22:55:02周期仍 `all_green=true`，但这只证明旧机当时健康，且源 Goal 暂停不自动停止daemon或迁移定时。

仍须接续：下一正常图片任务的真实像素回读；商品列表身份/排序/SSO零发送诊断；外置 `registry-routing.json` 严格校验与变更审计（方案已写，代码/测试/共享同步均未实施）；2026-10-29另一机器三流摘要；新业务日真实数据、权限、release和班次回执。另一机器三流不接管，摘要缺失不阻断本机24流。

02/06/08/20/22五项定时的完整历史配置保存在仓库内 `runtime/state/night-goal-handoff/automation-transfer-20261028.json` 和 `runtime/state/next-day-preflight/2026-10-29/automation-before-transfer.json`。暂停源 Goal 不会自动迁移这些定时。正式切换必须先完成新机只读核收，确认没有在途任务、组锁、物理岗位租约或未领取UI任务，并封住旧机调度入口，再恢复完整Goal和唯一化五项定时归属；任何时刻只允许一个生产控制通道。

历史晚间完整交接仍保存在 `runtime/state/night-goal-handoff/20261028-evening-full-handoff.json`，与本页冲突时，以最新用户指令、本次机器迁移交接及实时证据为准。不能把资料齐全、测试通过或旧机健康当作新机迁移完成。
