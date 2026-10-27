#!/usr/bin/env node
// 只读检查 9230 页面 seed 判据（不点击、不导航）
const PORT = process.argv[2] || '9230';
const http = require('http');

function getJSON(path) {
  return new Promise((resolve, reject) => {
    http.get({ host: '127.0.0.1', port: PORT, path }, res => {
      let d = '';
      res.on('data', c => d += c);
      res.on('end', () => { try { resolve(JSON.parse(d)); } catch (e) { reject(e); } });
    }).on('error', reject);
  });
}

async function main() {
  const targets = await getJSON('/json/list');
  const pages = targets.filter(t => t.type === 'page' && !/devtools/.test(t.url));
  console.log('pages:', pages.length);
  for (const p of pages) console.log('  url:', p.url.slice(0, 120));

  const main = pages[0];
  if (!main) { console.log('NO_PAGE'); process.exit(0); }
  const WebSocket = require('ws');
  const ws = new WebSocket(main.webSocketDebuggerUrl, { maxPayload: 64 * 1024 * 1024 });
  let id = 0;
  const pending = new Map();
  const send = (method, params) => new Promise((res, rej) => {
    const mid = ++id;
    pending.set(mid, { res, rej });
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  ws.on('message', m => {
    const msg = JSON.parse(m);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id).res(msg.result || msg.error); pending.delete(msg.id); }
  });
  await new Promise(r => ws.on('open', r));

  const tree = await send('Page.getFrameTree');
  const frames = [];
  (function walk(f) { frames.push(f.frame); (f.childFrames || []).forEach(walk); })(tree.frameTree);
  console.log('--- frames ---');
  for (const f of frames) console.log(' ', (f.url || '').slice(0, 140));

  // 文本判据
  const ev = await send('Runtime.evaluate', { expression: 'document.body ? document.body.innerText.slice(0,3000) : ""', returnByValue: true });
  const txt = (ev.result && ev.result.value) || '';
  const marks = ['品牌版', '数据中心', '今日实时数据'];
  console.log('--- main text marks ---');
  for (const m of marks) console.log(`  ${m}: ${txt.includes(m)}`);

  const statsFrame = frames.find(f => /melody-stats-next\.ele\.me/.test(f.url || ''));
  const seedOk = !!statsFrame && (statsFrame.url || '').includes('#/chain/business-analysis') && marks.every(m => txt.includes(m));
  console.log('stats frame url:', statsFrame ? statsFrame.url : 'NONE');
  console.log('seed 完整判据:', seedOk);
  ws.close();
  process.exit(0);
}
main().catch(e => { console.error('ERR', e.message); process.exit(1); });
