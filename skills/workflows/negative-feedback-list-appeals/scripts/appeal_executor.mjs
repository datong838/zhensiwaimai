// 负反馈列表 · 逐条申诉执行器
//
// 防重四态（同族契约，适配负反馈页 DOM）：
//   prepared → ready_for_confirmation → submitted_once → 点「确定」→ 权威回读
// 权威回读 = 同条目从当前状态页移除 且 该状态页计数减少（美团）；
//          或该卡申诉按钮文案不再以「立即申诉」开头（淘宝，页面无申诉状态维度）。
// 回读失败 ⇒ unknown + （美团）停止批次、（淘宝）跳过该条并由跨日账本防重复。
//
// 跨日账本（existingStatusAnyDate）：淘宝「全部」视图不呈现申诉状态，所有卡片都带
// 「立即申诉」，故必须用历史任意日期的本地记录去重，禁止对同订单重复提交。
import {
  PLATFORMS, RANGE_DAYS, RECORDS, atomicWrite, businessDate, clean, eligible, existingRecordAnyDate,
  excerpt, now, parsePassRate, sleep, stableRecordKey,
} from './jinsha.mjs';
import { assertState, openFilteredPage, readState } from './page_state.mjs';

const TERMINAL = ['verified_submitted', 'unknown', 'blocked'];

const mdField = (label, value) => `- ${label}：${String(value ?? '').replaceAll('\n', ' ').replaceAll('\r', ' ').trim()}`;

export function buildMarkdown(r) {
  return [
    `# ${r.platformLabel || '负反馈'}申诉临时记录`, '',
    mdField('业务日期', r.businessDate),
    mdField('记录键', r.key),
    mdField('平台', r.platformLabel),
    mdField('时间范围', `${r.windowStart} 至 ${r.windowEnd}（近${r.rangeDays}日）`),
    mdField('门店', r.store),
    mdField('评价日期', r.date),
    mdField('订单编号', r.orderNo),
    mdField('星级', r.score ? `${r.score} 星` : '未读取'),
    mdField('反馈渠道', r.channel || '未读取'),
    mdField('问题分类', r.category || '未读取'),
    mdField('页面状态', r.pageState),
    mdField('平台预申诉语句', r.preAppeal || '未读取'),
    mdField('弹窗申诉内容', r.dialogText || '未打开申诉弹窗；不读取、不生成。'),
    mdField('字符计数', r.charCount || '未读取'),
    mdField('预估通过率', r.passRate === '' || r.passRate === undefined ? '未读取' : `${r.passRate}%`),
    mdField('页面核验结果', r.verification),
    mdField('记录状态', r.status),
    mdField('创建时间', r.createdAt),
    mdField('提交时间', r.submittedAt || '不适用'),
    mdField('核验时间', r.verifiedAt || '不适用'),
    mdField('异常原因', r.error || '无'),
    '',
    '> 记录键由页面可见的平台、门店、评价日期、订单编号与问题分类生成稳定摘要；',
    '> 本文件不保存账号、Cookie、手机号或顾客个人信息。申诉内容以平台预申诉语句为准，未做任何改写或扩写。',
    '',
  ].join('\n');
}

const recordFile = (business, key) => `${RECORDS}/${business}/${key}.md`;

// Only bound older records are deferred. Current/undated unknown still stops.
export function recordPriorOutcome(record, key, target, platformKey, business, receipt) {
  if (!record) return 'new';
  const prior = record.status;
  const historical = prior === 'unknown' && record.key === key
    && /^\d{4}-\d{2}-\d{2}$/.test(record.businessDate || '')
    && record.businessDate < business && /^[a-f0-9]{64}$/.test(record.sourceSha256 || '');
  if (historical) {
    receipt.historicalUnknown.push({ key, state: 'unknown', businessDate: record.businessDate,
      sourcePath: record.sourcePath, sourceSha256: record.sourceSha256, readOnly: true });
  } else if (prior === 'unknown') receipt.unknown.push(key);
  else if (prior === 'verified_submitted') receipt.verified_submitted.push(key);
  else if (prior === 'blocked') receipt.blocked.push(key);
  else receipt.skipped.push(key);
  receipt.platforms[platformKey].candidates.push({ key, store: target.store, outcome: prior,
    ...(historical ? { historicalDeferred: true } : {}) });
  return prior === 'unknown' && !historical ? 'stop' : 'continue';
}

