# 历史资料：禁止作为现行操作授权

已脱敏；现行规则见 skills/mechanisms/ 对应Skill。旧例中停守护、旧通道和改账本操作均不适用。

---
name: zhensi-supervisor-patrol
description: 臻肆车间体系的「监理常驻主动督查」SOP：周期性巡检各任务流与四岗位浏览器，**发现问题必须当轮修复+安排补跑（登录态除外），禁止只报不修**。当大同说「督查」「巡检」「看看任务跑得怎么样」「别等我问」、或需要为一个长程任务建立主动监督机制时使用。
agent_created: true
---

# 监理常驻主动督查（臻肆车间体系）

仓库：`/Users/ddt/work/projects/ai_agent/zhensi_waimai_back`

> **零上下文接手监理，先看这份**：`zhensi_waimai_back/docs/operations/20261009-监理交接手册-v1.md`
> （含角色边界、四岗位、微信通道、9 条自动化全景、故障速查、未闭环事项、首周清单）

**一句话**：监理的价值是**在没人问的时候也一直在看**。大同 2026-10-08 明确要求：
「你是监理，你得不停地督查每个任务的运行情况，不要等我喊你、问你才去看。」

## 一条命令

```bash
cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back && \
/usr/bin/python3 runtime/supervisor_patrol.py          # 人读
/usr/bin/python3 runtime/supervisor_patrol.py --json   # 机读
```

退出码：`0` = 无 RED；`2` = 有 RED（需上报）。脚本**纯只读**，不跑流程、不发消息、不写生产数据。

巡检覆盖七项：

| 项 | 内容 |
|---|---|
| daemon | pid 存活、`last_cycle_at` 落后分钟数（阈值 45） |
| flows | 各流当日收口（复用 `daily_progress.py`），未完成清单 |
| last_cycle | 守护最近周期的非 SUCCESS 条目 |
| chrome | 四岗位 9230/9231/9232/9233：**枚举全部 page**、标记 `/login` 页与重复业务页；附 `runtime/chrome_asn_guard.sh`（只读）查「幽灵前台」——headless 岗位 ASN type=Foreground 会抢走点 Dock 图标的打开事件（10-18 两连复发，详见 macos-ui-automation skill），只报不动手 |
| outbound | 今日对外发送回执；`attempted` 且未 verified 的项 |
| **popup** | 9232 金鲨遮罩白名单覆盖（`check_popup` → `runtime/jinsha_popup_probe.mjs`，F11-4 兜底） |
| alerts | `runtime/state/alerts.jsonl` 今日聚合 |

### ★★★ 第八项（必须手工看）：互斥组孤儿锁 = SKIPPED_BUSY 假繁忙

`runtime/state/locks/<group>.lock` 是**进程级互斥组租约**，`POST_GROUP_LOCK_TTL_SECONDS = 90*60`（90 分钟）。
**持锁进程被 SIGTERM 杀死时不会释放锁**（`launchctl kickstart -k`、手动 kill daemon、daemon 崩溃都算），
于是同组流水线在整整 90 分钟里每轮都打 `[skip-busy] ... 被同组流水线新鲜占用`，
看起来像「有别的流在跑」，其实**同组无人** —— 两条流静默停摆，台账上表现为"没跑"。

**判据（一条命令，30 秒）**：

```bash
cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back && \
for f in runtime/state/locks/*.lock; do [ -f "$f" ] || continue; \
  pid=$(/usr/bin/python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['pid'])" "$f" 2>/dev/null); \
  if kill -0 "$pid" 2>/dev/null; then echo "OK     $f pid=$pid ALIVE"; \
  else echo "ORPHAN $f pid=$pid DEAD"; fi; done
```

- `pid` 已死 ⇒ 孤儿锁，**`mv` 成 `.lock.orphan-<HHMM>` 归档**（等价于代码里的过期自愈，但不用等 90 分钟）。
- 2026-10-22 实测：top10 自己 10:30:29 创建锁后被 SIGTERM 杀掉 ⇒ 锁把**自己**挡住；contract-termination 同因。
  清锁后下个周期两条都正常起跑。**先清锁，再谈"修流"**，否则会把"被挡住"误诊成"流本身坏了"。
- 别用 `ps aux | grep "run_all.py --daemon"` 判 daemon 死活：**grep 会匹配到你自己的命令行**，看起来永远有进程。
  真判据 = `launchctl print gui/$(id -u)/com.zhensi.waimai.careloop` 的 `state` +
  `runtime/state/daemon.json` 的 `pid` 是否 `kill -0` 存活 + `daemon.out.log` 是否仍在追加。

