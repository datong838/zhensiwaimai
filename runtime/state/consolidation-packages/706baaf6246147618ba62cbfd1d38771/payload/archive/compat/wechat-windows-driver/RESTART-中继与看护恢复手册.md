# 中继与看护 · 重启恢复手册

> 适用：臻肆外卖监理体系（WorkBuddy 监理 / 车间主任 daemon）
> 维护：2026-10-06 · 权威源 = 本文件 + `baseline-check.sh` + `relay-up.sh`
> 配套：`zhensi_waimai_back/docs/看护职责交接手册-监理与车间主任.md`（SSOT §10 接力记录）

---

## 0. 一句话结论

**WorkBuddy 一退出，中继（`127.0.0.1:8732`）和每小时看护会一起停** —— 这不是 bug，是结构决定的：
中继必须跑在「**有本地网络（Local Network）授权的 GUI 会话**」里，而 WorkBuddy 进程本身就是这样一个会话。
**重启后跑一次 `relay-up.sh` 即恢复**（幂等，10 秒）。

---

## 1. 触发场景与恢复动作

| 场景 | 后果 | 恢复动作 |
|---|---|---|
| Mac 重启 / 注销登录 | 中继进程消失 | §3 三步 |
| **WorkBuddy 退出 / 升级 / 崩溃** | 中继消失 **+** 每小时看护不再触发（两者同生命周期） | §3 三步；并确认看护自动化仍在册（§5） |
| 换网 / 路由器断电重启 | 候选 IP 可能变（该机有两块网卡） | §4 体检；中继会自动重发现，无需改配置 |
| Windows 机重启 | 驱动服务需自启；worker 冷启动，**首个发送指令易 503 超时** | 重试 1～2 次通常即成功（勿立即判服务故障） |
| 只有 `.5` 通 / `.2` 不通（Mac 侧） | 候选兜底会自动切 | 无需动作；§4 体检会显示实际选中上游 |

---

## 2. 为什么中继必须在 GUI 会话（不能做成 LaunchAgent）

同机同目标 A/B 实测（2026-10-06）：

- **GUI 会话**（WorkBuddy / Terminal.app）直连 `192.168.0.2:8731` → ✅ 通
- **launchd 上下文**（daemon）直连同一目标 → ❌ `Errno 65 No route to host`（macOS「本地网络」TCC 拦截）

⇒ 用 launchd 拉起中继**同样连不到 LAN**，做不成开机自启。
本沙箱内 `launchctl bootstrap gui/501 …` 报 `EIO(5)`、`launchctl submit` rc=1，也印证同一件事。
故架构为：**中继 = GUI 会话里的一个分离进程**，daemon 连 `127.0.0.1:8732`（localhost 不受 TCC 管）。

`relay-up.sh` 用「新会话双重 fork + `setsid` + `exec`」把中继彻底脱离调用方进程组，
因此**跨命令、跨会话存活**（不会随 Bash 工具的命令结束被回收）。

---

## 3. 重启后恢复（三步 · 约 10 秒）

**必须在有 GUI 权限的上下文执行**（WorkBuddy 内 / Terminal.app）。**不要**在 ssh、daemon 上下文跑（无 TCC 授权，必失败）。

```bash
# ① 起中继（幂等：已在监听会打印「跳过」）
bash /Users/ddt/work/projects/ai_agent/wechat-windows-driver/relay-up.sh

# ② 三条线一键体检
bash /Users/ddt/work/projects/ai_agent/wechat-windows-driver/baseline-check.sh

# ③ 期望输出（判读见 §4）
#    B: 已在监听 127.0.0.1:8732 + /health 回 "agent up" + 上游 192.168.0.2:8731
#    C: 192.168.0.2 回驱动签名 + wxsend --status 里 'route': 'direct'
#    A: 心跳 < 90 分钟 且 run_all.py 进程在（launchd: state = running）
```

> 也可以把 `bash relay-up.sh` 并入「每日环境复位」（与美团 IM 复位同批，大同已确认职责）。

---

## 4. 一键体检与判读