/** 定位目标卡片内的唯一可见 .appeal_btn 并点击（不按索引、不按坐标）。 */
export async function clickAppeal(cdp, target) {
  return cdp.eval(`(()=>{
    const t = ${JSON.stringify({ store: target.store, date: target.date, orderNo: target.orderNo })};
    const cards = [...document.querySelectorAll('.feedback_list')].filter(c => c.offsetParent !== null && c.querySelector('.order_no'));
    const matches = cards.filter(c => {
      const text = c.innerText || '';
      const no = (c.querySelector('.order_no')?.innerText || '').replace(/^订单编号[:：]?/, '').trim();
      return (c.querySelector('.info_name')?.innerText || '').trim() === t.store
        && text.includes(t.date) && no === t.orderNo;
    });
    if (matches.length !== 1) throw Error('feedback-card-node-count:' + matches.length);
    const btns = [...matches[0].querySelectorAll('.appeal_btn')].filter(b => b.offsetParent !== null);
    if (btns.length !== 1) throw Error('feedback-appeal-button-count:' + btns.length);
    btns[0].click();
    return true;
  })()`);
}

/** 读取申诉弹窗：必须等文本连续两次一致（避免刚打开的空白被当成无内容）。 */
export async function readStableDialog(cdp, { attempts = 24, intervalMs = 800, pause = sleep } = {}) {
  let previous = '', stable = 0, last = null;
  for (let attempt = 0; attempt < attempts; attempt++) {
    last = await cdp.eval(`(()=>{
      const dlg = [...document.querySelectorAll('.appeal-custom-dialog')].filter(d => d.offsetParent !== null)[0];
      if (!dlg) return null;
      const T = v => String(v ?? '').replace(/\\s+/g, ' ').trim();
      const ta = dlg.querySelector('.appeal-dialog-body textarea, .el-textarea__inner');
      return {
        open: true,
        text: T(ta && ('value' in ta ? ta.value : ta.innerText)),
        count: T(dlg.querySelector('.el-input__count')?.innerText),
        store: T(dlg.innerText.match(/店铺名称[:：]?\\s*([^\\n]+)/)?.[1]),
        order: T(dlg.innerText.match(/订单编号[:：]?\\s*([^\\n]+)/)?.[1]),
        buttons: [...dlg.querySelectorAll('.dialog-footer button, .dialog-footer .el-button')]
          .filter(b => b.offsetParent !== null).map(b => T(b.innerText)),
      };
    })()`);
    if (last) {
      const text = clean(last.text);
      stable = text && text === previous ? stable + 1 : 0;
      previous = text;
      if (stable >= 1) return { ...last, text };
    }
    await pause(intervalMs);
  }
  if (!last) return null;
  if (clean(last.text)) throw Error('feedback-dialog-text-not-stable');
  throw Error('feedback-dialog-text-empty');
}

/** 点击「确定」—— 必须唯一可见。
 *  ★ Element UI 会在两字按钮文案中插空格（实际渲染为「确 定」），必须先去空白再比对，
 *    否则真实点击时永远匹配不到（2026-10-06 实机 verify_dialog 抓出）。 */
