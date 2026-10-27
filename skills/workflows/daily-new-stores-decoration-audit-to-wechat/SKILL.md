---
name: daily-new-stores-decoration-audit-to-wechat
description: 读取当天完整的新店机器收据，仅对淘宝新店逐店核验门店装修四项配置（顶部招牌/店内海报/门店头像/店内橱窗），缺项向指定群提醒。
---

# 淘宝新店装修缺项巡检与提醒

本 Skill 是 `daily-new-stores-activity-audit-to-wechat`（新店活动审计）的**姊妹流**，2026-10-12 由大同指定开发：流程骨架完全对齐活动审计流，检查内容换成「门店装修」——逐店进入门店装修页，打开基础模版中**已应用**的模版，检查右侧组件列表中「顶部招牌」「店内海报」两个组件是否带「已配置」徽标，缺项时向「上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰」发送提醒。执行前阅读统一 [wechat-messaging](../../wechat-messaging/SKILL.md) 的输入/恢复合同。

## 运行入口

```sh
# 每日全量巡检（无当天完整收据时自动先跑一次开业流的 --collect-only 刷新名单）
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python \
  /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-new-stores-decoration-audit-to-wechat/scripts/decoration_daily.py --execute

# 单店只读采集（不发送）
/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python \
  /Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-new-stores-decoration-audit-to-wechat/scripts/decoration_workflow.py --shop-name <完整店名>
# 单店按完整收据发送缺项提醒（加 --execute）
```

## 两项装修配置

淘宝品牌商 `taobao-brand:9230` 的门店装修页通过 `scripts/decoration_daily.py` 读取当天完整的新店机器收据，仅对其中淘宝新店逐店核验；若当天无完整收据，先运行开业流的 `workflow.py --collect-only` 一次，只读刷新新店名单，不发送开业天数通知。`scripts/decoration_workflow.py --shop-name <完整店名>` 可单店只读采集，加 `--execute` 才允许按完整收据向业务群发送缺项提醒。

检查路径（2026-10-12 现场确认）：选店进入 shop 域 → 左侧菜单「门店装修」→ 基础模版 tab → 点**已应用**模版的「编辑此模版」→ 右侧组件列表读四张卡片（顶部招牌/店内海报/门店头像/店内橱窗）是否有「已配置」徽标。仅这四项，其余 8 个组件不检查不报告。多项缺时报「店铺装修缺失：A、B」。

### 2026-10-12 晚判据纠错事故（v1→v2，大同目视纠错触发）

首跑（20:41）发出的 4 条提醒**内容有误**：v1 判据「找文本=已配置」遇到「已配置」徽标实为 svg 图片（DOM 无文本）⇒ 全部误报 missing。大同目视发现重庆鸡公煲店内海报实为已配置 ⇒ 全链路取证（DECOR_DUMP dump DOM + 面板截图 + 选中态实验）定案判据 v2。**误发清单**（均报「顶部招牌、店内海报」，实际）：
- 虬师傅·沙县小吃(汇海广场店)：实际四项全配置（无缺失，**不应发**）
- 甬潮·宁波小市(静安大融城店)：实际仅缺「店内橱窗」
- 重庆鸡公煲·特色纸包鱼烤鱼(赣职理工店)：实际仅缺「顶部招牌」（大同目视与 v2 判据一致）
- 甬潮·宁波小市(新邻店)：实际仅缺「店内橱窗」
处置：4 个旧 marker 保留原文存证（sha 不符时 `same-event-payload-conflict` 挡自动重发）；更正消息待大同拍板后人工单条发送。

### 2026-10-12 现场校准记录（decoration_collector.mjs 实证）

