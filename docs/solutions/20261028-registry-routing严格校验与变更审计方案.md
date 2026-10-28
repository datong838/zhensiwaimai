# 2026-10-28 registry-routing 严格校验与变更审计方案

## 目标与边界

关闭 `skills/wechat-messaging/config/registry-routing.json` 作为外置路由数据的剩余完整性缺口，同时保留“授权串与防重账本路径不外置”的原设计。实现只收紧配置读取，不新增路由、群、载荷、发送、重试或业务授权；生产仍沿原工作流/主任、原桥、原队列、System Events 可见 UI 和原账本。

本轮不把 `registry-routing.json` 或其 changelog 混入共享代码封印。共享封印只登记负责验证它们的代码字节；数据文件继续外置，但每次运行必须通过严格结构和审计链核验。

## 当前问题

1. `workflow_bridge.py` 当前对文件缺失、JSON 损坏、未知结构和非法条目采用忽略或内置默认回退，无法区分“明确批准的外置路由”与“被破坏后碰巧可运行”。
2. `workflow_bridge_windows.py` 独立读取 `channel`，异常时默认 `windows`。当前生产只允许本地企业微信，这个默认会形成通道降级侧门。
3. 配置包含14条路由，但当前加载器不拒绝未知路由、缺少路由或额外字段；`channel` 也未由统一合同校验。
4. `registry-routing.changelog.jsonl` 只有初始说明，没有当前配置文件 SHA、规范化路由 SHA、允许集合或授权引用，无法对当前字节形成机器审计。

## 严格合同

### 配置结构

- 顶层字段必须精确为 `schemaVersion`、`description`、`updatedAt`、`updatedBy`、`reason`、`routes`；未知字段和缺字段均拒绝。
- `schemaVersion` 必须是整数1；四个说明字段必须是非空字符串，`updatedAt` 必须是有效 `YYYY-MM-DD`。
- `routes` 的键必须精确等于桥内14个已注册路由，不允许缺少、重复或新增路由。
- 每条路由字段必须精确为 `group`、`kind`、`count`、`channel`。
- 每条路由的 `group/kind/count` 必须等于当前已审允许值；`channel` 必须为 `wecom`。任何改群、改类型、改数量或改通道须先修改方案和封印验证代码，不得只改数据文件绕过审查。

### 变更审计

- changelog 允许保留旧历史行，但最后一行必须是严格审计记录，字段精确为：`schemaVersion`、`ts`、`by`、`action`、`authorizationRef`、`reason`、`previousConfigSha256`、`configSha256`、`routesSha256`、`changedRoutes`。
- `configSha256` 必须等于当前配置原字节 SHA-256；`routesSha256` 必须等于按 UTF-8、排序键、无空白规范化后的 routes SHA-256。
- 本次建立 `strict-baseline`，`changedRoutes=[]`、`previousConfigSha256=null`。后续实际更新必须使用 `update`、写明上一条配置 SHA 和非空精确路由集合。
- changelog 缺失、末行损坏、摘要不一致或字段越界时，运行时失败关闭。

## 实现文件

- `skills/wechat-messaging/scripts/workflow_bridge.py`
  - 新增统一严格加载、审计核验和 `route_channel()`；删除静默逐条回退。
- `skills/wechat-messaging/scripts/workflow_bridge_windows.py`
  - 删除独立 fail-open 读取，复用桥内已验证的 `route_channel()`。
- `skills/wechat-messaging/config/registry-routing.changelog.jsonl`
  - 追加当前配置严格基线，不改配置业务字节。
- `skills/wechat-messaging/tests/test_registry_routing_integrity.py`
  - 覆盖合法配置、缺/多字段、未知/缺少路由、路由字段或值漂移、通道漂移、配置 SHA 与 routes SHA 审计不匹配、Windows 桥不再默认降级。
- `skills/wechat-messaging/scripts/dependency_maintenance.py` 与 `skills/wechat-messaging/dependencies.json`
  - 通过受控维护登记验证代码的新摘要；数据文件与 changelog 仍不进入封印。
- 三个直接消费者的原维护入口与策略文件
  - 只同步新的共享摘要，保持 Top10 策略、新商家 `SEALED` 真实非空验收、差评 `UNSEALED_ACCEPTANCE` 和业务日期不变。

## 执行顺序

1. 冻结当前配置 SHA、共享摘要、三个消费者状态、原队列/账本/游标摘要和运行 PID。
2. 先写严格合同测试，再最小修改两处桥代码并追加基线审计行。
3. 运行定向测试、统一微信完整回归和配置审计 CLI；确认任何非法样本均在账本/UI前拒绝。
4. 通过原共享依赖维护器登记代码摘要，再按原 Top10、差评、新商家维护入口串行同步共享摘要。
5. 运行三个消费者全量回归，核对原策略/验收状态/业务日期、主任和四浏览器 PID、UI队列、账本、游标均未发生业务变化。
6. 落盘机器审计证据，更新遗留与迁移交接，提交并推送 `main`。

## 停止规则与风险

- 主任有 `live_steps`、组锁、物理岗位锁或 UI 队列新增时，不执行共享摘要维护。
- 任一文件字节与方案冻结值不符、测试失败、维护回执不匹配或消费者拒绝时立即停止；不调用业务执行器，不创建消息。
- 配置校验改为失败关闭后，格式损坏会显式阻断相关桥，而不再静默沿默认运行。这是预期安全收紧，但必须通过当前真实配置和全回归证明合法路径不变。
- 本轮不改变历史 `attempted/unknown/verified`，不重发任何事件，也不把离线通过当作图片像素真实验收。

## 验收标准

- 当前14条路由严格校验通过；所有构造的结构、允许集合、通道和审计漂移样本均失败关闭。
- Windows 桥只消费统一已验证通道，不存在异常默认 Windows 的分支。
- `registry-routing.json` 原业务内容 SHA 不变；changelog 最后一行精确绑定该 SHA 与 routes SHA。
- 共享摘要与三个消费者同步后全部原门通过，发送、UI队列新增、账本/游标改写均为0。
- 当前主任与四浏览器保持原身份，下一周期仍由原主任正常运行。