export async function confirmDialog(cdp) {
  const clicked = await cdp.eval(`(()=>{
    const dlg = [...document.querySelectorAll('.appeal-custom-dialog')].filter(d => d.offsetParent !== null)[0];
    if (!dlg) throw Error('feedback-dialog-missing');
    const btns = [...dlg.querySelectorAll('.dialog-footer button, .dialog-footer .el-button')]
      .filter(b => b.offsetParent !== null && String(b.innerText).replace(/\\s+/g, '') === '确定');
    if (btns.length !== 1) throw Error('feedback-confirm-button-count:' + btns.length);
    btns[0].click();
    return true;
  })()`);
  if (clicked !== true) throw Error('feedback-confirm-click-failed');
  // 点击后监听 toast —— ⚠ 2026-10-06 大同实证：toast 可能误报（「反馈渠道不存在」出现但申诉
  // 实际成功），toast 一律只作参考信息入档，绝不作为 blocked/失败判定。页面状态才是唯一权威。
  for (let i = 0; i < 4; i++) {
    await sleep(700);
    try {
      const toast = await cdp.eval(`(()=>{const t=[...document.querySelectorAll('.el-message--error')].filter(x=>x.offsetParent!==null);return t.length?(t[0].innerText||'').trim():''})()`);
      if (toast) return { toast };
    } catch { /* 页面跳转中 */ }
  }
  return { toast: '' };
}

/** 翻到下一页；无下一页返回 false。 */
async function advancePage(cdp, previousPage) {
  const clicked = await cdp.eval(`(()=>{const n=[...document.querySelectorAll('.el-pagination .btn-next')].filter(x=>x.offsetParent!==null);if(n.length!==1||n[0].classList.contains('disabled')||n[0].getAttribute('disabled')!==null)return false;n[0].click();return true})()`);
  if (!clicked) return false;
  for (let attempt = 0; attempt < 20; attempt++) {
    await sleep(400);
    const state = await readState(cdp);
    const page = state.pageActive;
    if (page === previousPage + 1 && state.cards.length > 0) return true;
  }
  return false;
}

/** 确认后权威回读：美团=卡片移除且计数减少；淘宝=按钮文案不再以「立即申诉」开头或卡片消失。
 *  淘宝回读窗口取 10 次（8s）而非 24 次：淘宝结果本就由跨日账本兜底（submitted_once 永久跳过），
 *  且 139 条若每条都走满 24×800ms 会把批次拖出 daemon 超时（2026-10-06 加固）。 */
async function verifyAfterConfirm(cdp, target, beforeTotal, gate, mode) {
  let after = null;
  const attempts = mode === 'status' ? 24 : 10;
  // 提交后只读回查；未知结果不能再次点击确认。
  for (let attempt = 0; attempt < attempts; attempt++) {
    await sleep(800);
    try {
      // ⚠ 不看 toast（2026-10-06 实证 toast 会误报「反馈渠道不存在」但申诉实际成功）。
      // 平台拒绝后常把页面重定向走 —— 每轮先核对当前路由，不在列表页就导航回来再读，
      // 这样「确认已受理但页面跳走」不会被误判为 unknown。
      const here = await cdp.eval(`(()=>({hash:location.hash||'',title:document.title}))()`);
      if (!String(here.hash || '').includes('evaluationManagement/feedback')) {
        const { openFilteredPage } = await import('./page_state.mjs');
        await openFilteredPage(cdp, gate);
      }
      after = await readState(cdp);
      if (mode === 'status') {
        assertState(after, gate);
        const stillThere = after.cards.some(c => c.store === target.store && c.date === target.date && c.orderNo === target.orderNo);
        if (!stillThere && after.totalNumber < beforeTotal) return { verified: true, after };
      } else {
        const card = after.cards.find(c => c.store === target.store && c.date === target.date && c.orderNo === target.orderNo);
        if (!card) return { verified: true, after };
        if (!(clean(card.appealBtnText) || '').startsWith('立即申诉')) return { verified: true, after };
      }
    } catch { /* 页面异步重排，继续等 */ }
  }
  return { verified: false, after };
}

