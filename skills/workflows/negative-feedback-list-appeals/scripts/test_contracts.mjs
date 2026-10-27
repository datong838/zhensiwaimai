// 负反馈列表申诉工作流 · 离线自测（不触碰浏览器、不发任何消息）
import assert from 'node:assert/strict';
import path from 'node:path';
import { businessPath } from '../../../../runtime/business_storage.mjs';
import {
  APPEAL_STATUS, PLATFORMS, RANGE_DAYS, RECORDS, STATUS_ORDER, TIME_RANGE,
  businessDate, clean, eligible, parsePassRate, recentRange, shanghaiDay, stableRecordKey,
} from './jinsha.mjs';
import { assertState, candidateSignature } from './page_state.mjs';
import { buildMarkdown, DEFAULT_EXECUTION_PLATFORMS, assertConfirmationAvailable } from './appeal_executor.mjs';
import { assertSnapshot, isCoherentSnapshot, snapshotSignature } from './all_feedback_collector.mjs';
import { buildArgs } from './deliver_batch.mjs';

let tests = 0;
const ok = (cond, name) => { assert.ok(cond, name); tests++; };

/* ---------- 1. 近7日窗口 ---------- */
{
  // 平台实测口径：近7日 = 今天-7 至 今天-1（不含今天）
  assert.deepEqual(recentRange('2026-10-06'), ['2026-09-29', '2026-10-05']);
  assert.equal(RANGE_DAYS, 7);
  // 跨月边界
  assert.deepEqual(recentRange('2026-10-01'), ['2026-09-24', '2026-09-30']);
  // 闰年 2 月（2028-02-29 存在）
  assert.deepEqual(recentRange('2028-03-01'), ['2028-02-23', '2028-02-29']);
  // 窗口必须恰好 7 天且不含当天
  for (const day of ['2026-10-06', '2026-10-01', '2026-03-01', '2028-03-01']) {
    const [s2, e2] = recentRange(day);
    const span = (new Date(`${e2}T00:00:00Z`) - new Date(`${s2}T00:00:00Z`)) / 86400000 + 1;
    assert.equal(span, 7, `window spans 7 days for ${day}`);
    assert.notEqual(e2, day, `window excludes today for ${day}`);
  }
  ok(TIME_RANGE === '近7日', 'time range label');
  ok(APPEAL_STATUS === '未申诉', 'appeal status label');
  ok(businessDate() === shanghaiDay(), 'business date is shanghai today');
  tests += 8;
}

/* ---------- 2. 平台定义 ---------- */
{
  assert.equal(PLATFORMS.length, 2);
  assert.deepEqual(PLATFORMS.map(p => p.key), ['meituan', 'taobao']);
  ok(PLATFORMS.every(p => p.option && !('context' in p)), 'platforms use option only, no context field');
  assert.deepEqual(PLATFORMS.map(p => p.option), ['美团', '淘宝']);
  ok(new Set(PLATFORMS.map(p => p.label)).size === 2, 'labels unique');
  tests += 5;
}

/* ---------- 3. 状态维度顺序（Excel 头部） ---------- */
{
  assert.deepEqual(STATUS_ORDER, ['全部', '未申诉', '申诉中', '申诉成功', '申诉失败']);
  tests += 1;
}

/* ---------- 4. 记录键稳定性 ---------- */
{
  const base = { platform: 'meituan', store: '门店A', date: '2026-10-04', orderNo: '2002329163515998082', category: '餐品有普通异物' };
  assert.equal(stableRecordKey(base), stableRecordKey({ ...base }));
  // 星级/通过率变化不应改变键（同一订单同一问题）
  assert.equal(stableRecordKey(base), stableRecordKey({ ...base, score: 3, passRate: 75 }));
  // 关键字段任一变化 ⇒ 新键
  assert.notEqual(stableRecordKey(base), stableRecordKey({ ...base, platform: 'taobao' }));
  assert.notEqual(stableRecordKey(base), stableRecordKey({ ...base, store: '门店B' }));
  assert.notEqual(stableRecordKey(base), stableRecordKey({ ...base, orderNo: '999' }));
  assert.notEqual(stableRecordKey(base), stableRecordKey({ ...base, category: '有异味/看着不新鲜' }));
  assert.notEqual(stableRecordKey(base), stableRecordKey({ ...base, date: '2026-10-05' }));
  // 跨平台同订单不得撞键
  ok(stableRecordKey(base).length === 12, 'key length 12');
  tests += 8;
}