1. **iframe**：装修页内容（模版区/编辑页/组件面板）全部在 `r.ele.me/melody-decorate-pc` iframe 内，主 frame 只有左侧菜单与顶部。所有 locator 操作必须落在该 frame 上（`page.frames().find(f => f.url().includes('melody-decorate-pc'))`）。
2. **菜单两级**：左侧「门店管理」是折叠父菜单，必须先点开才能看到并点击「门店装修」子菜单。
3. **升级推广弹窗**：进装修页会弹「门店装修升级啦！」模态（iframe 内 `.index_close__V-lf9` X 按钮），不关会遮挡模版区。
4. **按钮形态**：已应用模版卡上的按钮实际文本是「已应用，编辑此模板」（`button.cook-deco-themes-btn`）；视觉 click 会超时（遮挡/重渲染），须 `dispatchEvent('click')` JS 级点击。
5. **双状态**：iframe 可能残留 `template-config`（编辑页）状态（上次运行/探针留下），此时直接读组件面板，不再点「编辑此模板」。
6. **模版别名**：行业通用模版第一个组件叫「顶部招牌」，匠心品质模版叫「门店招牌」（语义同为店招）；判据按别名匹配。该模版无此组件时按 `missing`（未配置）处理，fail-closed 向报警方向。
7. **chain home 默认店坑**：reset 后 chain 页顶部店名恰为目标店时，选店逻辑会跳过搜索但 URL 仍在 chain 页（非 `/app/shop/{id}/`）⇒ 超时。跳过搜索的前提是「已在目标店的 shop 域页面」。
8. **判据 v2（2026-10-12 晚大同纠错后重写）**：「已配置」徽标是 44×20 橙色 svg **图片**（`img[class*=moduleIcon]`），DOM 内无任何文本 ⇒ 旧版「文本=已配置」扫描**必然全报 missing，已造成 4 条误发**。「去配置」按钮在未配置卡与已配置选中卡都会出现，**不能作判据**；「新组件」标签（`img[class*=newTag]`）= 未配置。最终判据：卡内存在 `moduleIcon` 图 ⇒ configured，否则 missing。该判据抽成 `readComponentBadges()` 纯函数（浏览器上下文执行），生产与离线对照共用同一份逻辑。
9. **采集器必须显式退出（2026-10-12 晚根因）**：为不杀 9230 岗位，采集器严禁 `browser.close()`，但 CDP WebSocket 句柄会让 node 事件循环非空 ⇒ **进程永不自行退出**，上层 `subprocess(timeout=120)` 会把「已成功落盘的采集」掐成超时 unknown（当日 19:46/19:53 两轮均为此形状：collection.json 已写、进程仍挂着）。收尾统一走 `flushExit(code, payload)`（write 回调后 `process.exit`），上层 timeout 同步提到 300s。
10. **正负对照（2026-10-12 晚 v2，`tests/badge_offline_test.mjs`）**：8/8 PASS——P1 图标=configured / P2 别名「门店招牌」/ P3 已配置选中卡（图标+按钮并存）仍 configured / N1 只有按钮=missing / N2 新组件标签=missing / N3 无此组件=missing / N4 跨卡隔离 / N5 无关 img 不触发。模拟 DOM class 名按真机形态复刻。
11. **检查口径（2026-10-12 晚大同扩充）**：检查 4 项——顶部招牌（别名门店招牌）、店内海报、**门店头像**、**店内橱窗**，其余 8 个组件不检查。workflow.py 与 collector.mjs 的 COMPONENTS 必须同步（两边不一致会被 `decoration-components-incomplete` 拒收，这是故意的防漂移闸）。
12. **现场取证钩子**：`DECOR_DUMP_PATH=<file>` 环境变量开启时，采集器把组件卡真实 DOM + 伪元素 content + 徽标图 src 落盘，用于徽标形态争议时的定性（本流判据 v2 即由此取证得出）。

## 发送制动闸（默认放行 / 一键制动）

- `deliver()` 最前面是制动闸：**默认放行**（与其它流水线一致的日常自动发送）；只有存在制动文件 `.runtime/decoration/SEND_DISARMED.json` 时才 `blocked/send-disarmed`、`sendAttempts=0`、零外发。
- 操作：`python scripts/decoration_workflow.py --disarm`（制动）；`--arm`（解除制动）；`--arm-status`（查询）。
- 2026-10-12 晚校准：首版做成「默认关闭、需每日 arm」，会让日常调度每天被闸挡成 `blocked/unknown` ⇒ 每日告警噪音，故反转语义。
- **开发/验证期**的正确用法：先 `--disarm`，再随意跑真机验证（采集/校验/消息照常产出，绝不会外发）；验证完毕 `--arm` 解除。
- 大同 2026-10-12 指示：新流先开发好、真机实操验证好，**到发微信的时候先提醒他**（首跑 20:37 已由其确认后发送）。

## 与开业流/活动审计流的关系与数据复用