```bash
bash /Users/ddt/work/projects/ai_agent/wechat-windows-driver/baseline-check.sh | tee baseline/latest.txt
```

| 段 | 正常判据 | 已知「非故障」 |
|---|---|---|
| **A** daemon | 心跳 mtime < 90 分钟 **且** `run_all.py` 进程在 | — |
| **B** 中继 | `8732` 在监听，且 `/health` 回 `{"ok":true,"msg":"agent up",…}` | 中继不在 ⇒ 按 §3① 拉起 |
| **C** 直连 | `192.168.0.2:8731` 回驱动签名（`msg=="agent up"` 且含 `uiautomation`/`worker`）；`wxsend --status` → `'route': 'direct'` | **`192.168.0.5`（无线网卡）从 Mac 侧不可达属常态**，不报障 |

**探测三个必备姿势**（否则会得到假故障）：
1. `curl` 必须带 `--noproxy '*'` —— 否则被本机代理截胡返回 **502 假故障**；
2. Python 探针必须 `env -u PYTHONPATH` —— 否则被沙箱 `sitecustomize` 污染；
3. 判断 launchd 必须用 `launchctl print gui/501/<label>` —— 见 §5 的坑。

---

## 5. 看护自动化

| 项 | 值 |
|---|---|
| id | `2b96a699-dc69-416e-b2e9-b8e8a3f11527` |
| 名称 | zhensi 看护：daemon 心跳 + 中继保活 + 直连探活 |
| 频率 | 每小时（`FREQ=HOURLY;INTERVAL=1`） |
| A | daemon 心跳（mtime > 90min 且无 `run_all.py` ⇒ 报警 + 给恢复命令） |
| B | **中继保活**：`relay-up.sh status` → 未监听则拉起 → 验 `/health` → 读 `upstream target` |
| C | **直连探活**：`.5/.2:8731` 验驱动签名 → `wxsend.py --status` / `--sessions` 带 token 校验 |

**看护自身的边界**（写进 prompt）：只读、禁发消息、不 kill daemon、不改配置、不 rm、不动 launchd、不写台账/不推游标。

### ⚠ 两个已踩过的坑（看护误报来源）

1. **`launchctl list | grep careloop` 在本上下文恒为空**（实测 0 行 —— 不在同一 launchd domain），
   会把**正常服务误判成「没注册」**。权威源只能 `launchctl print gui/501/com.zhensi.waimai.careloop`。
2. **中继注册成 LaunchAgent 无效**（§2）：即使 bootstrap 成功，它也连不到 LAN。

---

## 6. 故障对照表

| 症状 | 判据 | 处置 |
|---|---|---|
| `windows-driver-local-network-blocked` | 直连即时 `Errno 65` + GUI 通 | 该进程是 launchd 上下文 ⇒ 走中继（§3①）；若中继不在则拉起 |
| `windows-driver-unreachable` / 30s 超时 | ping 也不通 / 非 TCC | **主机不可达或 IP 变了** ⇒ §4 探候选，别归咎 TCC |
| `/health` 通但发送失败 | `/health` **不校验 token** | 必须用 `wxsend.py --sessions`（带 token）确认鉴权链通 |
| 中继在监听但 `/health` 不通 | 上游不可达 | 看 `relay.err.log` 尾部候选探测结果；换网后等自动重发现（20s） |
| 首次发送 503 | Windows worker 冷启动 | 重试 1～2 次 |
| 多任务同时发送报 `windows-transport-busy` | 驱动**单线程串行** | 发送任务必须**串行**排队 |

---

## 7. 最新实测基线（存档）

- 采集时间：**2026-10-06 13:09:04 CST**
- 存档文件：`baseline/baseline-20261006-130911.txt`（同名 `baseline/latest.txt`）
- 采集方式：`bash baseline-check.sh`（与看护自动化同一组命令，仅只读探活、零发送）