/* ---------- 5. 通过率解析（.appeal_btn 文案） ---------- */
{
  assert.equal(parsePassRate('立即申诉(通过率75%)'), 75);
  assert.equal(parsePassRate('立即申诉(通过率65%)'), 65);
  assert.equal(parsePassRate('  立即申诉( 通过率 80% )  '), 80);
  assert.equal(parsePassRate('立即申诉'), '');
  assert.equal(parsePassRate(''), '');
  assert.equal(parsePassRate(null), '');
  assert.equal(parsePassRate('已申诉成功(通过率75%)'), 75);
  tests += 7;
}

/* ---------- 6. 候选资格 ---------- */
{
  assert.equal(eligible({ hasAppealBtn: true }), true);
  assert.equal(eligible({ hasAppealBtn: false }), false);
  assert.equal(eligible({}), false);
  tests += 3;
}

/* ---------- 7. 状态门禁：每种破坏都必须被拒 ---------- */
{
  const win = recentRange('2026-10-06');
  const good = {
    url: 'https://data.guoshuyufen.com/#/evaluationManagement/feedback',
    title: '臻肆外卖运营', risk: false,
    context: '美团', platform: '美团', timeTab: '近7日',
    dates: ['2026-09-29', '2026-10-05'], appealFilter: '全部', status: '未申诉',
    statusCounts: { 全部: 54, 未申诉: 9 }, totalNumber: 9,
    cards: [{ store: '门店A', date: '2026-10-04', orderNo: '1', hasAppealBtn: true }],
  };
  assert.equal(assertState(good, { platformKey: 'meituan', status: '未申诉', window: win }), true);

  const breaks = {
    'route-mismatch': { ...good, url: 'https://data.guoshuyufen.com/#/negativeAnalyse' },
    'title-mismatch': { ...good, title: '别的站' },
    'risk-detected': { ...good, risk: true },
    'platform-tab-mismatch': { ...good, platform: '淘宝' },
    'time-tab-mismatch': { ...good, timeTab: '昨日' },
    'date-window-mismatch': { ...good, dates: ['2026-10-04', '2026-10-05'] },
    'appeal-filter-mismatch': { ...good, appealFilter: 'AI申诉' },
    'status-mismatch': { ...good, status: '申诉中' },
    'card-date-out-of-window': { ...good, cards: [{ store: 'A', date: '2026-10-07', orderNo: '1', hasAppealBtn: true }] },
    'card-date-missing': { ...good, cards: [{ store: 'A', date: '', orderNo: '1', hasAppealBtn: true }] },
    'declared-cards-missing': { ...good, cards: [] },
    'card-count-over-total': { ...good, totalNumber: 1, cards: [{ store: 'A', date: '2026-10-04', orderNo: '1' }, { store: 'B', date: '2026-10-04', orderNo: '2' }] },
  };
  for (const [name, bad] of Object.entries(breaks)) {
    assert.throws(() => assertState(bad, { platformKey: 'meituan', status: '未申诉', window: win }), new RegExp('.*'), `should reject: ${name}`);
    tests++;
  }
  // 未知平台 key
  assert.throws(() => assertState(good, { platformKey: 'jd', status: '未申诉', window: win }), /platform-key-invalid/);
  tests++;
  // 淘宝（category 模式）：必须有 category=全部；申诉类型/状态不校验
  const taobao = { ...good, platform: '淘宝', category: '全部' };
  assert.equal(assertState(taobao, { platformKey: 'taobao', window: win }), true);
  tests++;
  // 淘宝 category 不匹配必须被拒
  assert.throws(() => assertState({ ...taobao, category: '食品安全负反馈率' }, { platformKey: 'taobao', window: win }), /feedback-category-mismatch/);
  tests++;
  // 淘宝不校验申诉类型/状态：即便这些字段异常也不应被拒（结构差异的核心）
  assert.equal(assertState({ ...taobao, appealFilter: 'AI申诉', status: '申诉中' }, { platformKey: 'taobao', window: win }), true);
  tests++;
}

