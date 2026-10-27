# 臻肆四岗位登录态保活探针 · 21:00 档（外发告警档·末班）· 2026-10-23

## 对时
- 对时：`date` → 2026-10-23 21:06:20 CST（校准）。
- 随机等待：504s（21:07:39 → 21:16:03），21:16:03 起开跑；通道自检 21:17:22、四岗位探活 21:19。

## 1. 通道自检结论（第 0 步）
- 候选序（gateway.json 权威）：`192.168.110.184 → 192.168.188.39 → 192.168.0.3 → 172.16.8.157 → 192.168.0.2 → 192.168.0.5`，port 8731，relay 8732。
- **`192.168.110.184:8731/health` → HTTP 200，但 `wechat_running=false` / `logged_in=false` / `ready=false`（agent up，微信未运行）。**
- 其余 5 候选全部 HTTP 0（不可达）。
- 8732 中继：`HTTP 0`（宕）。
- POST `list_sessions` 身份校验：**未执行**——`logged_in=false` 时微信未登录，无法枚举会话，属通道死亡预期，非漏检。
- 判定：⚠️ **Windows 微信未运行/未登录（wechat_running=false）**，微信外发通道死亡。本档**不发送任何微信告警/台账**（发不出去）。

## 2. 判据自检（auth_keepalive --self-test）
- **10 passed, 0 failed**（v2 API + 渲染，正负对照）。判据可信。

## 3. 四岗位登录态真会话探活（auth_keepalive，exit 0 全活）
- `:9230 taobao-brand` ✅ 商家首页（melody.shop.ele.me 业务特征命中）
- `:9231 taobao-agent-service` ✅ API 认证通过（result=false，HTTP 200，合法）
- `:9232 jinsha-business` ✅ 数据总览（data.guoshuyufen.com 业务特征命中）
- `:9233 meituan-im` ✅ 顾客消息（waimaie.meituan.com 工作台 reception 路由命中）
- 无 exit 3（无真掉登录）→ 步骤 3（掉登录外发）不触发；且即便触发亦因微信通道死亡无法发送。

## 4. 闭环看板超时告警（war_room.json）
- 检出 **2 个 `breached`**（awaiting_you=0），均需大同拍板；**因微信通道死亡，无法经微信外发「⚠️ 监理待办超时」**，仅在此报告：
  1. **`marker/unknown-marker-sent-evidence`**（YELLOW；SLA 17:33 已超时，连续多次「二次置顶@大同」未获回应）：金鲨发运营群 marker=unknown，`transport.data.sent=None`，读回 `title-mismatch`（运营群已改企微通道，Windows 网关读回不适用）；无确认送达证据。→ **需大同按「企微侧」确认是否真送达**。
  2. **`ledger-send-hold-2026-10-23`**（RED；SLA 23:59）：2026-10-23 台账 `ledger_gate=GO`（meituan 已补跑成功），但 `last_cycle all_green=false`、xlsx 20/21 故未发。唯一「未全绿」流 `daily-negative-reviews` 实际 09:59 已 SUCCESS 并外发（晚间 20:18/20:26/20:32 三连败为环境抖动冗余重跑，latest_run 失败致判未全绿）；重跑会触发重复外发（监理红线：attempted≠没发过、同日重跑必重复外发），故未发台账。→ **需大同拍板是否按「当日实际已完成」结论化补发台账**。
- 佐证：`sent_today.json` 无 `2026-10-23` 条目 → 当日台账确实未发。

## 5. 末尾三问
- **通道自检结论**：微信外发通道死亡（Windows 微信未运行/未登录；`192.168.110.184:8731` agent up 但 `logged_in=false`；其余候选不可达、8732 中继宕）。本档不发送任何微信消息。
- **自检**：passed=10, failed=0。
- **是否完成真会话探活**：四岗位真会话探活已完成（exit 0，命中真实业务页/API）；微信网关 `list_sessions` 真会话探活**未完成**（`logged_in=false` 无法枚举会话，属通道死亡预期，非漏检）。

## 6. ⚠️ 需要人工介入
- **Windows 微信未运行/未登录**（`wechat_running=false, logged_in=false`）。需在该 Windows 机上**启动并登录微信**，恢复后微信外发告警与台账方可投递。
- 当日（2026-10-23）台账尚未发出（`sent_today.json` 无今日记录），原因二重：① 台账因 `all_green=false` 被门禁 HOLD（war_room breached #2，待大同拍板）；② 微信通道死亡无法投递。恢复微信登录后，由看护 daemon 或人工按拍板结论补发。
- 2 个 war_room `breached` 项均需大同在企微侧确认/拍板（详见第 4 节）；因微信通道死亡本次**无法外发提醒**，请大同在此报告中查阅。
