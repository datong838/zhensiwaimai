# M01–M11 正式工作流实施方案

2026-10-21，用户已授权开发和测试现有11项；不等待M12–M20。此阶段不启用生产调度、不发真实群、不改正式台账数据。

## 架构与范围

沿用runtime/run_all.py（派班/岗位互斥）→本流薄编排→现有品牌商切店与截图器（9230）→wechat-messaging WindowsAdapter（唯一投递通道）。不复制调度器或发送驱动、不新增常驻进程。项目目录无Git仓库，原有脚本和台账保留，变更文件有开发前备份。

入口 scripts/metrics_rotation_daily.py 提供plan（纯本地、默认）、capture（截图演练）、execute（真实投递须授权引用）。字典为现有metrics_catalog.json；config/workflow.json只允许M01–M11，默认逐项轮转，支持显式指标批次验收。自动轮转须配置start_date；不擅自选择尚在提案中的400×3排班。不同日期/月仍按起始日期连续轮转；发送幂等按店/指标/月。

输入优先品牌商store_pool_brand.json快照，或当月台账店铺池；只纳入营业中，ID唯一、名称非空、快照7日内。群映射取现有确定性map（含店/组织/默认的解析结果），不模糊找群。缺群条目blocked；不因个别店阻塞跳过其他店。plan输出全量数量、待处理、缺群、防重阻断；不触碰浏览器/网关。

## 状态与门禁

每个店/指标/月独占文件锁。先查月度marker、旧日marker与当月台账，再采集；verified/already_verified零重发，attempted/unknown只对账。blocked明确未发才可重试。dry-run不写发送marker。

capture子进程必须有超时；结构化收据必须ok=true、店ID/名称/metric正确、单店作用域、时间验证通过、图片完整未截断、PNG有效；当前run的新路径作为唯一图片来源，禁止glob复用旧图片。M11三张原始截图按顺序无损纵向合成一张，原图保留，一店一指标仍只投一条图。M06互动行为固定近7日，与画像近30日并列说明，不伪称全30日。

投递前落attempted，返回verified后先持久化发送事实再回写Excel；写台账失败继续保留verified，重跑仅修台账不再发送。跨日仍查询同月marker。非零sendAttempts的blocked按unknown处理。子进程超时/异常涉及发送时不得当作安全可重发。每店采集后回读登录、安全、chain复位结构；掉登录/风险停止本批。普通单店无数据/采集失败登记后继续，其余未完成保留断点。

批量状态与每步elapsedMs/pitfalls写receipt.json；以实际状态判完成，unknown、缺群、采集失败不能因进程exit0当成功。只在计划要求全部已verified/already才输出ok=true；capture仅capture_complete，不声称发送成功。只读或测试收据不写daemon当天成功。

## 文件与验证

新增：scripts/metrics_rotation_daily.py、rotation_workflow.py、capture_receipt.mjs、runtime/metrics_rotation_registration.py、runtime/register_metrics_rotation_flow.py、tests/test_rotation_workflow.py、tests/test_registration.py、config/workflow.json、SKILL.md。
维护：deliver_metric.py（月度防重/attempted/锁/台账参数与恢复）、capture_for_metric.mjs（统一收据、子进程超时、finally复位）、lib/cdp.mjs（唯一强域名目标，禁止兜底其他标签）；ledger_ops.py（表头兼容、unknown不记已完成、原子写）；不修改共享发送库或已封印岗位。

测试临时台账/假适配器/本地生成图片，加载tests/isolation_guard，所有真实出站和生产台账写入禁止。覆盖11指标路由、M06/M11时间口径、混店/错作用域/截断/旧图片、无数据、同月跨日防重、unknown/attempted、超时、账本失败后修复、批次恢复、锁争用、部分覆盖统计、跨月轮转、登记幂等与既有配置不变。真实采集仅作为另行明确的只读验收，真实投递不在开发测试内。

正式任务登记为enabled=false/dev_state=pending，登记品牌商usedBy与待验收台账行；不重启daemon。后续群映射/灰度验收完成再启用。

### 批量租约与文档一致性复核

长批次超过岗位锁TTL，因此入口复用runtime岗位锁并在持有期间每20秒续租；按runId+PID复核归属，丢锁后禁止下一次采集和投递。daemon直接子任务只接受父PID与同工作流名都匹配的继承锁，不释放父进程锁。未修改任何封印岗位文件。M01采集器补了点击“评价详情”后的激活态回读；指标字典只更新M01截图范围和M06静态7日例外，不改user_rules原话。生产启用仍待真实灰度，禁止把本轮离线送达模拟当成真实群验收。

## 2026-10-21 真机只采集一轮

用户明确授权正式工作流真机实操且禁止发送。选正式台账首家营业中店，M01–M11各采一次；capture模式不依赖群映射，不能为了只采集填假群。修正原来将缺群前置条件误用于capture的门禁，plan/execute缺群仍blocked。只采集不产生发送marker、不写反馈成功；使用本轮独立runtime目录保留逐项截图/收据。遇可恢复执行器缺陷修复并测试后续跑，仅重试未完成项；登录/风险验证交用户处理，不能将失败冒充验收通过。

### 真机首轮共因诊断

M01初始收据通过（后续视觉复核拒收），后续M02–M11均在switch_shop exit4提前失败，登录探活正常。先让父执行器保留子脚本的白名单FAIL错误码（不落页面原文/URL参数），单独诊断M02，再基于同一页面的DOM/可见性证据修复切换器。首轮所有失败记录保留；未完成项修复后续跑，不重发、不写成功台账。

### 共因已定位：可选绑定手机号提醒遮住切店

只读elementFromPoint证据：店名中心实际命中ant-modal-wrap，正文精确为绑定手机号提醒/为保障您的账号与资产安全，建议绑定手机号/跳过/去绑定。沿用既有装修审计流的同类处理思想，新增lib/known_overlay.mjs，仅允许精确标题+建议绑定手机号+唯一跳过按钮；登录、验证码、安全验证或未知弹窗不关闭。switch_shop切店前调用并确认提醒消失。新增白名单正负测试后再续跑M02–M11，保持单店作用域、时间、截图完整性等硬校验。

### 截图前遮罩复核与M10诊断

首轮M01的“captured”仅表示旧收据校验成功，视觉复核发现绑定提醒覆盖，判为不合格，必须重采。在lib/cdp.mjs统一拦截Page.captureScreenshot，先执行已验证的精确可选提醒处理，未知弹窗或检查失败不得截图；所有采集器自动受约束，不能仅依赖切店前一次检查。测试覆盖检查失败时底层截图零调用。M10时间校验失败时保留子采集器的结构化时间/区域诊断，禁止为通过而放宽时间判据。真实图片中的空值/暂无数据如实标记，不作为数据完整或投递验收。

### M10时间定位修复依据

同店商品页实测唯一ant-radio组的文档y=245.42，原yMin150/yMax240排除了整组。改为当前goods页唯一且选项精确为“今日实时/昨日/近7日/近30日/自定义”的可见radio组定位，回读仍要求近30日且唯一选中；不存在或多组歧义立即失败。不扩大坐标区间碰运气，其他指标保持原逻辑。
