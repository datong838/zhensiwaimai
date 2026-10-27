# 监理每小时进度汇报（12条任务流）· 执行记忆

## 2026-10-08 21:40（白天窗口，hour=21 · 本窗口最后一轮）
- **15/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 130 日志，仅 `legacy-marker-binding-mismatch` x16，与 12:16 起各轮完全相同 ⇒ 零新增，taobao-flash 幂等历史）。
- ❌ 仅 #4 daily-taobao-download-to-jinsha（13:00）：**当日 14 次全败**（13:01→21:40），failure_watch consecutive_failures=**14**（20:36 轮为 12）。
- **★ #4 真因再次确认不变（自 16:07 轮起）**：最新 21:39:26 记录 detail=`stage=wechat-send-failed / phase_last=jinsha_open`，日志真实 reason＝`recovery-budget-exhausted:jinshaLogReload`（x32）、`jinsha-upload-overlay-unrecognized`（x8）、`completed-log-missing-first-read`（x8）、`safe-failed-receipt-reused`（x40，复用失败收据死循环续跑）；**当日最新日志中 `taobao-login-expired` 已为 0** ⇒ 淘宝登录已恢复，卡点完全在金鲨上传日志读取/去重步骤。微信侧 `receipt-not-completed`、sendAttempts=0、零外发（闸门拒发，非微信故障）。当日全量 reason 汇总：safe-failed-receipt-reused 120 / recovery-budget 120 / receipt-not-completed 104 / taobao-login-expired 70 / auth-seed-not-unique 56 / overlay-unrecognized 50 / completed-log-missing 48。
- 跨日该 reason 仅 2026-10-08 出现，但当日 14 次远超 3 次线 ⇒ 维持并升级「建议开单/需人工介入：① 金鲨上传弹层识别 overlay-unrecognized ② 失败收据复用死循环 ③ 淘宝闪购 16 家店铺授权失败横幅」。
- 较 20:36 轮：#5 刷新 21:40:09、#16 三班收口 17:42:42；#10（17:00）✅ 17:11:32。
- 网关健康：`.5` health 200 全 true（logged_in=true）、中继 8732 200 全 true；`.2` EXIT=28 不可达（延续）。
- 守护健康：pid=38617、started 10:47:12、存活 10h53m、last_cycle 21:39:23、next 22:09:23、running；locks 空。
- #7/#9/#10/#14 外发待核 → 群回读核验。未全绿故未代发台账。全程只读。
- 下一小时 22:xx 仍是白天窗口（<23）；23:00 起应自暂停为 PAUSED。

## 2026-10-08 15:26（白天窗口，hour=15）
- **14/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 104 日志，仅 `legacy-marker-binding-mismatch` x16，与 12:16/13:20/14:24 三轮完全相同 ⇒ 零新增，taobao-flash 幂等历史）。
- ❌ 仅 #4 daily-taobao-download-to-jinsha（13:00）：**当日 5 次全败**（13:01/13:33/14:03/14:35/15:06），真因 `taobao-login-expired`（s1 日志 10 处）+ 连带 `receipt-not-completed`（8 处，sender_integrity_preflight，零外发）；failure_watch consecutive_failures=**5**（14:24 轮为 3）。跨日该 reason 仅今日 ⇒ **维持并升级「需人工介入：重登淘宝 profile taobao-brand:9230」**。
- 较 14:24 轮新增 ✅：#5 15:06:14、#8 金鲨差评申诉14:25 档 14:35:38（noop）、#9 智能客服15:00 档 15:06:48（外发待核）。
- ⏳ #10（17:00 档）排班未到点，非失败。
- 网关：`.5` health 200 全 true（logged_in=true）、中继 8732 200 全 true；`.2` EXIT=28 不可达（延续）。
- 守护健康：pid=38617、started 10:47:12、存活 4h39m、last_cycle 15:06:04、next 15:36:04、running；locks 空。
- #7/#9/#14 外发待核 → 群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-08 14:24（白天窗口，hour=14）
- **12/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 94 日志，仅 `legacy-marker-binding-mismatch` x16，与 12:16/13:20 轮完全相同 ⇒ 零新增，均属 taobao-flash 00:25–08:31 幂等历史，09:14 marker 已 verified）。
- ❌ 仅 #4 daily-taobao-download-to-jinsha（13:00）：当日 3 次全败（13:01:53/13:33:17/14:03:48），**真因 `taobao-login-expired`**（工作流 item2/3/4 均落此 reason，耗时 ~0.1s 即失败）+ 连带 `receipt-not-completed`（sender_integrity_preflight，sendAttempts=0 零外发）；failure_watch consecutive_failures=**3 达线** ⇒ 已报「需人工介入：重登淘宝 profile taobao-brand:9230」。跨日该 reason 仅今日出现。
- #8（14:25 档）**非失败**：今日零 record；昨日成功 14:31:43；当前 14:24 未到点，守护 last_cycle 14:03:46、next 14:33:46 ⇒ 首跑落 14:33 那轮。
- 较 13:20 轮好转：#3 金鲨日报 ✅ 12:30:24（原 2 败 `desktop-send-outcome-unknown` 已自愈）、#5 ✅ 14:04:45、#7 ✅ 12:31:26、#11 ✅ 13:33:19、#15 ✅ 13:02:50、#16 ✅ 13:33:21。
- **网关恢复**：`.5` health 200 全 true（logged_in=true）、中继 8732 200 全 true（12:16 轮双侧不可达已自愈）；`.2` EXIT=28 不可达（延续）。
- 守护健康：pid=38617、started 10:47:12、存活 3h37m、last_cycle 14:03:46、next 14:33:46、status=running；locks 空。
- #7/#14 外发待核 → 群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-08 12:16（白天窗口，hour=12）
- **9/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 78 日志，仅 `legacy-marker-binding-mismatch` 16，与 10:07/11:12 轮完全相同 ⇒ 零新增）。
- 较 11:12 轮（7/16）新增 ✅：#5 11:58:05（verified=true/COMPLETE）、#6 11:22:48 noop、#11 11:22:50、#13 11:22:52 noop。
- **#3 金鲨日报11:00 当日 2 败，真因 `desktop-send-outcome-unknown`**（Mac 桌面微信外发结果未定，policy=jinsha-business-code-enforced-v1）；failure_watch consecutive=2；**跨日累计 10-07(1)+10-08(2)=3 达线 ⇒ 已报开单/人工介入**。Mac WeChat pid 35155 在位。
- #7(12:00)/#15(12:30) ❌ = **尚未被调度**（零 record；守护 last_cycle 11:53:19 < 12:00，next 12:23:19），非失败。
- **网关本轮双侧翻转不可达**：`.5`/.2 均 ping 100% 丢包 + health EXIT=28；中继 8732 EXIT=56（进程在但拒连）。对比 11:12 轮 `.5` 200 ⇒ 观察项，涉 Windows 桥的 #7/#9/#10/#14/#15 后续风险。
- 告警核实：16 次 legacy-marker 全落 00:25–08:31；marker `taobao-flash-appeals-2026-10-07.json` 现 verified=true、sendAttempts=1、groupName=FEIBING NEO AI数字员工 ⇒ 幂等历史。
- 守护：pid=38617、started 10:47:12、存活 1h30m、next 12:23:19、running；locks 空。#14 外发待核→群回读。未代发台账。全程只读。

## 2026-10-08 11:12（白天窗口，hour=11）
- **7/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 69 日志，仅一条 reason `legacy-marker-binding-mismatch` x16，与 10:07 轮完全相同 ⇒ 本小时零新增）。
- ✅：#1 10:21:05、#2 09:13:10、#5 10:46:57、#11 09:14:20、#12 10:21:54（noop 无待发）、#14 09:49:26（外发待核）、#16 09:17:30。较 10:07 轮新增 #1 top10 由 ❌ 转 ✅ 10:21:05。
- **三条 ❌（#3/#6/#13，均 11:00 档）实为「尚未被调度」，非失败**：run_history/2026-10-08 下三条流**零 record**（精确 glob 无匹配）；last_cycle.json 中三者 status=**PENDING**、finished_at=""；守护 last_cycle 10:47:12 **< 11:00 排班点**，next_cycle 11:17:12 ⇒ 首次调度落在 11:17 周期。昨日(10-07)三条均成功（15:22 / 12:04 / 14:32），无跨日复发 ⇒ **不开单**。脚本仍显示 ❌ 属口径滞后（说明列误显示 "SUCCESS"）。
- 告警核实：**16 次 legacy-marker 全落在 00:25:59–08:31:27**，09:13:31 SUCCESS 之后零新增；`taobao-flash-appeals-2026-10-07.json` 现 state=**verified**、sendAttempts=1（08:58 void → 09:14 重验），s2 日志 verified=true ⇒ 幂等历史，非真故障。跨日累计（10-06 32 + 10-07 51 + 今日 16）**维持开单建议（修 daily_progress 口径）**。
- 守护：pid=38617、started 10:47:12、last_cycle 10:47:12、next 11:17:12、status=running、%CPU 0.0（本实例仅跑完 1 轮，节奏正常，11:17 轮待验）；`runtime/state/locks/` 空。
- 网关：`.5:8731` 200 全 true（logged_in=true）、中继 127.0.0.1:8732 200 全 true；`.2` EXIT=28 不可达（延续形态）。
- #14 外发待核 → 群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-08 10:07（白天窗口，hour=10 · 当日首轮）
- **4/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 63 日志，仅 1 条 reason `legacy-marker-binding-mismatch` x16）。
- ✅：#2 09:13:10、#11 09:14:20、#14 09:49:26（外发待核）、#16 09:17:30。
- 三条 ❌ 真因（已下钻 receipt，非状态字）：
  - **#1 top10 当日 3 次全败、三种不同 reason**：08:31 `windows-wechat-not-ready`（休眠唤醒登录空窗）→ 09:02 `background-profile-process-not-alive` → 09:47 `desktop:Command failed: .../scripts/ocr_vision 2026-10-07_top10seller.png zh-Hans`（OCR 步骤命令失败，截图已产出 validatedFileCount=7，sendAttempts=0 未外发）。**ocr_vision 跨日 0 次＝当日首现**，未达线，观察。
  - **#5 new-merchants 当日 22 败**：codex-runtimes node 缺失 x15（**跨日累计 10-05(16)+10-06(2)+10-07(19)+10-08(15)=52 次，老问题持续复发，维持开单**）、`background-profile-process-not-alive` x3、`filtered-table-not-stable:merchant-row-id-invalid:2` x6。
  - #12 新店开业 **非失败**：24h cadence，上次成功 10-07 10:53:06 ⇒ 今日 10:53 才 due（10:07 未到点），脚本口径滞后。
