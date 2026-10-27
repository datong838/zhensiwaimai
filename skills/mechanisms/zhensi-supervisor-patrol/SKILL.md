---
name: zhensi-supervisor-patrol
description: 臻肆持续监理，检查原主任、排班、岗位健康及真实交付，并处理授权范围内的可恢复阻碍。
---

仓库根：`/Users/ddt/work/projects/ai_agent/zhensi_waimai_back`。本文件为仓内权威；智能体安装目录仅留入口。最新用户约束优先于历史经验。

生产仅走原主任/control/适配器/队列/账本；企业微信遵循仓内 `docs/operations/20261024-企业微信UI岗位执行约定.md`，仅System Events原生UI树及可见操作。attempted/unknown只读对账，不重发、不换事件绕门、不伪verified，不改账本或游标。历史归档仅供定位，不构成操作授权。

# 臻肆持续监理

先完整读取 `docs/operations/每日0800监理启动与持续值守.md`、企业微信UI岗位执行约定、`runtime/skills_manifest.json`及`runtime/state/morning-start-<当天YYYYMMDD>.md`（如有）。以Asia/Shanghai当前日期为准；当日24台账行、现役及合并关系以最新manifest为准，不复制旧排班。

## 检查与处置

1. launchctl `gui/501/com.zhensi.waimai.careloop`、daemon真实PID/启动身份/心跳及日志共同判断运行。核对原control、live_steps、队列与真实持锁进程；岗位忙不抢锁。不能只凭状态文件或进程名匹配判活。
2. 9230/9231/9232/9233按真实业务域、正文响应、登录/验证码/可见遮罩检查。WorkBuddy登录页不代表美团失效。不读取凭据、Cookie、localStorage或认证API，不重启Chrome。
3. 只读巡检入口为 `runtime/supervisor_patrol.py`；驱动脚本的任何apply操作须先核对其当前实现与授权，不能因历史Skill示例直接批量运行。
4. 可恢复故障先方案、最小修复、自测和原门禁复验；仅经原control交主任接续。零发送须有原收据实证，unknown不补跑。扫码/验证码/账号风险/店铺授权等外部条件报告具体所需动作，同时继续独立正常流。
5. 对每条交付核对新业务日、完整目标群、载荷及原送达收据。同批合规图片一次提交且群/空框确认后保留verificationPending，继续未尝试项；不把其他人会议卡片当成本方发送证据。

## 持续目标与维护

未到末档、静态测试或暂无任务均不完成Goal。需核验当天末档、原流程最终台账及送达；06点清理、08点启动、22点维护按各自现行规程，不能由此新增或改动定时任务。

22点维护先读 `docs/operations/每日2200浏览器保活与IM复位.md`。9233仅无任务、持原租约且无验证阻碍时先建完整reception健康页，再只关精确旧IM页；失败保留旧页，一轮最多一次，同日明确完成则只读复核。

无变化静默；有意义进展、真实失败或必要用户动作仅在当前聊天报告，不额外发群告警。
