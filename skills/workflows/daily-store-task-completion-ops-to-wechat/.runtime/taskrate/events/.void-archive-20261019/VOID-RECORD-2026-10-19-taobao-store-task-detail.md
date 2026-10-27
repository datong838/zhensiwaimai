# VOID 记录：2026-10-19-taobao-store-task-detail（12:16 假 verified）

- **void 时间**：2026-10-19 16:25
- **对象**：`2026-10-19-taobao-store-task-detail.json`（明细 xlsx，sendAttempts=1，verificationLevel=windows-readback-file-card）
- **定性**：假阳性 verified。三路证据：
  1. 大同目视：群里只见统计图、无明细 xlsx（最高优先级现场证据）。
  2. 12:17 紧邻的统计图发送即报「主窗口未出现」HTTP 500——窗口状态劣化在前，文件卡片疑似发送侧渲染但未投递（红感叹号）。
  3. #37 锚点盲区镜像：回读锚点 `[文件]` 不绑定文件名，无法区分真投递 vs 挂起失败。
- **安全性论证**：补发构成重复外发的条件不存在——群内无人见过该文件（大同目视+时间线）。重发风险=0。
- **处置**：补发原字节（run 目录 2026-10-19-17923 record 保留），补发成功后重写 marker。
- **关联**：同目录 stats 事件 12:15 首跑 void（PNG 从未发出）+ 本记录（detail 假 verified void）。同日两 void 均根因于 12:15 网关「主窗口未出现」窗口状态劣化。
- **产物快照**：verified-snapshots/2026-10-19-taobao-store-task-detail/（12:15 原字节，sha f02d91c4…）
