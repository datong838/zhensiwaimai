import {selectExistingJinshaTarget,assertSelectedJinshaTarget} from './existing_owned_target.mjs';
import crypto from 'node:crypto';

const ENDPOINT = 'http://127.0.0.1:9232';
const ORIGIN = 'https://data.guoshuyufen.com/';
const HOME = `${ORIGIN}#/businessData/realTimeData`;
const NEGATIVE = `${ORIGIN}#/negativeAnalyse`;
const STATUS_TABS = [
  ['未申诉', '未申诉'],
  ['申诉中', '申诉中'],
  ['申诉成功', '申诉成功'],
  ['申诉失败', '申诉失败'],
  ['已删除', '已删除'],
];
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
const clean = value => String(value ?? '').replace(/\s+/g, ' ').trim();

export const stableReviewKey = ({ store, date, comment }) => crypto.createHash('sha256').update([clean(store), clean(date), clean(comment)].join('|')).digest('hex').slice(0, 12);
export const sumCounts = counts => Object.values(counts || {}).reduce((sum, value) => sum + Number(value || 0), 0);
export const statusSnapshotSignature = state => JSON.stringify({
  total: state.total,
  statusCounts: Object.fromEntries(Object.entries(state.statusCounts || {}).sort(([a], [b]) => a.localeCompare(b))),
  page: state.page,
  cards: state.cards.map(card => ({ key: stableReviewKey(card), score: card.score, comment: card.comment, auto: card.auto, appealMethod: card.appealMethod, appealTime: card.appealTime, appealContent: card.appealContent })),
});
export const isCoherentStatusSnapshot = (state, status) => Number.isInteger(state.total)
  && Number.isInteger(state.statusCounts?.[status])
  && state.total === state.statusCounts[status]
  && (state.total === 0 ? state.cards.length === 0 : state.cards.length > 0 && state.cards.length <= state.total);
export async function readStableStatusSnapshot(readState, status, { attempts = 20, intervalMs = 350, pause = sleep } = {}) {
  let previousSignature = null;
  // 2026-10-02：原来这里裸 `catch {}` 会把 pageState 抛出的**真因**整口吞掉
  // （平台/渠道/日期区间/卡片日期 读回不符、风控命中、页面不在差评页等），
  // 耗尽后只抛出 `appeal-status-not-stable:<status>` —— 一个把真因藏起来的
  // 误导性错误，与「把 No route to host 当成服务端宕机」是同一类误判：看护
  // 只能看到症状，永远定位不到根因。现在记录最后一次真因，耗尽时一并抛出。
  let lastCause = null;
  for (let attempt = 0; attempt < attempts; attempt++) {
    await pause(intervalMs);
    try {
      const state = await readState();
      if (!isCoherentStatusSnapshot(state, status)) {
        previousSignature = null;
        lastCause = Error(`snapshot-not-coherent:${status}`);
        continue;
      }
      const signature = statusSnapshotSignature(state);
      if (signature === previousSignature) return state;
      previousSignature = signature;
      lastCause = null;
    } catch (error) {
      previousSignature = null;
      lastCause = error;
    }
  }
  throw Error(`appeal-status-not-stable:${status}`
    + (lastCause ? ` (cause: ${lastCause.message})` : ''));
}
// D13（2026-09-30）：点击渠道项后菜单可能自动收起 ⇒ `.cutli` 全部不可见（offsetParent
// 为 null），原读回循环只会空转 5 秒后抛 `channel-context-readback-mismatch`。现在显式
// 区分「菜单收起」（可见项为 0 且汉堡菜单可点）与「选错/未选中」：前者重新展开菜单再读，
// 后者照旧等下一轮；尝试次数与最终报错完全不变，判定强度不降、fail-closed 保留。
export async function readSelectedChannel(probe, reexpand, contextLabel, { attempts = 20, intervalMs = 250, pause = sleep } = {}) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    await pause(intervalMs);
    const state = await probe();
    if (state.pitch.join(',') === contextLabel) return state.pitch.join(',');
    if (attempt === attempts - 1) throw Error('channel-context-readback-mismatch');
    if (state.visible === 0 && state.menu === 1) { await reexpand(); continue; }
  }
  throw Error('channel-context-readback-mismatch');
}
// 2026-10-02：`el-menu--collapse` 的展开**带过渡动画**，固定 sleep(400ms) 不够
// —— 实测需 ~1.5s `.cutli` 才可见。等待不足时 context 读回为空，pageState 抛
// `appeal-page-readback-mismatch`，又被 readStableStatusSnapshot 吞成
// `appeal-status-not-stable`（真因被藏）。改为轮询等待「可见且选中项回读正确」，
// 等不到就再点一次汉堡菜单；最终仍不可见则交回 pageState 照旧 fail-closed。
async function waitForChannelVisible(cdp, reexpandMenu, contextLabel,
                                     { attempts = 14, intervalMs = 400 } = {}) {
  for (let attempt = 0; attempt < attempts; attempt++) {
    let state = { visible: 0, pitch: '' };
    try {
      state = await cdp.eval(`(()=>{const visible=[...document.querySelectorAll('.cutli')].filter(x=>x.offsetParent!==null);return {visible:visible.length,pitch:visible.filter(x=>x.classList.contains('pitchOn')).map(x=>x.innerText.trim()).join(',')};})()`);
    } catch { state = { visible: 0, pitch: '' }; }
    if (state.visible > 0 && state.pitch === contextLabel) return state;
    if (attempt > 0 && attempt % 3 === 0) {
      try { await reexpandMenu(); } catch { /* 交给下一轮轮询或 pageState fail-closed */ }
    }
    await sleep(intervalMs);
  }
  return null;
}
export function assertSnapshot(snapshot) {
  if (!snapshot || !Array.isArray(snapshot.rows) || !snapshot.counts) throw Error('appeal-snapshot-invalid');
  if (snapshot.rows.length !== Number(snapshot.counts.全部)) throw Error(`appeal-snapshot-row-count-mismatch:${snapshot.rows.length}:${snapshot.counts.全部}`);
  if (snapshot.total !== snapshot.rows.length) throw Error(`appeal-snapshot-total-mismatch:${snapshot.total}:${snapshot.rows.length}`);
  if (snapshot.rows.some(row => row.status !== '全部' || !row.store || !row.date || !Number.isInteger(row.score))) throw Error('appeal-snapshot-required-field-missing');
  return true;
}