```
【A】daemon 心跳
  心跳 mtime  = 2026-10-06 12:45:47 （距今 23 分钟）
  run_all.py  = 25146
  launchd     = state = running  pid = 25146  last exit code = 0  runs = 26
  next_cycle  = 2026-10-06T13:15:47

【B】中继 127.0.0.1:8732
  已在监听 (pid=44881)
  /health     = {"ok": true, "msg": "agent up", "uiautomation": true, "wechat_running": true,
                 "logged_in": true, "ready": true, "worker": true, "host": "0.0.0.0:8731"}
  上游         = [relay] upstream target -> 192.168.0.2:8731

【C】直连 192.168.0.x:8731
  192.168.0.2 = {"ok": true, "msg": "agent up", … "worker": true, "host": "0.0.0.0:8731"}
  192.168.0.5 = (无响应)          ← 无线网卡，Mac 侧不可达属常态
  wxsend --status   = {'ok': True, …, 'route': 'direct'}
  wxsend --sessions = FEIBING NEO AI数字员工 / 上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰 /
                      偷懒别偷懒-臻肆 / AGI技术交流群 / 和恒中队家长群 / 飞冰学习群 / 杜大同 …
```

图证：大同提供的 `Clipboard_Screenshot.png`（会话内联图，**未落盘**，故此处以**机器原始输出**代替——可复核性更强）。

---

## 8. 拓扑与地址（2026-10-06 大同确认）

```
[Windows 机 DESKTOP-TH91SO5]  ← 登录着真实微信，驱动绑 0.0.0.0:8731
        ├── 192.168.0.5  = 无线网卡
        └── 192.168.0.2  = 有线网卡   ← Mac 侧当前唯一稳定可达
                 ↑
        ┌────────┴─────────────────────────────┐
        │ 直连（前台/GUI，route=direct）        │ ← 正解路径
        └────────┬─────────────────────────────┘
                 │
[MAC]            │  launchd daemon 直连被 TCC 拦（Errno 65）
                 │        ↓
                 └── 127.0.0.1:8732 中继（跑在 GUI 会话）→ 最后一跳到 .2:8731
```

- **候选顺序：`192.168.0.2,192.168.0.5`（有线优先、无线兜底）**。
  规则是「**按优先级取第一个通过驱动身份校验的**」（非先到先得）；Mac 侧必失败的 `.5` 排前只会白烧探测，
  且有线不受 Wi-Fi 断电影响（2026-10-05 晚事故即 Wi-Fi 断电引发）。
- 硬件地址：`.2` 的 MAC `d2:36:db:4f:f6:8a` 第二位置 = 2 ⇒ **本地管理位（LAA）**，Windows「随机硬件地址」特征 ⇒ 勿把 IP 当常量。
- 关键文件：`接入包/连接信息.txt`（权威配置）、`localhost_relay.py`（中继）、`client.py`（直连优先 + TCC 时回落中继一次）、
  `relay-up.sh`（幂等启停）、`baseline-check.sh`（一键体检）。

---

## 9. ⛔ 已过期结论（**勿再引用**）

| 过期说法 | 现状（2026-10-06 校正） | 遗留位置 |
|---|---|---|
| 「网关 IP 是 `192.168.0.5`」 | `.5` 是**无线网卡**；Mac 侧走 **`.2`（有线）** | 旧台账、旧文档 |
| 「`.5` 腾给了另一台设备 / 是别的设备」 | ❌ **错**：`.5` 与 `.2` 是**同一台机的两块网卡** | `localhost_relay.py` 旧注释（已改） |
| 「失败根因 = 纯 macOS TCC」 | 并列两个独立故障：**IP/网卡路径（主因，已修）+ daemon 的 launchd TCC（次因，靠中继兜底）** | 旧接力记录 |
| 「心跳看护自动化 id = `2e96784f…`」 | ❌ 误记；实际 **`2b96a699-dc69-416e-b2e9-b8e8a3f11527`** | 2026-09-30 日志、旧 MEMORY |
| 「中继可以做 LaunchAgent 常驻」 | ❌ 无效（§2）：launchd 上下文连不到 LAN | — |
| 「`relay.err.log` 里的 `[Errno 65]` = TCC 证据」 | ❌ errno 65 二义：旧目标 `.5` 不可达也会报 65 | — |