**popup 项依赖 node**：按 `SUPERVISOR_NODE` → PATH → 脚本内置 `NODE_CANDIDATES` 择优；
缺失/超时降级 INFO `probe-unavailable`，**绝不因依赖缺失误报 RED**。
该项判据：「存在可见 `.upload` 但文案未命中白名单」⇒ RED（执行器会静默放过）。
白名单在两侧各有一份（执行器 `closeKnownJinshaPopup` 与探针 `KNOWN`），**改一边必须同步另一边**。

## 判据分级（决定要不要惊动大同）

- **GREEN** → 只回一行结论，不展开、不罗列。
- **YELLOW** → 列异常 + 定性（排期内正常态 vs 真问题）+ 建议；追加一行到 `runtime/state/patrol_log.jsonl`。
- **RED** → 回复**开头**置顶「⚠️ 需要大同处理」，讲清 ① 是什么 ② 为什么是 RED ③ 需要他做什么一个动作（如「扫 9230 的码」）。

## 闭环驱动（2026-10-10 大同痛批后新增，关键）

> **核心教训**：原 `supervisor_patrol.py` 是「纯只读」，发现问题只落 `patrol_log.jsonl`，
> 没有任何东西去消费这些 finding 并当场处置 ⇒ 白天发现 bug → 只进日志 → 没人动 →
> 晚上被催才修。**这是「从白天卡到晚上」的真因，不是"懒"，是闭环断在最后一环。**
>
> 2026-10-10 起，巡检必须接 `runtime/supervisor_drive.py` 形成「发现→处置→排期→闭环」：
> 能当场安全处置的当场做，要人工的立即生成【具体动作请求】+ SLA 闹钟写进
> `runtime/state/war_room.json`，**绝不静默搁置等大同催**。SLA 超时由
> `c89f6bc8`（唯一告警发送者）自动发群告警给大同。

```bash
cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back && \
/usr/bin/python3 runtime/supervisor_drive.py            # 干跑（建看板/出报告，不执行）
/usr/bin/python3 runtime/supervisor_drive.py --apply    # 执行自处置类动作
```
退出码：`0`=无待处理；`2`=有待你处理项（自动化据此判 RED）。

分类口径：
- **可自处置（无对外重复发送，必须当场做）**：daemon 落后/死 pid→`launchctl kickstart`；
  四岗位 CDP 不可达→`runtime/bg-chrome-up.sh`；**四岗位「端口健康但渲染线程卡死」→
  `runtime/post_page_probe.mjs --apply`（仅 CDP Page.reload 复位 hung 页，不新开/关 tab、不点页面、不发送）**；
  marker 死点无证据→读回取证后 `conclude_attempt_deadlock --apply`（不重发）；
  outbound attempted 未 verified→读回标 verified；
  **封印漂移（白名单内）→ `runtime/seal_drift_repair.py --apply`（详见下节，2026-10-19 新增）**。
- **需上报（越红线/要人工）**：对外发送/重发、Mac 桌面微信、**白名单外的封印改动（=真篡改）**、
  登录页残留、金鲨未知遮罩。这类生成具体请求 + SLA，**超时（工作时段 30min）二次置顶**。

## 封印漂移自修（2026-10-19 大同裁定后新增，最高频故障）

> **事故原型（10-19 上午）**：前夜 `wechat-messaging/dependencies.json` 被合法重绑，下游三处钉死未同步
> ⇒ merchants 05:52 起连败 8 轮、top10 08:26 起连败 4 轮。42 条监控全都看到了，但
> `flows-not-green`/`cycle-non-success` 被判 INFO「归另一分工域」，而那一域自己声明只报不跑 ⇒ 无人修。
> 大同定性：**只要不是登录态问题，阻塞当日工作流的任何问题都要修复+补跑。**

```bash
cd /Users/ddt/work/projects/ai_agent/zhensi_waimai_back && \
env -u PYTHONPATH /usr/bin/python3 runtime/seal_drift_repair.py            # dry-run
env -u PYTHONPATH /usr/bin/python3 runtime/seal_drift_repair.py --apply    # 真修+排补跑
```

- **只修一类**：失配项全 ∈ `messaging_dependencies`（即上游共享微信清单被合法重绑）。白名单外一律 `escalate`（可能是真篡改）。
- **安全门**：修前查上游 `dependency_maintenance.py inspect`==clean；修后必须真校验器 PASS
  （merchants `verify_for_run` / top10 `validate_runtime_policy` / negative-reviews `--self-test`）。
