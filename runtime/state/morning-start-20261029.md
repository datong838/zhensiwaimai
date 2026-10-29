# 2026-10-29 旧机重新接管晨间证据

## 最新用户约束

用户明确由旧机重新接管，要求商家预检、双Top10、活动、装修等入口临时改走Windows，企业微信登录后再切回。企业微信实现、队列和历史保留。当前Windows能力不足以证明空输入框与载荷绑定回执，切换尚未部署，不能据此称发送已恢复。方案见 `docs/solutions/20261029-旧机接管与Windows网关恢复方案.md`。

## 真实运行证据

- 原安装入口已执行，旧机主任实际PID65429，启动时间2026-10-29 08:57:06；launchctl与ps均确认存活，心跳status=running。
- Windows网关192.168.110.184:8731实际ready=true/logged_in=true，旧机127.0.0.1:8732中继PID63552监听，health端到端通过。
- Windows current_chat实际仅返回title；运营群可见，电销群不在当前会话列表；深度12只读树未提供可核验composer空态。未以业务发送作探针。
- 共享依赖原verify_dependencies通过，企微代码与路由配置字节未改，源机历史定时暂停/删除状态未恢复。

## 今日已产生的业务事实

1. `runtime/run_history/2026-10-29/negative-feedback-list-appeals-0930--20261029-084946--a1--s1.log`：业务日10月29日，数据窗10月22日至28日，美团18条verified_submitted；淘宝依原用户裁定未提交。不能把申诉成功描述为已向群发送Excel。
2. `runtime/run_history/2026-10-29/negative-feedback-list-appeals-1230--20261029-085722--a1--s1.log`：同日双Excel生成，美团57条、淘宝138条；位于 `outputs/negative-feedback-list-appeals-20261029/`。
3. 同轮s2原回执：state=blocked、sendAttempts=0、newSendAttempts=0、items=[]，原因为ui-post-preflight-not-verified；不是已发unknown，也未结论化为verified。零发送恢复须沿原事件、冻结文件和原control执行。
4. `runtime/run_history/2026-10-29/daily-agent-new-merchants-to-wechat--20261029-085707--a1--s1.log`：原SEALED门通过，两页16行全量采集，筛出6条目标，阶段止于desktop_wechat_preflight，sendAttempts=0；completion=RECOVERABLE_NO_SEND。目标商家ID547439706、541693043、1362213629、545665462、1359516596、1338962506；不改游标或重建事件。
5. 双Top10与差评分析当前原预检受企微登录/主窗锚阻断，不能报已送达；各自原收据保留。

## 下一步

- 由当前原主任在09:00固定排班继续合同流及其他已到点任务，不能把心跳next_cycle_at的30分钟上界误读为固定班次必须等09:27；daemon_loop已实现fixed_schedule.next_boundary唤醒。
- 取得Windows实际部署driver.py/server.py及其直接驱动模块，补齐真实空框与载荷绑定回执，再实现并验证统一双向通道选择、维护封印和真实正常任务。不能用本仓旧4-action骨架覆盖线上真身，不启用HTTP失败重试或媒体占位符判成功。
- 当前在途步骤以真实PID和live_steps核查；不得用本页快照抢锁、重启在途任务或重复发送。