- 本流**不重新采集**新店名单：直接读开业流 `daily-new-stores-opening-to-wechat/scripts/workflow.py` 产出的当天新店机器收据（跨目录复用其 collection 结果），筛选口径与活动审计流完全一致（淘宝渠道、开业 ≤3 天）。
- 与活动审计流共用同一套选店/弹窗消解/复位原语（`dismissBindModal`、`shop-not-found/shop-not-operating/shop-search-timeout` skipped 语义、`reset_chain_seed` 收尾），互不替代。
- **deep-link `/app/shop/{id}/decorate` 会被 302 到 /login（2026-10-12 实测）**，必须像活动流一样从 chain 数据中心搜索选店、SPA 内导航进入。

## 装修提醒去重台账（自包含）

装修提醒「同一事件最多发一次」的 canonical ledger 位于**本技能目录内** `.runtime/decoration/events/`。同一业务日同一店铺的装修提醒事件已 `verified` 时再次调用返回 `already_verified`、新增发送 0 次。该目录缺失时 `deliver()` 返回 `blocked`（reason: canonical-decoration-ledger-unavailable）。

## 完成与停止

- 每日入口只使用同业务日完整的新店收据；无收据、淘宝品牌商未登录或目标歧义时为 `unknown`、零发送。
- 页面登录失效、验证码、账号风险、门店身份或清单状态歧义、名称持续变化、字段缺失：保留阻断，不推断无店、不发送。
- Windows 网关或目标群预检失败：保留当日记录与零发送事实；发送已 `attempted`、`unknown` 或次数不明时，保留原事件并只读对账，绝不改事件、切通道或重复发送。
- 共享微信技能的发送逻辑、策略、依赖摘要及防重账本不能通过修改 Markdown 放行。若需修复，先更新阶段方案，最小改动并通过针对性自测，再由其受控维护入口处理。

## 自愈闭环（2026-10-12 晚大同批准的下波次 #1）

`.runtime/decoration/watchlist.json` 跟踪「已提醒未配置」的店，`decoration_daily.py` 每次巡检（含 dry）后增量维护：

- **入表/刷新**：本次有缺失 ⇒ upsert（记录 lastSeenMissingDay / lastMissing / lastSeenStatus）；`state=alerted` 仅当本次 `verified/already_verified`（或表内已 alerted），否则 `pending-alert` 且 `firstAlertDay=None`（没真发过不算提醒日）。
- **康复**：四项全 configured ⇒ 移出表并记 `healed`（自愈闭环的康复侧）。
- **升级登记**：`alerted` 且距 `firstAlertDay` ≥ `ESCALATION_AFTER_DAYS`(3) 天仍未配 ⇒ `state=escalation-due` 并进 summary，**当前不接任何外发**，升级提醒须大同拍板后再开发。
- **skipped/unknown 店不动表**（避免用数据缺口污染跟踪结论）。
- 单测 5/5（新增 alerted / 未发 pending-alert / 康复 healed / 超期 escalation-due / skipped 不动表）；真机 dry 联动通过：updated 3 家、零外发。
- 初始化依据：2026-10-12 更正事件（correction，verified）已向群内告知缺失的 3 家，`alertRef` 记录该事件可追溯。

## 2026-10-24 夜间选店修正（覆盖旧店名span进入描述）
搜索有防抖，旧完整店铺树也可能已有目标；必须等可见结果均匹配本次搜索，再点击唯一店名的可见容器，不对被tooltipMask覆盖的span派发事件。头部店名切换不代表URL已切换；必要时点击原商家首页，再核对目标shop ID和店名。原采集器老张→山城跨店真实只读通过；不保存装修设置。旧已发/unknown提醒仍不重发。参见夜间遗留问题收口方案。

## 2026-10-27用户明确的查无店铺完成方式

当日完整新店来源中的淘宝店，在原品牌商主账号返回明确“未搜索到店铺”时，原daily入口发送本流查无店铺提示，包含完整店名及原开业天数；记录固定“店铺在主账号查不到未能检查”。提示经原队列真实verified/already_verified后可作为本任务成功结束；不声称实际检查了活动或装修。搜索超时、岗位忙、登录失败不转换为查无店铺；unknown不重发。原普通缺项逻辑、制动、授权与防重保留。