async function processPlatform(cdp, platformKey, window, receipt) {
  const spec = PLATFORMS.find(p => p.key === platformKey);
  const business = businessDate();
  const mode = spec.mode;
  const resolvedStatus = mode === 'status' ? spec.appealStatus : undefined;
  const gate = { platformKey, status: resolvedStatus, window };
  await openFilteredPage(cdp, { platformKey, status: resolvedStatus, window });
  const [windowStart, windowEnd] = window;

  const base = {
    businessDate: business, platformLabel: spec.label, windowStart, windowEnd, rangeDays: RANGE_DAYS,
  };

  receipt.platforms[platformKey] = { label: spec.label, total: 0, statusCounts: {}, categoryCounts: [], candidates: [] };

  const doneThisRun = new Set();
  let page = 1;
  while (true) {
    const state = await readState(cdp);
    assertState(state, gate);
    if (page === 1) {
      receipt.platforms[platformKey].total = state.totalNumber;
      receipt.platforms[platformKey].statusCounts = state.statusCounts || {};
      receipt.platforms[platformKey].categoryCounts = state.categoryCounts || {};
    }
    const dim = mode === 'status' ? `申诉类型=全部 / 状态=${resolvedStatus}` : `分类=${spec.category}`;
    const pageStateNow = `${spec.label} / 近7日 / ${dim}；页面共 ${state.totalNumber} 条（第 ${page} 页）。`;

    for (const initial of state.cards.filter(eligible)) {
      const target = state.cards.find(c =>
        c.store === initial.store && c.date === initial.date && c.orderNo === initial.orderNo);
      if (!target || !eligible(target)) {
        receipt.warnings.push(`candidate-no-longer-appealing:${platformKey}:${initial.store}`);
        continue;
      }
      const key = stableRecordKey({ platform: platformKey, store: target.store, date: target.date, orderNo: target.orderNo, category: target.category });
      if (doneThisRun.has(key)) continue;

      // 既有记录只读复用；unknown保持未知，禁止自动再次提交。
      const prior = await existingRecordAnyDate(key);
      const disposition = recordPriorOutcome(prior, key, target, platformKey, business, receipt);
      if (disposition !== 'new') {
        doneThisRun.add(key);
        if (disposition === 'stop') break;
        continue;
      }

      const record = {
        ...base, key, store: target.store, date: target.date, orderNo: target.orderNo, score: target.score,
        channel: target.channel, category: target.category, pageState: pageStateNow,
        preAppeal: target.preAppeal, passRate: target.passRate, createdAt: now(),
      };

      // ① 首次提交前落prepared；既有未知记录不会进入此路径。
      const retryNote = '已创建临时记录，尚未打开申诉弹窗。';
      await atomicWrite(recordFile(business, key), buildMarkdown({ ...record, verification: retryNote, status: 'prepared' }));
      await clickAppeal(cdp, target);
      const dialog = await readStableDialog(cdp);
      if (!dialog) {
        await atomicWrite(recordFile(business, key), buildMarkdown({ ...record, verification: '点击「立即申诉」后弹窗未出现，条目可能已被平台处理。', status: 'blocked', error: '申诉弹窗未打开；未点击「确定」。' }));
        receipt.blocked.push(key);
        receipt.platforms[platformKey].candidates.push({ key, store: target.store, outcome: 'blocked' });
        doneThisRun.add(key);
        continue;
      }
      // 弹窗订单号必须与目标一致，防止张冠李戴
      if (dialog.order && clean(dialog.order) !== target.orderNo) {
        await atomicWrite(recordFile(business, key), buildMarkdown({ ...record, dialogText: dialog.text, charCount: dialog.count, verification: '弹窗订单编号与目标条目不一致。', status: 'blocked', error: `弹窗订单号不符：${dialog.order}` }));
        receipt.blocked.push(key);
        receipt.platforms[platformKey].candidates.push({ key, store: target.store, outcome: 'blocked' });
        doneThisRun.add(key);
        continue;
      }

      assertConfirmationAvailable(dialog, platformKey);

      // ② 弹窗内容稳定后落 ready
      await atomicWrite(recordFile(business, key), buildMarkdown({
        ...record, dialogText: dialog.text, charCount: dialog.count,
        verification: '弹窗申诉内容已连续两次稳定读取；条目归属（订单编号）已复核；未点击「换一个」，内容以平台预申诉语句为准。',
        status: 'ready_for_confirmation',
      }));

      // ③ 落 submitted_once 之后才允许点「确定」
      const beforeTotal = state.totalNumber, submittedAt = now();
      await atomicWrite(recordFile(business, key), buildMarkdown({
        ...record, dialogText: dialog.text, charCount: dialog.count,
        verification: '确认前门禁已通过；即将执行唯一一次「确定」。', status: 'submitted_once', submittedAt,
      }));
      const confirmResult = await confirmDialog(cdp);

      // ④ 权威回读
      const { verified, after } = await verifyAfterConfirm(cdp, target, beforeTotal, gate, mode);
      const verifiedAt = now();
      if (!verified) {
        const toastNote = confirmResult?.toast ? `（提交后页面出现提示「${confirmResult.toast}」，仅作参考——toast 可能误报，以页面状态为准。）` : '';
        const note = mode === 'status'
          ? `确认后未能以「同条目移除且该状态计数减少」完成权威回读。${toastNote}`
          : `确认后页面未呈现明确状态变更（淘宝列表无申诉状态维度）；按钮仍显示「立即申诉」。${toastNote}`;
        await atomicWrite(recordFile(business, key), buildMarkdown({
          ...record, dialogText: dialog.text, charCount: dialog.count,
          pageState: `${pageStateNow} 确认前 ${beforeTotal} 条，确认后 ${after ? after.totalNumber : '未读取'} 条。`,
          verification: note,
          status: mode === 'status' ? 'unknown' : 'submitted_once',
          submittedAt, verifiedAt, error: mode === 'status' ? '提交结果未知；按防重规则停止批次，不重试。' : '结果未由 UI 确认；跨日账本已记录，禁止重复提交。',
        }));
        if (mode === 'status') {
          receipt.unknown.push(key);
          receipt.platforms[platformKey].candidates.push({ key, store: target.store, outcome: 'unknown' });
          doneThisRun.add(key);
          break; // 美团：结果未知 ⇒ 立即停止，防重复提交
        } else {
          receipt.skipped.push(key); // 淘宝：跳过该条，继续后续，账本兜底
          receipt.platforms[platformKey].candidates.push({ key, store: target.store, outcome: 'submitted_once' });
          doneThisRun.add(key);
          continue;
        }
      }
      await atomicWrite(recordFile(business, key), buildMarkdown({
        ...record, dialogText: dialog.text, charCount: dialog.count,
        pageState: `${pageStateNow} 确认前 ${beforeTotal} 条，确认后 ${after.totalNumber} 条。`,
        verification: mode === 'status'
          ? '同条目已从当前状态列表移除，且该状态计数同步减少。'
          : '该卡申诉按钮文案已不再以「立即申诉」开头（或卡片已从列表移除），判定为已受理。',
        status: 'verified_submitted', submittedAt, verifiedAt,
      }));
      receipt.verified_submitted.push(key);
      receipt.platforms[platformKey].candidates.push({ key, store: target.store, outcome: 'verified_submitted' });
      doneThisRun.add(key);
    }

    // 美团：结果未知已 break；其余情况翻页继续
    if (receipt.unknown.length) break;
    const more = await advancePage(cdp, page);
    if (!more) break;
    page += 1;
  }
  return receipt;
}

