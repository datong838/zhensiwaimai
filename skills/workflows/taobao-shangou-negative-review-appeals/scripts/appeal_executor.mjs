#!/usr/bin/env node
// taobao-shangou-negative-review-appeals 标准工作流 · 金鲨岗位 · 自动差评申诉执行器（淘宝闪购）
//
// 归属：金鲨岗位（商家后台 data.guoshuyufen.com 的「差评列表」页，平台切到「淘宝闪购」）。
// 模式：监理-车间主任-岗位-工作流。本文件是金鲨岗位的自包含工作流组件。
// 血缘：2026-10-22 由 meituan-waimai-negative-review-appeals 派生（同一后台换平台 tab，契约与选择器同源）。
// 与美团版实测差异（2026-10-22 现场勘察，非推演）：
//   ① 平台 radio value=2（美团 1）、渠道上下文 .cutli='淘宝'；弹窗 .representations / .type_txt .txt /
//      .sure_btn 与美团完全一致，故 stableModal、confirmOnce 逻辑零改动；
//   ② 「立即申诉」按钮常在视口外（200 条/页，第 7 条已在 y≈3331，视口高 617），JS click 静默失效、
//      elementFromPoint 打空 ⇒ 必须 scrollIntoView 后走 CDP 真实鼠标事件（Input.dispatchMouseEvent）；
//   ③ 点击后按钮变「申诉语句生成中...」，实测 5~7.5s 才弹出 AI 申述内容 ⇒ 弹窗轮询上限放宽到 60s。
//
// 契约：进入差评页后，对"自动申诉已关闭 + 存在唯一立即申诉"的条目，依次写入
//   prepared → ready_for_confirmation → submitted_once → 点击确认 → 权威回读（条目移除且未申诉总数减少）
// 回读失败标 unknown 并停止批次（防重），绝不重发。
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
// 金鲨入口门禁（岗位共享判定）。2026-10-05 重构为独立自包含执行器时丢失了本 import，
// 导致 preparePage/readState 调用 assertJinshaEntry 抛 ReferenceError（--execute 每轮必失败）。
import { assertJinshaEntry } from '../../../posts/jinsha-post/scripts/auth.mjs';

const ENDPOINT = 'http://127.0.0.1:9232';
const ORIGIN = 'https://data.guoshuyufen.com/';
const HOME = `${ORIGIN}#/businessData/realTimeData`;
const NEGATIVE = `${ORIGIN}#/negativeAnalyse`;
// 2026-10-06 跨树整改（大同授权）：原硬编码旧树 zhensi_waimai（迁移后遗留），
// 改为线上树 zhensi_waimai_back，与同族 taobao-flash-sale-negative-review-appeals 同构。
const ROOT = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
const CONTEXT = '淘宝';
const PLATFORM = '2';
const LABEL = '淘宝闪购';
// ★ 关键设计（2026-10-22）：records 目录刻意与 taobao-flash-sale-negative-review-appeals **共用**。
// 理由：①该目录是申诉防重的唯一事实源，两条流若各写各的目录，会对同一批未申诉条目重复提交；
// ②18:30 报表流（taobao-flash-sale）的 appeal_report_builder 正是从这个目录回读
//   verified_submitted 的「平台建议回复/申诉类型/页面核验」，换目录会导致报表列全部显示「未读取」。
// 故本流只做申诉，不做报表与发送（报表由 18:30 既有流携带）。
const RECORDS = path.join(ROOT, 'records', 'taobao-flash-sale-negative-review-appeals');
// 淘宝闪购申诉类型枚举与美团不同（美团「骑手送餐慢」/ 淘宝「骑手配送超时」，实测 .type_txt .txt 回读值）。
const FALLBACK = '骑手配送超时';
const EMPTY_LIST_RETRIES = 3;
// 淘宝 AI 申述内容为异步生成（按钮先变「申诉语句生成中...」，5~7.5s 后才出弹窗），轮询上限放宽。
const MODAL_POLL_ATTEMPTS = 60;