class Cdp {
  constructor(ws) { this.ws = ws; this.next = 0; this.pending = new Map(); }
  static async open() {
    const targets = await (await fetch(`${ENDPOINT}/json/list`)).json();
    const selected = await selectExistingJinshaTarget(targets);
    const ws = new WebSocket(selected.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, { once: true }); ws.addEventListener('error', reject, { once: true }); });
    const cdp = new Cdp(ws);
    ws.addEventListener('message', event => { const message = JSON.parse(event.data); const pending = cdp.pending.get(message.id); if (pending) { cdp.pending.delete(message.id); message.error ? pending.reject(Error(message.error.message)) : pending.resolve(message.result); } });
    try { await assertSelectedJinshaTarget(cdp,selected); } catch(error) { cdp.close(); throw error; }
    return cdp;
  }
  call(method, params = {}) { return new Promise((resolve, reject) => { const id = ++this.next; this.pending.set(id, { resolve, reject }); this.ws.send(JSON.stringify({ id, method, params })); }); }
  async eval(expression) { const out = await this.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (out.exceptionDetails) throw Error(out.exceptionDetails.exception?.description || out.exceptionDetails.text || 'cdp-evaluate-failed'); return out.result.value; }
  close() { this.ws.close(); }
}

async function navigate(cdp, url, waitMs = 1200) { await cdp.call('Page.enable'); await cdp.call('Page.navigate', { url }); await sleep(waitMs); }
const cardsScript = `(()=>[...document.querySelectorAll('.cryptonym')].filter(card=>card.offsetParent!==null).map(card=>{const text=card.innerText||'',lines=text.split('\\n').map(x=>x.trim()).filter(Boolean),date=(text.match(/20\\d{2}-\\d{2}-\\d{2}/)||[])[0]||'',dateIndex=lines.indexOf(date),orderIndex=lines.findIndex((x,index)=>index>dateIndex&&x.startsWith('订单详情：')),comment=card.querySelector('.cryptonymText')?.innerText.trim()||(dateIndex>=0&&orderIndex>dateIndex?lines.slice(dateIndex+1,orderIndex).join(' '):''),appealContent=card.querySelector('.bottom_info_content')?.innerText.trim()||'',appealTime=card.querySelector('.bottom_info_time')?.innerText.trim()||'',appealMethod=card.querySelector('.bottom_info_object')?.innerText.trim()||'';return {store:card.querySelector('.shopName')?.innerText.trim()||'',date,score:Number(((([...card.querySelectorAll('.pointLi')].map(x=>x.innerText.trim()).find(x=>/^总分\\d/.test(x))||'').match(/\\d/)||[])[0]||0)),comment,auto:(text.match(/自动申诉已(?:开启|关闭)/)||[])[0]||'',appealMethod,appealTime,appealContent:appealContent.replace(/^申诉内容[:：]/,'').trim()};}))()`;

