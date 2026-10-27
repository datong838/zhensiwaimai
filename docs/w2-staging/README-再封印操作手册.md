# W2-C 桥外置 · 已就绪待切换（2026-10-03 深夜 staging）

## 状态
- `workflow_bridge.py.new`（sha `e4ae8d13e9165879…`）：REGISTRY 落群路由外置版，
  已逐条目验证与封印版等价（9/9 条目，含 taobao-evidence (1,2) 区间）。
- `dependency_maintenance.py.new`：含新授权登记 `user-20261003-selfevolve-w1-w6-full-dev-night`
  （allowedAfterSha256 钉死上面的新桥 sha）+ prepare 校验分支。
- 外置数据文件已就位：`skills/wechat-messaging/config/registry-routing.json`（+changelog）。

## 为什么没切（卡点，实测证据）
prepare 的「统一微信完整离线测试」阶段被 **5 个预存测试失败** 卡住
（sha 精确还原封印字节后基线复跑同样失败 ⇒ 与本次改动无关）：
- test_runtime ×4：test_interrupt_is_durable / test_real_engine_idempotent /
  test_unknown_never_resends / test_verified_reconcile_clears_stale_failure_reason
- test_workflow_bridge ×1：test_confirmed_zero_attempt_can_retry_with_fresh_lookup
- 症状：单测直调通过；unittest discover 顺序跑挂（模块间/顺序污染，'blocked' ≠ 预期）。
- 另注意：今天白天 Plan B 的 prepare 回执未落盘（全盘无 2026-10-03 receipt.json），
  Sep-29 唯一成功回执 testCount=197（非 246）。

## 切换步骤（白天窗口，约 10 分钟）
1. 先修上述 5 个测试污染（测试文件不在封印清单，修复不触发漂移）；
2. `cp docs/w2-staging/workflow_bridge.py.new skills/wechat-messaging/scripts/workflow_bridge.py`
   `cp docs/w2-staging/dependency_maintenance.py.new skills/wechat-messaging/scripts/dependency_maintenance.py`
3. `python3 skills/wechat-messaging/scripts/dependency_maintenance.py prepare \
   --authorization user-20261003-selfevolve-w1-w6-full-dev-night \
   --expires-at 2026-10-09T23:59:59+08:00 \
   --output-dir state/taobao-agent-new-merchants/maintenance/w6-registry-externalize-<ts>`
4. 重绑下游（搜旧桥 sha `52a587d0…`）：daily-agent executor-lock / negative-reviews
   dependencies.json+runtime-policy / Top10 runtime-policy；跑各自测试。
5. `inspect` 应为 clean；跑一遍 run_all --selftest。

## 事故复盘：2026-10-04 13:12 executor-lock-digest-mismatch
- **根因**：步骤 4 重绑只按旧摘要 grep，替换了 bridge（52a587d0→e4ae8d13）与 deps（af100726→3b6d54ff）两处，
  漏掉 executor-lock 还单独钉了 `files.messaging_dependency_maintenance` 的 sha（9bcc4530→应为 22993f59）。
  文件已换、锁没更 ⇒ 13:12 档 executor_integrity 即 FAIL（RECOVERABLE_NO_SEND，零外发）。
- **修复**（13:30）：executor-lock `files.messaging_dependency_maintenance.sha256` 更新为部署文件实际 sha
  （先与 prepare 验收过的 `dependency_maintenance.py.new`=22993f59… 比对一致）；13:31 补跑 SUCCESS
  （sent=0 为真·今日无新商家，final_cursor 验证到 11:15:46，非假成功）。
- **方法论纠偏**：按旧摘要 grep 只能找到「引用旧值的消费者」，**找不到「该更新但没更新的钉值」**。
  重绑收尾必须逐个重算锁/策略里钉的文件实际 sha 与钉值 diff，任何不一致=漏绑。
- **次生坑**：首次 manual 补跑在嵌套抢锁处崩溃未释放 run_all 互斥组锁（taobao-svc-9231，O_EXCL 文件，TTL=90min），
  守护后续周期假报 SKIPPED_BUSY。清理姿势：`kill -0 <pid>` 确认持锁进程已死 → 才可 remove 锁文件（等价 TTL 过期自愈）。
- 备份：`docs/w2-staging/rebind-bak-20261004/executor-lock.bak-20261004-1330.json`
