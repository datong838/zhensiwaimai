# platforms/ — DEPRECATED

> 状态：**废弃（2026-09-30）**，保留仅供历史参考，**禁止新代码 import**。

## 为什么废弃

本目录是臻肆外卖早期的「手机 app 操控」抽象（`MeituanClient` / `TaobaoFlashClient` / 微信适配），基于
`anti_popup` / `human` / `locator` / `mobile_runtime` 等 adb/UIAutomator 辅助层。

经 2026-09-30 盘点确认：**14 条流水线零引用本目录**——它们实际统一走 `skills/` 下的桌面浏览器
CDP 实现，发送经 `skills/wechat-messaging`（已封印）。

## 取代架构

按《岗位实体化技术方案》，每个平台是 `skills/posts/<platform>-post/` 下的独立岗位：

| 平台 | 岗位 | 工位（端口） |
|---|---|---|
| 金鲨 | `posts/jinsha-post`（已建成 + 自封印） | 9232 |
| 淘宝品牌商 | `posts/taobao-brand-post`（规划） | 9230 |
| 淘宝服务商 | `posts/taobao-svc-post`（规划） | 9231 |
| 美团 | `posts/meituan-post`（规划） | 9233 |
| 抖音/快手/视频号/小红书 | `posts/video-*`（按端口拆分） | 9222/9224/9225/9226 |

如未来确有「手机端」能力需求，应作为新岗位按上述方案重建，**不要**复用此处代码。

## 删除条件

待全部 `posts/*-post` 岗位上线并通过回归、且无人再引用本目录后，由大同授权整体删除。
