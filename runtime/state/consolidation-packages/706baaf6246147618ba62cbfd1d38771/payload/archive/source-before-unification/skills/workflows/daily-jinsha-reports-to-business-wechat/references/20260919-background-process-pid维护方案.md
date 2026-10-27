# 金鲨后台进程 PID 存活门禁维护方案（2026-09-19）

## 背景与证据

生产运行 `jinsha-business-production-20260919-01` 在下载动作前连续三次失败，原因均为 `jinsha-background-process-not-alive`，没有下载点击、发送或未知结果。

只读核验确认固定专用实例实际存在：`127.0.0.1:9232` 正在监听，监听进程命令行为 Google Chrome，绑定 `--remote-debugging-port=9232` 与 `--user-data-dir=/Users/ddt/Library/Application Support/AOS Background Chrome/jinsha-business`；CDP 页面为金鲨站点。状态文件仍保留 2026-09-15 的旧 PID `41925`，该 PID 已退出。故障是状态 PID 陈旧导致的错误阻断，不是登录失效。

## 目标与边界

1. 保留 `jinsha-business`、9232、金鲨站点、CDP 附着、visible-handoff/任务绑定等全部现有门禁。
2. 不再把状态文件中的历史 PID 作为唯一存活证据；允许状态 PID 陈旧时，以当前 9232 监听进程的严格命令行绑定证明同一专用实例。
3. 若 9232 无监听、监听进程不是 Chrome、端口不符或 Profile 路径不符，继续失败关闭。
4. 不修改隐藏封板底座、业务日期、平台方案、下载点击预算、微信目标、授权或 unknown/attempted 防重合同。

## 同轮继续排查：微信目标群定位与批量回执

运行 `20260919/02` 已通过金鲨下载和报表准备，但微信预检四次均停在错误会话“李老哈（品牌）💰臻肆外卖运营对接群 (36)”。截图证据显示目标群出现在搜索结果的“最常使用”分区，当前实现对生产日报仍使用完整群名搜索，结果行被截断后未稳定命中；本轮没有创建发送尝试、没有发送回执，不属于 attempted/unknown。

为同一运行目录恢复，先做两项最小修复：

1. 生产 `jinsha-reports` 请求也固定传入核心检索文字 `上海臻肆外卖运营-盯个盯-饭敢当`，但仍只接受打开后完整标题 `上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰` 复核；不放宽目标群门禁。
2. 批量桌面回执允许“两个文件各一次物理发送、聚合 `sendAttempts=2`”这一已验证的真实回执形态，同时要求两项均 verified、每项 transport `sendAttempts=1`、运行时模型决策为 0；保留旧的单次聚合形态兼容，不改变 unknown/attempted 防重。

本轮恢复又确认 OCR 将目标搜索行识别为 `1上海臻肆外卖运营-盯个盯…`，其中前置 `1` 对应头像/图标噪声。定位代码仅对以中文核心文字开头的候选允许最多 3 个非中文前置噪声字符；打开后仍必须精确复核完整群标题。

另外，第一次修复后的同目录恢复已消耗完 4 次“零发送预检”预算，执行器因计数达到上限而没有再次进入发送器。增加安全恢复规则：仅当阶段仍为 `prepared`、历史状态为 `needs-resume`、发送防重 marker 不存在且所有发送尝试均未产生 marker 时，恢复会记录维护事件并将本阶段零发送预算归零；一旦存在 marker，绝不重置、绝不重发。

对账发现原生产回执沿用了第一次运行的 `startedAt`，导致恢复时把已过期的 180 秒截止时间传给授权校验；marker 明确记录 `state=blocked, sendAttempts=0, reason=authorization-or-request-expired`。发送管线改为每次真实 `--send/--verify-only` 以当前时间建立新的 180 秒窗口，并仅允许这种明确零发送 blocked marker 进入维护恢复；任何 `attempted`、`unknown` 或 `sendAttempts>0` marker 仍保持不可重发。

恢复前必须通过 Python/Node 定向测试、执行器自测和冻结核心哈希校验；恢复使用 `--resume .../20260919/02`，不得另起生产轮次。

## 最小实现

- 在 `business_jinsha_browser_exam.mjs` 增加只读 `assertDedicatedBrowserProcess`：通过固定系统 `lsof` 找到 9232 唯一监听 PID，再读取该 PID 的命令行，严格匹配 Chrome、9232 和 `jinsha-business` Profile 路径。
- 保留状态文件 PID 校验字段作为诊断信息，不再因其陈旧单独拒绝；当前监听进程证明失败时仍拒绝。
- 在 `test_jinsha_browser_channel.mjs` 增加真实命令行匹配的正反纯函数测试，覆盖专用 Profile、错误 Profile、错误端口、非 Chrome 和多 PID/缺失场景。

## 验收顺序

1. Node 语法、浏览器通道测试、策略测试、生产执行器测试、冻结核心哈希和 `--self-test`。
2. 通过唯一生产入口创建全新运行；不修改或恢复 `20260919/01` 的终态状态文件。
3. 只有新运行达到 `phase=complete` 才报告当日完成；若出现下载/发送 attempted 或 unknown，立即停止并只读核验。
