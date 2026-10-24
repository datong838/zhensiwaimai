# 负反馈列表申诉工作流（金鲨岗 · 美团 + 淘宝）

## 2026-10-24生效规则（覆盖下文历史排班与停产说明）

- 08:20由车间主任串行启动申诉与汇总，08:30前交付；08:22/08:25/08:28检查恢复。已成功不重发，unknown只读对账。
- 申诉步骤不发群；汇总依赖当日申诉执行成功，双平台各一份非空Excel紧接发送。
- 以平台近7日全部视图分页明细为准；今天无新申诉不等于无数据。实际Excel行数、业务日期、窗口、名称、路径均须校验，0行拒发。
- 淘宝负反馈提交以实际页面入口为准，不把平台建议当成已提交。它与另一个差评列表“立即申诉”流程不同。
- 目标群为“上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰”，经本地Mac企业微信发送。

> 岗位实体：金鲨岗（CDP 端口 9232，互斥组 `jinsha-9232`）。
> 编排模式：监理 → 车间主任 → 岗位 → 工作流。本工作流是车间主任排班下的一个独立任务流，
> 不替代任何其他任务流；监理不下场代跑（详见《监理职责铁律》）。
> 微信岗（发群）能力**沿用**既有 `workflow_bridge_windows.py`，本工作流不重复实现发送。

## 一、业务目标

在金鲨 SaaS（data.guoshuyufen.com）的「外卖 → 评价&负反馈 → 负反馈列表」页
（`#/evaluationManagement/feedback`）：

1. 对 **美团** 与 **淘宝** 两个平台、近 7 日窗口内的负反馈发起平台自带的「立即申诉」。
2. 每条申诉明细写入当日 md 临时台账（不保存账号/Cookie/手机号/顾客隐私）。
3. 全部申诉完成后，按平台分别生成 **两份独立 Excel**，发到客户微信群
   **FEIBING NEO AI数字员工**。

排班（大同 2026-10-06 批准）：**09:30 执行申诉** + **12:30 汇总发群**。

## 二、⚠️ 两平台 DOM 结构完全不同（核心事实，勿凭直觉）

两个平台共用同一个负反馈页 URL，切换只用**顶部 `.optionli`**（全部/美团/淘宝），
**绝不切换左侧渠道 `.cutli`**（切它会把整页换成淘宝渠道后台，`.appeal-filters-box` 与
`.status-btn` 双双消失，日期默认跳「近 1 个月」）。

| 维度 | 美团（mode:`status`） | 淘宝（mode:`category`） |
|------|----------------------|------------------------|
| 申诉类型 tab | `.appeal-filters-box .nav-item`（全部/AI申诉/商家申诉） | **无** |
| 申诉状态 tab | `.status-btn`（全部/未申诉/申诉中/申诉成功/申诉失败） | **无** |
| 分类筛选 | — | `.nav_li`（全部/食品安全负反馈率/服务负反馈率） |
| 申诉源 | 申诉类型=「全部」 + 状态=「未申诉」（仅该页带按钮） | 分类=「全部」视图下的**全部卡片**（所有卡片都带「立即申诉」） |
| 已/未申诉区分 | 靠状态 tab（页面直接可见） | **页面不呈现** → 靠**跨日本地账本**去重 |
| Excel 头部维度 | 五维状态计数 | 三分类维度计数 |
| 申诉后回读 | 卡片移出当前状态页 + 计数减少 | 按钮文案不再以「立即申诉」开头（或卡片消失） |

**为什么淘宝只用「全部」**：用户明确「淘宝就只有全部」。淘宝没有未申诉筛选维度，
默认激活的是「食品安全负反馈率」，必须显式点「全部」。

**★ 淘宝申诉先放弃（大同 2026-10-06 拍板，记入流程）**：淘宝申诉弹窗**没有「确定」按钮**
（只有 取 消/换 一个/复 制 实测三种），「差评申述」菜单是门店级配置页而非申诉入口——
**站内不存在可用的申诉提交口**。因此 `appeal_executor.mjs` 的 `execute()` 默认
`platforms = ['meituan']`，淘宝仅进页面快照不申诉；如站方日后补口子，用
`--platforms meituan,taobao` 恢复双平台。

**★ 淘宝 Excel 停产停发（大同 2026-10-06 21:15 拍板）**：既然不给淘宝申诉，
汇总报表**只产美团一份、只发美团一份**。`report_builder.mjs` 的 `REPORT_PLATFORMS`
收窄为 meituan；桥件数由 `config/registry-routing.json` override 为
`count: 1`（零封印数据文件通道）。当日已发出的淘宝 Excel 不撤回，自次日起生效。

## 三、关键契约（代码即事实，详见 `scripts/`）

- **近 7 日窗口** = 今天-7 至 今天-1（**不含今天**），平台真实口径，已被门禁实测拦截纠正。
- **卡片容器** = `.feedback_list` 且含 `.order_no`（注意 `.feedback` 是整页容器，不是卡片）。
- **申诉按钮** = 卡片内唯一可见 `.appeal_btn`（文案形如「立即申诉(通过率75%)」）。
- **弹窗** = `.el-dialog.appeal-custom-dialog` → `.appeal-dialog-body textarea` + `.dialog-footer`
  （取消/换一个/确定）。**只用平台预填内容，绝不点「换一个」**。
  ★ **Element UI 两字按钮空格坑**：按钮实际渲染文案是「取 消」「确 定」（两字间插空格），
  匹配时必须先 `innerText.replace(/\s+/g,'')` 再比对——直接 `trim() === '确定'` 永远匹配不到
  （2026-10-06 实机弹窗预演抓出，已修）。