const sleep = ms => new Promise(r => setTimeout(r, ms));
const shanghaiDate = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
const yesterday = () => { const d = new Date(`${shanghaiDate()}T00:00:00+08:00`); d.setUTCDate(d.getUTCDate() - 1); return new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(d); };
const now = () => new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }).format(new Date()).replace(' ', 'T') + '+08:00';
const clean = v => String(v ?? '').replace(/\s+/g, ' ').trim();
const excerpt = v => clean(v).slice(0, 80);
const escapeMd = value => String(value ?? '').replaceAll('\n', ' ').replaceAll('\r', ' ').trim();

export const stableRecordKey = ({ store, date, comment }) => crypto.createHash('sha256').update([clean(store), clean(date), clean(comment)].join('|')).digest('hex').slice(0, 12);
export const parseRecordStatus = text => (String(text).match(/^- 记录状态：([^\n\r]+)/m) || [])[1]?.trim() || '';
// 2026-10-22 大同明确：「自动申诉已开启」的条目**不跳过**，一律点「立即申诉」。
// （此前照抄美团契约会把已开启的标 skipped，大同当场纠正。）
export const eligible = card => card.hasAppeal === true;
export const shouldRetryEmptyList = (cardCount, attempt) => cardCount === 0 && attempt < EMPTY_LIST_RETRIES;
export const sameCandidateSignature = (previous, signature) => previous !== null && signature === previous;
export function buildMarkdown(record) {
  return `# ${escapeMd(record.channelLabel || LABEL)}差评申诉临时记录\n\n- 业务日期：${escapeMd(record.businessDate)}\n- 记录键：${escapeMd(record.key)}\n- 门店：${escapeMd(record.store)}\n- 评价日期：${escapeMd(record.date)}\n- 星级：${escapeMd(record.score)} 星\n- 评价最小摘录：${escapeMd(record.commentExcerpt)}\n- 当前页面状态：${escapeMd(record.pageState)}\n- 自动申诉状态：${escapeMd(record.auto)}\n- 平台建议回复：${escapeMd(record.suggestion || '未打开申诉弹窗；不读取、不生成。')}\n- 最终申诉理由：${escapeMd(record.reason || '不适用。')}\n- 申诉类型：${escapeMd(record.appealType || '不适用。')}\n- 剩余次数：${escapeMd(record.remaining || '未读取。')}\n- 页面核验结果：${escapeMd(record.verification)}\n- 记录状态：${escapeMd(record.status)}\n- 创建时间：${escapeMd(record.createdAt)}\n- 提交时间：${escapeMd(record.submittedAt || '不适用')}\n- 核验时间：${escapeMd(record.verifiedAt || '不适用')}\n- 异常原因：${escapeMd(record.error || '无')}\n\n> 记录键由页面可见的门店、评价日期与评价文本生成稳定摘要；本文件不保存账号、Cookie、手机号、订单号或完整评价正文。\n`;
}