- **补跑**：只写 `runtime/state/control.json` 的 `force_run`（daemon 下个周期采纳，周期 30min），
  且校验「今日无 SUCCESS + 今日零真实外发」，防重复外发。
- 已在 `supervisor_drive.py` 里接线（`heal_seal_drift`，守卫：`live_steps/` 非空不动）。
- 审计：`runtime/state/seal_drift_repair.jsonl`。
- 三条受管流的修复通道：merchants=SEALED resync（clean 回执+离线测试）、top10=直接重绑 runtime-policy、
  negative-reviews=`maintenance_executor.mjs prepare-unsealed-acceptance`（当日跑通后自动重封印）。

## 硬边界（监理不下场 ≠ 不处置）

「纯只读」原意是**不替车间跑带对外副作用的生产流、不碰 Mac 桌面微信、不重发**，
**不是「发现问题只记录不处理」**。安全范围内（上面「可自处置」类）必须当场处置。

**禁止**：跑带对外发送副作用的生产流（`manual_run_once.py` 属下场重发）、发送任何微信消息/文件/图片、
改生产代码、白名单外的封印改动、为「看一眼」新开浏览器标签页。

**允许**：只读探针、读回执日志、写 `patrol_log.jsonl` / `war_room.json`、
以及下面这些**当场自处置**：
- **daemon 落后 >45 分钟且 phase≠night** 时 `launchctl kickstart -k gui/501/com.zhensi.waimai.careloop`
- 四岗位 CDP 不可达时 `bash runtime/bg-chrome-up.sh`（幂等拉起）
- **四岗位页渲染线程卡死时 `node runtime/post_page_probe.mjs --apply`（仅对 hung 页发 CDP
  Page.reload；守卫=先确认 `runtime/state/live_steps/` 为空即无流在跑）**
- marker 死点读回取证后 `python3 runtime/conclude_attempt_deadlock.py --apply`（本地结论化，不重发）
- **marker 死角（`blocked∧0` 但 reason 不在发送器白名单）→ 机器取证「零发送」后双层 void**
  （见判据备忘 #17；零外发、不手动跑流，等 daemon 下一 cadence）
- 驱动引擎 `supervisor_drive.py --apply` 的全部「可自处置」类动作
  （驱动已在每次运行时自动跑上一行的页面卡死自愈 + 封印漂移自修，**无需手工**）
- **封印漂移自修** `runtime/seal_drift_repair.py --apply`（白名单内，含自动排补跑）

**唯一例外 = 登录态**：`*-login-expired` / `NEEDS_LOGIN` / `state=out` / `UNAUTHORIZED`
只能报人工重登（#63：服务端会话失效，本地无从续期）。其余一切阻塞当日工作流的问题，
一律当轮修复 + `control.json force_run` 排补跑，**禁等下一档、禁只报告**。

## 判据备忘（都是踩过的坑）

1. **`*-login-expired` 先枚举全部 page**：执行器用 `pages.some(isTaobaoLoginUrl)` 扫全量 URL，
   残留任意一个 `/login` 页就整轮 fail-closed。10-08 因此误判 3 次假阳性、白叫大同重登。
   `curl -s --noproxy '*' -m 4 -H "Host: localhost" http://127.0.0.1:<port>/json/list`
2. **夜间（23:00–06:00）双侧不可达是预期**（Windows 主机被大同休眠），不告警。
3. **`recovery-budget-exhausted:*`** = 还有别的恢复预算继承点（F11-3 同族），
   交车间按「单轮内 vs 跨轮语义」复查，**不要放宽预算**。
4. **当日未全绿** 先判是否在 cadence 内/是否已排下一档；**当日末档仍未成功才算真故障**。
5. **`attempted` 不等于「没发过」**：attempted 实际已外发。重跑前必须对账，否则重复外发（10-08 事故）。
6. **告警发了没人接 = 一样是事故**：10-08 登录告警 13:12 就发了，没人处理，堵了 9 小时。
   所以 RED 必须显式@大同，不能只写进日志。
7. **先 `date` 对时**：会话注入时间可能过期数小时，任何时效性定性前以本机时间为准。
8. **守护「卡没卡」别信 `daemon.json.next_cycle_at`**：它 = "本轮开始 + cycle"（**没算本轮耗时**），
   实际下一轮 = 本轮结束 + cycle，常比显示值晚 5–10 分钟（10-10 我因此误判"卡住"）。
   正确判据 = `daemon.out.log` 是否仍在追加 `▶ 执行 <flow>` + `status=running` + launchd `pid` 存活。