- `background-profile-process-not-alive` 当日 2 次 + 10-06 1 次 = 累计 3 次达线；但 10:09 实测后台 Chrome 9230/9231/9233 全 HTTP=200 ⇒ 判瞬态，待 10:17 周期验证自愈。
- 告警核实：**16 次 legacy-marker 全部落在 00:25–08:31**（09:13:31 SUCCESS 之前）；marker `taobao-flash-appeals-2026-10-07.json` 08:58 void、09:14 重验 verified（4/4 completed、result=verified）⇒ 幂等历史，09:14 后零新增拒发。
- 守护健康：pid=33503、started 10-07 15:23:48、存活 18h45m、last_cycle 09:47:55、next 10:17:55、running；locks 空。网关 `.5` 200 全 true（logged_in=true）、relay 8732 200；`.2` EXIT=28 不可达。
- #14 外发待核 → 群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-07 23:54（夜间窗口，hour=23 → 触发自暂停）
- 窗口守卫：date +%H = 23（>=23），未跑 daily_progress.py / alert 探测，未做任何检查。
- 已 automation_update（list→update，id 7a6c1a59-cce2-43ed-9442-612f360b5e22）置 **PAUSED**；明早 09:00 由「监理晨间唤醒（id d456b850…）」恢复。
- 交接：白天末轮 22:49 为 16/16 全绿（连续第四轮，脚本口径）；遗留 #5 new-merchants `offline_selftest` node 缺失（`/Users/ddt/.cache/codex-runtimes/` 不存在，当日 17 次、跨日复发）维持开单；网关双侧不可达疑为大同休眠。全程只读。

## 2026-10-07 22:49（白天窗口，hour=22 · 本窗口最后一轮）
- **脚本口径 16/16 全绿（连续第四轮），daily_progress 退出码 0**；但**下钻发现脚本口径滞后**：#5 new-merchants 最新两个周期 22:17:23 / 22:47:51 均为 **FAILED/UNKNOWN**，且形态**换了新真因**——`stage=offline_selftest` FAIL，`error=[Errno 2] No such file or directory: '/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node'`（实测 `/Users/ddt/.cache/codex-runtimes/` 整个目录不存在），completion=`RECOVERABLE_NO_SEND`（涉离线自检，不涉外发）。当日该 reason 共 17 次：00:10~07:29 连续 15 次 + 22:17/22:47 复活 2 次；**跨日复发（10-05 11:08 轮 #6 流同因 17 次），远超 3 次线 ⇒ 已报「建议开单/需人工介入」**。脚本仍计 ✅ 是因取当日末次 SUCCESS（21:16:27）。`last_cycle.json all_green=false` 与此一致。
- 告警（扫 147 日志，退出码 1）**本小时零新增**：三条 reason 计数**连续第八轮完全相同**（legacy-marker 19 / legacy-attempt-reconcile-only 3 / existing-attempt-reconcile-only 2）；逐条最新日志时间戳为 10:52:53（taobao-flash）与 20:45:22（new-merchants），22:00 后无任何 verified=false 新日志。真实 reason：① `legacy-marker-binding-mismatch` 19 = 幂等绑定不匹配（top10 x1 + taobao-flash x18，均有当日 verified marker 覆盖）；② `legacy-attempt-reconcile-only` 3 + ③ `existing-attempt-reconcile-only` 2 = #5 的 attempt marker 处于 attempted/reconcile-only 去重状态，sendAttempts=null 从未外发（已被 21:16 SUCCESS 覆盖）。
- **网关双侧不可达（形态变化）**：`.5` ping 100% 丢包 + health EXIT=28；`.2` health EXIT=28；中继 `127.0.0.1:8732` EXIT=56（拒绝连接，中继进程已不在）。对比 21:45 轮 `.5` 全 true ⇒ 疑为大同提前休眠/中继会话退出。**但本轮失败真因在 Mac 本地 node 缺失，与网关无关**，未误判为掉登录。
- 守护健康：pid=33503、started 15:23:48、存活 7h26m、last_cycle 22:47:48、next 23:17:48、status=running；`runtime/state/locks/` 空。
- **台账 22:47:51 已重新落盘**（`work/2026-10-07臻肆工作台账.xlsx`，6684B）但未见发送证据。已说明「脚本口径全绿可走 ledger_gate 判定」**但未代发**，并标注 #5 最新失败以免误发。
- #7/#9/#10/#14/#15 外发待核 → 群回读核验。全程只读：未改状态/未写 control.json/未重启守护/未代跑/未发微信。

## 2026-10-07 21:45（白天窗口，hour=21 · 22 点前末轮）
- **16/16 全绿，连续第三轮**，daily_progress 退出码 0；alert 探测退出码 1（扫 143 日志，三条 reason 计数**连续第七轮完全相同**：legacy-marker 19 / legacy-attempt-reconcile-only 3 / existing-attempt-reconcile-only 2）⇒ 零新增拒发。
- **20:42 轮头号异常 #5 已自愈闭环**：21:15:57 new-merchants SUCCESS，completion state=`COMPLETE`、reason=`final-cursor-and-history-verified`、sent=1（商家「口缸米线·米线」→ 电销+直播攻坚组）⇒ 游标已推进，windows-readback-anchor-not-trailing 不再阻塞。**但当日 26/31 条 FAILED，超线定性维持**（真因=回读锚点校验，非发送失败；transport 实为 sent=true、route=relay）。
- 三条 reason 逐条核实均为**幂等/已闭环**，无真未送达：
  - `legacy-marker-binding-mismatch` 19 = top10 x1（08:37，当日 marker `2026-10-06-main-16379fcc7508.json` verified=true/sendAttempts=1，09:09:01 SUCCESS）+ taobao-flash x18（00:15~10:52；业务日 marker `taobao-flash-appeals-2026-10-06.json` 12:06 verified=true/sendAttempts=1 外发 xlsx；19:44:01 s2 reason=`business-date-marker-already-verified` verified=true）。
  - `legacy-attempt-reconcile-only` 3（19:43/20:14/20:45）与 `existing-attempt-reconcile-only` 2：底层真因 `windows-readback-anchor-not-trailing`；transport route=relay（直连 `[Errno 65] No route to host`、local_network_blocked=true）、Windows 侧 sent=true ⇒ **已物理发出但回读未过校验**，非「从未发出」。
- 守护彻底恢复：pid=33503、started 15:23:48、last_cycle 21:46:52、next 22:16:52、status=running、last_cycle.json `all_green=true`（19:38 轮的 ~100 分钟停滞已消除，连续两轮正常）。
- 网关 `.5:8731` 全 true（logged_in/worker/uiautomation/wechat_running/ready）；`.2` EXIT=7 不可达；relay `127.0.0.1:8732` 200 全 true。排除掉登录/网关故障。
- #7/#9/#10/#14/#15 外发待核 → 群回读核验。已提示「全绿可发台账」但**未代发**（须守护跑 ledger_gate.py 为 GO）。全程只读。

## 2026-10-07 20:42（白天窗口，hour=20）
- **16/16 全绿，连续第二轮**，daily_progress 退出码 0；alert 探测退出码 1（扫 141 日志，较 19:38 轮 135 +6，但**三条 reason 计数连续第六轮完全相同**（legacy-marker 19 / legacy-attempt-reconcile-only 3 / existing-attempt-reconcile-only 2）⇒ 零新增拒发）。
- **19:38 轮头号异常「守护停滞 ~100 分钟」已自愈**：pid 仍 33503、started 15:23:48、存活 5h18m、last_cycle 20:14:46、next 20:44:46、status=running、daemon.out.log 20:14 仍在写；`runtime/state/locks/` 已空（跨 5 轮的陈旧锁已清理）。
- **新增超线真因（本轮首现）**：20:14 周期 #5 new-merchants FAILED/UNKNOWN，下钻 s1 日志真因＝`windows-readback-anchor-not-trailing`（stage=send:0、sendAttempts=1、state=RECONCILE_ONLY）＝ Windows 侧回读锚点不在会话末尾，无法确认送达。**当日 4 次（19:43、20:14 等），跨日 10-05/10-06 均为 0 ⇒ 当日首现即达 3 次线，已报「建议开单/人工介入」**。网关 `.5` health 全 true（logged_in=true）排除掉登录/网关故障。
- **台账 20:14 已重新落盘但未发送**：守护门判 active 15/16「未全绿 → 仅落盘 + 告警，不发送」（即上条 #5 未决所致）。已提示「全绿可发台账（脚本口径）」但监理**未代发**（须 ledger_gate.py GO，且守护自身门未开）。
- #7/#9/#10/#14/#15 外发待核 → 群回读核验。全程只读：未改状态/未写 control.json/未重启守护/未代跑/未发微信。

## 2026-10-07 19:38（白天窗口，hour=19）
- **16/16 全绿，当日首次**（daily_progress 退出码 0）；#10 智能客服17:00 档由 ⏳ 转 ✅ 17:27:39，failure_watch 全流 consecutive_failures=0。
- ⚠️ **守护停滞 ~100 分钟（头号异常）**：pid=33503、started 15:23:48、last_cycle 17:58:08、next 18:28:08，当前 19:38 ⇒ 18:28/19:28 两轮未执行；daemon.out.log 停写于 17:58:51，18:00 后零新 log/record；进程在（PPID=1、caffeinate 子进程 33504）但无活动。已报需人工介入，监理未重启。影响 #5 每小时档与 #11 20:40 汇总档。与 14:06 轮同形态。
- **台账已落盘未发**：`work/2026-10-07臻肆工作台账.xlsx`（17:58:51，守护「未加 --send：仅落盘」）。已提示「全绿可发台账」但**未代发**（须 ledger_gate.py GO）。
- 告警（扫 135 日志）三条 reason 计数**连续第五轮完全相同**（legacy-marker 19 / legacy-attempt-reconcile-only 3 / existing-attempt-reconcile-only 2）⇒ 零新增拒发，均幂等自愈。跨日 legacy-marker 51 ⇒ 维持开单。
- 陈旧锁 jinsha-9232.lock（pid=31859）跨 5 轮未清理，明日 11:00 档风险仍在。
- 网关 `.5` 200 全 true（logged_in=true）；`.2` EXIT=28。#7/#9/#10/#14/#15 外发待核→群回读核验。全程只读。

## 2026-10-07 17:15（白天窗口，hour=17）
- **15/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 130 日志，较 16:13 轮 127 +3，但**三条 reason 计数连续第四轮完全相同 ⇒ 零新增拒发**）。
- **唯一 ❌ 是 #10 智能客服17:00 档，属排班未到点而非失败**：last_cycle.json / failure_watch.json 均无 `-17` 条目，守护上轮 16:56:17 < 17:00，下轮 17:26:17 才可能首次调度；当日 run_history 只有 -12（12:04:26）与 -15（15:08:41）两条 SUCCESS。
- 告警三条逐条核实全部已自愈/幂等：legacy-marker 19（top10 x1 —— marker `2026-10-06-main-16379fcc7508.json` state=verified/sendAttempts=1，09:09:56 SUCCESS；taobao-flash x18 —— 末次失败 10:52:53，之后 12:05:19/14:32:33/16:56:27 三条 SUCCESS）；legacy-attempt-reconcile-only 3 + existing-attempt-reconcile-only 2（均 #5，15:54:14/16:56:25 SUCCESS）。跨日 legacy-marker 累计 51 → 维持开单建议。
- 守护稳定：pid=33503、started 15:23:48、存活 1h52m、last 16:56:17、next 17:26:17、running（连续第三轮同实例）。网关：`.5` code=200 全 true（logged_in=true）；`.2` EXIT=28/HTTP=000 不可达（延续形态）。
- #7/#9/#14/#15 外发待核 → 群回读核验。未全绿故未提示可发台账。全程只读。

