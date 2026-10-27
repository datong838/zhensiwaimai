# 每轮执行复盘

| 项目 | 耗时 | 结果 | 踩坑点 |
|---|---:|---|---|
| 封板完整性 | 0.007秒 | 通过 | 无 |
| 授权、群与通道门禁 | <0.001秒 | 通过 | 无 |
| 离线自测 | 0.191秒 | 通过 | 无 |
| 商家采集 | 7.138秒 | 通过 | 无 |
| 采集第1次 · 后台浏览器预检 | 0.042秒 | 通过 | 无 |
| 采集第1次 · 建立独立任务页 | 0.220秒 | 通过 | 无 |
| 采集第1次 · 进入意向商户列表 | 1.434秒 | 通过 | 无 |
| 采集第1次 · 日期设置与双帧回读 | 1.289秒 | 通过 | 无 |
| 采集第1次 · 第1页采集与稳定核验 | 0.294秒 | 通过 | 无 |
| 采集第1次 · selection_audit | <0.001秒 | 通过 | 无 |
| 采集第1次 · 商家详情核验 1347861248 | 0.773秒 | 通过 | 无 |
| 采集第1次 · 商家详情核验 546627135 | 2.371秒 | 通过 | 无 |
| 采集合同审计 | <0.001秒 | 通过 | 无 |
| 桌面微信预检 | 0.420秒 | 通过 | 无 |
| 群定位第1次 | 0.419秒 | 通过 | 无 |
| 逐条通知 | 0.082秒 | 失败 | dependency-drift:/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/windows_adapter.py |
| 福鲜砂锅 · 发送前合同复核 | <0.001秒 | 通过 | 无 |
| 福鲜砂锅 · 定位、输入与单次发送 | 0.077秒 | 失败 | dependency-drift:/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/windows_adapter.py |
| 福鲜砂锅 · 双帧与原生复制全文复核 | — | 未执行 | 前置阶段失败，代码禁止继续 |
| 福鲜砂锅 · 提交前证据门禁 | — | 未执行 | 前置阶段失败，代码禁止继续 |
| 福鲜砂锅 · 成功历史与原子游标提交 | — | 未执行 | 前置阶段失败，代码禁止继续 |
| 食焖坊黄焖鸡 · 通知流程 | — | 未执行 | 上一商家未完成，代码禁止越过游标 |
| 最终账本与游标复核 | — | 未执行 | 前置门禁未通过 |
| 真实非空验收重封 | — | 无待发 | 无真实新增发送，保持未封板 |
| 整轮总耗时（含子阶段，不重复相加） | 7.964秒 | 失败 | 无 |

父阶段包含子阶段耗时，不能把所有行重复相加。

## 机器决定的下一动作

- 状态：`RECONCILE_ONLY`
- 下一动作：`native-copy-read-only-reconcile-no-resend`
- 自动恢复：`true`
- 恢复预算：`1`
- 原因：`dependency-drift:/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/windows_adapter.py`