9. **区分「设计内阻塞」与「真卡点」**（★★避免误改代码）：出现"每档必失败且**快失败**（<3s）"时，
   先查该流有无**生命周期/授权到期**机制，而不是当成缺陷。
   实例：`brand-negative-review-appeal-followup` 的 `prior-attempt-still-unknown`，
   是事件授权未到期前的**设计内阻塞**——查 `.runtime/delivery-<date>-<event>/authorization.json`
   的 `expiresAt`，到期后自动走 `prior-event-authorization-expired-event-closed` → **skipped 记 SUCCESS**。
   （10-06 授权 10-07 11:19 到期 → 当天 14:32 档即收口；10-10 授权 11:20:22 到期 → 13 档收口。）
   **铁律：这类阻塞不下场改代码、不告警催办，只确认"到期时刻 < 下一档时刻"即可。**
10. **★「端口健康但页渲染线程卡死」是全盲区（10-10 新增机制缺口，已补）**：症状是某岗位**多条流同时**
    报 `connectOverCDP: Timeout 30000ms exceeded`（`<ws connected>` 后超时，**不是** 404）或
    `locator.click ... Timeout`。排查三步：
    ① `curl -s --noproxy '*' -m4 -H "Host: localhost" http://127.0.0.1:<port>/json/list` 能回 ⇒ 端口健康，
    而 `assert_post_pages.py`（只发 /json/list）**照样 PASS**、`bg-chrome-up.sh` 因端口在听**幂等空转**
    ⇒ 老手段全部看不见；
    ② 用 `runtime/post_page_probe.mjs --json` 逐 page 做硬超时 `Runtime.evaluate('1+1')` 定位**哪张页 hung**；
    ③ `--apply` 对 hung 页发 CDP `Page.reload` 即恢复（实测 9232 两张无关 tab 卡死 ⇒ connectOverCDP 20s 超时；
    reload 后 connectOverCDP 145ms 成功）。**根因常是内存压力**（`sysctl vm.swapusage` 打满 ⇒ 渲染线程饿死），
    属环境告警，复位页只止血、不能治本，须同步报大同（重启高内存进程/机器）。
11. **★四岗位开机自启/高恢复（10-10 大同要求"四岗位同等级"）**：四岗位后台 Chrome 必须统一走
    **`bg-chrome-up.sh` 驱动**（它才写采集器硬校验的 `state.json` 的 `mode=headless/port/pid`），
    不要「直接 exec Chrome」（旧 `com.zhensi.bg-chrome.taobao-agent-service.plist` 就是这样：
    无 `--headless`、不写 state.json，且 `launchctl print` = `Could not find service`，实为僵尸）。
    现状：`~/Library/LaunchAgents/com.zhensi.bg-chrome.{taobao-brand,taobao-agent-service,jinsha-business,meituan-merchant}.plist`
    四个，`RunAtLoad=true`+`StartInterval=300`（**不用 KeepAlive**）。
    **`launchctl bootstrap` 在沙箱必报 EIO(5)** ⇒ 要么等重启（launchd 登录时自动加载
    `~/Library/LaunchAgents/*.plist`），要么让大同在 GUI Terminal 跑
    `bash runtime/bg-chrome-agents-load.sh`。**不要**因为 bootstrap 失败就判"没配上"——
    文件就位即算完成（重启生效）。**巡检 cdp-unreachable 自愈已按端口精确拉起对应岗位**
    （`supervisor_drive.act_chrome` 的 `POST_SPECS`），不是无脑拉 9231。
    **重启后核验四岗位登录态**：`python3 runtime/login_health_check.py`（只读，查目标页非登录页）
    或 `node runtime/session_keepalive.mjs`（reload 后判 login 跳转）。**真判据=state.json 的 mode/port/pid**。
