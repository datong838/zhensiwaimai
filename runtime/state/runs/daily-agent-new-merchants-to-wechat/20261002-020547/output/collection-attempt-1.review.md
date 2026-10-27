# 只读采集复盘

| 项目 | 耗时 | 结果 | 踩坑点 |
|---|---:|---|---|
| 后台浏览器预检 | 0.133秒 | 通过 | 无 |
| 建立独立任务页 | 0.597秒 | 通过 | 无 |
| 进入意向商户列表 | 1.363秒 | 通过 | 无 |
| 日期设置与双帧回读 | 1.474秒 | 失败 | calendar-day-count:2026-09-30:0:evidence=[{"classes":["ant-picker-cell","ant-picker-cell-end"],"panelLabel":"2026年10月"}] |
| 选择审计 | — | 未执行 | 前置门禁未通过 |
| 只读采集总耗时（含子阶段，不重复相加） | 4.040秒 | 失败 | calendar-day-count:2026-09-30:0:evidence=[{"classes":["ant-picker-cell","ant-picker-cell-end"],"panelLabel":"2026年10月"}] |

父阶段包含子阶段耗时，不能把所有行重复相加。
