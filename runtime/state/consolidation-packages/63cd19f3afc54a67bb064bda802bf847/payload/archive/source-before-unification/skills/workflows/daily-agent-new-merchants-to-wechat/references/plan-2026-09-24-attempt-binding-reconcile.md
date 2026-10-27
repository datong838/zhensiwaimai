# Attempted 标记绑定恢复方案

## 问题

桌面微信发送已经发生但原生复制复核失败时，统一桥接可能先写入一个 `state=unknown`、`sendAttempts=1` 的 marker，业务层随后才得到完整私有 receipt。旧路径只在 marker 不存在时从 receipt 恢复；当 marker 已存在但缺少 `payloads`、商家 ID 或正文哈希时，下一轮无法做只读绑定复核，游标也无法提交。

## 目标与边界

1. 只接受同一生产群、同一商家正文 SHA-256、一次物理发送、`post_send_verify` UNKNOWN 的唯一私有 receipt。
2. 已存在但绑定字段为空的 marker，只能由执行器代码补齐绑定并进入原生复制全文只读复核。
3. 不改变新发送路径；不删除 marker、不重置 `sendAttempts`、不点击发送、不手工推进游标。
4. receipt 搜索覆盖执行器私有 `runs/` 与历史 `state/.../runs/`，仍要求唯一匹配。

## 实现

- 扩展 `workflow_executor.recover_unknown_marker_from_receipt`：对已有不完整 marker 也执行严格 receipt 匹配；兼容旧版顶层 `completed`、内层 `commonReceipt.status=unknown` 包装；匹配唯一后原子写回完整绑定 receipt。
- 增加回归测试，覆盖已有空绑定 marker、私有 runs receipt、唯一匹配、重复匹配拒绝和零发送约束。

## 验收

1. 相关离线测试全部通过。
2. 生产执行器新一轮仅进入 `reconcile-only`，原生复制全文和双帧通过后提交历史与游标。
3. `sendAttempts` 保持 1，`verifiedNewSends=0`，不重封；最终游标等于清源牛腩蒸面。

## 2026-09-26 补充：物理发送次数未知的只读对账

### 根因与目标

当前生产 marker 已完整绑定生产群与正文 SHA-256，但 `sendAttempts`、`physicalSendAttempts` 均为 `null`。其 `commonReceipt` 明确记录同一群、同一正文哈希、唯一 item、`status=unknown`，且唯一失败阶段为 `send:0`，失败原因为桌面窗口 Quartz 截图失败。旧版共享桥接只允许 `sendAttempts=1` 的未知记录进入只读复制核验，造成已经有完整 unknown marker 的记录在打开微信前被拒绝。另有完成分类缺少对嵌套 unknown marker 的识别，会错误报告为可重试的零发送失败。

### 约束与改动

1. 只允许以下精确兼容分支进入桌面只读对账：顶层和嵌套回执均为 unknown；发送次数都仍为 `null`；群、唯一文本 item、正文与哈希严格一致；既有失败证据只有 `send:0` 的该 Quartz 截图错误。其他未知次数记录保持拒绝。
2. 对账仍必须由桌面 WeChat 执行器在指定群中找到唯一消息，读取两帧稳定锚点、唯一复制菜单、空输入框，并原生复制全文后逐字节哈希匹配；本次流程 `sendAttempts=0`。截图、旧回执或用户口述均不替代这些证据。
3. 成功时只将绑定 marker 状态改为 verified 并通过既有代码提交历史与游标；保留 `sendAttempts=null`、`physicalSendAttempts=null`，标明 `reconciledWithoutSend=true`。业务计数为 `verifiedExisting=1`、`verifiedNewSends=0`。失败继续留在 unknown/reconcile-only，绝不点击发送。
4. workflow executor 对任何非安全 blocked marker（包括 null 次数的 unknown）跳过常规微信发送预检，强制进入 reconciliation-only；若成功，只完成首条对账后返回。随后必须由新的唯一输出目录再运行主执行器处理剩余队列。
5. completion classifier 将 marker/common receipt 中的 unknown、attempted 或 null 次数的任何已有发送标记一律分类为 `RECONCILE_ONLY`，绝不能分流到自动重发。

### 实施与验收

- 先新增共享桥接、业务 runtime contract、执行器分流和发送计数回归测试，再做最小代码修改。
- 跑共享 wechat-messaging 与新商家完整离线测试集；用真实桌面微信仅做一次只读对账，机器证据通过后由正式执行器提交游标，再以新唯一目录继续剩余 merchant 队列。
- 不重封；本轮无新增发送。共享依赖清单和新商家 unsealed acceptance 收据只经各自代码维护器原子更新。