12. **★★★「JS 能响应 ≠ 页面可用」：有头岗位窗口被 macOS 判定不可见(occlusion) ⇒ 视口 0×0（10-10 新增）**：
    **只有 9232 金鲨是有头窗口**（其余三岗 headless 恒 visible）。若某岗位多条流同时报
    `element is outside of the viewport` / `locator.click: Timeout ... waiting for locator('.hamburger')`，
    而 `curl /json/list` 200、`Runtime.evaluate('1+1')` 也正常——**别判"页面没问题"**：
    这是窗口不可见。**判据**：对**流程页** evaluate `{visibilityState, innerWidth}`，`hidden` 或 `0` ⇒ blind。
    **修法 = `Page.bringToFront`**（实测 0×0→1200×613；`Browser.setWindowBounds` 移屏内**单独无效**）。
    已机制化：`runtime/post_page_probe.mjs`（`--apply`）会自动检测 blind 并发 bringToFront
    （**只对 TARGETS 流程页**，勿激活大同自用的 ctyun 等 tab），由 `supervisor_drive` 每轮调用；
    `bg-chrome-up.sh` 已去掉 `--window-position=2000,200`（窄屏会推窗口出屏）。**遇 9232 失败先查 blindness。**
13. **★★★9232 金鲨【不能用 headless】——站点检测 `--headless=new`，headless 下必跳登录页（10-10 新增，勿再试）**：
    大同 10-10 曾同意改 headless 彻底消除遮挡风险，实测**三变体全被站点拒**：headless（UA=`HeadlessChrome/154`）、
    headless+`--user-agent` 覆写、headless+UA覆写+`--window-size=1280,760`（后两者 webgl=true、视口同 headful）
    **全部跳 `#/login?redirect=...`**（bodyLen≈49 空壳）⇒ **UA / WebGL / 视口尺寸三变量均排除**，是 headless
    模式本身被检测。**结论：金鲨必须 headful，任何人不要再试图改 headless**（会掉登录态）。
    判据铁律：**判 headless/headful 页登录态必须等 SPA 加载完**——`readyState=complete` 且 `bodyLen>100k` 才算数；
    `interactive` + `bodyLen≈1` 是中间态（headful 首拉后 SPA 需 ~10-15s），据此判"掉登录"会误判。
    遮挡风险保障（headful 前提下）：去屏外位置参数 + 每轮 `bringToFront` 自愈 + plist 5min 保活。
14. **★★★「同一家店，多处显示名不一致」是精确相等判定的陷阱（10-10 新增）**：岗位后台常见
    「来源清单店名无分店后缀，而站内头部/下拉/表格店名带后缀」（实测 9230：开业流来源名 `甬潮·宁波小市`
    ↔ 头部 `甬潮·宁波小市(淮海店)`；且该根名在账号下命中 **2 家分店**）。凡 `===` / `Array.includes(精确元素)`
    判据都会**永不命中** ⇒ 流整档连败（症状：`page.waitForFunction: Timeout 15000ms exceeded` 或
    `flow-list-incomplete-or-other-shop`）。**判据=判店名一律「归一化（去空白）+ 前缀」**，绝不精确相等。
    定位法：**直跑采集器**（`node scripts/activity_collector.mjs <临时out> <店名>`，**只采集、不外发**）
    拿全 stack 精确到行；改前先确认脚本**未被 `dependencies.json` 封印**（可自由改）。
    **修采集器铁律**：① 只改真正相等的比较点，其余路径不动（最小改动，旧路径已连跑多日稳定）；
    ② **切勿把「命中元素的 `waitFor`」换成 `.count()`/`.nth()` 判据**——下拉有动画/重复渲染过渡窗口，
    count 读数非确定会**间歇误抛**（10-10 实测被自己的"改进"坑回，旧实现反而更稳）。
    验证法：`activity_daily.py`（**不加 `--execute`** ⇒ ready 而非发送）连跑两轮全 `complete` + 14 条 unittest。
15. **★受控关闭「干扰页」（非流程页的杂散 tab）（10-10 新增）**：岗位 CDP 里可能混入与流程无关的 tab
    （实测 9230 混入 3 个 `auth.openai.com/oauth` 登录页）。用 `runtime/close_stray_tabs.mjs`：
    `--port 9230 --match 'auth\.openai\.com' [--apply]`——**默认 dry-run**；只关 `--match` 命中页、
    **硬性排除流程目标页**（`TARGETS` 守卫，永不误关）、**需持岗位锁**（业务在跑即 busy 跳过）；
    关闭用 CDP `Target.closeTarget`（不新开/不点击/不发送）。**注**：这类杂散页通常**不是**岗位流的失败
    原因（采集器按 `melody.shop.ele.me` 前缀过滤本就无视它），关它是为环境整洁、防页数统计失真。
    **别把它当根因**——10-10 即先误疑 OpenAI 页致流失败，实为店名后缀精确匹配问题。