/* ---------- 8. 候选签名（只含可申诉条目） ---------- */
{
  const mk = (store, hasAppealBtn = true) => ({ store, date: '2026-10-04', orderNo: store, hasAppealBtn });
  const a = { cards: [mk('A'), mk('B', false)] };
  const b = { cards: [mk('B', false), mk('A')] };
  assert.equal(candidateSignature(a), candidateSignature(b), 'signature order-independent');
  // 无申诉按钮的条目变化不应影响签名（它们不是候选）
  assert.equal(candidateSignature({ cards: [mk('A')] }), candidateSignature({ cards: [mk('A'), mk('Z', false)] }));
  // 空集合签名合法（空态也须稳定）
  assert.equal(candidateSignature({ cards: [] }), '');
  tests += 3;
}

/* ---------- 9. Markdown 契约 ---------- */
{
  const rec = {
    businessDate: '2026-10-06', key: 'abc123', platformLabel: '美团外卖',
    windowStart: '2026-09-29', windowEnd: '2026-10-05', rangeDays: 7,
    store: '毛家湘菜馆(人民广场店）', date: '2026-10-04', orderNo: '2002329163515998082',
    score: 4.4, channel: '订单评价', category: '餐品有普通异物',
    pageState: '美团外卖 / 近7日 / 未申诉；页面共 9 条。',
    preAppeal: '用户声称餐品有普通异物…', dialogText: '用户声称餐品有普通异物…',
    charCount: '111/300', passRate: 75, verification: '已核验', status: 'verified_submitted',
    createdAt: '2026-10-06T09:30:00+08:00', submittedAt: '2026-10-06T09:31:00+08:00',
    verifiedAt: '2026-10-06T09:31:20+08:00',
  };
  const md = buildMarkdown(rec);
  for (const label of ['业务日期：', '记录键：', '平台：', '时间范围：', '门店：', '订单编号：', '问题分类：',
    '平台预申诉语句：', '弹窗申诉内容：', '预估通过率：75%', '页面核验结果：', '记录状态：verified_submitted', '异常原因：无']) {
    ok(md.includes(label), `markdown contains ${label}`);
  }
  assert.ok(md.includes('不保存账号、Cookie、手机号'), 'privacy notice');
  assert.ok(!/cookie\s*[:=]\s*\S/i.test(md), 'no cookie value');
  // 状态解析回读
  assert.equal((md.match(/^- 记录状态：([^\n\r]+)/m) || [])[1], 'verified_submitted');
  // 换行被压平（单行字段）：21 个 `- ` 字段行
  const fields = md.split('\n').filter(l => l.startsWith('- '));
  assert.equal(fields.length, 21, 'field line count fixed at 21');
  // 每个字段都必须单行（不含裸换行）
  assert.ok(fields.every(l => !l.includes('\n')), 'all fields single-line');
  // 异常写入也要落状态
  const bad = buildMarkdown({ ...rec, status: 'unknown', error: '回读失败' });
  assert.ok(bad.includes('记录状态：unknown') && bad.includes('回读失败'));
  tests += 6;
}

/* ---------- 10. 快照一致性（Excel 行数门禁） ---------- */
{
  const state = (total, cards, statusCounts = {}) => ({ totalNumber: total, statusCounts, page: ['1'], cards });
  // isCoherentSnapshot 仅校验页面自洽（total vs cards），状态计数一致性由 assertSnapshot 负责
  assert.equal(isCoherentSnapshot(state(54, [{ a: 1 }])), true);
  assert.equal(isCoherentSnapshot(state(0, [])), true);
  // 声明有条目但卡片为空 ⇒ 不自洽
  assert.equal(isCoherentSnapshot(state(54, [])), false);
  // 卡片多于计数 ⇒ 不自洽
  assert.equal(isCoherentSnapshot(state(1, [{ a: 1 }, { b: 2 }])), false);
  // 非负整数但卡片数为负/异常 ⇒ 不自洽
  assert.equal(isCoherentSnapshot(state(-1, [])), false);
  // 签名对卡片顺序不敏感、对内容敏感
  const s1 = state(2, [{ store: 'A', date: 'd', orderNo: '1', category: 'c', preAppeal: 'p' }]);
  const s2 = state(2, [{ store: 'A', date: 'd', orderNo: '1', category: 'c', preAppeal: 'p' }]);
  assert.equal(snapshotSignature(s1), snapshotSignature(s2));
  const s3 = state(2, [{ store: 'A', date: 'd', orderNo: '1', category: 'c', preAppeal: 'DIFFERENT' }]);
  assert.notEqual(snapshotSignature(s1), snapshotSignature(s3));
  tests += 8;
}

