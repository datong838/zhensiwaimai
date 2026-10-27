# 监理常驻主动督查 — 执行留痕

## 2026-10-08 23:38 (night) — GREEN
- 首轮执行，无历史 memory 文件，已新建。
- 巡检 verdict=GREEN，exit=0。四岗位 Chrome 全 ok：9230(1页)/9231(1页)/9232(6页)/9233(2页)，无残留 /login 页、无重复业务页。
- daemon careloop 存活：pid 90951，last_cycle 23:16:55，next 23:46:55（落后 21 分钟，未触发 >45min kickstart）。
- 上轮 22:54 的 YELLOW（21:59 jinsha 证据图 attempted 未 verified）本轮已消失，判定已收口，不再上报。
- 仅 1 条 INFO：今日有 1 条登录类告警历史记录（历史，非当前登录态）。
- 未执行任何下场动作（无生产流、无发送、无改码、无新开标签页）。

### 复用要点
- 本任务只管环境面+外发面，进度表交给 7a6c1a59，勿重复输出 14 行状态表。
- GREEN 时按规范只输出一行结论，不展开。
- 夜间 phase=night：Windows 主机双侧不可达属预期，不告警。

## 2026-10-09 00:39 (night) — 脚本 YELLOW / 职责面 GREEN
- 脚本 verdict=YELLOW，两条 YELLOW 全是 flow 进度项（flows-not-green、cycle-non-success PENDING×14），**非环境面**；按分工交 7a6c1a59，不到 21:30 末档不上报车间主任。
- 四岗位 Chrome 全 ok；用 `curl -s --noproxy '*' -m 4 -H "Host: localhost" http://127.0.0.1:<port>/json/list` 枚举全量标签页，无 `/login` 残留、无重复业务页（9232 的多个 ctyun 子页属正常）。
- careloop pid 90951 存活，last_cycle 00:18:59 / next 00:48:59，落后 ~21min < 45min ⇒ 未执行 kickstart。
- 外发面：sent_today 无 2026-10-09 键 ⇒ 今日零发送，无 attempted 未 verified。
- 两条 FAILED 已定性为**发送前失败、零外发**：`daily-agent-new-merchants-to-wechat`=windows-driver-unreachable(RECOVERABLE_NO_SEND)；`taobao-flash-sale-negative-review-appeals`=0 条禁发 + legacy-marker-binding-mismatch(sendAttempts null)。
- 双侧 .2/.5 `/health` 均 http=000 超时 ⇒ 夜间休眠预期态。
- 新增经验：`runtime/state/sent_today.json` 是判断「今日是否已外发」的最快只读凭据（无当日键=当日零发送），比翻 run 目录快得多。

## 2026-10-09 01:43 (night) — RED（9233 残留 /login 页）
- 巡检 verdict=RED，exit=2。唯一 RED：`chrome/login-page-present:9233`——9233 里多出一个非业务页 `http://localhost:3001/login?redirectTo=%2F`（标题「Carbon | Login」，node pid 33722 本地服务，page id A2C78824…）。已用 /json/list 枚举全量 page 复核，**非假阳性**：9233 共 3 页（imworkbench 正常 + 该 login 页 + 美团外卖商家版正常），残留 URL 含 /login ⇒ 执行器会整轮 fail-closed。
- 定性：不是美团掉登录，是本地 3001 前端登录页被开在了 IM 岗位浏览器里 → 属岗位污染，需大同关掉该标签页（勿关两个美团页）。上报，未自行处理。
- 其余环境面 GREEN：9230(1 业务页)/9231(1)/9232(ctyun 多子页，正常)；careloop pid 90951 running，last_cycle 01:28:09 / next 01:58:09，落后 ~15min <45min ⇒ 未 kickstart。
- 外发面 GREEN：`runtime/state/sent_today.json` 无 2026-10-09 键 ⇒ 今日零外发，无 attempted 未 verified。
- 今日 alerts 10 条全 category=UNKNOWN，两条族：appeals=legacy-marker-binding-mismatch（幂等拒发，sendAttempts=0 零外发）；new-merchants=desktop_wechat_preflight 失败（夜间 Windows 休眠/微信窗口不可用的环境态）。均非外发事故，交车间。
- 两条 YELLOW（flows-not-green / cycle-non-success PENDING）为 flow 进度项，按分工交 7a6c1a59，未到 21:30 末档不上报。
- 未执行任何下场动作。

### 新增经验
- `runtime/state/alerts.jsonl` 字段是 `ts/skill/category/detail/log`，用 `detail` 取正文；本次 10 条全 UNKNOWN，判轻重看 detail 里的 stage/embedded-reason，而不是 category。
- 9233 岗位可混入本地 dev server 页（localhost:300x）造成假 /login 污染，巡检时除看 URL 含 /login 外，要区分「美团自家登录」与「本地项目登录页」再定性话术。

