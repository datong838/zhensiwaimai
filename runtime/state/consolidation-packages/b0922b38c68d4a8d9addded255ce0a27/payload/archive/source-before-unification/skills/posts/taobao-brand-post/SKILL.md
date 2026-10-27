# 岗位：taobao-brand-post（淘宝闪购·商家版）

> 状态：已实体化为独立岗位（2026-09-30 岗位实体化方案 / L2）。本目录是「淘宝闪购·商家版」的**专人专岗**，
> 流水线（skills/ 下的工作流）只调用本岗，不自己连接浏览器。

## 工位（端口）
- **9230**（`http://127.0.0.1:9230`）——淘宝品牌商工位：单店数据/活动三项核验、新店装修核验（顶部招牌/店内海报「已配置」徽标读取）。

## 流水线消费者（2026-10-12 登记）
| 流水线 | 业务 |
|---|---|
| daily-taobao-download-to-jinsha | 淘宝数据下载→金鲨处理 |
| daily-top10-to-wechat-group | Top10 日报 |
| daily-new-stores-activity-audit-to-wechat | 新店活动审计（满减/折扣/活动缺失提醒） |
| daily-new-stores-decoration-audit-to-wechat | 新店装修审计（顶部招牌/店内海报缺失提醒） |

## 职责边界（软件功能内聚）
- **本岗负责（通用）**：连到正确的工位浏览器（`connect.mjs`）、工位互斥锁（`lease.mjs`，锁路径 `/tmp/zhensi-post-9230.lock`）、**固定通道契约**（`channel.mjs`）、**工位身份与登录态断言**（`auth.mjs`）。
- **流水线负责（专属）**：业务抽取（店铺选择/活动核验/报表下载/**装修页读取**）、认证锚点恢复、冷启动预算——保持在工作流逻辑内，不进本岗。
- 注：`channel.mjs` 钉死 `taobao-brand:9230` 的端口 / CDP / app origin 与禁止动作清单；认证锚点恢复、冷启动预算是业务耦合逻辑，仍留工作流执行器。装修页读取（菜单导航进 `/app/shop/{id}/decorate`、`melody-decorate-pc` iframe 内已应用模版定位、组件徽标读取）属业务抽取，留在 `daily-new-stores-decoration-audit-to-wechat/scripts/decoration_collector.mjs`。

## 接口契约
- `connectToPost()` → `{browser, context, page}`：连接本工位；无 context 抛 `post-taobao-brand-post-context-missing`。
- `acquirePostLease(runId)` / `releasePostLease(lease)`：工位互斥。持有锁时其他同端口流水线抛 `post-9230-lease-busy:<runId>`。
- 互斥语义（L2）：不同工位（端口）可并发；同一工位多流水线强制串行。
- `channel.mjs` 导出（固定通道契约，**流水线只读核对，不得改写**）：
  - `TAOBAO_BRAND_PORT=9230` / `TAOBAO_BRAND_CDP` / `TAOBAO_BRAND_APP_ORIGIN='https://melody.shop.ele.me/app/'`
  - `describeChannel()`：冻结的 {port, cdp, appOrigin, forbidden[]}
- `auth.mjs` 导出（域原语，**流水线只调这些，不自己写登录态判定**）：
  - `assertOrigin(url)`：非品牌商 app 路径 → `taobao-brand-origin-changed`。
  - `assertAuthenticated(url)`：未落在 app 路径 → `brand-login-required`（保留既有错误码）。

## 自封印
- `dependencies.json` 钉死本岗文件 sha256；`verify_dependencies.mjs` 校验。改动本岗任何被钉文件须走受控流程重算。