16. **★★★Windows 网关 IP 迁移必漏「已安装副本」；中继必须在 GUI 会话跑（10-10 再次踩实）**：
    症状=多条带外发的流同时报 `stage=desktop_wechat_preflight` 或 `stage=wechat-send-failed`
    （`phase_last=profiles_ready`）。**`desktop` 这个名字是陷阱——发送器实走 Windows 网关**
    （`desktop_wechat_sender.py` → `workflow_bridge_windows.py`/`WindowsAdapter`），不是 Mac 桌面微信。
    排查顺序：
    ① **别信记忆里的 IP**（「静态不变」是假设）：跑 `bash wechat-windows-driver/baseline-check.sh`，
       它会打印真实命中（10-10 实测网关已迁 **`192.168.0.3`**，`.2/.5` 全不可达）；
    ② 若「直连 .3 通、但守护的流失败」⇒ **守护是 launchd 语境、必须走中继 127.0.0.1:8732**，
       而中继可能挂了/上游钉错 IP；
    ③ **查 `~/Library/LaunchAgents/com.zhensi.windows-relay.plist` 的 `RELAY_TARGET_HOSTS`**——
       10-09 迁 .3 时脚本都改了、**唯独这份「已安装副本」没改**（教训 #10 经典漏项），
       而它 `KeepAlive=true`，会**一直用旧候选重拉并占着 8732 挡道**；
    ④ **实测铁律：launchd 语境的中继即使候选含 .3 也 `no candidate passed driver identity check`**
       ⇒ launchd 被本地网络 TCC 拦，**中继不能做 LaunchAgent**。正解=`launchctl bootout + disable
       gui/501/com.zhensi.windows-relay`，再在 **GUI 会话** 跑
       `RELAY_TARGET_HOSTS=192.168.0.3,192.168.0.2,192.168.0.5 bash relay-up.sh`。
    **判据（易误判）**：`localhost_relay.py` 是**纯 TCP 转发、无本地 /health** ⇒ 中继 `/health`
    回驱动 JSON 就证明上行已通；**别用 `/status`、`/sessions` 测中继**（驱动本就没这两个路径，
    直连也回 `not found`）。另：**中继每次重启都需在 GUI 会话重跑 `relay-up.sh`**（`post-reboot-recover.sh` 含此步）；
    只读体检 `baseline-check.sh` 零发送，放心跑。
17. **★★★「blocked∧0 marker 死角」必须双层 void；只看桥的 `safe` 会误判自愈（10-13 新增）**：
    症状=某流每档都失败在发送阶段、reason 为 `legacy-attempt-reconcile-only`（或「采集 PASS、发送 RE-ONLY」），
    `collection` 正常而 marker 是 `state=blocked / sendAttempts=0 / newSendAttempts=0`。
    **坑**：桥 `execute` L533 `safe`(bridgeVersion1∧blocked∧sendAttempts0) **看着放行** ⇒ 易误判"下轮自动重投"
    （10-13 我即此误判，被 09:49 周期实证打脸）。
    **真因**：卡点在**发送器** `desktop_wechat_sender.blocked_zero_send_text_marker_matches()`（L28-79）
    **只认两种 reason**（`desktop-text-input-write-failed` / `resume-prepared-text-readback-mismatch`）；
    reason 属网关拒绝类（`windows-send-rejected:HTTP 500…未完成登录`）时发送器 `safe_blocked=False`
    ⇒ 走 L389 `elif previous and not safe_blocked` → `--reconcile` → 桥 `legacy_text_reconcile`
    因 state=blocked 不在 `(unknown,verified)` 白名单 ⇒ 返死角码，**永久空转**。
    **处置（可自处置，零外发）**：机器取证「零发送」后**双层 void**——
    ① `send-attempts/<identity>.json`；② `send-attempts/.wechat-messaging/events/<eventKey>/`
    （eventKey 取 `marker.commonReceipt.eventKey`）。两者同时间戳归档为 `*.voided-<ts>`，
    再写 `void-receipt-<ts>.json`（含 `evidenceNeverSent` / `preconditionCheckAtVoid`）。
    **为什么必须双层**：桥传 `rebind_event = bool(prior) and never_sent(prior)`；void 掉 marker 令 prior=None
    ⇒ rebind=False；而 `ledger.event_lock`（L48-56）在 rebind=False 时对 binding 漂移**抛 `event-payload-conflict`**
    （binding 钉的是上一轮 requestDigest）。只清① ⇒ 下轮撞②。（与 10-07 `void-receipt` 教训同源）
    **零发送三证据（缺一不可）**：marker `attempts=0` + 事件层 `transport.sendAttempts=0` +
    `attemptErrors` 全为发送前失败（"打开会话失败，当前标题=''"）。**void 前先探网关 `/health`
    是否 `logged_in/ready`**（微信未登录则重发也无意义）；**void 后不手动跑流**，等 daemon 下一 cadence。
    参考 `docs/solutions/20261008-F10-1-桥状态机根治包-设计稿.md` §1（auto-void 未实施 ⇒ 人工前置）。