// User decision 2026-10-25: Taobao has no submit entry; reports still include both platforms.
export const DEFAULT_EXECUTION_PLATFORMS = ['meituan'];
export function excludedPlatforms(platforms) {
  return platforms.includes('taobao') ? {} : {taobao: {execution: 'not_requested', submitted: false, reason: 'user-20261025-no-taobao-feedback-submit-entry'}};
}
export function assertConfirmationAvailable(dialog, platform) {
  if ((dialog?.buttons || []).filter(text => clean(text).replace(/\s+/g, '') === '确定').length !== 1)
    throw Error(`feedback-submit-control-unavailable:${platform}`);
}
export async function execute({ platforms = DEFAULT_EXECUTION_PLATFORMS, window } = {}) {
  const { Cdp, navigate, HOME, recentRange } = await import('./jinsha.mjs');
  const win = window || recentRange();
  const receipt = {
    ok: false, businessDate: businessDate(), window: win, endpoint: 'http://127.0.0.1:9232',
    verified_submitted: [], skipped: [], blocked: [], unknown: [], historicalUnknown: [], warnings: [], platforms: excludedPlatforms(platforms),
    runtimeModelDecisions: 0, startedAt: now(),
  };
  const cdp = await Cdp.open();
  let platformFailed = false;
  try {
    for (const platformKey of platforms) {
      try {
        await processPlatform(cdp, platformKey, win, receipt);
      } catch (error) {
        platformFailed = true;
        receipt.warnings.push(`platform-failed:${platformKey}:${String(error.message || error)}`);
        // 平台级失败不吞掉：记录后继续下一个平台；任一平台失败 ⇒ 整批不算 ok（fail-closed）
      }
    }
    // blocked = 有证据的合法终态（如平台不支持该条申诉），不算失败；
    // unknown 与平台级失败才算（fail-closed：结果未知必须人工/看护介入）。
    receipt.ok = receipt.unknown.length === 0 && !platformFailed;
    receipt.finishedAt = now();
    return receipt;
  } catch (error) {
    receipt.error = String(error.message || error);
    receipt.finishedAt = now();
    return receipt;
  } finally {
    try { await navigate(cdp, HOME, 1200); } catch { /* 收尾失败不覆盖主结果 */ }
    cdp.close();
  }
}

