# 只读采集复盘

| 项目 | 耗时 | 结果 | 踩坑点 |
|---|---:|---|---|
| 后台浏览器预检 | 0.048秒 | 通过 | 无 |
| 建立独立任务页 | 30.034秒 | 失败 | page.goto: Timeout 30000ms exceeded. Call log:   - navigating to "https://open.shop.ele.me/manager/base/home", waiting until "domcontentloaded"  |
| 进入意向商户列表 | — | 未执行 | 前置门禁未通过 |
| 日期设置与双帧回读 | — | 未执行 | 前置门禁未通过 |
| 选择审计 | — | 未执行 | 前置门禁未通过 |
| 只读采集总耗时（含子阶段，不重复相加） | 30.420秒 | 失败 | page.goto: Timeout 30000ms exceeded. Call log:   - navigating to "https://open.shop.ele.me/manager/base/home", waiting until "domcontentloaded"  |

父阶段包含子阶段耗时，不能把所有行重复相加。
