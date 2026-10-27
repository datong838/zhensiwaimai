# 金鲨岗（jinsha-post）

> 岗位 = 端口 `9232`。这是「专人专岗」中的金鲨采集工位，一个内聚主题、一块独占浏览器身份。

## 内聚主题（唯一理由）

**金鲨 SaaS（`https://data.guoshuyufen.com/`）的专用浏览器采集**：连接、登录态校验、遮罩处理、分页一致性核对、工位租约锁（互斥）。

## 工位（专用 Chrome）

- CDP：`http://127.0.0.1:9232`
- profile：`jinsha-business`（由 AOS `control-background-dedicated-chrome` 插件管理，常驻运行）

## 接口契约（流水线只能这样调它）

| 模块 | 导出 | 契约 |
|---|---|---|
| `scripts/connect.mjs` | `connectJinsha(cdp?)` | 连接 9232，返回 Browser；调用方负责 close，不关闭共享 Chrome |
| | `assertJinshaOrigin(url)` | origin 不在金鲨 → `jinsha-origin-changed` |
| | `assertAuthenticated(page, body?)` | 登录态失败 → `jinsha-authentication-required` |
| | `closeDrawer(page)` | 关侧栏抽屉遮罩，遮罩 >1 → `drawer-overlay-count` |
| | `dismissAnnouncement(page, markers, waitMs?)` | 公告白名单关闭；白名单外 → `unknown-page-overlay`（fail-safe） |
| `scripts/lease.mjs` | `acquireJinshaLease(runId, path?, ttlMs?)` | 工位租约；被占 → `jinsha-lease-busy` |
| | `releaseJinshaLease(lease)` | 释放；owner 不符 → `jinsha-lease-owner-mismatch` |
| `scripts/pagination.mjs` | `waitPaginationStable(page, opts)` | 分页四方一致稳定两次放行 |
| | `nextPage(page, ready, opts)` | 翻页 + 跨页漂移校验 |
| | `collectAllPages(page, ready, extract, opts)` | 泛化遍历所有分页收集行 |

## 红线

- 岗位**只做通用采集**，不掺任何流水线专属业务（日报下载 / 差评提取 / 新店识别）。
- 租约锁是「金鲨工位同时只允许一条流水线当班」的物理保证，契约不得破坏。
- 公告遮罩「白名单外熔断」是 fail-safe，新公告须先只读探针确认再入白名单，勿盲点。

## 来源

从三处重复实现收敛（语义逐字一致）：
- `.daily-jinsha-reports-core/scripts/jinsha_cua_exam.js`（租约锁 + 连接）
- `daily-negative-reviews/scripts/browser_collect.mjs`（登录态 + 遮罩 + 分页）
- `daily-new-stores-to-wechat/scripts/collector.mjs`（公告遮罩白名单）
