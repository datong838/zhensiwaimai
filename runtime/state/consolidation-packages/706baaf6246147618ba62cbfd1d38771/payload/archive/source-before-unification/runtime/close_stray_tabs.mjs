#!/usr/bin/env node
// close_stray_tabs.mjs —— 受控关闭某岗位 CDP 里的「干扰页」（非流程页的杂散 tab）。
//
// 背景：2026-10-10 发现 9230（淘宝品牌岗）里混入 3 个 auth.openai.com/oauth 登录页，
//   与 1 个正常业务页并存。杂散页会：① 让岗位页数统计失真；② 个别站点挂起时拖累整浏览器。
//   ——需要一个「只关干扰页、绝不误关流程页」的受控入口。
//
// 铁律（安全设计）：
//   1) 必须显式给 --match <regex>，只考虑 URL 命中该正则的页；
//   2) 命中 --match 但同时命中该岗位「流程目标页」正则的，一律跳过（双重保险，永不误关）；
//   3) 默认 dry-run，仅 --apply 才真正关闭；关闭用 CDP Target.closeTarget（只关指定 target）；
//   4) 关闭前先取岗位锁（复用各岗位 lease），业务在跑 ⇒ busy 跳过，绝不与运行中的流抢浏览器；
//   5) 绝不新开 tab、绝不点击、绝不发送任何外发消息。
//
// 用法: node close_stray_tabs.mjs --port 9230 --match 'auth\.openai\.com' [--apply] [--json]

import process from 'node:process';

const argv = process.argv.slice(2);
const APPLY = argv.includes('--apply');
const JSON_OUT = argv.includes('--json');
const getArg = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : null; };

const port = Number(getArg('--port'));
const matchStr = getArg('--match');
if (!port || !matchStr) {
  console.error('usage: node close_stray_tabs.mjs --port <9230> --match <regex> [--apply] [--json]');
  process.exit(2);
}
const MATCH = new RegExp(matchStr);

const ROOT = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
// 与 post_page_probe.mjs 保持一致的岗位流程目标页正则（用于「永不误关」守卫）。
const TARGETS = {
  9230: /melody\.shop\.ele\.me|shop\.ele\.me/,
  9231: /open\.shop\.ele\.me/,
  9232: /guoshuyufen\.com/,
  9233: /waimaie\.meituan\.com/,
};
// 与 session_keepalive.mjs 一致的岗位锁（业务在跑则跳过）。
const LEASES = {
  9230: { mod: `${ROOT}/skills/posts/taobao-brand-post/scripts/lease.mjs`, acquire: 'acquirePostLease', release: 'releasePostLease', path: '/tmp/zhensi-post-9230.lock' },
  9231: { mod: `${ROOT}/skills/posts/taobao-svc-post/scripts/lease.mjs`, acquire: 'acquirePostLease', release: 'releasePostLease', path: '/tmp/zhensi-post-9231.lock' },
  9232: { mod: `${ROOT}/skills/posts/jinsha-post/scripts/lease.mjs`, acquire: 'acquireJinshaLease', release: 'releaseJinshaLease', path: '/tmp/zhensi-jinsha-cua-exam.lock' },
  9233: { mod: `${ROOT}/skills/posts/meituan-post/scripts/lease.mjs`, acquire: 'acquirePostLease', release: 'releasePostLease', path: '/tmp/zhensi-post-9233.lock' },
};

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

async function listPages(p) {
  const ctrl = new AbortController();
  const to = setTimeout(() => ctrl.abort(), 3000);
  const r = await fetch(`http://127.0.0.1:${p}/json/list`, { headers: { Host: 'localhost' }, signal: ctrl.signal });
  clearTimeout(to);
  const arr = await r.json();
  return (Array.isArray(arr) ? arr : []).filter(t => t && t.type === 'page');
}

async function browserWsUrl(p) {
  const ctrl = new AbortController();
  const to = setTimeout(() => ctrl.abort(), 3000);
  const r = await fetch(`http://127.0.0.1:${p}/json/version`, { headers: { Host: 'localhost' }, signal: ctrl.signal });
  clearTimeout(to);
  const j = await r.json();
  // Chrome 返回的 ws 地址只带 Host（无端口），按目标端口重建。
  let path = '/devtools/browser';
  try { path = new URL(j.webSocketDebuggerUrl).pathname; } catch {}
  return `ws://127.0.0.1:${p}${path}`;
}

async function main() {
  const out = { at: new Date().toISOString(), port, match: matchStr, apply: APPLY,
    busy: false, total: 0, stray: [], closed: [], skipped: [], remaining: [] };
  const lease = LEASES[port];
  let leaseMod = null, held = null;
  if (lease) {
    try {
      leaseMod = await import(lease.mod);
      held = await leaseMod[lease.acquire](`close-stray-${Date.now()}`, lease.path, 3 * 60 * 1000);
      if (!held) { out.busy = true; emit(out); process.exit(0); }
    } catch (e) { out.leaseError = String(e?.message || e); }
  }
  try {
    const pages = await listPages(port);
    out.total = pages.length;
    for (const pg of pages) {
      const url = String(pg.url || '');
      const hitMatch = MATCH.test(url);
      const hitTarget = TARGETS[port] ? TARGETS[port].test(url) : false;
      const rec = { id: pg.id, title: String(pg.title || '').slice(0, 60), url: url.slice(0, 110) };
      if (hitMatch && !hitTarget) out.stray.push(rec);
      else if (hitMatch && hitTarget) out.skipped.push({ ...rec, why: '命中 --match 但同时是流程目标页，跳过' });
      else out.remaining.push(rec);
    }
    if (APPLY && out.stray.length) {
      const ws = await openWs(await browserWsUrl(port), 5000);
      for (const s of out.stray) {
        try {
          const r = await rpc(ws, 'Target.closeTarget', { targetId: s.id }, 6000);
          out.closed.push({ ...s, ok: r.result ? r.result.success !== false : true });
        } catch (e) { out.closed.push({ ...s, ok: false, err: e.message }); }
      }
      try { ws.close(); } catch {}
      await new Promise(r => setTimeout(r, 1200));
      const after = await listPages(port);
      out.pagesAfter = after.length;
      out.pagesAfterList = after.map(pg => ({ title: String(pg.title || '').slice(0, 40), url: String(pg.url || '').slice(0, 100) }));
    }
  } finally {
    if (leaseMod && held) await leaseMod[lease.release](held).catch(() => {});
  }
  emit(out);
  process.exit(0);
}

function emit(o) {
  if (JSON_OUT) process.stdout.write(JSON.stringify(o) + '\n');
  else {
    if (o.busy) { console.log(`:${o.port} BUSY —— 岗位锁被业务持有，跳过（未做任何事）`); return; }
    console.log(`close-stray-tabs :${o.port} apply=${o.apply} match=${o.match}`);
    console.log(`  页数=${o.total} 干扰页=${o.stray.length} 跳过=${o.skipped.length} 保留=${o.remaining.length}`);
    for (const s of o.stray) console.log(`  [关] ${s.title} | ${s.url}`);
    for (const s of o.skipped) console.log(`  [跳] ${s.title} | ${s.why}`);
    for (const s of o.remaining) console.log(`  [留] ${s.title} | ${s.url}`);
    if (o.apply) console.log(`  关闭后页数=${o.pagesAfter}`);
  }
}

main().catch(e => { console.log(JSON.stringify({ error: String(e?.message || e) })); process.exit(1); });