async function pageState(cdp, expectedDate, expectedPlatform, expectedContext, expectedStatus) {
  const state = await cdp.eval(`(()=>({url:location.href,title:document.title,risk:/验证码|滑块|账号风险|请重新登录|登录失效/.test(document.body.innerText),platform:[...document.querySelectorAll('input[type=radio]')].filter(x=>x.checked).map(x=>x.value),context:[...document.querySelectorAll('.cutli')].filter(x=>x.offsetParent!==null&&x.classList.contains('pitchOn')).map(x=>x.innerText.trim()),dates:[...document.querySelectorAll('input.el-range-input')].map(x=>x.value),active:[...document.querySelectorAll('.navLi.active')].map(x=>x.innerText.trim()),statusCounts:Object.fromEntries([...document.querySelectorAll('.navLi')].filter(x=>x.offsetParent!==null).map(x=>{const m=x.innerText.trim().match(/^(全部|未申诉|申诉中|申诉成功|申诉失败|已删除)\\s*\\((\\d+)\\)/);return m?[m[1],Number(m[2])]:null}).filter(Boolean)),total:document.querySelector('.el-pagination__total')?.innerText||'',page:[...document.querySelectorAll('.el-pager li.active')].filter(x=>x.offsetParent!==null).map(x=>x.innerText.trim()),cards:${cardsScript}}))()`);
  const total = Number((state.total.match(/共\s*(\d+)\s*条/) || [])[1]);
  if (state.url !== NEGATIVE || state.title !== '臻肆外卖运营' || state.risk || state.platform.join(',') !== expectedPlatform || state.context.join(',') !== expectedContext || state.dates.length !== 2 || state.dates.some(date => date !== expectedDate) || state.active.length !== 1 || !state.active[0].startsWith(expectedStatus) || !Number.isInteger(total) || state.cards.some(card => card.date !== expectedDate)) throw Error(`appeal-page-readback-mismatch:${expectedStatus}`);
  return { ...state, total };
}

async function selectStatus(cdp, expectedDate, expectedPlatform, expectedContext, status) {
  await cdp.eval(`(()=>{const tabs=[...document.querySelectorAll('.navLi')].filter(x=>x.offsetParent!==null&&x.innerText.trim().startsWith(${JSON.stringify(status)}));if(tabs.length!==1)throw Error('status-tab-count:'+tabs.length);tabs[0].click();return true})()`);
  return readStableStatusSnapshot(() => pageState(cdp, expectedDate, expectedPlatform, expectedContext, status), status);
}

async function nextPage(cdp, expectedDate, expectedPlatform, expectedContext, status, previousPage) {
  await cdp.eval(`(()=>{const next=[...document.querySelectorAll('.el-pagination .btn-next')].filter(x=>x.offsetParent!==null);if(next.length!==1||next[0].classList.contains('disabled')||next[0].getAttribute('disabled')!==null)throw Error('pagination-next-unavailable');next[0].click();return true})()`);
  for (let attempt = 0; attempt < 20; attempt++) { await sleep(350); const state = await pageState(cdp, expectedDate, expectedPlatform, expectedContext, status); const page = Number(state.page[0] || 0); if (page === previousPage + 1 && state.cards.length > 0) return state; }
  throw Error(`pagination-next-readback-mismatch:${status}:${previousPage}`);
}

async function collectStatus(cdp, expectedDate, expectedPlatform, expectedContext, status) {
  let state = await selectStatus(cdp, expectedDate, expectedPlatform, expectedContext, status);
  const total = state.total, rows = [], seenPages = new Set();
  while (true) {
    const page = Number(state.page[0] || (total === 0 ? 1 : 0));
    if (!page || seenPages.has(page) || rows.length + state.cards.length > total) throw Error(`pagination-state-invalid:${status}:${page}`);
    seenPages.add(page); rows.push(...state.cards.map(card => ({ ...card, key: stableReviewKey(card), status })));
    if (rows.length === total) return { rows, statusCounts: state.statusCounts };
    state = await nextPage(cdp, expectedDate, expectedPlatform, expectedContext, status, page);
  }
}