18. **★★ 发送类流「执行结果」的权威判据=run 内 `workflow.json.wechat` + `*/receipt.json` + 游标，勿只看进度文件（10-13 新增）**：
    查某流是否真发成功时，`desktop-wechat/delivery-progress.json` 可能**写盘滞后**——10-13 该文件终态仍写
    `sent=6/7 ok=false`，而权威 `workflow.json.wechat = {sent:7, ok:true}`、run 内 7 个 `receipt.json` 全
    `verified=true`、游标已推进到第 7 家。**只看进度文件会误判「少发 1 家/未完成」**。正确三件套：
    ① `workflow.json.wechat.sent/ok`；② `desktop-wechat/*/receipt.json` 逐店 `verified`；③ `cursor.json` 的
    `merchantId/tableOrder/verified` 是否等于最后一家。`completion.state=COMPLETE`＋`reconciliationOnly=false`
    是收口铁证。
19. **★ 「唯一对外通道」类巡检必须新会话探活，别信旧 tab**：见判据备忘（旧 tab 可能是已渲染 SPA 僵尸，
    看着正常却已掉登录）。登录态判据用 `login_health_check.py`（新会话），不以现有页正文为准。
20. **★★ 「页面健康」≠「会话有效」；`post_page_reset` G1 对页内坏态是盲区（10-13 美团客服 12:00 实战）**：
    9233 美团 IM 页 URL/标题全对（`#/im/page/workbench/reception`、标题「美团商家IM客服工作台」），
    但 DOM 叠了 `riskControlModal` 风控遮罩拦点击；执行每日复位（关 imworkbench 页→重开）后
    URL 跳 `#/noPermission`、弹「登录已失效」。⇒ ① 页存在+标题对 **判不出登录失效/风控遮罩**，
    G1 会判「健康」跳过复位；② 页面卡住先复位没毛病，但复位后必须**内容级复检**
    （查目标业务文本如「未回复/待人工回复」+ 遮罩元素计数 + URL hash 是否跳 noPermission/login），
    复位不达标立即升级为「登录态故障」报大同，别停在「已复位」；③ 复位前查 `live_steps`
    且确认无该岗位的流在窗口内（美团 12/15/17 三 entry，窗口外复位不碰采集）。
21. **★★★ 全屏公告弹窗（站点发版）会整片遮住左侧菜单 ⇒ `locator.click ... intercepts pointer events`（10-22 金鲨 V5.8 实战）**：
    症状＝负评/申诉类流三连失败，报错里反复出现 `<div class="zzc">… subtree intercepts pointer events`。
    真因不是选择器、也不是页面卡死，而是站点发版弹窗 `.upload > .zzc`（`position:fixed; inset:0; background:rgba(0,0,0,.3)`）。
    处置＝CDP 连该工位现有页（**禁新开页**），`document.querySelector('.upload .close').click()`（关闭按钮文案「关闭」），
    再验 `.zzc`/`.upload` 计数归零 + 对目标菜单做命中测试（`document.elementFromPoint(中心)` 是否命中自身），
    最后 `Page.reload` 复验不复现（关掉状态会持久化）。**不要**用「删 DOM 节点」代替点关闭。
22. **★★★ `/health` 四项全 true ≠ 能发；微信「会话列表空」才是判据（10-22 02:24 起堵 7 小时）**：
    症状＝所有走 Windows 网关的外发同时失败，统一 `windows-send-rejected:HTTP 500 打开会话失败，当前标题='昨天 10:33'`。
    `health` 的 `logged_in/ready/wechat_running/uiautomation` 全 true，`list_sessions` 也正常，**全是假绿**。
    真判据＝`{"action":"dump_tree"}` 数控件：正常有几十上百个会话项，卡死时只剩 ~48 个（会话列表 0 项、搜索框空而结果空）。
    恢复＝人工彻底退出微信（托盘右键「退出微信」，点 X 只是最小化）再重开，**Mac 侧无键盘注入动作，监理无法代做**。
    连带教训：`blocked ∧ sendAttempts==0` 的 marker 桥侧永久闭口（`legacy_text_reconcile` 只认 unknown|verified∧sendAttempts==1），
    必须双层 void（marker + `.bridge.lock` + `events/<digest>`）+ void-receipt；void 后下轮立刻回到真发送路径，
    可用这一点把「标记层故障」和「通道层故障」干净切开。