## 2026-10-07 16:13（白天窗口，hour=16）
- **15/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 127 日志，较 15:10 轮 122 +5，但**三条 reason 计数完全相同 ⇒ 连续第三轮零新增拒发**）。
- **❌ 已清零**：15:10 轮唯二失败 #3 金鲨双平台日报（11:00）→ ✅ 15:23:39、#4 淘宝昨日报表（13:00）→ ✅ 15:14:20。真因 `desktop-preflight-retry-limit-exceeded` / `taobao-auth-seed-not-unique:2` 均已自愈，无需再追加人工介入。**仅剩 #10（17:00 档）⏳ 排班未到点**，非失败。
- 告警三条逐条核实**全部为已送达幂等/已自愈**，无真未送达：① legacy-marker x19（top10 x1 —— marker `skills/daily-top10-to-wechat-group/.runtime/send-ledger/2026-10-06-main-16379fcc7508.json` state=**verified**、sendAttempts=1，业务日=昨日 top10 符合口径；taobao-flash x18 —— 末次失败 10:52:53，之后 12:05:19/14:32:33 两条 SUCCESS「全部 2 步 exit=0」已自愈）；② legacy-attempt-reconcile-only x3 + existing-attempt-reconcile-only x2（均为 #5 new-merchants，12:48 title-mismatch 之后 14:30:10 / 15:54:14 双 SUCCESS，已自愈）。
- **守护实例本轮再换**：pid 33503、started 15:23:48、存活 50m、last 15:54:12、next 16:24:12、status=running（15:10 轮的 30852 已退出）；last_cycle.json cycle_at 15:55:25、all_green=false。周期节奏正常，未停机。
- 网关：`.5` code=200 全 true（logged_in=true）；`.2` EXIT=28/HTTP=000 不可达（延续形态）。
- #7/#9/#14/#15 外发待核 → 群回读核验。未全绿（#10 未到点）故未代发台账。全程只读。

## 2026-10-07 15:10（白天窗口，hour=15）
- **13/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 122 日志，较 14:06 轮 99 +23，但**三条 reason 计数完全相同 ⇒ 连续第二轮零新增拒发**）。
- **较 14:06 轮大幅好转（7/16→13/16），14:06 报的两个「需人工介入」均自愈**：① 守护停滞已解除——新实例 pid=30852、started 15:06:55、next 15:36:55、status=running、last_cycle.json cycle_at 15:08:41；② 陈旧锁 `runtime/state/locks/jinsha-9232.lock` **已消失（locks 目录为空）** ⇒ #3/#4/#13 等恢复被调度。
- **❌ 仅 #3、#4 两条，均已下钻到真因（非状态字）**：
  - #3 金鲨双平台日报11:00：当日 5 条全 FAILED，14:53/14:54/15:05/15:06 **连续 4 次同一 reason `desktop-preflight-retry-limit-exceeded`**（Mac 桌面微信预检重试耗尽，duration 68s）⇒ 超线，报开单/人工介入。
  - #4 淘宝昨日报表13:00：当日 4 条全 FAILED，record 层 reason=`stage=wechat-send-failed / phase_last=profiles_ready`，**日志真因＝`taobao-auth-seed-not-unique:2`（stage=taobao_task_open，淘宝认证锚点不唯一命中 2 个）+ `receipt-not-completed`（sender_integrity_preflight）** ⇒ 采集侧锚点歧义，非外发通道问题。超线，报开单。
  - 二者均为 **Mac 桌面微信/后台浏览器通道**；Mac WeChat 进程在位（pid 80483），Windows 网关 `.5` health 全 true（logged_in=true）⇒ 排除掉登录/网关故障。
- 恢复亮点：#5 new-merchants 由全天失败转 ✅（14:31:41 / 15:08:08，consecutive_failures 归 0）、#9 智能客服15:00 ✅ 15:08:41、#16 brand-followup ✅ 14:32:52、#15 ✅ 14:32:51、#13 ✅ 14:32:35、#8 ✅ 14:32:32、#11 ✅ 14:32:34。
- 网关：`.5` code=200 全 true（logged_in=true）；`.2` EXIT=28 不可达（延续形态）。
- #7/#9/#14/#15 外发待核 → 群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-07 14:06（白天窗口，hour=14）
- **7/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 99 日志，较 12:27 轮 98 仅 +1，**零新增拒发**）。
- **本轮头号发现：守护停滞 76 分钟** —— daemon.json pid=20292、started 12:17:06、**last_cycle 12:48:02、next 13:18:02**，当前 14:06 ⇒ 13:18/13:48 两轮周期未执行；`ps` 进程在但 %CPU 0.0；last_cycle.json/mtime 停于 12:50。⇒ #4(13:00)/#8(14:25)/#15(12:30) 等**当日零 record、从未被调度**（run_history 精确 glob 确认无文件），非业务失败。已报「需人工介入」，监理未重启。
- **陈旧锁仍在（12:27 轮首报，未清理）**：`runtime/state/locks/jinsha-9232.lock` acquiredAt 11:48:01、**pid=26326（昨日实例，已死）**，当前守护 pid=20292 ⇒ #3/#13/#15/#16 持续 SKIPPED_BUSY。12:27 已报人工介入，本轮升级重申。
- **#5 new-merchants 真因变了（重点）**：不再 reconcile-only，最新 12:48:13 记录 reason=`windows-current-session-title-mismatch`（`titleProven:false`，stage=desktop_wechat/send:0）＝ Windows 微信当前会话标题≠目标群，防发错群保护拒发；采集侧正常（targetCount=3）。failure_watch `consecutive_failures=25` → 远超线，维持开单。
- #16 brand-followup 仍 ❌ x3（末次 10:54:48，reason=`prior-attempt-still-unknown`），无新 run（守护停滞所致）。
- 告警三条计数与 12:27 轮**完全相同**（legacy-marker 19 / legacy-attempt-reconcile-only 3 / existing-attempt-reconcile-only 2）。逐条核实均为幂等：top10 当日有 verified marker `2026-10-06-main-16379fcc7508.json`（09:09 写入，口径=昨日 top10）、taobao-flash 12:06:08 SUCCESS 且 s2 `sendAttempts:1` ⇒ 已外发。
- 网关：`.5` health 全 true（**logged_in=true**）；`.2` EXIT=28 不可达（延续 10-06 晚以来形态）。
- #7/#14 外发待核 → 群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-07 12:27（白天窗口，hour=12）
- **7/16 已完成，未全绿**，daily_progress 退出码 1（设计信号）；alert 探测退出码 1（扫 98 日志）。
- 较 11:22 轮明显好转（3/16→7/16）：**#2 差评分析由 ❌ 转 ✅ 12:16:41**（此前 `locator.click Timeout 30000ms` 三次同因已自愈）、**#11 taobao-flash 由 ❌ 转 ✅ 12:06:08**（18 次 legacy-marker 后成功，属幂等自愈）、#6 差评申诉11 ✅ 12:05:17（noop）、#7 智能客服12 ✅ 12:04:26（外发待核）。
- **新发现（当日首现，重点）：陈旧锁 `runtime/state/locks/jinsha-9232.lock`** —— acquiredAt 11:48:01、runId=daily-negative-reviews、**pid=26326（昨日守护实例，现已不存在）**；当前守护 pid=20292（12:17:06 启动）⇒ 锁未随旧守护退出释放。判为 #3 金鲨日报11:00 与 #13 新店活动巡检11:00 双双 SKIPPED_BUSY 且**当日 run_history 零 record** 的直接原因。已报「需人工介入清理陈旧锁」，监理只读未删。
- #5 new-merchants 仍全天未成功（失败 x24）：最新 12:17:17 `stage=desktop_wechat`，真因 `existing-attempt-reconcile-only`（deduplication blocked，attemptMarker b26956b5… status=attempted、sendAttempts=null 从未外发）。跨日 reconcile-only 10-06(2)+10-07(5)=7 → 超线，维持开单。
- #16 brand-followup ❌ x3（09:23/10:08/10:54）同一 reason `prior-attempt-still-unknown` → 达 3 次线，已报人工介入。
- #15（12:30 档）12:27 时 PENDING 未到点，脚本按 ❌ 显示属口径滞后。
- 告警三条真实 reason：legacy-marker 19（top10 x1 + taobao-flash x18，均已由当日 SUCCESS 覆盖）、legacy-attempt-reconcile-only 3、existing-attempt-reconcile-only 2（均 #5）。跨日累计 legacy-marker 112 次 → 维持「建议开单修正脚本口径」。
- 网关：`.5` health 全 true（logged_in=true）；`.2` 空响应不可达（延续 10-06 晚间以来的无线侧可达形态）。守护健康：pid=20292、started 12:17:06、存活 10m、next 12:47:06，11:22 轮「守护卡住」观察项已自愈（旧实例退出、新实例接管）。
- #7/#14 外发待核 → 群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-07 11:22（白天窗口，hour=11）
- **3/16 已完成，未全绿**，daily_progress 退出码 1（设计信号）；alert 探测退出码 1（扫 82 日志）。
- **当日主根因：今晨 Windows 微信未登录**（延续 10:05 轮研判，但形态变了）：09:23 前后 `windows-sessions-unavailable:HTTP 500 微信进程在但主窗口未出现——尚未完成登录`，把两个 marker 写成 blocked/attempted；11:23 实测 `.5` health `logged_in=true/ready=true/worker=true` ⇒ 微信现已在位，**但卡死的是 marker 状态，桥按「已尝试」拒重发**：
  - #11 taobao-flash：桥写死绑定 marker `taobao-flash-appeals-2026-10-06.json`（今日 09:23 被写成 state=blocked/sendAttempts=0）→ `legacy-marker-binding-mismatch` x18；**当日无 verified marker** ⇒ 按 P0-1b 判真故障非幂等。区别于 10-06（当日 19:19 有 SUCCESS 可自愈）。
  - #5 new-merchants：attempt marker `b26956b5…json` item status=attempted、deduplication stage blocked → `legacy-attempt-reconcile-only` x2 + `existing-attempt-reconcile-only` x1，sendAttempts=0 未外发；采集全 PASS（targetCount=2，含「寿小卤·潮汕猪脚饭」）。
  - #16 brand-followup：09:23 未登录 → 10:08 attempted-items-still-require-reconcile → 10:54 prior-attempt-still-unknown（连带）。
  - #2 daily-negative-reviews：`locator.click Timeout 30000ms` 点「200条/页」下拉项（element not visible），当日 3 次同因（09:21/10:07/10:51）。
- **超 3 次线已报「建议开单/需人工介入」**：#5 x22、#11 x20、#2 x3、#16 x3。真因指向 attempt/marker 状态未随微信登录恢复而复位，缺「marker void/重绑」机制。
- 较 10:05 轮变化：#12 新店开业 ✅ 10:54:40（noop 无待发）、#14 负反馈0930 ✅ 10:08:27（外发待核）。#1 top10 ✅ 09:09:56：08:00/08:37 两次 FAILED（sendAttempts=null），09:09:01 那次 ok=true/sendAttempts=1 ⇒ 告警中 top10 x1 属已自愈幂等。
- #3/#6/#13（11:00 档）last_cycle=PENDING、run_history 零 record ⇒ 尚未被调度（守护上轮 10:54 < 11:00），非失败。#4/#7/#8/#9/#10/#15 排班未到点。
- 网关：`.2` EXIT=28 不可达；`.5` code=200 全 true（同 10-06 晚间结论，Mac 侧走无线 .5）。
- 守护：pid=26326、started 10-06 21:05:48、存活 14h18m、status=running、last_cycle 10:54:48、all_green=false；`next_cycle_at 11:10:13` 已过 13 分钟无新 cycle 且 %CPU 0.0 → **列为观察项（未定性）**。
- #14 ✅ 外发待核 → 群回读核验。未全绿故**未代发台账**。全程只读，未改状态/未发微信。