class Cdp {
  constructor(ws) { this.ws = ws; this.next = 0; this.pending = new Map(); }
  static async open() {
    const targets = await (await fetch(`${ENDPOINT}/json/list`)).json();
    const pages = targets.filter(x => x.type === 'page' && x.url.startsWith(ORIGIN));
    if (pages.length !== 1) throw Error(`jinsha-page-count:${pages.length}`);
    const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('cdp-connect-timeout')), 20000);
      ws.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      ws.addEventListener('error', e => { clearTimeout(timer); reject(Error('cdp-connect-error:' + (e?.message || 'unknown'))); }, { once: true });
    });
    const cdp = new Cdp(ws);
    ws.addEventListener('message', event => { const m = JSON.parse(event.data); const done = cdp.pending.get(m.id); if (done) { cdp.pending.delete(m.id); m.error ? done.reject(Error(m.error.message)) : done.resolve(m.result); } });
    return cdp;
  }
  call(method, params = {}, timeoutMs = 45000) {
    return new Promise((resolve, reject) => {
      const id = ++this.next;
      const timer = setTimeout(() => { this.pending.delete(id); reject(Error(`cdp-call-timeout:${method}`)); }, timeoutMs);
      this.pending.set(id, {
        resolve: v => { clearTimeout(timer); resolve(v); },
        reject: e => { clearTimeout(timer); reject(e); },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) { const out = await this.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (out.exceptionDetails) throw Error(out.exceptionDetails.exception?.description || out.exceptionDetails.text || 'cdp-evaluate-failed'); return out.result.value; }
  close() { this.ws.close(); }
}

async function navigate(cdp, url, waitMs = 3500) { await cdp.call('Page.enable'); await cdp.call('Page.navigate', { url }); await sleep(waitMs); }
async function atomicWrite(file, text) { await fs.mkdir(path.dirname(file), { recursive: true }); const temp = `${file}.${process.pid}.tmp`; await fs.writeFile(temp, text, { mode: 0o600 }); await fs.rename(temp, file); if (await fs.readFile(file, 'utf8') !== text) throw Error('record-readback-mismatch'); }
async function existingStatus(file) { try { return parseRecordStatus(await fs.readFile(file, 'utf8')); } catch (error) { if (error.code === 'ENOENT') return ''; throw error; } }

const CARD_SCRIPT = `(()=>[...document.querySelectorAll('.cryptonym')].filter(card=>card.offsetParent!==null).map(card=>{const lines=card.innerText.split('\\n').map(x=>x.trim()).filter(Boolean);const date=(card.innerText.match(/\\d{4}-\\d{2}-\\d{2}/)||[])[0]||'';const dateIndex=lines.indexOf(date);const orderIndex=lines.findIndex((x,i)=>i>dateIndex&&x.startsWith('订单详情：'));const comment=dateIndex>=0&&orderIndex>dateIndex?lines.slice(dateIndex+1,orderIndex).join(' '):'';const appealButtons=[...card.querySelectorAll('.btn')].filter(x=>x.offsetParent!==null&&x.innerText.trim()==='立即申诉');return {store:card.querySelector('.shopName')?.innerText.trim()||'',score:(([...card.querySelectorAll('.pointLi')].map(x=>x.innerText.trim()).find(x=>/^总分\\d/.test(x))||'').match(/\\d/)||[])[0]||'',date,comment,auto:(card.innerText.match(/自动申诉已(?:开启|关闭)/)||[])[0]||'',remaining:(card.innerText.match(/本周剩余申诉次数[:：]?[^\\n]*/)||[])[0]||'',hasAppeal:appealButtons.length===1};}))()`;

async function readState(cdp, date) {
  const state = await cdp.eval(`(()=>({url:location.href,title:document.title,risk:/验证码|滑块|账号风险|请重新登录|登录失效/.test(document.body.innerText),platform:[...document.querySelectorAll('input[type=radio]')].filter(x=>x.checked).map(x=>x.value),dates:[...document.querySelectorAll('input.el-range-input')].map(x=>x.value),active:[...document.querySelectorAll('.navLi.active')].map(x=>x.innerText.trim()),total:document.querySelector('.el-pagination__total')?.innerText||'',cards:${CARD_SCRIPT}}))()`);
  const totalMatch = (state.total.match(/共\s*(\d+)\s*条/)||[])[1];
  const total = totalMatch !== undefined ? Number(totalMatch) : state.cards.length;
  assertJinshaEntry(state, { home: NEGATIVE, errorCode: 'jinsha-route-login-or-risk-gate' });
  if (state.platform.join(',') !== PLATFORM || state.dates.length !== 2 || state.dates.some(x => x !== date) || state.active.length !== 1 || !state.active[0].startsWith('未申诉')) throw Error('filter-readback-mismatch');
  if (!Number.isInteger(total) || state.cards.length > total || (total > 0 && state.cards.length === 0) || state.cards.some(x => x.date !== date)) throw Error(`page-card-readback-mismatch:${total}:${state.cards.length}`);
  state.totalNumber = total;
  state.cards = state.cards.map(card => ({ ...card, key: stableRecordKey(card) }));
  return state;
}

async function stableState(cdp, date) {
  let previous = null, last = null;
  for (let attempt = 0; attempt < 16; attempt++) {
    last = await readState(cdp, date);
    const signature = last.cards.map(card => card.key).sort().join('|');
    if (sameCandidateSignature(previous, signature)) return last;
    previous = signature;
    await sleep(750);
  }
  throw Error('candidate-list-not-stable');
}

async function preparePage(cdp, date) {
  await navigate(cdp, HOME);
  const entry = await cdp.eval(`(()=>({url:location.href,title:document.title,risk:/验证码|滑块|账号风险|请重新登录|登录失效/.test(document.body.innerText)}))()`);
  assertJinshaEntry(entry, { home: HOME });
  let contextSelected = false;
  for (let attempt = 0; attempt < 20; attempt++) {
    const count = await cdp.eval(`(()=>[...document.querySelectorAll('.cutli')].filter(x=>x.offsetParent!==null&&x.innerText.trim()===${JSON.stringify(CONTEXT)}).length)()`);
    if (count === 1) { await cdp.eval(`(()=>{const target=[...document.querySelectorAll('.cutli')].find(x=>x.offsetParent!==null&&x.innerText.trim()===${JSON.stringify(CONTEXT)});target.click();return true})()`); contextSelected = true; break; }
    if (count > 1) throw Error(`channel-context-count:${count}`);
    if (attempt === 0) await cdp.eval(`(()=>{const menu=[...document.querySelectorAll('.hamburger-container')].filter(x=>x.offsetParent!==null);if(menu.length===1)menu[0].click();return menu.length})()`);
    await sleep(250);
  }
  if (!contextSelected) throw Error('channel-context-not-rendered');
  for (let attempt = 0; attempt < 20; attempt++) { await sleep(250); const selected = await cdp.eval(`(()=>[...document.querySelectorAll('.cutli')].filter(x=>x.offsetParent!==null&&x.classList.contains('pitchOn')).map(x=>x.innerText.trim()))()`); if (selected.join(',') === CONTEXT) break; if (attempt === 19) throw Error('channel-context-readback-mismatch'); }
  await navigate(cdp, NEGATIVE);
  await cdp.eval(`(()=>{const radio=document.querySelector('input[type=radio][value=${JSON.stringify(PLATFORM)}]');if(!radio)throw Error('platform-radio-missing');radio.click();const inputs=[...document.querySelectorAll('input.el-range-input')];if(inputs.length!==2)throw Error('date-input-count');const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;for(const input of inputs){setter.call(input,${JSON.stringify(date)});input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}document.body.click();return true})()`);
  await sleep(1300);
  await cdp.eval(`(()=>{const tabs=[...document.querySelectorAll('.navLi')].filter(x=>x.innerText.trim().startsWith('未申诉'));if(tabs.length!==1)throw Error('unappealed-tab-count:'+tabs.length);tabs[0].click();return true})()`);
  await sleep(3200);
  return stableState(cdp, date);
}

// 淘宝闪购「立即申诉」：直接 JS click（实测有效；此前误判为"JS click 失效"，
// 真因是淘宝 AI 申述内容异步生成需 5~7.5s，而我当时只等了 2.5~3.5s 就断定无反应）。
// 点完只做一件事：等「按钮转生成中 / 弹窗出现」这个受理证据，最多 30s。
const TARGET_LIT = target => JSON.stringify({ store: target.store, date: target.date, comment: target.comment });
const FIND_CARD = target => `(()=>{const target=${TARGET_LIT(target)};const nodes=[...document.querySelectorAll('.cryptonym')].filter(card=>card.offsetParent!==null);const matches=nodes.filter(card=>{const text=card.innerText||'';const buttons=[...card.querySelectorAll('.btn')].filter(x=>x.offsetParent!==null&&x.innerText.trim()==='立即申诉');return text.includes(target.store)&&text.includes(target.date)&&text.includes(target.comment)&&buttons.length===1});if(matches.length!==1)throw Error('candidate-node-count:'+matches.length);return matches[0];})()`;

async function clickCandidate(cdp, target) {
  await cdp.eval(`(()=>{const card=${FIND_CARD(target)};const button=[...card.querySelectorAll('.btn')].filter(x=>x.offsetParent!==null&&x.innerText.trim()==='立即申诉')[0];if(!button)throw Error('appeal-button-missing');button.click();return true;})()`);
  for (let i = 0; i < 60; i++) {
    await sleep(500);
    const accepted = await cdp.eval(`(()=>{const modal=document.querySelector('.representations');if(modal&&getComputedStyle(modal).display!=='none')return true;return [...document.querySelectorAll('.cryptonym')].filter(c=>c.offsetParent!==null).some(c=>/申诉语句生成中/.test(c.innerText));})()`);
    if (accepted) return;
  }
  throw Error('appeal-click-not-accepted');
}

async function stableModal(cdp) {
  let previous = '', stable = 0, last = null;
  // 淘宝 AI 申述内容异步生成：先「申诉语句生成中...」，5~7.5s 后弹窗才出内容。
  // 轮询放宽到 MODAL_POLL_ATTEMPTS(60s)，并要求连续 3 次读到同一文案，避免抓到半成品。
  for (let attempt = 0; attempt < MODAL_POLL_ATTEMPTS; attempt++) {
    last = await cdp.eval(`(()=>{const modal=document.querySelector('.representations');if(!modal||getComputedStyle(modal).display==='none')return null;return {text:document.querySelector('.representations textarea')?.value||'',type:document.querySelector('.representations .type_txt .txt')?.innerText.trim()||'',remaining:[...document.querySelectorAll('.representations-content-footer div')].map(x=>x.innerText.trim()).find(x=>x.includes('剩余申诉次数'))||'',confirmCount:[...document.querySelectorAll('.representations .sure_btn')].filter(x=>x.innerText.trim()==='确认申诉').length}})()`);
    if (last) { const text = clean(last.text); stable = text && text === previous ? stable + 1 : 0; previous = text; if (stable >= 2 && last.type && last.confirmCount === 1) return { ...last, text }; }
    await sleep(1000);
  }
  if (!last) throw Error('appeal-modal-missing');
  if (clean(last.text)) throw Error('appeal-suggestion-not-stable');
  await cdp.eval(`(()=>{const input=document.querySelector('.representations textarea');if(!input)throw Error('appeal-textarea-missing');const setter=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;setter.call(input,${JSON.stringify(FALLBACK)});input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));return input.value})()`);
  await sleep(300);
  const final = await cdp.eval(`(()=>({text:document.querySelector('.representations textarea')?.value||'',type:document.querySelector('.representations .type_txt .txt')?.innerText.trim()||'',remaining:[...document.querySelectorAll('.representations-content-footer div')].map(x=>x.innerText.trim()).find(x=>x.includes('剩余申诉次数'))||'',confirmCount:[...document.querySelectorAll('.representations .sure_btn')].filter(x=>x.innerText.trim()==='确认申诉').length}))()`);
  if (clean(final.text) !== FALLBACK || !final.type || final.confirmCount !== 1) throw Error('appeal-fallback-readback-mismatch');
  return { ...final, text: clean(final.text) };
}

async function confirmOnce(cdp) {
  const clicked = await cdp.eval(`(()=>{const buttons=[...document.querySelectorAll('.representations .sure_btn')].filter(x=>x.innerText.trim()==='确认申诉');if(buttons.length!==1)throw Error('confirm-button-count:'+buttons.length);buttons[0].click();return 1})()`);
  if (clicked !== 1) throw Error('confirm-click-count');
}

async function execute() {
  const businessDate = yesterday(), startedAt = now(), receipt = { ok: false, businessDate, startedAt, endpoint: ENDPOINT, runtimeModelDecisions: 0, verified_submitted: [], skipped: [], blocked: [], unknown: [], warnings: [] };
  const cdp = await Cdp.open();
  try {
    let state;
    for (let attempt = 1; attempt <= EMPTY_LIST_RETRIES; attempt++) {
      state = await preparePage(cdp, businessDate);
      // 稳定的空列表（total 与 cards 均为 0）无需重跑整页 preparePage；仅当“分页声明有条目、
      // 卡片却没渲染”时才重试，避免每天空档白耗 3 轮整页导航。
      if (state.cards.length > 0 || state.totalNumber > 0) break;
      if (!shouldRetryEmptyList(0, attempt)) break;
      receipt.warnings.push(`empty-list-readback-retry:${attempt}`);
    }
    receipt.discovered = state.cards.length;
    receipt.closedCandidates = state.cards.filter(eligible).length;
    receipt.autoEnabled = state.cards.filter(x => x.auto === '自动申诉已开启').length;
    // 2026-10-22 大同明确：「自动申诉已开启」不跳过，与「已关闭」一视同仁点「立即申诉」。
    for (const initial of state.cards.filter(eligible)) {
      state = await readState(cdp, businessDate);
      const target = state.cards.find(x => x.key === initial.key);
      if (!target) { receipt.warnings.push(`candidate-no-longer-unappealed:${initial.key}`); continue; }
      if (!eligible(target)) throw Error(`candidate-state-drift:${initial.key}`);
      const file = path.join(RECORDS, businessDate, `${target.key}.md`), prior = await existingStatus(file);
      if (['verified_submitted', 'unknown', 'blocked'].includes(prior)) { receipt[prior].push(target.key); continue; }
      if (prior === 'submitted_once') {
        const createdAt = now();
        await atomicWrite(file, buildMarkdown({ businessDate, key: target.key, store: target.store, date: target.date, score: target.score, commentExcerpt: excerpt(target.comment), pageState: `${LABEL} / 昨日 / 未申诉；页面共 ${state.totalNumber} 条。`, auto: target.auto || '页面未提供', verification: '检测到上次记录已进入 submitted_once，无法排除确认动作已发生。', status: 'unknown', createdAt, error: '防重门禁：禁止再次确认申诉。' }));
        receipt.unknown.push(target.key); break;
      }
      const createdAt = now(), base = { businessDate, key: target.key, store: target.store, date: target.date, score: target.score, commentExcerpt: excerpt(target.comment), pageState: `${LABEL} / 昨日 / 未申诉；页面共 ${state.totalNumber} 条。`, auto: target.auto || '页面未提供', createdAt };
      await atomicWrite(file, buildMarkdown({ ...base, verification: '已创建临时记录，尚未打开申诉弹窗。', status: 'prepared' }));
      await clickCandidate(cdp, target);
      const modal = await stableModal(cdp);
      const suggestion = clean(modal.text), appealType = clean(modal.type), remaining = clean(modal.remaining);
      await atomicWrite(file, buildMarkdown({ ...base, suggestion, reason: suggestion, appealType, remaining, verification: '弹窗申诉内容已连续两次稳定读取；条目、自动申诉状态、类型与剩余次数已复核。', status: 'ready_for_confirmation' }));
      const beforeTotal = state.totalNumber, submittedAt = now();
      await atomicWrite(file, buildMarkdown({ ...base, suggestion, reason: suggestion, appealType, remaining, verification: '确认前门禁已通过；即将执行唯一一次确认申诉。', status: 'submitted_once', submittedAt }));
      await confirmOnce(cdp);
      let after = null;
      for (let attempt = 0; attempt < 20; attempt++) { await sleep(750); try { after = await readState(cdp, businessDate); if (!after.cards.some(x => x.key === target.key) && after.totalNumber < beforeTotal) break; } catch {} }
      const verified = after && !after.cards.some(x => x.key === target.key) && after.totalNumber < beforeTotal, verifiedAt = now();
      if (!verified) {
        await atomicWrite(file, buildMarkdown({ ...base, suggestion, reason: suggestion, appealType, remaining, verification: '确认后未能以同条目移除且未申诉总数减少完成权威回读。', status: 'unknown', submittedAt, verifiedAt, error: '提交结果未知；按防重规则停止批次，不重试。' }));
        receipt.unknown.push(target.key); break;
      }
      await atomicWrite(file, buildMarkdown({ ...base, suggestion, reason: suggestion, appealType, remaining, pageState: `${LABEL} / 昨日 / 未申诉；确认前 ${beforeTotal} 条，确认后 ${after.totalNumber} 条。`, verification: '同条目已从未申诉列表移除，且未申诉总数同步减少。', status: 'verified_submitted', submittedAt, verifiedAt }));
      receipt.verified_submitted.push(target.key);
    }
    receipt.ok = receipt.unknown.length === 0 && receipt.blocked.length === 0;
    receipt.finishedAt = now();
    return receipt;
  } catch (error) {
    receipt.error = String(error.message || error);
    receipt.finishedAt = now();
    return receipt;
  } finally {
    try { await navigate(cdp, HOME, 1200); } catch (error) { receipt.warnings.push(`home-restore-failed:${String(error.message || error)}`); }
    cdp.close();
  }
}

async function inspect() {
  const businessDate = yesterday(), cdp = await Cdp.open();
  try {
    const state = await preparePage(cdp, businessDate);
    return { ok: true, businessDate, total: state.totalNumber, visibleCount:state.cards.length, visibleKeys:state.cards.map(card=>card.key), checkedAt:now(), closedCandidates: state.cards.filter(eligible).map(x => ({ key: x.key, store: x.store })), autoEnabled: state.cards.filter(x => x.auto === '自动申诉已开启').map(x => ({ key: x.key, store: x.store })), runtimeModelDecisions: 0 };
  } finally {
    try { await navigate(cdp, HOME, 1200); } catch {}
    cdp.close();
  }
}

function selfTest() {
  const card = { store: '门店A', date: '2026-09-21', score: '1', comment: '差评内容', auto: '自动申诉已关闭', hasAppeal: true };
  if (!CONTEXT || stableRecordKey(card) !== stableRecordKey({ ...card, score: '2' })) throw Error('stable-key-contract');
  // 2026-10-22 大同明确：只要有「立即申诉」按钮就受理，不因「自动申诉已开启」而跳过。
  if (!eligible(card)) throw Error('eligibility-contract');
  if (!shouldRetryEmptyList(0, 1) || shouldRetryEmptyList(1, 1) || shouldRetryEmptyList(0, EMPTY_LIST_RETRIES)) throw Error('empty-list-retry-contract');
  if (!sameCandidateSignature('', '') || sameCandidateSignature(null, '')) throw Error('empty-list-stability-contract');
  const md = buildMarkdown({ businessDate: card.date, key: stableRecordKey(card), store: card.store, date: card.date, score: card.score, commentExcerpt: card.comment, pageState: '淘宝闪购 / 昨日 / 未申诉', auto: '已关闭', verification: 'ok', status: 'prepared', createdAt: '2026-09-22T00:00:00+08:00' });
  if (parseRecordStatus(md) !== 'prepared' || !md.includes('记录键：') || !md.includes('异常原因：无')) throw Error('markdown-contract');
  return { ok: true, tests: 6, endpoint: ENDPOINT, runtimeModelDecisions: 0 };
}

async function main() {
  const mode = process.argv[2];
  if (mode === '--self-test') console.log(JSON.stringify(selfTest()));
  else if (mode === '--inspect') console.log(JSON.stringify(await inspect()));
  else if (mode === '--execute') { const out = await execute(); console.log(JSON.stringify(out)); if (!out.ok) process.exitCode = 1; }
  else throw Error('usage: appeal_executor.mjs --self-test|--inspect|--execute');
}
if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) main().catch(error => { console.log(JSON.stringify({ ok: false, error: String(error.message || error), runtimeModelDecisions: 0 })); process.exitCode = 1; });
