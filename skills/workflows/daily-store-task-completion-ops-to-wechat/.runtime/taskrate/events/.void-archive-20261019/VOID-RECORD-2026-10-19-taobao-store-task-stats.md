# Void 记录：2026-10-19-taobao-store-task-stats
- 时间：2026-10-19 15:0x（监理修复，大同「非登录态阻塞立即修+补跑」指令）
- 原因：12:15 首跑 xlsx 明细 verified 送达；PNG 截图发送时 Windows 网关微信未就绪（HTTP 500 主窗口未出现）被拒，事件 blocked。
- 安全性：PNG 从未送达（sendAttempts 被拒、无 verified/unknown+sent 标记）→ 补发不构成重复外发；xlsx 事件保持 verified，流重跑时幂等保护继续挡住 xlsx 不重发。
- 补发条件：网关 /health logged_in+ready 双 true（15:0x 实测均为 True）。
- 依据：#45 void 双层归档 + #26 重跑前校验今日零真实重复外发。