## 2026-10-09 02:45 (night) — 环境面 GREEN（脚本 YELLOW 全为进度项）
- 脚本 verdict=YELLOW / exit=0（exit=2 才代表 RED）。两条 YELLOW 仍是 flow 进度项（flows-not-green、cycle-non-success PENDING×14）⇒ 按分工交 7a6c1a59，未到 21:30 末档不上报。
- **上轮 01:43 的 RED（9233 残留 localhost:3001/login 页）本轮已消失**：/json/list 枚举确认 9233 仅剩 imworkbench 业务页 + 2 个 Omnibox Popup ⇒ 污染页已被关掉，RED 自动收口，无需再上报。
- 四岗位环境面全绿：9230(淘宝闪购商家版，含 alicdn frame/blob 附属页属正常)/9231(服务商平台)/9232(臻肆外卖运营 negativeAnalyse，ctyun 子页已从 6 减到 1，业务页在位)/9233(美团 IM 工作台)；无 /login、无重复业务页。
- careloop pid 90951 存活（started 10-08 22:15:55），last_cycle 02:30:56 / next 03:00:56，落后 ~14min <45min ⇒ 未 kickstart。
- 外发面：`runtime/state/sent_today.json` 无 2026-10-09 键 ⇒ 今日零外发，无 attempted 未 verified。
- 今日 alerts 14 条（较上轮 10 条新增 4 条）：02:00 `daily-agent-new-merchants-to-wechat` stage=collection 采集阶段失败；02:00 appeals error-code=connect；另 AUTH_EXPIRED(executor-lock 过期 49.3h) 与 3 条 `__desktop_channel__` NEEDS_USER（微信窗口非本空间/外来窗口遮挡）。均属 flow/Windows 夜间环境态，非外发事故，交车间。
- 未执行任何下场动作（无生产流、无发送、无改码、无新开标签页）。

### 新增经验
- 巡检脚本 **exit=0 不代表 GREEN**：YELLOW 也返回 0，只有 RED 返回 2。看结论以 stdout 标题行 `# 监理督查 ... — <verdict>` 为准。
- 守护心跳权威源是 `runtime/state/daemon.json`（pid/started_at/last_cycle_at/next_cycle_at/status）与 `runtime/state/last_cycle.json`，比 ps 更快算落后分钟。
- 上轮 RED 若本轮消失，说明已被人工/流程收口，属正常，不需重复上报；但要在结论里点一句「已收口」。

## 2026-10-09 03:47 (night) — 环境面 GREEN（脚本 YELLOW 全为进度项）
- 脚本 verdict=YELLOW / exit=0。两条 YELLOW 仍是 flow 进度项（flows-not-green「未完成 0 条：?」、cycle-non-success PENDING×14）⇒ 按分工交 7a6c1a59，未到 21:30 末档不上报车间主任。
- 上轮 01:43 的 RED（9233 残留 localhost:3001/login 页）已收口，连续第二轮未复现。
- 四岗位环境面全绿：9230(淘宝闪购商家版 1 业务页 + alicdn iframe×2 + blob worker，属正常附属)/9231(服务商平台)/9232(臻肆外卖运营 realTimeData)/9233(美团 IM 工作台)；无 /login、无重复业务页、无本地 dev server 污染页。
- careloop pid 90951 存活，last_cycle 03:33:39 / next 04:03:39，落后 ~14min <45min ⇒ 未 kickstart。
- 外发面 GREEN：`runtime/state/sent_today.json` 仍无 2026-10-09 键 ⇒ 今日零外发，无 attempted 未 verified（`send_receipts/` 目录本就不存在，脚本未报回执项即绿）。
- 今日 alerts 增至 18 条（上轮 14）。三条稳定族，全部**零外发**：① `daily-agent-new-merchants-to-wechat` 在 desktop_wechat_preflight / collection 间交替失败（夜间 Windows 休眠 + 微信窗口非本空间，环境态）；② `taobao-flash-sale-negative-review-appeals` = legacy-marker-binding-mismatch 幂等拒发 + error-code=connect；③ AUTH_EXPIRED(executor-lock 过期 49.3h) 与 `__desktop_channel__` NEEDS_USER。均交车间，非外发事故。
- 未执行任何下场动作。

### 新增经验
- 02:31→03:02 起 `new-merchants` 从 `stage=collection` 变回 `stage=desktop_wechat_preflight`、`appeals` 从 `error-code=connect` 变回 `legacy-marker-binding-mismatch`：**夜间同一族告警会随周期在两三个 stage 间来回跳**，不要逐条当新故障，按「族」归并定性即可。
- `appeals` 的 `idempotent-skip-UNVERIFIED` 含 UNVERIFIED 字样但**不等于 attempted 未 verified 外发回执**——它是 marker 幂等拒发（sendAttempts=0），判外发面只认 `sent_today.json` 当日键与回执状态。