/* ---------- 11. 报表快照门禁 ---------- */
{
  const good = { counts: { 全部: 2 }, total: 2, rows: [{ store: 'A', date: '2026-10-04', orderNo: '1', status: '全部' }, { store: 'B', date: '2026-10-03', orderNo: '2', status: '全部' }] };
  assert.equal(assertSnapshot(good), true);
  // 行数 != 「全部」计数 ⇒ 拒绝
  assert.throws(() => assertSnapshot({ ...good, rows: [good.rows[0]] }), /row-count-mismatch/);
  // total 不符 ⇒ 拒绝
  assert.throws(() => assertSnapshot({ ...good, total: 5 }), /total-mismatch/);
  // 必填字段缺失 ⇒ 拒绝
  assert.throws(() => assertSnapshot({ ...good, rows: [{ ...good.rows[0], store: '' }, good.rows[1]] }), /required-field-missing/);
  // 非「全部」状态混入 ⇒ 拒绝
  assert.throws(() => assertSnapshot({ ...good, rows: [{ ...good.rows[0], status: '未申诉' }, good.rows[1]] }), /status-must-be-all/);
  // 空快照（0 条）本身合法，但由调用方的 0 条硬闸拦截发送
  assert.equal(assertSnapshot({ counts: { 全部: 0 }, total: 0, rows: [] }), true);
  tests += 6;
}

/* ---------- 12. 固定投递器参数（三要素固定，不可漂移；单件美团文件） ---------- */
// 2026-10-06 大同拍板：淘宝申诉先放弃 ⇒ 淘宝 Excel 停产停发，只投递美团一份。
{
  const args = buildArgs({
    items: [
      '/tmp/负反馈申诉汇总_美团外卖_2026-10-06.xlsx',
    ],
  });
  const joined = args.join(' ');
  ok(joined.includes('--workflow-id negative-feedback-appeals'), 'workflow id fixed (bridge registry key)');
  ok(joined.includes('--group 上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'), 'group fixed');
  ok(joined.includes('负反馈申诉汇总_美团外卖_2026-10-06.xlsx'), 'meituan payload item');
  ok(joined.includes('--execute'), 'execute flag');
  assert.ok(!args.includes('--correction-v1'), 'no correction route by default');
  // 不得出现手工文件选择器相关参数
  assert.ok(!/choose|manual|select-file/i.test(joined), 'no manual file picker');
  // ledger 路径固定到本 flow
  assert.equal(args[args.indexOf('--ledger')+1],path.join(businessPath('negative-feedback'),'wechat-attempts'));tests++;
  tests += 6;
}

/* ---------- 13. 记录目录隔离 ---------- */
{
  ok(RECORDS.endsWith('/records/negative-feedback-list-appeals'), 'records dir isolated');
  ok(!RECORDS.includes('meituan-waimai') && !RECORDS.includes('taobao-flash'), 'not reusing other flow records');
  tests += 2;
}



assert.deepEqual(DEFAULT_EXECUTION_PLATFORMS,['meituan']);
assert.doesNotThrow(()=>assertConfirmationAvailable({buttons:['取消','确 定']},'meituan'));
for(const buttons of [['取消','复制'],['确定','确定'],[]])assert.throws(()=>assertConfirmationAvailable({buttons},'taobao'),/submit-control-unavailable/);

const {excludedPlatforms}=await import('./appeal_executor.mjs');
assert.deepEqual(excludedPlatforms(['meituan']).taobao,{execution:'not_requested',submitted:false,reason:'user-20261025-no-taobao-feedback-submit-entry'});
assert.deepEqual(excludedPlatforms(['meituan','taobao']),{});
tests += 7;
// Regression: readback must not issue another business confirmation.
const executorSource=await (await import('node:fs/promises')).readFile(new URL('./appeal_executor.mjs',import.meta.url),'utf8');
const readbackSource=executorSource.slice(executorSource.indexOf('async function verifyAfterConfirm('),executorSource.indexOf('async function processPlatform('));
assert.ok(!readbackSource.includes('.click(')&&!readbackSource.includes('confirmDialog('));
assert.ok(!executorSource.includes("prior && prior !== 'unknown'"));
assert.ok(executorSource.includes("if (prior === 'unknown') receipt.unknown.push(key)"));
tests+=3;
console.log(JSON.stringify({ ok: true, tests, runtimeModelDecisions: 0 }));