## 2026-10-07 10:05（白天窗口，hour=10 · 当日首轮）
- **1/16 已完成，未全绿**，daily_progress 退出码 1（设计信号）；alert 探测退出码 1（扫 66 日志）。
- ✅ 仅 #1 top10 09:09:56（SUCCESS「全部 1 步 exit=0」）；08:00/08:37 两次 FAILED 后被 09:09 覆盖。
- **今日主根因＝微信登录态/窗口态（夜间休眠后未登录）**，三流同源不同面：
  - #5 new-merchants 当日 18 条全 FAILED，`stage=desktop_wechat_preflight`（Mac 桌面微信未前台/未登录）→ 超线，已报人工介入。
  - #11 taobao-flash 当日 18 条全 FAILED，`embedded-reason=windows-sessions-unavailable:HTTP 500`（微信进程在但主窗口未出现）→ 超线，已报人工介入。
  - #16 brand-negative-review 1 次同一 reason，未达线。
- #2 昨日差评分析 09:21:40 FAILED，真因 `locator.click Timeout 30000ms`（`.el-select-dropdown__item`「200条/页」不可见）→ 页面态问题，当日 1 次未达线。
- 假 ❌ 两条（24h cadence，非失败）：#12 新店开业 last_SUCCESS 10-06 10:29:44 → 今日 10:29 才 due；#14 负反馈0930 last_SUCCESS 10-06 20:35:45 → 今日 20:35 才 due。脚本未做「未到点」判定，口径滞后。
- 告警两条真实 reason：`legacy-marker-binding-mismatch` 17（top10 x1 已由 09:09 成功覆盖属自愈；flash x16 **当日零 SUCCESS、无 verified 证据 ⇒ 按 P0-1b 判真故障非幂等**）、`legacy-attempt-reconcile-only` 1（new-merchants）。跨日累计 legacy-marker 10-06(32)+今日(17)=49 → 维持「建议开单」。
- 网关可达性**仍翻转**：`.5:8731 code=200 全 true（logged_in=true）**已恢复登录**；`.2` code=000 不可达。⇒ 09:22 那批失败为休眠唤醒后的登录空窗，预计 10:25 周期自愈。
- 守护正常：pid=26326、started 10-06 21:05:48、存活 13h00m、last_cycle_at 09:55:26、next 10:25:26；last_cycle.json cycle_at 09:24:38、all_green=false（09:55 周期在跑，多流未 due 故无新 record）。
- 未全绿故未提示可发台账。全程只读，未改状态/未发微信。

## 2026-10-06 23:15（夜间窗口，hour=23 → 触发自暂停）
- 窗口守卫判定 hour=23（>=23），未跑 daily_progress.py / alert 探测，未做任何检查。
- 已 automation_update（list→update）将本任务 id 7a6c1a59-cce2-43ed-9442-612f360b5e22 置为 **PAUSED**，明早 09:00 由「监理晨间唤醒（id d456b850…）」恢复。
- 交接：白天窗口最后一轮为 22:13，状态 **16/16 全绿、连续第二轮、本小时零新增拒发**；#1/#7/#9/#10/#14 外发待核→群回读核验；workflow-not-registered 当日累计 4 次维持「建议开单」。全程只读。

## 2026-10-06 17:59（白天窗口，hour=17）· 当日首次 14/14 全绿
- **14/14 全绿**，daily_progress 退出码 0；alert 探测退出码 1（扫 168 日志，较 16:57 轮的 161 增 7 个文件但**无新增拒发**）。
- 较 16:57 轮变化：**#10 智能客服17:00 由 ⏳ 转 ✅（17:31:16）**；#5 刷新 17:30:23；#11 闪购 16:59:25。
- #10 下钻确认：`meituan-intelligent-customer-service--20261006-173024--record.json` = SUCCESS/SUCCESS，「全部 4 步 exit=0」；#5 `daily-agent-new-merchants-to-wechat--20261006-172953` = SUCCESS「全部 1 步 exit=0」。
- 告警 reason 与 16:57 轮**完全一致**：`legacy-marker-binding-mismatch` 30（top10 x7 幂等 + flash x23 上午时段）、`legacy-attempt-reconcile-only` 1、=`workflow-ledger-mismatch` 1；均 verified=false+sendAttempts=null。top10 最新两条 record（16:00:38/16:28:41）仍是 SKIPPED_IDEMPOTENT + evidence-verified marker（10-05-main-16379fcc7508 state=verified）。
- 跨日累计 legacy-marker 63 次（09-30/10-03/10-04/10-05/10-06）→ 已报「建议开单修正 daily_progress 口径」。
- 守护**再换实例**：pid=89939、started 17:47:19、存活 12:39（16:57 轮的 80136 已退出，属正常重启）。网关 **192.168.0.2:8731 全 true**（logged_in=true）。
- **已提示「全绿可发当日台账」但未代发**（门由守护：须 ledger_gate.py <日期> 为 GO）。#1/#7/#9/#10 外发待核 → 保持原样 + 群回读核验。全程只读。

## 2026-10-06 16:57（白天窗口，hour=16）
- **13/14 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 161 日志）。
- 较 15:55 轮变化：**#1 top10 由 ❌ 转 ✅ 外发待核（16:28:58）**；#5 刷新 16:02:19；#14 14:25:08。仅剩 #10（17:00）⏳ 未到点。
- #1 下钻：16:28:41 / 16:00:38 两条 record 均 `SKIPPED / SKIPPED_IDEMPOTENT`，reason=`desktop-wechat:legacy-marker-binding-mismatch`，附 evidence-verified marker `.../daily-top10-to-wechat-group/.runtime/send-ledger/2026-10-05-main-16379fcc7508.json`（10-06 12:27 写入，state=verified、sendAttempts=2）→ 实为已送达的幂等保护；marker 业务日 10-05 符合「昨日 top10」口径。
- 告警三条真实 reason：`legacy-marker-binding-mismatch` 30（top10 x7 幂等 + flash x23 上午时段，12:46/14:58 后已恢复）、`legacy-attempt-reconcile-only` 1（#5 流 14:26:30）、`workflow-ledger-mismatch` 1（top10 10:31:20 FAILED/UNKNOWN，已被 12:26 成功覆盖）。均 verified=false+sendAttempts=null。
- 跨日累计：legacy-marker 09-30(1)+10-03(7)+10-04(20)+10-05(5)+10-06(30)=63 次 → 已报「建议开单修正 daily_progress 口径」。
- 守护**已换新实例**：pid=80136、started 16:28:40、next 16:58:40、存活 28:48（原 59783 已退出，属正常重启）。网关 **192.168.0.2:8731 全 true**（logged_in=true）；.5 超时 EXIT=28（已知 Mac 侧仅有线可达）。
- #1/#7/#9 外发待核 → 保持原样 + 提示群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-06 15:55（白天窗口，hour=15）
- **12/14 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 158 日志）。
- ✅ 新增/刷新 vs 14:50 轮：#5 淘宝新增商家增量通知 14:57:33（由 ❌ 转 ✅）、#8 差评申诉 14:25 档 14:58:23、#9 智能客服 15:00 档 15:30:09（外发待核）、#11 闪购 14:58:25。#10（17:00）⏳ 未到点。
- 唯一 ❌ 仍为 #1 top10：status=SKIPPED / category=SKIPPED_IDEMPOTENT，reason=`desktop-wechat:legacy-marker-binding-mismatch`，附 evidence-verified marker `2026-10-05-main-16379fcc7508.json state=verified`（12:26 写入）→ 实为已送达的幂等保护，脚本 ❌ x11 属口径滞后，已报开单修正。
- 告警三条真实 reason：`legacy-marker-binding-mismatch` 28（top10 x5 + flash x23，flash 全在 00:58–11:03 上午时段，12:46/14:58 两次 SUCCESS 后已恢复）、`legacy-attempt-reconcile-only` 1、`workflow-ledger-mismatch` 1；均 verified=false+sendAttempts=null＝从未外发。
- 守护正常：pid=59783、status=running、last_cycle 15:29:12、next 15:59:12、进程存活 01:33:38。网关 **192.168.0.2:8731 全 true**（logged_in=true）→ 排除微信掉登录/网关故障。
- #7/#9 外发待核 → 保持原样 + 提示群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-06 13:47（白天窗口，hour=13，当日首轮）
- **7/14 已完成，未全绿**，退出码 1。✅：#2(10:32:04)、#4(13:18:40)、#7(11:42:37 noop)、#8(12:14:58 外发待核)、#12(12:46:55)、#13(10:30:16 noop)、#14(11:04:10 noop)。⏳ 未到点：#9(14:25)/#10(15:00)/#11(17:00)。
- ❌ 4 条，均已下钻到真因（非状态字）：
  - **#3 `daily-rows-not-all-explicitly-reportable`**（stage=读取并校验日报，businessDate=2026-10-05）：**当日 20 次、跨日仅今日首现** → 已报「建议开单/需人工介入」。
  - **#6 `background-profile-state-mismatch`**（后台 Chrome profile `taobao-agent-service` port 9231，completion=RECOVERABLE_NO_SEND）：**当日 5 次** → 已报「建议开单/需人工介入」。
  - **#5 `daily-flow-environment-not-ready` → `installed-skill-drift`**（executor `daily-taobao-download-to-jinsha/scripts/background_browser_executor.mjs` 封印漂移）：当日 1 次，未达线，观察。
  - **#1 `legacy-marker-binding-mismatch`**：category=SKIPPED_IDEMPOTENT，幂等保护不计失败（脚本仍显示 ❌ x11 属展示口径滞后），按 10-05 23:35 口径不再列开单项。
- 告警探测（136 日志，退出码 1）：legacy-marker 24 次（top10 x1 + taobao-flash x23）、workflow-ledger-mismatch 1 次；均 verified=false+sendAttempts=null＝从未外发。
- 网关 **192.168.0.2:8731/health 全 true**（logged_in=true）；**192.168.0.5 无响应** → 再证「Mac 侧只有有线 .2 可达」。
- 守护正常：pid=25146、started 11:40:43、last_cycle 13:17:29、next 13:47:29，进程存活。
- 未全绿 → 未代发台账。全程只读：未改状态 / 未写 control.json / 未重启守护 / 未代跑 / 未发微信。
- 注：本自动化名仍写「12条任务流」，实际已 14 条，建议改名。

## 2026-10-05 22:36（白天窗口，hour=22，本窗口最后一轮）
- **14/14 全绿**，脚本退出码 0，连续第二小时全绿（21:34 首次）。较 21:34 轮：#6 刷新至 21:53:01，其余 ✅ 无变化。
- 告警探测（扫 169 日志，退出码 1）三条 reason：`legacy-marker-binding-mismatch` **4 次（较上轮 +1，新增 daily-top10-to-wechat-group 21:44:45 FAILED，12:04 那次仍 SUCCESS 故脚本仍判 ✅）**、`workflow-ledger-mismatch` 4 次、`workflow-meituan-customer-reply-path-mismatch` 3 次，均 verified=false+sendAttempts=null＝从未发出。
- **跨日累计已达线并报开单**：legacy-marker-binding-mismatch 09-30(1)+10-03(7)+10-04(20)+10-05(5)=33 次，远超连续 3 次线 → 已报「建议开单/需人工介入」，监理未改代码/未代跑。
- daemon 正常：pid=70959、status=running、started 21:53:22、last_cycle 22:23:59、next 22:53:59，进程存活。网关 192.168.0.5:8731/health 全 true（logged_in/worker/uiautomation/ready）。
- #9/#13/#14 外发待核，保持原样 + 提示群回读核验。已提示「全绿可发台账」但**未代发**。全程只读。
- 下一小时 23:00 进入夜间窗口，应自暂停为 PAUSED。

## 2026-10-05 16:23（白天窗口，hour=16）
- **12/14 已完成**，未全绿，退出码 1。新增/刷新：#6 16:02:18（每小时流）；#9 由 ❌ 转 ✅（14:45:41）；#12 15:31:43。
- 唯一 ❌ #10 智能客服 15:00 档：当日 2 条 run（15:31:41、16:02:20）均 `reason=workbench-entry-page-missing`，log 仅一行 `{"ok":false,...}`，跨日该原因仅今日 2 次（未达 3 次线，暂不开单）。网关 192.168.0.5:8731/health 全 true（logged_in=true）→ 排除微信掉登录/网关故障，判为美团 IM 工作台页面状态问题，**按大同铁律应上报车间主任做「关掉 IM 页重开」环境复位**（监理未下场）。
- **15:19 轮的「daemon 已停」已自愈**：runtime/state/daemon.json status=running、pid=39691、updated 16:01，进程存活。
- #9/#13/#14 外发待核，保持原样 + 提示群回读核验。#11（17:00）排班未到点。未代发台账，全程只读。

## 2026-10-05 14:17（白天窗口，hour=14）
- **任务流已由 12 条扩为 14 条**（脚本现报 11/14），本自动化标题仍写「12条」，建议后续改名。
- **11/14 已完成**，未全绿，退出码 1。较 13:15 轮新增/刷新：#6 13:34:21、#7 13:58:57（11:00 档补跑成功，record detail=「全部 3 步 exit=0」）。
- 唯一 ❌ 是 #9「金鲨美团外卖差评申诉（每日14:25）」：**当前 14:17 未到 14:25 排班点，当日 0 条 run 记录**（ls 确认无 -1425 前缀文件），属脚本未对 14:25 档做「未到点」判定而落 ❌，**非真实业务失败**，不需开单。
- #10（15:00）、#11（17:00）⏳ 排班未到点。
- #12/#13/#14 仍为「外发待核」（12:47:18 / 12:18:49 / 12:18:52），保持原样 + 提示群回读核验，未改状态。
- 只读探测 192.168.0.5:8731/health：ok/wechat_running/logged_in/ready/worker/uiautomation 全 true → 排除微信掉登录与网关故障。
- 未代发台账（未全绿）。全程只读：未改状态文件 / 未写 control.json / 未重启守护 / 未代跑业务流 / 未发微信。

## 2026-10-05 13:15（白天窗口，hour=13）
- **10/12 已完成**，未全绿，脚本退出码 1（设计信号）。**无 ❌**，未触发失败下钻。
- ✅ 已外发：#1 12:04:47、#2 12:12:35、#3 12:14:43、#4 12:16:33、#5 13:03:22（13:00 档准时）、#6 12:08:09、#7 12:18:06。
- ✅ 外发待核：#10 12:47:18、#11 12:18:49、#12 12:18:52 → 保持原样 + 提示群回读核验，未改状态。
- ⏳ 排班未到点：#8（15:00）、#9（17:00）。
- 较 12:12 轮（3/12）大幅恢复：#7 `send-button-not-enabled` 已自愈；#10 workflow_bridge_windows 外发桥已恢复成功；#3/#4/#11/#12 从 SKIPPED_BUSY 转成功。
- 只读探测 192.168.0.5:8731/health：ok/wechat_running/logged_in/ready/worker 全 true → 排除微信掉登录与网关故障，「外发待核」判为脚本日志侧未匹配回执，未升级人工介入。
- 未代发台账（未全绿）。全程只读：未改状态文件 / 未写 control.json / 未重启守护 / 未代跑业务流 / 未发微信。
- 注：用户 query 内仍写 192.168.0.4，实际网关为 192.168.0.5，探测已按 192.168.0.5 执行（沿用 12:12 轮结论）。

## 2026-10-05 11:08（白天窗口，hour=11）
- 0/12 已完成，未全绿；脚本退出码 1。4 条 ❌（#1 x6、#2、#6 x17、#10 x1），5 条 ⏳ 排班未到点（#5/#7/#8/#9），#3/#4/#11/#12 说明 SUCCESS 但本日无成功记录（#11 10:50、#12/#4 11:00 档当日尚无文件生成）。
- 根因与 10:05 轮一致，无好转：① 网关链路断——192.168.0.4:8731 curl exit=7、本地中继 127.0.0.1:8732 亦 exit=7（本轮为拒绝连接，上轮为超时），Windows 主机仍离线 → #1 累计 6 次 windows-driver-unreachable、#10 workflow_bridge_windows.py 命令失败。② #6 独立根因：`/Users/ddt/.cache/codex-runtimes/` 仍不存在，`codex-primary-runtime/dependencies/node/bin/node` 缺失，offline_selftest FAIL、completion=RECOVERABLE_NO_SEND、recoveryAttemptBudget 已耗尽。
- #2 仍静默失败：当日 4 个 log 全 0 字节、无 record.json。
- 新观察：#6 与 #10 自 08:35 起不再产生新 run（~2.5h 无新记录），疑似守护对连续失败退避/熔断；careloop 守护存活（launchctl PID 97325，exit 0），com.zhensi.probe 退出码 127。
- 三条失败原因均已达连续 3 次以上，已明确「建议开单 / 需人工介入」，未自行处置。
- 全程只读：未改状态文件、未写 control.json、未重启守护、未代跑业务流、未发任何微信消息；未代发台账（0/12）。

## 2026-10-05 10:05（白天窗口，hour=10，当日首轮）
- 0/12 已完成，未全绿；脚本退出码 1（设计信号）。4 条 ❌（#1/#2/#6/#10），3 条 ⏳ 排班未到点（#4/#5/#7/#8/#9/#12），#3/#11 说明 SUCCESS 但本日无成功记录。
- **根因 A（网关链路断）**：`192.168.0.4` ping 100% 丢包、主机离线；curl :8731 exit=7/HTTP=000；本地中继 127.0.0.1:8732 exit=28 超时无监听。→ #1 连续 4 次 `windows-wechat:windows-driver-unreachable`；#10 1 次 workflow_bridge_windows.py 命令失败。**已达连续 3 次线，已在汇报中建议人工介入（未自行处置）**。
- **根因 B（与网关无关，易误判）**：#6 连续 17 次 FAIL，真因是 `/Users/ddt/.cache/codex-runtimes/` 整个目录不存在，缺 `dependencies/node/bin/node` 二进制；stage=offline_selftest，completion=RECOVERABLE_NO_SEND。→ 已建议人工介入。
- **#2 特殊形态**：当日 2 个 log 均为 0 字节、无 record.json，属静默失败，日志侧无法定位，已标注需守护下钻。
- 教训：不要把所有 ❌ 归为「网关掉线」——#6 是独立的 node 运行时缺失，必须先读 record.json 的 detail/error 再定性。
- 全程只读：未改状态文件、未写 control.json、未重启守护、未代跑业务流、未发任何微信消息；未代发台账（0/12）。

## 2026-10-04 23:55（夜间窗口，hour=23 → 触发自暂停）
- 窗口守卫判定 hour=23（>=23），未跑 daily_progress.py，未做任何检查。
- 已 automation_update mode=update 将本任务（id 7a6c1a59-cce2-43ed-9442-612f360b5e22）置为 PAUSED；明早 09:00 由「监理晨间唤醒」自动恢复。
- 当日白天窗口 12:44–22:54 共 11 轮汇报，17:49 起 12/12 全绿并保持到窗口结束；#7/#8/#9/#11/#12 全程「外发待核」，待群回读核验。

## 2026-10-04 22:54（白天窗口，hour=22，本窗口最后一次）
- 12/12 全绿，脚本退出码 0；较 21:53 新增 #6 刷新至 22:17:11（每小时流），其余无变化。无 ❌，未触发下钻 / 网关探测。
- #7/#8/#9/#11/#12 仍为「外发待核」，保持原样 + 提示群回读核验，未改状态、未代跑。
- 已提示「已全绿，可发当日台账」但**未代发**（时机与门由守护判断）。全程只读，未改状态文件 / 未发微信。
- 下一小时（23:00）进入夜间窗口，届时应自暂停为 PAUSED。

## 2026-10-04 12:44（白天窗口，hour=12）
- 9/12 已完成，未全绿（3 条均为排班未到点：#5 13:00、#8 15:00、#9 17:00），无 ❌ 失败。
- #7/#11/#12 标记「外发待核」：run record 状态均为 SUCCESS（#7 detail=「全部 4 步 exit=0」），仅日志未见外发回执。
- 跨日核对 10-01~10-04：#7 连续 3 天 SUCCESS，属正常，不构成「同一失败原因连续 3 次」，未升级为人工介入。
- 未代发当日台账（未全绿）。全程只读，未改状态文件 / 未发微信。
- 注：#11/#12 的 run_history 文件名前缀与猜测不符（taobao-new-shop-notify / taobao-new-shop-activity-check 无匹配），后续下钻需先用 ls 确认真实文件名。

## 2026-10-04 13:45（白天窗口，hour=13）
- 10/12 已完成，未全绿；新增完成 #5 淘宝昨日报表（13:12:07）。#8 15:00、#9 17:00 排班未到点。无 ❌。
- #7/#11/#12 仍为「外发待核」，按规则保持原样 + 提示群回读核验，未改状态。
- 未代发台账（未全绿）。全程只读。

## 2026-10-04 14:46（白天窗口，hour=14）
- 10/12 已完成，未全绿；新增完成 #6 淘宝新增商家增量通知（14:04:01）。#8 15:00、#9 17:00 排班未到点。无 ❌ 失败，未触发下钻。
- #7/#11/#12 仍为「外发待核」，按规则保持原样 + 提示群回读核验，未改状态、未代跑。
- 未代发台账（未全绿）。全程只读，未改状态文件 / 未发微信。

## 2026-10-04 15:47（白天窗口，hour=15）
- 11/12 已完成，未全绿；新增完成 #8（15:37:41），#3/#6 刷新至 15:05、#10 至 15:37。仅剩 #9 排班未到点（17:00）。无 ❌。
- #7/#8/#11/#12 仍为「外发待核」，按规则保持原样 + 提示群回读核验，未改状态、未代跑。
- 只读探测网关 192.168.0.4:8731/health：ok/wechat_running/logged_in/ready 全 true → 排除微信掉登录与网关故障，「外发待核」判定为脚本日志侧未匹配到回执，非真实外发失败，未升级人工介入。
- 未代发台账（未全绿）。全程只读，未改状态文件 / 未发微信。

## 2026-10-04 16:48（白天窗口，hour=16）
- 11/12 已完成，未全绿；新增 #6 刷新至 16:08:16。仅剩 #9 排班未到点（17:00）。无 ❌，未触发下钻与网关探测。
- #7/#8/#11/#12 仍为「外发待核」，按规则保持原样 + 提示群回读核验，未改状态、未代跑。
- 未代发台账（未全绿）。全程只读，未改状态文件 / 未发微信。

## 2026-10-04 17:49（白天窗口，hour=17）
- **12/12 全绿**（当日首次收口）：新增 #9（17:10:10）、#6 刷新至 17:09:38、#10 至 17:40:47。脚本退出码 0。无 ❌，未触发下钻与网关探测。
- #7/#8/#9/#11/#12 仍为「外发待核」，按规则保持原样 + 提示群回读核验，未改状态。
- 已提示「可发当日台账」但**未代发**（发送时机与门由守护判断）。全程只读，未改状态文件 / 未发微信。

## 2026-10-04 18:50（白天窗口，hour=18）
- 12/12 全绿，脚本退出码 0；较 17:49 新增 #6 刷新至 18:12:05（每小时流），其余无变化。无 ❌，未触发下钻 / 网关探测。
- #7/#8/#9/#11/#12 仍为「外发待核」，保持原样 + 提示群回读核验，未改状态、未代跑。
- 已提示「可发当日台账」但**未代发**（时机与门由守护判断）。全程只读，未改状态文件 / 未发微信。

## 2026-10-04 19:51（白天窗口，hour=19）
- 12/12 全绿，脚本退出码 0；较 18:50 新增 #3 刷新至 19:12:55、#6 至 19:13:01、#10 至 19:43:32。无 ❌，未触发下钻 / 网关探测。
- #7/#8/#9/#11/#12 仍为「外发待核」，保持原样 + 提示群回读核验，未改状态、未代跑。
- 已提示「已全绿，可发当日台账」但**未代发**（时机与门由守护判断）。全程只读，未改状态文件 / 未发微信。

## 2026-10-04 20:52（白天窗口，hour=20）
- 12/12 全绿，脚本退出码 0；较 19:51 新增 #6 刷新至 20:14:29（每小时流），其余无变化。无 ❌，未触发下钻 / 网关探测。
- #7/#8/#9/#11/#12 仍为「外发待核」，保持原样 + 提示群回读核验，未改状态、未代跑。
- 已提示「已全绿，可发当日台账」但**未代发**（时机与门由守护判断）。全程只读，未改状态文件 / 未发微信。

## 2026-10-04 21:53（白天窗口，hour=21）
- 12/12 全绿，脚本退出码 0；较 20:52 新增 #6 刷新至 21:15:39、#10 至 21:46:22。无 ❌，未触发下钻 / 网关探测。
- #7/#8/#9/#11/#12 仍为「外发待核」，保持原样 + 提示群回读核验，未改状态、未代跑。
- 已提示「已全绿，可发当日台账」但**未代发**（时机与门由守护判断）。全程只读，未改状态文件 / 未发微信。

## 2026-10-05 12:12（白天窗口，hour=12）
- **3/12 已完成**，未全绿，脚本退出码 1（设计信号）。✅：#1(12:04:47)、#2(12:12:35)、#6(12:08:09)。⏳ 排班未到点：#5(13:00)、#8(15:00)、#9(17:00)。
- ❌ 真实失败 2 条（均卡在外发环节，非业务数据问题）：
  - #7 美团智能客服12:00 → `reason=send-button-not-enabled`（今日首现，未达 3 次）。
  - #10 淘宝闪购差评申诉 → `Command failed: workflow_bridge_windows.py ...`（workflow_bridge_windows 外发桥失败）。跨日统计：10-04 FAILED 21 / SUCCESS 7，10-05 已 2 FAILED 0 SUCCESS → **同一原因连续远超 3 次，已按规则报「建议开单/需人工介入」**。属间歇性失败（重试可成功），未自行处置。
- #3/#4/#11/#12 为 SKIPPED_BUSY（11:00 档未成功），record.json 内无该字段，未深挖，按脚本状态原样报。
- **网关地址已切**：探测 192.168.0.5:8731/health → ok/wechat_running/logged_in/ready/worker 全 true；旧 IP 192.168.0.4 已不可达（curl EXIT=7，与用户记忆「192.168.0.4 作废」一致）。今早 #1 曾连现 6 次 `windows-driver-unreachable` + 2 次 `windows-driver-local-network-blocked`（08:03–11:42），12:04 后恢复成功 → 判定为网关换址后的连锁，现已自愈，但**提示：后续汇报/脚本内硬编码的 192.168.0.4 需同步改为 192.168.0.5**。
- 未代发台账（未全绿，且监理铁律禁止代跑/代发）。全程只读，未改状态文件 / 未写 control.json / 未发微信。

## 2026-10-05 15:19（白天窗口，hour=15）
- 12/14 已完成，未全绿，脚本退出码 1。新增 ✅：#5(13:03)、#6(14:46)、#7(13:58)、#9(14:45)。
- 唯一 ❌ #10 智能客服15:00 档：**非业务失败**，last_success=10-04 15:37:41 + cadence 24h → 15:37:41 才 due，当日 0 条 run 记录。
- **关键发现：车间 daemon 已停**（daemon.json status=stopped，last_cycle 15:07:31，无存活进程，日志「信号15→已停止」）→ 15:00/17:00 档无人拉起，已报「需人工介入」，监理未重启。
- #9/#12/#13/#14 外发待核，保持原样 + 提示群回读核验。未代发台账，全程只读。
- 备注：任务流已由 12 条扩到 14 条，自动化名「12条任务流」建议后续改名。

## 2026-10-05 17:24（白天窗口，hour=17）
- **12/14 已完成**，未全绿，退出码 1。较 16:23 轮：#6 刷新至 17:03:02；其余 ✅ 无变化。
- ❌ 扩为 2 条，同一根因 `reason=workbench-entry-page-missing`（duration 0.35s 瞬时失败，log 仅一行 {"ok":false,...}）：
  - #10 智能客服15:00：当日 **4 次连续失败**（15:31:41 / 16:02:20 / 16:32:26 / 17:03:04），**已超连续 3 次线 → 已报「建议开单/需人工介入」**。
  - #11 智能客服17:00：首次 run 17:03:05 即同一原因失败（17:00 档被同一页面问题波及）。
- 跨日统计：该 reason 仅 2026-10-05 出现（10 个文件），属今日新发页面状态问题。
- 网关 192.168.0.5:8731/health 全 true（logged_in=true、worker=true）→ 排除微信掉登录/网关故障。
- daemon 正常：pid=39691、status=running、last_cycle 17:02:28、next 17:32:28（15:19 轮的停机已自愈并稳定运行）。
- 定性：按大同铁律属「美团 IM 工作台页面状态问题」，应上报车间主任做「关页重开」环境复位；**监理未下场代跑**。
- #9/#13/#14 外发待核，保持原样 + 提示群回读核验。未代发台账，全程只读。

## 2026-10-05 19:28（白天窗口，hour=19）
- **12/14 已完成**，未全绿，退出码 1。较 18:26 轮：#6 仍 18:04:15、**无新增成功**（守护已停，见下）。
- ❌ 仍 2 条（#10 x7、#11 x4），但**根因换了**：不再是 `workbench-entry-page-missing`（s1~s3 已能跑通），改为 step4 外发被拒：`reason=workflow-ledger-mismatch`，`verified=false, sendAttempts=null` → **实际未外发**。
- 真因定位：调用方传 `--ledger .../zhensi_waimai_back/skills/state/meituan-customer-reply-daily/wechat-attempts`，而封印注册表 `_REGISTRY_LEDGERS` 期望 `PROJECT/state/meituan-customer-reply-daily/wechat-attempts`（PROJECT=SKILLS.parent，**无 skills/ 段**）→ 路径多一层被 prepare() 拒发。证据：12:17:34 成功那次的 receipt 内台账路径正是根 `state/...`；根 state 目录存在且 12:18 更新，而 `skills/state/` 整个目录不存在。
- 该 reason 当日仅 2 次（18:34 / 18:35，首次出现），未达连续 3 次线；但 #10/#11 当日累计失败 7/4 次。**已建议开单/人工介入**（改调用方 ledger 路径），监理未下场改代码/代跑。
- 无「0 表外发」风险：待发 xlsx 4 行数据且 12:17 已成功外发过同一文件（sha 一致），重发被闸门拦下反而未造成重复外发。
- **守护已停（重要）**：daemon.json 仍写 pid=39691/status=running/next 19:04:20，但 `ps -p 39691`、`pgrep run_all.py` 均无进程，state 文件最后更新 18:36:39 → 19:04、19:34 两轮周期未执行。**已报需人工介入，监理未重启**。
- 网关 192.168.0.5:8731/health 全 true（logged_in/worker/uiautomation=true）→ 排除微信掉登录与网关故障。
- #9/#13/#14 外发待核，保持原样 + 提示群回读核验。未代发台账，全程只读。

## 2026-10-05 18:26（白天窗口，hour=18）
- **12/14 已完成**，未全绿，退出码 1。较 17:24 轮：#6 刷新至 18:04:15；其余 ✅ 无变化。
- ❌ 仍 2 条且**同一根因 `reason=workbench-entry-page-missing`**（duration 0.35~0.36s，log 仅一行 {"ok":false,...}）：
  - #10 智能客服15:00：当日 **6 次连续失败**（15:31 / 16:02 / 16:32 / 17:03 / 17:33 / 18:04），远超 3 次线。
  - #11 智能客服17:00：当日 **3 次连续失败**（17:03 / 17:33 / 18:04），已达 3 次线。
  - 交叉证据：#8 智能客服12:00 档 12:16:34 仍成功 → 12:16 之后美团 IM 工作台页面状态才坏掉，指向页面/环境态而非业务逻辑。
- 网关 192.168.0.5:8731/health 全 true（logged_in=true、worker=true、uiautomation=true）→ 排除微信掉登录与网关故障。
- daemon 正常：pid=39691、status=running、last_cycle 18:03:17、next 18:33:17。
- 定性 + 已报「建议开单/需人工介入」：按大同铁律应由车间主任执行「关闭 IM 页→重开」环境复位；监理全程未下场代跑。
- #9/#13/#14 外发待核，保持原样 + 提示群回读核验。未代发台账，全程只读。

## 2026-10-05 21:34（白天窗口，hour=21）
- **当日首次 14/14 全绿**，脚本退出码 0。较 20:32 轮关键变化：**#10/#11 由 ❌ 转 ✅**（#10 20:58:45、#11 20:47:23），#3 刷新至 21:02:26、#6 至 21:18:05。
- 根因确认：20:38 之前连续拒发（workflow-ledger-mismatch 4 次 / workflow-meituan-customer-reply-path-mismatch 3 次），20:47 起 s4 日志出现 `sendAttempts:1` → ledger/marker 路径被修正后外发恢复，属**已自愈**。
- 告警探测（alert_send_rejections.py，扫 166 日志，退出码 1）三条 reason 全是 20:38 前的历史：`workflow-ledger-mismatch` x4、`workflow-meituan-customer-reply-path-mismatch` x3、`legacy-marker-binding-mismatch` x3（taobao-flash s2，12:08~12:21）。均 `verified=false + sendAttempts=null`＝从未发出。ledger-mismatch 当日 4 次超线 → 已报「建议开单」固化路径修复，监理未改代码/未代跑。
- #9/#13/#14 外发待核，保持原样 + 提示群回读核验。已提示「全绿可发台账」但**未代发**（需守护跑 ledger_gate.py 为 GO）。全程只读。
- 下一小时 22:xx 为白天窗口最后一轮；23:00 应自暂停。

## 2026-10-05 20:32（白天窗口，hour=20）
- **12/14 已完成**，未全绿，退出码 1。较 19:28 轮：#6 刷新至 20:26:49、#12 至 20:27:58；其余 ✅ 无变化。
- ❌ 仍 2 条（#10 x8、#11 x5），根因与 19:28 一致：step4 外发 `reason=workflow-ledger-mismatch`，`verified=false, sendAttempts=null` → **实际未外发**。s1~s3 均跑通（#10 20:26 那次 scanned 24 / candidateCount 0）。
- 该 reason 当日累计 **4 次**（18:34/18:35/20:26/20:27，两条流各连续 2 次），跨日仅今日出现；#10/#11 当日累计失败 8/5 次 → **已报「建议开单/需人工介入」**（真因：调用方 ledger 传 `skills/state/...`，封印注册表期望根 `state/...`）。监理未改代码、未代跑。
- **守护已自愈**：19:28 轮的停机结束，daemon pid=62346、status=running、started 20:26:37、next 20:56:37，进程存活。
- 网关 192.168.0.5:8731/health 全 true（logged_in/worker/uiautomation/ready）→ 排除微信掉登录与网关故障。
- #9/#13/#14 外发待核，保持原样 + 提示群回读核验。未代发台账，全程只读。

## 2026-10-05 23:05（迁移收尾验证轮）
- 迁移收尾完成：修 FROZEN_HASHES 哈希、补 isLoginUrl 既有缺陷、mjs 33 测试 31 OK（2 个为验收型需真实产物）。
- 全流检查：daily_progress 14/14 全绿、守护存活（70959）、网关 health 全 true、alert 探测无新增拒发。
- 整点 automation 在岗自验；已清理 2 个过期一次性 automation。遗留：test_run_all_coverage 8 个既有漂移失败等 4 项已登记当日日志。

## 2026-10-05 23:35（遗留项清零轮）
- 4 项遗留全部闭环：test_run_all_coverage 重写后根测试 74/74 OK；legacy-marker 幂等拒发改 SKIPPED_IDEMPOTENT（三层：skill_runner/receipt/record_outcome）；jinsha entrypoint 钉值核对一致零改动；#9/#13/#14 定性为显式 noop 转"无待发内容"。
- daily_progress 新增 noop 识别；ledger_gate GO。后续整点轮按新口径汇报：root 测试已全绿，legacy-marker 不再列为开单项。

## 2026-10-06 14:50（白天窗口，hour=14）
- **9/14 已完成，未全绿**，daily_progress 退出码 1（设计信号），alert 探测退出码 1（有告警）。
- ✅：#2 10:32:04、#3 13:18:40、#4 14:26:29、#6 11:42:37、#7 12:14:58（外发待核→群回读）、#11 12:46:55、#12 10:30:16、#13 11:04:10、#14 14:25:08。
- #1 top10 口径异常（重点）：脚本计 ❌ x11，但**当日 12:26:20 存在 verified 外发硬证据**（marker `send-ledger/2026-10-05-main-16379fcc7508.json`，verified=true、sendAttempts=2、windows-readback-file-card 回读、图 2026-10-05_top10seller.png → FEIBING NEO AI数字员工）⇒ 实为已送达；13:17/13:49/14:22 三次为幂等保护不重发。已报「建议开单修正 daily_progress 口径」，监理未改状态。
- #5 淘宝新增商家增量通知：当日 30 条 record 全败、0 外发（cursor 末次 verified=10-05 18:04:15）。三段根因：00:27–08:13 x17 `windows-driver-local-network-blocked`（daemon 缺本地网络 TCC / Errno65）；09:16–13:18 x11 `background-profile-state-mismatch`（collection）；14:04 `desktop-send-invalid-receipt`、14:26 `legacy-attempt-reconcile-only`（desktop_wechat）。远超连续 3 次线 → 已报「建议开单/需人工介入」。
- #8（1425 档）**非失败**：last_success 10-05 14:45:41，24h cadence → 14:45:41 才 due；守护周期 :22/:52，当日首跑落在 14:52:09 那轮。#9(15:00)/#10(17:00) 排班未到点。
- 网关：**192.168.0.2:8731 全 true**（ok/agent up/uiautomation/wechat_running/**logged_in**/ready/worker）；192.168.0.5 超时 EXIT=28（与大同 10-06 定性一致：Mac 侧仅有线 .2 可达）。排除微信掉登录/网关故障。
- 守护正常：pid=59783、status=running、last_cycle 14:22:09、next 14:52:09、进程存活 28:47。
- #7 外发待核 → 保持原样 + 提示群回读核验。未全绿故未代发台账。全程只读，未改状态文件/未发微信。

## 2026-10-06 19:01（白天窗口，hour=19）
- **14/16 已完成，未全绿**，daily_progress 退出码 1（设计信号）；alert 探测退出码 1（有告警）。
- **流总数由 14 → 16**：新增 #14 negative-feedback-list-appeals-0930、#15 negative-feedback-list-appeals-1230（负反馈列表申诉·双平台）。
- #14/#15 定性（重点，非失败）：manifest 中已登记 enabled=true/dev_state=active（09:30/12:30），**但守护 17:47 启动、manifest 18:23 才改**，守护仍跑旧快照 14 条 → last_cycle.json/failure_watch.json 均无这两条，`run_history/2026-10-06/` 零 record。**从未被调度执行**，非执行失败、无 receipt reason。已报「需人工介入（重启守护加载新 manifest 或排班生效）」，监理未重启。
- #14/#15 产物已由大同并行开发进程手工产出（outputs/negative-feedback-list-appeals-20261006/，18:10，美团+淘宝两个 xlsx/png 齐全），但**无任何外发证据**（无 receipt/send marker）→ #15 的「Excel 汇总发群」未执行。
- 告警三条 reason 均**已核实为当日幂等**，非真故障：top10 当日 verified marker 2026-10-05-main-16379fcc7508.json（12:27:30，verified=true、sendAttempts=2）；taobao-flash receipt verified=true/sendAttempts=1/windows-readback-file-card；new-merchants 18:48:30 receipt verified=true。→ legacy-marker-binding-mismatch x30、legacy-attempt-reconcile-only x1、workflow-ledger-mismatch x1 全部属幂等保护。
- 网关：**192.168.0.2:8731 全 true（logged_in=true）**；.5 超时 EXIT=28（与 10-06 定性一致）。守护正常：pid=89939、started 17:47:19、last_cycle 18:48:27、next 19:18:27、进程存活。
- #1/#7/#9/#10 外发待核，保持原样 + 提示群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-06 20:05（白天窗口，hour=20）
- **14/16 已完成，未全绿**，daily_progress 退出码 1（设计信号）；alert 探测退出码 1，扫 174 日志。
- ❌ 仅 #14/#15（negative-feedback-list-appeals-0930/-1230）：当日 run_history 精确 glob **零 record**，last_cycle.json 仅 14 条且无此两条 ⇒ **从未被调度**。根因：守护 17:47:19 启动早于 manifest（skills_manifest.json）18:23:34 改动，仍跑旧 14 条快照。已报「需人工介入：重启守护加载新 manifest」，监理未重启。
- ⚠️ **网关可达性翻转（与 10-06 上午定论相反）**：`.2` ping 100% 丢包 / health code=000；`.5` ping 0% 丢包（17ms）/ health 200 全 true。⇒ 当前 Mac 侧只有无线 `.5` 可达；中继 127.0.0.1:8732 仍 200。
- 告警三条 reason 逐条核实**均为当日幂等**：top10 x7 有 evidence-verified marker 2026-10-05-main-16379fcc7508.json(state=verified)；taobao-flash x23 有 19:19:41 `verified=true / already_verified`；new-merchants reconcile-only 为 14:26（19:50 已自愈）；workflow-ledger-mismatch 仅 10:31 一次未达线。
- 守护正常：pid=89939、last_cycle 19:50、next 20:20、存活 2h18m。#1/#7/#9/#10 外发待核 → 群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-06 21:09（白天窗口，hour=21）
- **16/16 全绿**，daily_progress 退出码 0；alert 探测退出码 1（扫 206 日志，有告警）。
- **当日首次全天全绿**：#14/#15（负反馈双平台 09:30/12:30）由 20:05 轮的「从未被调度」转 ✅（#14 20:35:56、#15 21:05:19），因守护重载新 manifest。守护 pid 由 89939 → **26326，started 21:05:48**，last_cycle.json `all_green=true`，next 21:35:48。
- 告警四条 reason 逐条核实，全部为**已自愈/幂等**，无真未送达：
  - `workflow-not-registered` x4（#15 @20:11:55/20:23:51/20:26:47/20:28:26）：s2 bridge `--workflow-id negative-feedback-list-appeals` 被 Windows 侧判未注册，verified=false/sendAttempts=null。**连续 4 次超 3 次线 → 已报「建议开单」**；21:03:48 已 SUCCESS（verified=true、sendAttempts=2、windows-readback-file-card，两个 xlsx 送达 FEIBING NEO AI数字员工）。真因=workflow-id 注册时序，次日 12:30 档可能复发。
  - `legacy-marker-binding-mismatch` x32：top10 x7（13:17~16:28，当日 12:27 verified marker `2026-10-05-main-16379fcc7508.json` state=verified/sendAttempts=2）；taobao-flash x23（00:58~12:14，19:19:41 SUCCESS 且 reason=`business-date-marker-already-verified`）；#15 x2（20:53/20:58，随后 21:03 成功）→ 均幂等。
  - `legacy-attempt-reconcile-only` x1（new-merchants，20:54 已 SUCCESS）、`workflow-ledger-mismatch` x1（top10 10:31，仅 1 次未达线）。
- 网关可达性**仍与 10-06 上午定论相反**：`.2` code=000 不可达；`.5` code=200 全 true（logged_in=true）。与 20:05 轮一致 ⇒ 晚间 Mac 侧仅有线之外实为无线 `.5` 可达，已如实提示，未改任何配置。
- #1/#7/#9/#10/#14 外发待核 → 保持原样 + 提示群回读核验。已提示「全绿可发台账」但**未代发**（需守护跑 ledger_gate.py 为 GO）。全程只读，未改状态/未发微信。

## 2026-10-06 22:13（白天窗口，hour=22 · 当日最后一轮）
- **16/16 全绿且连续第二轮**，daily_progress 退出码 0；alert 探测退出码 1（扫 209 日志）。
- **关键：本小时零新增拒发**。四条 reason 计数与 21:09 轮完全相同（legacy-marker 32 / workflow-not-registered 4 / reconcile-only 1 / ledger-mismatch 1），仅扫描日志数 206→209（新增日志无拒发）⇒ 21:05 后无新故障。
- #15「外发待核」→「已外发」：最新 record `negative-feedback-list-appeals-1230--20261006-210348--record.json` status=SUCCESS、detail「全部 2 步 exit=0」、21:03:48→21:05:19、耗时 91s ⇒ workflow-not-registered（20:11/20:23/20:26/20:28 共 4 次）已自愈闭环，但**当日累计 4 次仍超线，维持「建议开单」**（真因=workflow-id 注册时序，次日 12:30 档可能复发）。
- 刷新时刻：#5 淘宝新增商家 21:36→22:07:39（每小时档，本轮仍在跑）。守护健康：pid=26326、started 21:05:48、last_cycle 22:06:39、next 22:36:39、status=running、last_cycle.json `all_green=true`。
- #1/#7/#9/#10/#14 外发待核 → 群回读核验。已提示「全绿可发台账」但**未代发**（须守护跑 ledger_gate.py 为 GO）。全程只读，未改状态/未发微信。

## 2026-10-08 13:20（白天窗口，hour=13）
- **12/16 已完成，未全绿**，daily_progress 退出码 1（设计信号）；alert 探测退出码 1（扫 87 日志，有告警）。
- ❌ 仅 #4 daily-taobao-download-to-jinsha（每日13:00）：13:01:53 一次 run，真因 `taobao-login-expired`（伴 `taobao-auth-seed-not-unique:0`，stage=taobao_task_open，耗时 1.9s 即失败）⇒ 淘宝固定后台 profile `taobao-brand:9230` 登录态过期；微信侧只是 `receipt-not-completed`（sendAttempts=0、imageSha256=[] ⇒ 零外发），非微信故障。跨日统计该 reason 仅 2026-10-08 出现（首现，未达连续 3 次线）→ 已报「需人工介入：重新登录淘宝 profile」，监理未下场。
- 告警 1 条 reason：`legacy-marker-binding-mismatch` x16（taobao-flash，00:25~08:31 每 2h 一档）→ 已核实为**幂等且已闭环**：业务日期 2026-10-07 的 marker 于 09:14:20 写入 state=verified、windows-readback-file-card、sendAttempts=1、送达 FEIBING NEO AI数字员工；09:13:31/11:22:50 两次 SUCCESS（后者 reason=business-date-marker-already-verified）。但 00:25~08:31 期间确未发出，属**延迟至 09:13 才送达**。
- 网关可达性：`.5` code=200 全 true（logged_in=true）；`.2` code=000 不可达（延续 10-06 晚间翻转）。守护 pid=38617、started 10:47:12、last_cycle 13:01:50、next 13:31:50、存活 2h35m。
- #7/#14 外发待核 → 保持原样 + 提示群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-08 16:30（白天窗口，hour=16）
- **14/16 已完成，未全绿**，daily_progress 退出码 1（设计信号）；alert 探测退出码 1（扫 109 日志，1 条 reason）。
- ❌ 仅 #4 daily-taobao-download-to-jinsha（每日13:00）：**当日连续 7 次失败**（13:01:53/13:33:17/14:03:48/14:35:12/15:06:06/15:37:14/16:07:47），真因 `taobao-login-expired`（stage=taobao_task_open、63ms 即失败、pitfall code=run-failure）；微信侧 `receipt-not-completed`、sendAttempts=0、imageSha256=[] ⇒ 零外发，**非微信故障**，是闸门因回执未完成拒发。跨日统计该 reason 仅 2026-10-08 出现（首现），但当日 7 次远超连续 3 次线 → 已报「建议开单/需人工介入：重登淘宝固定后台 profile `taobao-brand:9230`」，监理未下场。
- 较 13:20 轮变化：#4 由 1 次失败累积到 7 次（失败计数 x1→x7）；#5 淘宝新增商家 16:07:54 成功（由 13:20 轮的持平时点刷新）；#16 品牌差评申诉 13:33:21 已 ✅；#6/#8 刷新至 11:22:48/14:35:38。
- 告警 `legacy-marker-binding-mismatch` x16（taobao-flash，00:25~08:31 每 2h 档）→ 已核实**幂等且闭环**：09:13:31 SUCCESS、09:14:20 写入业务日 2026-10-07 marker（state=verified/sendAttempts=1/windows-readback-file-card/送达 FEIBING NEO AI数字员工）；15:37:16 reason=`business-date-marker-already-verified` + verified:true ⇒ 属**延迟至 09:13 才送达**，非真未送达。计数与 13:20 轮完全相同（16），13:20 后零新增拒发。
- #10（美团智能客服 17:00 档）排班未到点，非失败。
- 网关：`.5` code=200 全 true（logged_in=true）；`.2` code=000 不可达（延续翻转）。守护 pid=38617、started 10:47:12、存活 5h43m、last_cycle 16:07:44、next 16:37:44、status=running。
- #7/#9/#14 外发待核 → 保持原样 + 提示群回读核验。未全绿故**未代发台账**。全程只读，未改状态文件/未发微信。

## 2026-10-08 17:32（白天窗口，hour=17）
- **15/16 已完成，未全绿**，daily_progress 退出码 1（设计信号）；alert 探测退出码 1（扫 116 日志，1 条 reason）。
- ❌ 仅 #4 daily-taobao-download-to-jinsha（每日13:00）：当日累计 **9 次失败**（13:01:53/13:33/14:03/14:35/15:06/15:37/16:07/16:38/17:10）。
- **★ 根因中途变更（本轮重点，与 13:20/16:30 轮口径不同）**：13:01–16:07 共 7 次为 `taobao-login-expired`（phase=profiles_ready，淘宝 profile 登录过期，63ms 即失败）；**16:38 起淘宝侧已恢复**——taobao_open/downloaded/closed 全 completed，门店/评价 xlsx 已落地（sha256 齐全），**新卡点在金鲨**：`jinsha_store_dedup_upload` → `completed-log-missing-first-read` → `jinsha-upload-overlay-unrecognized` → `recovery-budget-exhausted:jinshaLogReload`。16:38/17:10 两次均带 `production-resume: safe-failed-receipt-reused`，复用 09:10 那次的失败收据续跑（runId `f2e892bb-13e7-449e-ae2c-938d9b740e70`）。
- 微信侧零外发：sendAttempts=0、imageSha256=[]、reason=`receipt-not-completed` ⇒ 闸门因业务回执未完成拒发，**非微信故障**；网关 .5 health 全 true（logged_in=true），.2 EXIT=28 不可达（延续翻转）。
- 9 次远超连续 3 次线 → 已报「建议开单/需人工介入：① 金鲨上传弹层识别（overlay-unrecognized）② 失败收据复用导致死循环续跑」，监理未下场。
- 告警 `legacy-marker-binding-mismatch` x16（taobao-flash，00:25~08:31）→ 已核实幂等且闭环：当日 11:22:50/13:33:19/15:37:16 三次 SUCCESS，计数与 13:20/16:30 轮完全相同，13:20 后零新增拒发。
- #7/#9/#10/#14 外发待核 → 保持原样 + 群回读核验。未全绿故未代发台账。全程只读。

## 2026-10-08 20:36（白天窗口，hour=20）
- **15/16 已完成，未全绿**，daily_progress 退出码 1；alert 探测退出码 1（扫 123 日志，仅 `legacy-marker-binding-mismatch` x16 属 taobao-flash-sale-negative-review-appeals，与 12:16 起多轮完全相同 ⇒ 零新增，幂等历史）。
- ❌ 仅 #4 daily-taobao-download-to-jinsha（13:00）：**当日 12 次全败**（13:01→20:37），failure_watch consecutive_failures=**12**。
- **★ #4 真因已变更（重要）**：15:26 轮之前是 `taobao-login-expired`；自 16:07 轮起转为 **`recovery-budget-exhausted:jinshaLogReload`**——phase=`jinsha_open`、inner stage=`jinsha_store_dedup_upload`、`upload` 点击 0 次（store/review 均未上传）；且 phaseHistory 已到 `taobao_downloaded`（⇒ 淘宝登录已恢复，不再是登录问题）。18:13 轮页面快照含横幅「您的淘宝闪购平台当前有16家店铺授权失败 请及时查看」（业务级诱因，跨日仅今日出现）。⇒ 升级为「需人工介入：金鲨上传日志读取/去重步骤 + 16 家店铺授权」。
- 网关健康：`.5` health 200 全 true（logged_in=true）、中继 8732 200 全 true；`.2` EXIT=7 不可达（延续）。
- 守护健康：pid=38617、started 10:47:12、last_cycle 20:37:37、next 21:07:37、running（存活 ~9h50m）。
- 20:37 轮补跑：#5 SUCCESS 20:38:00、#11 SUCCESS 20:38:32（均无新增内容未刷新「当日成功时间」）；#16 三班（09/13/17）已收口。
- #7/#9/#10/#14 外发待核 → 群回读核验。未全绿故未代发台账。全程只读，未改任何状态文件。

## 2026-10-08 23:45（夜间窗口，hour=23 → 触发自暂停）
- 窗口守卫：date +%H = 23（>=23），未跑 daily_progress.py / alert 探测，未做任何检查。
- 已 automation_update（list→update，id 7a6c1a59-cce2-43ed-9442-612f360b5e22）置 **PAUSED**；明早 09:00 由「监理晨间唤醒（id d456b850…）」恢复。
- 交接：白天末轮 22:43 为 **16/16 全绿（当日首次）**，#4 daily-taobao-download-to-jinsha 连败 12 次后 22:13:55 自愈 SUCCESS、failure_watch consecutive_failures 归 0；告警仅 legacy-marker-binding-mismatch x16（taobao-flash 幂等历史，多轮零新增）；守护已换实例 pid=90951（22:15 起）；网关 .5 health 全 true（logged_in=true）、.2 不可达（延续）。#7/#9/#10/#14 外发待核 → 群回读核验；未代发台账。全程只读。

## 2026-10-08 22:43（白天窗口，hour=22 · 当日最后一轮）
- **★ 16/16 全绿（当日首次）**，daily_progress 退出码 0；alert 探测退出码 1（扫 141 日志，仅 `legacy-marker-binding-mismatch` x16）。
- **★ #4 daily-taobao-download-to-jinsha 已恢复**（13:20→20:36 连败 12 次后）：22:00:29 最后一次 FAILED（`stage=wechat-send-failed (receipt:stage)`、phase_last=profiles_ready），**22:13:55→22:15:22 SUCCESS、detail「全部 1 步 exit=0」**。当日共 21 条 record，failure_watch `consecutive_failures` 已归 0（全部 17 个流均 0）。⇒ 17:32/20:36 轮报的「金鲨上传弹层 unrecognized + 16 家店铺授权」卡点已自愈闭环，可撤单观察（次日 13:00 档需复核）。
- 告警 `legacy-marker-binding-mismatch` x16（taobao-flash）计数与 13:20/16:30/17:32/20:36 四轮**完全相同** ⇒ 20:36 后零新增拒发；当日 20:38:33 最后 SUCCESS（detail「全部 2 步 exit=0」）⇒ 幂等历史，非真未送达。
- **守护已重启**：旧 pid=38617 已退出，**新 pid=90951、started 22:15**（run_all.py --daemon），last_cycle cycle_at 22:15:55、`all_green=true`。
- 网关：`.5` health 200 全 true（logged_in=true/wechat_running=true/ready=true）；`.2` EXIT=28 不可达（延续 10-06 晚间翻转）。
- #7/#9/#10/#14 外发待核 → 保持原样 + 群回读核验。**已提示「全绿可发台账」但未代发**（须守护跑 ledger_gate.py 为 GO）。全程只读，未改状态文件/未发微信。