## 2026-10-09 04:48 (night) — 环境面 GREEN（脚本 YELLOW 全为进度项）
- 脚本 verdict=YELLOW / exit=0。两条 YELLOW 仍为 flow 进度项（flows-not-green、cycle-non-success PENDING×14）⇒ 交 7a6c1a59，未到 21:30 末档不上报车间主任。
- 四岗位全绿且**每岗仅 1 个业务页**（9230 淘宝闪购商家版 / 9231 服务商平台 / 9232 臻肆外卖运营 realTimeData / 9233 美团 IM 工作台），无 /login、无重复业务页、无 localhost:300x 污染页（01:43 的 RED 连续第三轮未复现）。
- careloop pid 90951 存活，last_cycle 04:37:14 / next 05:07:14，落后 ~11min <45min ⇒ 未 kickstart。
- 外发面 GREEN：`sent_today.json` 仍无 2026-10-09 键 ⇒ 今日零外发。
- 今日 alerts 22 条（上轮 18），**未出现新族**：仍是 new-merchants=desktop_wechat_preflight、appeals=legacy-marker-binding-mismatch 两族交替，全部零外发。
- 未执行任何下场动作。

### 新增经验
- 顺带确认：/json/list 里 `browser_ui`(Omnibox Popup) 与 `iframe`(alicdn xdomain-storage)、`worker`(blob:) 均为正常附属，不是重复业务页，巡检时看 `type=page` 计数即可。

## 2026-10-09 05:49 (night) — 环境面 GREEN（脚本 YELLOW 全为进度项）
- 脚本 verdict=YELLOW / exit=0。两条 YELLOW 仍为 flow 进度项（flows-not-green、cycle-non-success PENDING×14）⇒ 交 7a6c1a59，未到 21:30 末档不上报车间主任。
- 四岗位全绿且**每岗仅 1 个 `type=page` 业务页**（9230 淘宝闪购商家版 stats__center / 9231 服务商平台 / 9232 臻肆外卖运营 realTimeData / 9233 美团 IM 工作台 imworkbench）；无 /login、无重复业务页、无 localhost:300x 污染页（01:43 RED 连续第四轮未复现）。
- careloop pid 90951 存活（started 10-08 22:15:55），last_cycle 05:40:49 / next 06:10:49，落后 ~9min <45min ⇒ 未 kickstart。
- 外发面 GREEN：`sent_today.json` 无 2026-10-09 键（末键为 2026-10-08）⇒ 今日零外发，无 attempted 未 verified。
- 今日 alerts 26 条（上轮 22），**未出现新族**：new-merchants=desktop_wechat_preflight×9 + collection×2、appeals=legacy-marker-binding-mismatch×9 + connect×2，`__desktop_channel__` NEEDS_USER×3，均为零外发环境态/幂等拒发，交车间。
- 未执行任何下场动作（无生产流、无发送、无改码、无新开标签页）。

### 新增经验
- 判断「岗位页数」时 `/json/list` 会返回 iframe/worker/browser_ui，用 `type=page` 过滤后的计数才是真业务页数；本轮四岗都恰好=1，是最干净的一次形状，可作基线对照。

## 2026-10-09 06:50 (business) — 环境面 GREEN（脚本 YELLOW 全为进度项）
- **本轮是首个 phase=business 档**（06:44 起切出 night）。脚本 verdict=YELLOW / exit=0，两条 YELLOW 仍为 flow 进度项（flows-not-green「未完成 0 条」、cycle-non-success PENDING×14）⇒ 交 7a6c1a59，未到 21:30 末档不上报车间主任。
- 四岗位全绿，各 1 个 `type=page` 业务页：9230 淘宝闪购商家版 stats__center / 9231 服务商平台 / 9232 臻肆外卖运营 realTimeData / 9233 美团 IM 工作台 imworkbench；无 /login、无重复业务页、无 localhost:300x 污染页（01:43 RED 连续第五轮未复现）。
- careloop pid 90951 存活（started 10-08 22:15:55），last_cycle 06:44:25 / next 07:14:25，落后 ~6min <45min ⇒ 未 kickstart。
- 外发面 GREEN：`sent_today.json` 无 2026-10-09 键（末键 2026-10-08）⇒ 今日零外发，无 attempted 未 verified。
- 今日 alerts 30 条（上轮 26），**无新族**：new-merchants=desktop_wechat_preflight×11 + collection×2；appeals=legacy-marker-binding-mismatch×11 + connect×2；`__desktop_channel__` NEEDS_USER×3；AUTH_EXPIRED(executor-lock)×1。全部零外发。
- Windows 网关 .2/.5 双侧 `/health` 仍 http=000（4s 超时）。06:50 属「夜休未醒、08:00 前唤醒」窗口 ⇒ 记录不上报；这正好解释 new-merchants 06:45 的 desktop_wechat_preflight 失败。**若 08:00 后仍双侧不可达，则升级为 YELLOW/需人工唤醒排查。**
- 未执行任何下场动作（无生产流、无发送、无改码、无新开标签页）。

### 新增经验
- **夜→昼切换档的判据边界**：phase 变 business 后「Windows 休眠不可达」不再自动豁免，但 06:00–08:00 仍在大同承诺的唤醒窗口内 ⇒ 只留痕、不上报；以 08:00 为升级线。
- 告警族计数器写法：按 `(skill, detail[:60])` 聚类即可一眼看出「有没冒新族」，比逐条读快，且能顺带给出每族条数。
- 夜间告警族已高度稳定（05:41 档两族各 9 条）：只要没冒出新族、且 `sent_today.json` 无当日键，即可一句话 GREEN 结案，无需逐条展开。
