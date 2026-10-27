# 2026-10-21 12:36 退役 brand-negative 过期验收 scope

## 背景
- runtime-policy.json 中的 acceptance scope（groupName=李老哈（品牌）💰臻肆外卖运营对接群，
  authorizationRef=automation-10-user-authorized-brand-negative-appeal-all-outcomes-20260921）
  于 2026-10-19 21:30:51 到期（epoch 1792416651），过期 39h+ 无人续。
- brand-negative-review-appeal-followup 流已于 10-19 19:52 由大同令暂停（enabled=False），
  该 scope 的业务方已不存在。
- 生产任务流全部经 workflow_bridge.py → executor.deliver() 直调（grant 每轮现场构造），
  不经 executor.py CLI 的 runtime_gate()，故本 scope 过期不影响任何生产发送。

## 处置
- 将过期 acceptance 态退役为 offline 静息态（同 09-16/09-17 media-live-acceptance 先例：
  prior-policy.json 归档后主 policy 回到 mode=offline）。
- 活 policy 只保留 deviceHash/userId/releaseStatus/acceptedMobileReceipt 四个静息字段，
  不含任何 expiresAt（避免 auth_watch 递归扫描把归档字段当活窗口再报假告警——
  第一版把归档段内嵌进活文件，被 auth_watch 扫到 /retiredScope 过期，已修正）。
- 本文件（prior-policy.json + README.md）即完整审计线索。

## 恢复路径
若未来需要重新启用 executor.py CLI send 路径（手工/维护直发）：
1. 构造 request + authorization grant（scope ≤ 2h）
2. 走 policy_registration.py prepare 受控登记
3. 验证 runtime_gate 通过后再执行发送
