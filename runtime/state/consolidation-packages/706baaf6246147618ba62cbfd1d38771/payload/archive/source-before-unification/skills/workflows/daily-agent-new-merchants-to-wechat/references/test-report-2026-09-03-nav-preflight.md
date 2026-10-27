# 2026-09-03 进页与环境实操补验

## 范围

- 验证补齐后的：抢占 Chrome 焦点 → 打开 `https://open.shop.ele.me/manager/base/home` → 侧栏进入「意向商户管理」。
- 验证荣耀真机主微信可定位「臻肆测试群」（只读，未发送）。
- 未跑完整 AX 采集（本 Cursor 会话无 Computer Use `sky`）；未向生产群发送。

## 结果

| 项 | 结果 |
|---|---|
| 采集器离线自测 | GREEN（8） |
| `--preflight-nav` | GREEN；`intentionListVisible=true` |
| 页面 OCR | 意向商户管理 / 商家意向列表 / 推荐时间 / 查询 / 待处理 / 详情 / 开始日期 均命中 |
| 证据截图 | `/tmp/zhensi-preflight-intention-ok.png` |
| 微信 `--probe-locate-group` | GREEN；`groupTitleVerified=true`；`臻肆测试群`；耗时约 18s |
| 发送业务消息 | 未执行 |
| 生产游标 | 未触碰 |

## 修复点

- OCR 侧栏点击禁止写死 `scale=2`；改为 `imageSize / windowBounds` 动态换算。
- 侧栏与页标题同文案时，取最左侧命中。
- 若侧栏已露出「意向商户管理」，可直接点目标项。

## 下一步

在具备 Computer Use `sky` 的会话内跑完整 `runMerchantCollector`，再按站立授权对「臻肆测试群」发送当日增量。
