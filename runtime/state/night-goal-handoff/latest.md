# 2026-10-28 新机器迁移前最新交接

当前接班聊天为 `01a18298-0a79-7481-b24a-0b1743a38edf`，Goal 仍为 `active`，完整原 objective 保存在仓库内 `runtime/state/night-goal-handoff/20261028-evening-original-goal.json`，该原件不改写。当前机器可读交接为 `runtime/state/night-goal-handoff/20261028-2245-machine-migration-handoff.json`，可直接使用的交接词为 `docs/operations/20261028-新机器监理接续交接词.md`。

所有交接路径均从仓库根解析。不得把历史材料中的旧机器绝对路径复制到新机器。旧机 PID、锁、浏览器和登录状态只是快照，不是新机验收或所有权凭证；凭据、Cookie、localStorage、钥匙串和浏览器 profile 不迁移。

交接记录时，本地 `HEAD` 与 `origin/main` 均为 `8e875481a60ec6e29607508b6172c0e96dee315b`。2026-10-28 的 24 行客户台账、22:00 四岗维护、企业微信 UI 共享依赖闭环均已完成并有原证据，禁止重复发送或重复维护。原主任 22:40 周期 `all_green=true`，但这只证明旧机当时健康。

仍须接续：下一正常图片任务的真实像素回读；商品列表身份/排序/SSO 零发送诊断；外置 `registry-routing.json` 严格 schema 与变更审计；2026-10-29 另一机器三流摘要；新业务日真实数据、权限、release 和班次回执。另一机器三流不接管，摘要缺失不阻断本机 24 流。

02/06/08/20/22 五项定时的完整历史配置保存在仓库内 `runtime/state/night-goal-handoff/automation-transfer-20261028.json` 和 `runtime/state/next-day-preflight/2026-10-29/automation-before-transfer.json`。本次只更新交接资料，尚未切换机器、Goal 或定时归属。正式切换必须先完成新机只读核收，确认无在途任务并封住旧机调度入口，再一次性迁移；任何时刻只允许一个生产控制通道。

历史晚间完整交接仍保存在 `runtime/state/night-goal-handoff/20261028-evening-full-handoff.json`，与本页冲突时，以最新用户指令、本次机器迁移交接及实时证据为准。不能把资料齐全、测试通过或旧机健康当作新机迁移完成。
