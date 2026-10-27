# 旧版 verified marker 迁移复核方案

## 问题

专用微信技能桥接能按群名、完整正文和 SHA-256 绑定旧 marker，并在旧 marker 已标记 `verified` 时禁止再次发送。但旧 marker 可能缺少新版业务提交门禁要求的两帧、空输入框和原生复制字段。桥接直接复用旧对象会使业务门禁报 `delivery-evidence-incomplete`，流程无法提交历史与游标。

## 目标与边界

1. 旧 marker 已发生过一次物理发送时，任何迁移路径都不得再次发送。
2. 普通重放继续直接复用完整绑定的旧 `verified` marker，不主动操作微信。
3. 业务调用显式使用 `--reconcile` 时，旧 `unknown` 或 `verified` marker 都只能执行只读复制复核；复核成功后写回新版证据字段。
4. 只接受单条文本、一次既有发送、完整群名与正文绑定；复制证据不完整时失败关闭。
5. 群标题可由同帧前的 AX 精确标题与空输入框门禁确认；OCR 仍负责正文气泡定位。OCR 若识别到多个标题继续失败关闭，OCR 标题为零时不得推翻已经通过的 AX 唯一标题证据。
6. 不改变新事件的发送、防重和部分批次规则。

## 实现

- 调整 `skills/wechat-messaging/scripts/workflow_bridge.py`：把旧 marker 的显式只读复核放在旧 `verified` 快速复用之前；扩展只读复核允许 `state=verified` 且 `sendAttempts=1` 的旧文本事件。
- 补充回归测试：旧 `verified` 在普通执行时零 UI 复用；显式复核时调用一次预检和复制、物理发送次数保持一次、不会进入发送适配器。
- 更新 `executor-lock.json` 的当前代码摘要，保持 `UNSEALED_ACCEPTANCE`；完成真实非空发送验收后再封板。

## 验收

1. 专用微信技能与商户流程全部离线测试通过。
2. 首家旧 marker 通过只读复核并提交，`physicalSendAttempts=1`、`reconciledWithoutSend=true`。
3. 后续商户各自只有一次物理发送，均有两帧、空输入框和原生复制全文证据。
4. 历史唯一、游标推进到最后一家；封板后零待发重放不发送。
