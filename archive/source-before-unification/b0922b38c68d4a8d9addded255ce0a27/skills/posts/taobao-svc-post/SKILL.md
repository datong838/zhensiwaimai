# 岗位：taobao-svc-post（淘宝闪购·服务商平台）

> 状态：已实体化为独立岗位（2026-09-30 岗位实体化方案 / L2）。本目录是「淘宝闪购·服务商平台」的**专人专岗**，
> 流水线（skills/ 下的工作流）只调用本岗，不自己连接浏览器。

## 工位（端口）
- **9231**（`http://127.0.0.1:9231`）——淘宝服务商工位：意向商户游标增量采集。

## 职责边界（软件功能内聚）
- **本岗负责（通用）**：连到正确的工位浏览器（`connect.mjs`）、工位互斥锁（`lease.mjs`，锁路径 `/tmp/zhensi-post-9231.lock`）、**工位身份与登录态断言**（`auth.mjs`）。
- **流水线负责（专属）**：业务抽取（意向商户游标采集 / 核对）、业务分页、具体菜单路径校验——保持在工作流逻辑内，不进本岗。

## 接口契约
- `connectToPost()` → `{browser, context, page}`：连接本工位；无 context 抛 `post-taobao-svc-post-context-missing`。
- `acquirePostLease(runId)` / `releasePostLease(lease)`：工位互斥。持有锁时其他同端口流水线抛 `post-9231-lease-busy:<runId>`。
- 互斥语义（L2）：不同工位（端口）可并发；同一工位多流水线强制串行。
- `auth.mjs` 导出（域原语，**流水线只调这些，不自己写登录态判定**）：
  - `assertOrigin(url)`：非 `open.shop.ele.me/` → `service-origin-changed`。
  - `assertAuthenticated(body)`：正文命中 `账号密码|扫码登录|验证码登录|立即登录|无法登录` → `service-login-required`。

## 自封印
- `dependencies.json` 钉死本岗文件 sha256；`verify_dependencies.mjs` 校验。改动本岗任何被钉文件须走受控流程重算。