export async function inspect() {
  const { Cdp, navigate, HOME, recentRange } = await import('./jinsha.mjs');
  const win = recentRange();
  const cdp = await Cdp.open();
  const out = { ok: true, businessDate: businessDate(), window: win, platforms: {}, runtimeModelDecisions: 0 };
  try {
    for (const spec of PLATFORMS) {
      const resolvedStatus = spec.mode === 'status' ? spec.appealStatus : undefined;
      const state = await openFilteredPage(cdp, { platformKey: spec.key, status: resolvedStatus, window: win });
      out.platforms[spec.key] = {
        label: spec.label, mode: spec.mode, total: state.totalNumber,
        statusCounts: state.statusCounts, categoryCounts: state.categoryCounts,
        candidates: state.cards.filter(eligible).map(c => ({
          store: c.store, date: c.date, orderNo: c.orderNo, category: c.category, passRate: c.passRate,
        })),
      };
    }
    return out;
  } finally {
    try { await navigate(cdp, HOME, 1200); } catch { /* noop */ }
    cdp.close();
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const mode = process.argv[2];
  // --platforms meituan / taobao（逗号分隔）可选；缺省双平台
  const pFlag = process.argv.indexOf('--platforms');
  const only = pFlag > -1 ? process.argv[pFlag + 1]?.split(',').filter(Boolean) : undefined;
  if (mode === '--execute') {
    execute({ platforms: only }).then(r => { console.log(JSON.stringify(r)); process.exitCode = r.ok ? 0 : 1; })
      .catch(e => { console.error(JSON.stringify({ ok: false, reason: String(e.message || e) })); process.exitCode = 1; });
  } else if (mode === '--inspect') {
    inspect().then(r => console.log(JSON.stringify(r)))
      .catch(e => { console.error(String(e.message || e)); process.exitCode = 1; });
  } else {
    console.error('usage: appeal_executor.mjs --execute|--inspect');
    process.exitCode = 1;
  }
}
