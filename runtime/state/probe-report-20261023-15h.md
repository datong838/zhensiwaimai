# 四岗位登录态保活探针 · 15:00 档（外发告警档）· 2026-10-23

> 执行时刻：15:19 对时 → 随机等待 110s → 15:21 开始；报告生成 15:45。
> 结论速览：**通道自检 FAIL（Mac 异网，Windows 网关全不可达）；判据 10 passed/0 failed；真会话探活已完成，9231 真掉登录、其余活；未发任何微信告警（通道不可用）。**

## 0. 对时
- 系统时钟 Fri Oct 23 15:19:37 CST 2026（档位 15:00，时间可信）
- 随机等待 110s（1m50s）后于 15:21 开始探针

## 1. 通道自检（Windows 网关）—— FAIL
诊断链：
- Mac 当前 IP = **192.168.43.146**（接口 en0）；到全部 Windows 网关候选的路由出口均为 **192.168.43.1** → **Mac 不在 Windows 网关所在局域网（疑似切到热点/异网）**。
- 6/6 候选网关 8731 端口 `nc` 全部 closed（rc=1）；6/6 `ping` 全部 dead。
- 中继 8732（PID 5717）本地存活监听，但上游 Windows 不可达 → 转发亦无效。
- 已按规程跑 `wol_windows.py --fire` 发魔术包（广播 192.168.110.255），但**跨子网无法送达** → 无效。

> ⚠️ **需要人工介入：Windows 微信告警通道当前不可用。** 请确认 Mac 已连回原办公局域网（与 Windows 网关 192.168.110.x / 188.x 同网段）。当前 Mac 在 192.168.43.x（热点/异网），导致所有微信告警发不出去。这不是 Windows 关机，是网络拓扑分离。

## 2. 判据自检（--self-test）—— 10 passed, 0 failed
判据可信，未静默失效（含 API 正负对照 + 渲染正负对照 + UNKNOWN 不误判共 10 项）。

## 3. 真会话探活（本地 Chrome CDP，不依赖网关）—— 已完成
| 岗位 | 端口 | 状态 | 证据 |
|---|---|---|---|
| taobao-brand | 9230 | ✅ 活 | 商家首页 |
| taobao-agent-service | 9231 | ❌ **真掉登录** | API UNAUTHORIZED：session 不能为空（HTTP 200，已重定向 open.shop.ele.me/login） |
| jinsha-business | 9232 | ✅ 活 | 数据总览 |
| meituan-im | 9233 | ✅ 活 | 顾客消息 |

PROBE_RC=3（检测到真实掉登录）。

### 自修动作
- 尝试 `auth_keepalive.mjs --notify --open-login` 拉有头登录窗 → 沙箱对进程树投 SIGTERM(143)，有头实例未真正拉起，反致 9231 短暂彻底宕机（端口不监听、无进程）。
- 已幂等恢复 9231 无头实例（`bg-chrome-up.sh`）：现监听 pid=17746，页面落在 `open.shop.ele.me/login`，**确证 9231 真掉登录**，等待大同重登。
- 说明：有头登录窗在无人值守自动化上下文无法被沙箱稳定拉起（SIGTERM 杀进程树），故改为恢复无头、交由大同手动重登。LAST 已写入 `openLoginAt`（2h 冷却，压制重复弹窗，符合设计）。

## 4. 闭环看板超时检查（war_room.json）—— 有 2 项需置顶
状态分布：info:3 / resolved:25 / awaiting_you:1 / done:1 / breached:1

**本应经微信发「⚠️ 监理待办超时」，但网关不可达，未能发出，记录在案：**
1. 🚨 **[breached] marker/unknown-marker-sent-evidence** —— SLA 13:31:07 已超时未获回应（发现 13:01:07）。关于 jinsha-report-send 的 unknown marker 发送证据，需大同拍板。
2. ⏳ **[awaiting_you] chrome/login-page-present:9231** —— 即本次 9231 掉登录（发现 15:23:26，SLA 15:53:26 未到）。需大同重登 9231。

## 5. 告警动作汇总
- **未发送任何微信告警**（通道 FAIL，网关不可达；依铁律不盲目发送、不尝试发不出去的告警）。
- 真问题已本地自修/记录：9231 恢复无头待重登；war_room 2 项超时/待办已登记。
- **唯一上行通道 = 本自动化结果**：大同请查看本报文，处理 ① 连通办公 LAN 恢复告警通道；② 重登 9231；③ marker/unknown-marker-sent-evidence 拍板。

## 6. 收尾结论
- **通道自检结论**：FAIL（Mac 异网，Windows 网关全不可达；WOL 跨子网无效）
- **自检 passed/failed**：10 passed, 0 failed
- **是否完成真会话探活**：是（四岗位全探；9231 真掉登录，其余活）