- **防重四态**：`prepared → ready_for_confirmation → submitted_once → 点确定 → 权威回读`。
  回读失败：美团=停止整批（防重复提交）；淘宝=跳过该条并由跨日账本兜底。
- **跨日账本** `existingStatusAnyDate(key)`：遍历 `records/<业务日期>/<key>.md`，任何历史日期已终态
  （verified_submitted/blocked/unknown）或已进入 submitted_once 的键，禁止再次提交。这是淘宝
  不重复申诉的唯一护栏（页面不呈现申诉状态）。

## 三·五、★ 判据铁律（2026-10-06 实战沉淀，大同亲自纠正）

1. **页面状态 = 唯一权威，toast 不可信**（大同原话「以后不要看toast」）：Element UI 的
   error toast 可能是假阴性——实测「反馈渠道不存在」toast 弹出的同时申诉实际提交成功了。
   一切成败判定只能依据**卡片是否移出未申诉列表 / 状态计数是否变化**；toast 仅作佐证记录，
   绝不作为 blocked/failed 的判据。
2. **确认后页面被重定向是网站自己的问题**（会跳到「智能斗金」页）：回读自愈 = 检查
   `location.hash` 不含 `evaluationManagement/feedback` 时**重新导航** HOME→负反馈列表→筛选，
   再做权威回读（「重新点开菜单看最稳」）。`verifyAfterConfirm` 已内置。
3. **blocked 是合法终态，不是失败**：同一卡片多次独立尝试后页面状态零变化 ⇒ 该条在金鲨侧
   不可申诉，停止重试、记录证据（尝试次数+回读时间线）即为正确收尾。
   `receipt.ok = (unknown === 0 && !platformFailed)`，blocked 不拉低 ok。
4. **unknown + 卡片仍可申诉 ⇒ 允许重试**（页面证据优先于历史状态）；`prior && prior !== 'unknown'`
   才跳过。
5. **分页采集**：翻页成功需**页码前进 AND 首卡片内容键变化**双条件（防"页码动了内容没换"的
   渲染竞态）；总行数用**物理行口径**——淘宝列表实测含 11 条完全重复条目，139 物理行=平台
   口径，报表如实入表不去重。
6. **bridge 幂等残留**：发送失败会留下脏 marker + `.wechat-messaging/events/<eventKey>/binding.json`；
   Excel 每次重建字节都会变，重试前必须**把 marker 与 event 目录同批归档**（改 `.invalid-*` 后缀），
   否则 `legacy-marker-binding-mismatch` / `event-payload-conflict` 死循环。
7. **发送路线已注册**：桥 registry 已含 `negative-feedback-appeals`（GROUP/file/2 件，授权串
   `user-20261006-negative-feedback-list-appeals`），09:30/12:30 守护流可直发，不再报
   `workflow-not-registered`。

## 四、执行入口（CLI）

```bash
# 只读体检（不点申诉、不写 md、不发消息）：双平台导航门禁 + 候选采集
node scripts/verify_readonly.mjs
# 只读分页采集体检（验证 Excel 明细来源行数 == 声明总数）
node scripts/verify_collect.mjs
# 离线契约自测（107 项，不碰浏览器）
node scripts/test_contracts.mjs

# 09:30 申诉（美团 + 淘宝，真实点击确认）
node scripts/appeal_executor.mjs --execute
# 只读看板（双平台候选一览，不申诉）
node scripts/appeal_executor.mjs --inspect

# 12:30 生成双平台 Excel（金鲨浏览器在线时调用）
node scripts/build_report.mjs
# 12:30 发送（0 条硬闸：当日无任何 md 记录则绝不生成/发送）
node scripts/deliver_batch.mjs --execute
```

## 五、交付物

- 申诉明细 md：`records/negative-feedback-list-appeals/<业务日期>/<key>.md`（每单一条）。
- 汇总 Excel：`outputs/negative-feedback-list-appeals-<YYYYMMDD>/负反馈申诉汇总_美团外卖_<日期>.xlsx`
  （带预览 PNG）。**只产美团一份**——淘宝申诉放弃后 Excel 停产停发（2026-10-06 大同拍板）。
- 发送：一次 `workflow_bridge_windows.py` 调用，单 `--item` 发美团 Excel 到 FEIBING NEO AI数字员工
  （桥 count=1，registry-routing.json override）。

## 六、安全护栏（铁律）

1. **fail-closed**：任何写操作前逐项读回校验（路由/标题/风控/平台tab/时间tab/日期窗口/
   维度门禁/卡片数/卡片日期），任一不符立即抛错，绝不进入写操作。
2. **0 条硬闸**：当日 records 无任何 md ⇒ 不生成 Excel、不发群。
3. **不发假账**：已核验提交却不在页面快照 ⇒ 拒绝生成（防残缺报表）。
4. **隐私**：md 不保存账号/Cookie/手机号/顾客个人信息。
5. **复用**：微信发送沿用既有 bridge，本工作流不新增发送路线或手工选择器。
