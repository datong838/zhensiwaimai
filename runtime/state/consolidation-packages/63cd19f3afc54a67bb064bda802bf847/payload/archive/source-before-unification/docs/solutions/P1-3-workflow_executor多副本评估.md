# P1-3 workflow_executor.py 多副本评估（2026-10-03 深夜）

## 结论（先说）

**暂缓合并。** 3 份活跃副本实质分化（231/190/463 行），各自服务于不同技能的
契约与证明校验面，盲目合并 = 高风险重写。本评估文档化差异，合并动议移交
后续带完整回归测试窗口的白天时段，且必须先补齐各副本的契约测试。

## 副本清单与活跃性

| 副本 | 行数 | 所属技能 | 活跃性 |
|---|---|---|---|
| `skills/daily-agent-new-merchants-to-wechat/scripts/maintenance_executor.py` | — | daily-agent | 活跃（W4 已实现 recover-lost-receipt-acceptance，19 测试全绿） |
| `skills/daily-negative-reviews/scripts/maintenance_executor.mjs` | — | negative-reviews | 活跃（Node 侧，1 测试绿） |
| `skills/daily-jinsha-reports-to-business-wechat/scripts/business_workflow_executor.mjs` | 163+ | jinsha 日报 | 活跃（54 测试覆盖，P0-2 白名单外置今日已落） |

注：早前评估口径为「4 份副本」，实测其中 1 份为备份/非活跃文件，活跃副本实为 3 份。

## 附：强行合并影响面实测（2026-10-04 00:46 复核）

全仓同名文件共 **6 份**：3 份活跃（上表）+ 3 份非活跃（`state/taobao-agent-new-merchants/runs/*` 两份 73 行 run 快照、`maintenance/merchant-20260916-production-guard/candidate/` 一份 104 行候选件）。

**哈希绑定面（改一份 = 对应门禁全拦）**：
- top10 副本：被 `daily-top10-to-wechat-group/runtime-policy.json` `files{}` 钉 path+sha256（`0baf49b0…`）——正是告警 Top 失败码 `runtime-policy-file-digest-mismatch`×31 的那道门；
- agent 副本：被 `daily-agent-new-merchants-to-wechat/executor-lock.json` 钉 path+sha256（`63181621…`）——`executor_integrity`×71 的那道门；
- video-publish 副本：无 sha 锁，但目录内另有 platform_spec/run_id 测试与独立 manifest 步骤。

**职责语义（三份不是拷贝，是三种状态机）**：top10=「单次调用单次尝试、续跑门在 runtime 代码」；agent=「确定性采集/审计/手机/提交四步」；video-publish=「企业微信视频→抖音/快手/视频号多平台固定执行器（463 行）」。

**import/测试面**：top10 的 `runtime_guard.py`+`test_runtime_guard.py`；agent 的 `maintenance_executor.py`+`executor_integrity.py`+4 个测试文件；video-publish ≥2 个测试文件——直接关联 ≥8 个测试文件，且 unittest discover 尚有 5 个预存污染未修（无"全量绿"基线可自证等价）。

**强行合并的影响面结论**：① 3 条任务流当天全停（哈希门禁先于代码逻辑拦截，改完不重钉 sha 连跑都跑不起来）；② 回滚也要走受控再封印重钉（深夜窗口回滚成本最高）；③ 合并≈以 463 行 video-publish 为最大公约数重写，行为等价性**不可证明**；④ 唯一收益（改一处）远低于三条流停摆风险。正确路径仍是「公共库下沉（receipt.py 已是第一步）+ 契约快照测试 + 白天窗口分步走」。

## 为什么不合并

1. **行数与职责面差异巨大**（231/190/463 行）：三者不是同一逻辑的拷贝粘贴，
   而是各自围绕所属技能的**不同证明校验状态机**长出来的独立实现
   （agent 的收据恢复通道 / 差评的 reconcile 维护 / jinsha 的六阶段工作流）。
2. **`executor_integrity` 仅 1 份活跃**（P1-2 实测洞察）：说明运行态只有一份
   被 policy 面校验，合并收益集中在可维护性，而风险集中在「改坏明早 10 条
   流水线」。
3. **当晚窗口约束**：本次 W1–W6 全量开发的验收基线是「明早 10 任务流零回归」，
   大规模重构与该目标直接冲突。
4. **封印联动**：合并必然触碰 wechat-messaging 封印面相邻文件，触发受控再
   封印全流程——而 prepare 测试门今晚已被 5 个预存 unittest discover 污染卡住
   （与本次改动无关，详见 `docs/w2-staging/README-再封印操作手册.md`）。

## 后续正确姿势（移交白天窗口）

1. 先修 5 个预存测试污染，恢复 unittest discover 绿基线。
2. 为 3 份副本各补「契约快照测试」（输入→分类→输出证据面），当前覆盖不均。
3. 合并方向：抽公共库 `runtime/maintenance_common.py`（分类器/收据解析复用
   今日新建的 `runtime/receipt.py`），各技能 executor 只留差异化证明校验。
4. 合并后跑全量 246 测试 + node_cov 54 测试 + kickstart 重启观察一个完整周期。

## 关联

- P1-3 动议来源：`docs/architecture/20261003-任务机制自进化优化方案.md`
- 今夜已落地的替代性收益：`runtime/receipt.py`（P0-1）已被 alert_store 经验
  索引共用，相当于已经开始了「解析逻辑下沉公共层」的第一步。