## 挂成常驻自动化

> **★ 账号迁移注记（2026-10-09）**：监理机制已从旧账号（额度耗尽）迁到新账号重建。
> **automation_update 的 list/update 是账号隔离的**——旧账号 9 条（`2b96a699`/`7a6c1a59`/`5be64958`/
> `f8d6fbd4`/`d456b850`/`4722b31d`/`5522b7c4`/`fc351428`/`d4e37101`）在新账号**不可见也不可管理**。
> 手册 §4 表中的旧 id 全部作废，以本节新 id 表为准。旧账号若续命，两套会双跑，须二选一。

新账号 9 条（2026-10-09 建）：

| id | 名称 | 频率 | 职责 |
|---|---|---|---|
| `8d73d9a8` | 臻肆看护·七段 | 每小时 | 手册 §4.2 A-G 七段 |
| `df702034` | 臻肆监理·当日16流进度汇报 | 每小时 | daily_progress 状态表，夜间(<9 或 >=23)自暂停 |
| `0ac0549b` | 臻肆监理督查·环境与外发面 | 每小时 | supervisor_patrol 七项 |
| `c89f6bc8` | 臻肆岗位登录态保活探针 | 每2小时 | 四岗位登录态，唯一允许外发告警 |
| `86a8450c` | 臻肆监理晨间唤醒 | 每天09:00 | 恢复进度汇报为 ACTIVE + 跑一轮 |
| `73d16cc2` | 美团IM复位·15点档前 | 每天14:55 | 9233 复位 |
| `195e1e12` | 美团IM复位·17点档前 | 每天16:55 | 9233 复位 |
| `d2a3ce67` | 美团IM复位·每天17:30（收口冲刺前） | 每天17:30 | 9233 复位 |
| `ce978382` | E3b观察周复盘 | 一次性 2026-10-13 09:40 | 两码结论上报 |
| `a162f8c9` | 臻肆收口冲刺·当日任务闭环 | 每天18:30 | 驱动处置+查 ledger_gate；NO-GO 写入 war_room 超时项（"完成当日任务为最高原则"硬闸） |

> **2026-10-10 变更**：`0ac0549b`（监理督查·环境与外发面）已从「纯只读巡检」升级为
> **「巡检 + supervisor_drive.py --apply 闭环驱动」**——每小时自动把发现推到收口
> （自处置类当场修，需人工类建 SLA 看板）。`c89f6bc8` 新增「看板超时告警」职责，
> 把 SLA 超时的待办自动发群给大同。三者配合形成完整闭环，断点已补。

注意：`BYHOUR` **不支持多值列表**，做不出「只在工作时段每 30 分钟」；夜间噪音由脚本 `phase=night` 降级吸收。

同批处置的本账号旧遗留：已 PAUSED 三条——`680f9aa2`(12流进度表，与新进度汇报重复且带已废"直接修流"授权)、
`2e96784f`(心跳看护，判据用被禁的 `launchctl list`)、`2ac2067a`(投影值守，8770 已裁决下线)；
保留 `20fc849e`(daily-agent 真实发送监视，职责独特)；AOS 相关 3 条与过期 once 不动。

### ★ 职责分工（10-08 教训：新建前必须先 `automation_update mode=list`）

本车间的 hourly 自动化有两条，**新建任何监理类任务前先 list，别再制造重复**：

| id（新账号） | 名称 | 盯什么 | 不做什么 |
|---|---|---|---|
| `df702034` | 当日16流进度汇报（每小时） | `daily_progress` 状态表 + 发送被拒检查，带夜间自暂停 | 不看岗位浏览器、不看 daemon 心跳 |
| `0ac0549b` | 监理督查·环境与外发面（每小时） | `supervisor_patrol.py` 七项：daemon 心跳、四岗位 CDP、今日外发回执、金鲨遮罩、告警聚合 | **不重复输出任务流状态表** |

同一小时内两条都会跑，若不分工就是给大同刷两遍屏。

