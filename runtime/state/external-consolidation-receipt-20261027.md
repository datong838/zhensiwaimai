# 2026-10-27 外部状态、代码与重要任务流归位收据

- 执行时间：2026-10-27 00:58–02:11（Asia/Shanghai）
- 范围：`/Users/ddt/work/projects/ai_agent/state`、四组外部代码资产、源码 Git 历史、今日 24 行工作流门禁。
- 副作用：发送 0，生产补跑 0，消息回复 0，账本/登录/Cookie/localStorage 改动 0，Chrome 重启 0。
- 原件策略：外部原件保留；仓内有原字节归档和可回退证据。

## 1. `/state` 全量收拢

| 外部目录 | 仓内位置 | 外部文件数 | 结果 |
|---|---|---:|---|
| `state/meituan-waimai-negative-review-appeals` | `state/shared/meituan-waimai-negative-review-appeals` | 303 | 相对路径+逐文件 SHA-256 全等 |
| `state/taobao-flash-sale-negative-review-appeals` | `state/shared/taobao-flash-sale-negative-review-appeals` | 587 | 相对路径+逐文件 SHA-256 全等 |
| `state/negative-feedback-list-appeals` | `state/shared/negative-feedback-list-appeals` | 159 | 相对路径+逐文件 SHA-256 全等 |
| `state/taobao-agent-new-merchants/maintenance` | `state/taobao-agent-new-merchants/maintenance` | 3 | 外部 3 个文件均在仓内存在且 SHA-256 相等；仓内另有现役历史，未被覆盖 |

外部合计 1052 个文件、77,888,498 字节，全部有仓内等价副本。三个共享业务根已由 `business_storage` 解析；商家维护证据仅归档，不覆盖现役商家状态。

## 2. 外部代码资产收拢

| 资产 | 仓内位置 | 文件数 | 激活状态 |
|---|---|---:|---|
| 桌面微信控制 | `vendor/legacy-app-controler/wechat-desktop-control/scripts` | 17 | 现役共享调用已切换；全局互斥锁域原样保留 |
| 独立 Chrome 控制器 | `vendor/dedicated-chrome-controller` | 24 | 淘宝下载和视频相关调用已切换；账号 profile 不搬 |
| 淘宝下载 Skill 内部镜像 | `vendor/installed-taobao-skill` | 11 | canonical 与 mirror entrypoint SHA-256 一致 |
| 旧 Windows 驱动 | `archive/compat/wechat-windows-driver` | 48 | 只归档，不激活旧通道 |
| 外部代码原字节 | `archive/external-code-originals/b0922b38c68d4a8d9addded255ce0a27` | 按资产保留 | 可审计/回退 |
| 旧源码树与 Git 历史 | `archive/source-before-unification/b0922b38c68d4a8d9addded255ce0a27` | 完整镜像 | 不跟随外部符号链接 |
| 原全局淘宝 Skill | `archive/installed-skill-original-706baaf6246147618ba62cbfd1d38771` | 11 | 原字节保留 |

`/Users/ddt/.codex/skills/daily-taobao-download-to-jinsha` 现只保留薄入口，指向仓内 canonical Skill 和 entrypoint。现役工作树已接管源仓 Git 历史，HEAD=`1a99f8a`；只写 Git 元数据/索引，未 checkout/reset，未覆盖生产文件。

## 3. 路径和封印维护

- 共享 `workflow_bridge` 五条发送路由外部账本改为 `business_storage` 内部根；五条探针均已穿过账本门，只在人工故意缺失的 payload 门失败。
- 共享依赖维护回执：`runtime/state/code-consolidation-shared-maintenance-20261027-0240/receipt.json`，零发送。
- 商家封印重钉回执：`runtime/state/merchant-code-consolidation-resync-20261027-0300/maintenance-receipt.json`，状态 SEALED，19 文件，零发送。
- Top10 runtime policy 已重钉到归位后的共享依赖摘要；差评分析依赖维护后仍是 `UNSEALED_ACCEPTANCE`，正确业务日仍为 2026-10-26，只允许下一次真实非空业务验收重新封板。
- 归位后动态 `verify-active`：共享 clean、商家 SEALED、Top10/差评/五数据根全通过；`activeExternalReferences=[]`、`unmappedReferences=[]`、`opaqueCode=[]`、`sendAttempts=0`。

## 4. 重要任务流代码与回归

- 淘宝下载→金鲨：entrypoint 契约 50 项；恢复预算 A/B、历史 UI 恢复、金鲨 owner、计划证据恢复、图片前缀均通过，真实 UI 动作 0、发送 0。
- 金鲨日报→企业微信：Python 25 项、策略 32、执行器 29、浏览器 58、通道 8 项通过。修正的仅是离线测试仍打桩旧 WindowsAdapter 的过时接缝；生产 WeComAdapter 逻辑未改。
- 视频发布：8 个原回归脚本和 5 个存储迁移专项通过；旧 submitted/verified 状态迁移模拟中新发布 0。
- 归位工具：24 项准备/回退/幂等/反例回归、5 项源码归位回归、5 项视频迁移回归通过。
- runner 全量回归 69 项通过；修正了一个依赖实时早于 08:00 就失败的 cadence 测试，并将 control 删除失败的期望收紧为 fail closed 空名单。
- runner 回归已把 `alert_store` 的 raw/summary/archive 全部重定向临时目录；69 项重跑前后生产 `alerts_summary.json` 摘要不变。本次早先测试造成的 `__desktop_channel__`、`k` 假告警及已退役验收窗口告警已精确标记 resolved，未删除真实历史。
- 授权监控 3 项新边界回归通过；SEALED 商家锁中用于维护审计链的旧 `unsealedAcceptance` 不再生成 06:00 假到期告警，真正 UNSEALED 窗口仍会告警。
- Top10：Python 32、后台 12、收入排序 22 项通过，严格保持收入列口径。
- 统一微信依赖：412 项回归通过；新商家封印回归 123 项通过。
- 24 行工作流的逐项时间、业务日、历史隔离、路由、浏览器与数据门禁见 `runtime/state/preflight-audit-20261027-24-workflows.md`。

## 5. 恢复与外部阻碍

- launchctl `com.zhensi.waimai.careloop` 已恢复，PID 27422；`daemon.json.status=running`，最新心跳 02:10:23，下次周期 02:40:23。恢复后首周期 22 个现役流均为 `not_due`，仅落盘台账，未发送。
- 9230 仍是内容级 AMBER：一轮内已用完唯一次正常 reload，无登录/验证码/风控，但仍无业务正文。不再重载、不重启 Chrome。
- 9232 显示 34 家美团门店授权失效；其中 15 家仍在客户主表，34 家均缺失于最新 10-25 报表。这是真人重新授权或业务权威排除清单才能解决的数据阻碍；自动化不点击“立即授权”。
- 上述两项不会被历史 success/unknown 或已合并旧别名掩盖；受影响流将 fail closed，不伪报全量完成。