export async function collectAllAppeals({ businessDate, platformValue, channelLabel, contextLabel }) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(businessDate) || !['1', '2'].includes(platformValue) || !channelLabel || !['美团', '淘宝'].includes(contextLabel)) throw Error('appeal-collector-config-invalid');
  const cdp = await Cdp.open();
  try {
    await navigate(cdp, HOME);
    const entry = await cdp.eval(`(()=>({url:location.href,title:document.title,risk:/验证码|滑块|账号风险|请重新登录|登录失效/.test(document.body.innerText)}))()`);
    if (entry.url !== HOME || entry.title !== '臻肆外卖运营' || entry.risk) throw Error('jinsha-entry-or-login-gate');
    let contextClicked = false;
    for (let attempt = 0; attempt < 20; attempt++) {
      const count = await cdp.eval(`(()=>[...document.querySelectorAll('.cutli')].filter(x=>x.offsetParent!==null&&x.innerText.trim()===${JSON.stringify(contextLabel)}).length)()`);
      if (count === 1) { await cdp.eval(`(()=>{const target=[...document.querySelectorAll('.cutli')].find(x=>x.offsetParent!==null&&x.innerText.trim()===${JSON.stringify(contextLabel)});target.click();return true})()`); contextClicked = true; break; }
      if (count > 1) throw Error(`channel-context-count:${count}`);
      if (attempt === 0) await cdp.eval(`(()=>{const menu=[...document.querySelectorAll('.hamburger-container')].filter(x=>x.offsetParent!==null);if(menu.length===1)menu[0].click();return menu.length})()`);
      await sleep(250);
    }
    if (!contextClicked) throw Error('channel-context-not-rendered');
    const probeChannel = () => cdp.eval(`(()=>{const visible=[...document.querySelectorAll('.cutli')].filter(x=>x.offsetParent!==null);const pitch=visible.filter(x=>x.classList.contains('pitchOn')).map(x=>x.innerText.trim());const menu=[...document.querySelectorAll('.hamburger-container')].filter(x=>x.offsetParent!==null).length;return {visible:visible.length,pitch,menu};})()`);
    const reexpandMenu = () => cdp.eval(`(()=>{const menu=[...document.querySelectorAll('.hamburger-container')].filter(x=>x.offsetParent!==null);if(menu.length===1)menu[0].click();return menu.length})()`);
    await readSelectedChannel(probeChannel, reexpandMenu, contextLabel);
    await navigate(cdp, NEGATIVE, 1800);
    await cdp.eval(`(()=>{const radio=document.querySelector('input[type=radio][value=${JSON.stringify(platformValue)}]');if(!radio)throw Error('platform-radio-missing');radio.click();const inputs=[...document.querySelectorAll('input.el-range-input')];if(inputs.length!==2)throw Error('date-input-count');const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;for(const input of inputs){setter.call(input,${JSON.stringify(businessDate)});input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}document.body.click();return true})()`);
    await sleep(1200);
    // D13（2026-09-30）第二现场：导航到负向页后侧栏渠道菜单同样处于收起态（`.cutli` 全
    // 不可见），pageState 的 context 读回永远为空 ⇒ `appeal-status-not-stable`。重展开菜单
    // 让选中渠道（pitchOn 跨导航持久，已实测）可见；若展开失败，pageState 会以
    // `appeal-page-readback-mismatch` fail-closed。
    await reexpandMenu();
    await waitForChannelVisible(cdp, reexpandMenu, contextLabel);
    const all = await collectStatus(cdp, businessDate, platformValue, contextLabel, '全部');
    const counts = { 全部: all.rows.length, '申诉成功': Number(all.statusCounts.申诉成功 || 0), '申诉失败': Number(all.statusCounts.申诉失败 || 0), '申诉中': Number(all.statusCounts.申诉中 || 0), '未申诉': Number(all.statusCounts.未申诉 || 0) };
    const snapshot = { businessDate, channelLabel, counts, total: all.rows.length, rows: all.rows, collectedAt: new Date().toISOString(), runtimeModelDecisions: 0 };
    assertSnapshot(snapshot);
    return snapshot;
  } finally { try { await navigate(cdp, HOME, 700); } catch {} cdp.close(); }
}
