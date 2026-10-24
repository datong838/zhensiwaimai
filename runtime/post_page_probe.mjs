#!/usr/bin/env node
// post_page_probe.mjs —— 四岗位后台 Chrome「页面活性 + 可见性」探针 + 受控自愈
//
// 目的（2026-10-10 补两类机制缺口）：
//  A) 渲染线程卡死：assert_post_pages.py 只发 GET /json/list，只能证明「页存在」，
//     **看不见渲染线程卡死**。实测 9232 上两张无关 tab 的渲染线程 hung 时，
//     playwright connectOverCDP 超时、采集器 evaluate/click 30s 超时，
//     而 curl /json/version 仍 200、bg-chrome-up.sh 因端口在听而幂等空转。
//     判据：对每个 page target 做一次硬超时的 Runtime.evaluate('1+1')，超时 ⇒ hung。
//  B) 有头窗口不可见（occlusion）：2026-10-10 实测金鲨（9232，**唯一有头**窗口）
//     visibilityState=hidden、innerWidth/Height=0（窗口被 macOS 判定不可见/在屏外），
//     结果 Playwright 报 `element is outside of the viewport`，9232 上 3 条流同日挂。
//     根因：bg-chrome-up.sh 旧参数 `--window-position=2000,200` 在 1312 宽屏上把窗口推屏外。
//     判据：alive 页 evaluate `visibilityState`+`innerWidth`；hidden 或 0 ⇒ blind。
//     （注：headless 岗位由虚拟屏给 800×600，恒 visible，不会误报。）
//
// 处置（仅 --apply）：
//   - hung 页 → CDP Page.reload（browser 侧发起，可复位 hung 渲染线程）后复测；
//   - blind 页 → CDP Page.bringToFront 激活窗口后复测（实测 0×0 → 1200×613）。
//   **绝不新开/关闭 tab，绝不点页面，绝不发送任何外发消息。**
//   ⚠ bringToFront 会把有头窗口提到前台（可能一瞬打扰大同）——这是有头岗位可用的必要代价。
//
// 用法: node post_page_probe.mjs [--json] [--apply] [--ports 9230,9231,9232,9233]
// 退出码: 0 = 无异常（或已复位）；3 = 仍有 hung 或 blind（need-attention）。

import process from 'node:process';

const argv = process.argv.slice(2);
const JSON_OUT = argv.includes('--json');
const APPLY = argv.includes('--apply');
const pi = argv.indexOf('--ports');
const PORTS = (pi >= 0 && argv[pi + 1] ? argv[pi + 1] : '9230,9231,9232,9233')
  .split(',').map(s => Number(s.trim())).filter(Boolean);
const ROLES = { 9230: 'taobao-brand', 9231: 'taobao-agent-service', 9232: 'jinsha-business', 9233: 'meituan-im' };
// 各岗位的**流程目标页**域名。可见性（blind）判定/自愈**只对目标页**：
// 9232 上常有用户自用的天翼云等 tab，它们 hidden 属正常，绝不能 bringToFront（会弹用户窗口）。
const TARGETS = {
  9230: /melody\.shop\.ele\.me|shop\.ele\.me/,
  9231: /open\.shop\.ele\.me/,
  9232: /guoshuyufen\.com/,
  9233: /waimaie\.meituan\.com/,
};

const sleep = ms => new Promise(r => setTimeout(r, ms));

function openWs(wsUrl, ms) {
  return new Promise((res, rej) => {
    const ws = new WebSocket(String(wsUrl).replace('localhost', '127.0.0.1'));
    ws.addEventListener('open', () => res(ws), { once: true });
    ws.addEventListener('error', () => rej(new Error('ws-open-fail')), { once: true });
    setTimeout(() => rej(new Error('ws-open-timeout')), ms);
  });
}
function rpc(ws, method, params, ms) {
  const id = Math.floor(Math.random() * 1e9);
  return new Promise((resolve, reject) => {
    const on = e => { let d; try { d = JSON.parse(e.data); } catch { return; }
      if (d.id === id) { ws.removeEventListener('message', on); clearTimeout(t); resolve(d); } };
    const t = setTimeout(() => { ws.removeEventListener('message', on); reject(new Error('timeout:' + method)); }, ms);
    ws.addEventListener('message', on);
    ws.send(JSON.stringify({ id, method, params: params || {} }));
  });
}
async function responsive(wsUrl, ms) {
  try {
    const ws = await openWs(wsUrl, 5000);
    await rpc(ws, 'Runtime.evaluate', { expression: '1+1', returnByValue: true }, ms);
    try { ws.close(); } catch {}
    return true;
  } catch { return false; }
}
// 读取可见性：返回 {v,w,h} 或 null（超时/取不到）。
async function visibility(wsUrl, ms) {
  try {
    const ws = await openWs(wsUrl, 5000);
    const r = await rpc(ws, 'Runtime.evaluate',
      { expression: '(()=>JSON.stringify({v:document.visibilityState,w:innerWidth,h:innerHeight}))()', returnByValue: true }, ms);
    try { ws.close(); } catch {}
    const val = r.result && r.result.result && r.result.result.value;
    if (typeof val !== 'string') return null;
    return JSON.parse(val);
  } catch { return null; }
}
async function bringToFront(wsUrl, ms) {
  const ws = await openWs(wsUrl, 5000);
  await rpc(ws, 'Page.bringToFront', {}, ms).catch(() => {});
  try { ws.close(); } catch {}
}

async function probePort(port) {
  const out = { port, role: ROLES[port] || '', cdp: false, pages: 0,
    hung: [], reloaded: [], stillHung: [],
    blind: [], unblinded: [], stillBlind: [] };
  let list;
  try {
    const ctrl = new AbortController();
    const to = setTimeout(() => ctrl.abort(), 2500);
    const r = await fetch(`http://127.0.0.1:${port}/json/list`, { headers: { Host: 'localhost' }, signal: ctrl.signal });
    clearTimeout(to);
    list = await r.json();
    out.cdp = true;
  } catch { return out; }
  const pages = (Array.isArray(list) ? list : []).filter(t => t && t.type === 'page');
  out.pages = pages.length;
  for (const p of pages) {
    const alive = await responsive(p.webSocketDebuggerUrl, 5000);
    if (!alive) {
      out.hung.push({ title: String(p.title || '').slice(0, 40), url: String(p.url || '').slice(0, 90),
        _ws: p.webSocketDebuggerUrl });
      continue;
    }
    // 仅对**岗位流程页**做可见性判定/自愈（非流程 tab 的 hidden 属正常，不打扰）。
    const isTarget = TARGETS[port] ? TARGETS[port].test(String(p.url || '')) : false;
    if (isTarget) {
      const v = await visibility(p.webSocketDebuggerUrl, 5000);
      if (v && (v.v === 'hidden' || !v.w || !v.h)) {
        out.blind.push({ title: String(p.title || '').slice(0, 40), url: String(p.url || '').slice(0, 90),
          vis: v.v, iw: v.w, ih: v.h, _ws: p.webSocketDebuggerUrl });
      }
    }
  }
  if (APPLY && out.hung.length) {
    for (const h of out.hung) {
      try {
        const ws = await openWs(h._ws, 5000);
        await rpc(ws, 'Page.reload', { ignoreCache: true }, 8000).catch(() => {});
        try { ws.close(); } catch {}
        out.reloaded.push({ title: h.title, url: h.url });
      } catch (e) { out.reloaded.push({ title: h.title, ok: false, err: e.message }); }
    }
    await sleep(3000);
    for (const h of out.hung) {
      const ok = await responsive(h._ws, 6000);
      if (!ok) out.stillHung.push({ title: h.title, url: h.url });
    }
  }
  if (APPLY && out.blind.length) {
    for (const b of out.blind) {
      try { await bringToFront(b._ws, 6000); out.unblinded.push({ title: b.title }); }
      catch (e) { out.unblinded.push({ title: b.title, ok: false, err: e.message }); }
    }
    await sleep(1500);
    for (const b of out.blind) {
      const v = await visibility(b._ws, 5000);
      if (!(v && v.v === 'visible' && v.w > 0)) out.stillBlind.push({ title: b.title, url: b.url });
    }
  }
  for (const h of out.hung) delete h._ws;
  for (const b of out.blind) delete b._ws;
  return out;
}

async function main() {
  const results = [];
  for (const port of PORTS) results.push(await probePort(port));
  const anyHung = results.some(r => r.hung.length);
  const anyBlind = results.some(r => r.blind.length);
  const anyStillHung = results.some(r => r.stillHung.length);
  const anyStillBlind = results.some(r => r.stillBlind.length);
  const data = { at: new Date().toISOString(), apply: APPLY,
    anyHung, anyBlind, anyStillHung, anyStillBlind,
    ports: results.map(r => ({ port: r.port, role: r.role, cdp: r.cdp, pages: r.pages,
      hung: r.hung.length, reloaded: r.reloaded.length, stillHung: r.stillHung.length,
      blind: r.blind.length, unblinded: r.unblinded.length, stillBlind: r.stillBlind.length })) };
  if (JSON_OUT) process.stdout.write(JSON.stringify(data) + '\n');
  else {
    console.log(`post-page-probe ${data.at} apply=${APPLY}`);
    for (const r of results) {
      const flags = [];
      if (!r.cdp) flags.push('CDP-不可达');
      else {
        flags.push(r.hung.length ? `HUNG×${r.hung.length}` : 'alive');
        if (r.blind.length) flags.push(`BLIND×${r.blind.length}${r.unblinded.length ? '→fixed' + r.unblinded.length : ''}`);
        if (r.stillHung.length) flags.push(`stillHung×${r.stillHung.length}`);
        if (r.stillBlind.length) flags.push(`stillBlind×${r.stillBlind.length}`);
      }
      console.log(`  :${r.port} ${r.role.padEnd(20)} pages=${r.pages} ${flags.join(' ')}`);
    }
  }
  process.exit((anyStillHung || anyStillBlind) ? 3 : 0);
}

main().catch(e => { console.log(JSON.stringify({ error: e.message })); process.exit(1); });
