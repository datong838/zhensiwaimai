#!/usr/bin/env node
// 9232 金鲨岗位 · 已知弹窗白名单覆盖率只读探针
// 用途：执行器 closeKnownJinshaPopup 只认 hasText:'新功能上线'（见 F11-4 缺陷单），
//       遇到其它文案会**静默**，既不计 pitfalls 也不抛错。
//       本探针用现成页面只读检查是否存在「未命中白名单」的可见 .upload 遮罩，
//       让「站点改文案」在当天被发现，而不是等上传失败后绕路定性。
// 铁律：**不开新标签页、不点任何元素、不改页面**（新开页会残留 task marker 堵死流程）。
// 用法: node jinsha_popup_probe.mjs [--port 9232] [--json]

import process from 'node:process';

const argv = process.argv.slice(2);
const getArg = (flag, dflt) => {
  const i = argv.indexOf(flag);
  return i >= 0 && argv[i + 1] ? argv[i + 1] : dflt;
};
const PORT = getArg('--port', '9232');
const JSON_OUT = argv.includes('--json');
const BASE = `http://127.0.0.1:${PORT}`;
const HDR = { headers: { Host: 'localhost' } };
// ★ 与 background_browser_executor.mjs closeKnownJinshaPopup 现有白名单保持一致
const KNOWN = ['新功能上线'];

const sleep = ms => new Promise(r => setTimeout(r, ms));

async function main() {
  const list = await fetch(`${BASE}/json/list`, HDR).then(r => r.json());
  const pages = list.filter(t => t.type === 'page');
  const target = pages.find(p => /uploadData|jinsha/i.test(p.url || '')) || pages[0];
  if (!target) {
    emit({ port: PORT, error: 'no-page', hits: [] });
    return;
  }
  const meta = { port: PORT, title: (target.title || '').slice(0, 40), url: (target.url || '').slice(0, 120) };

  const ws = new WebSocket(target.webSocketDebuggerUrl.replace('localhost', '127.0.0.1'));
  await new Promise((res, rej) => {
    ws.addEventListener('open', res, { once: true });
    ws.addEventListener('error', () => rej(new Error('ws-open-fail')), { once: true });
    setTimeout(() => rej(new Error('ws-open-timeout')), 8000);
  });
  let id = 0;
  const rpc = (method, params) => new Promise((resolve, reject) => {
    const my = ++id;
    ws.send(JSON.stringify({ id: my, method, params: params || {} }));
    const on = e => {
      let d;
      try { d = JSON.parse(e.data); } catch { return; }
      if (d.id === my) { ws.removeEventListener('message', on); clearTimeout(t); resolve(d); }
    };
    const t = setTimeout(() => { ws.removeEventListener('message', on); reject(new Error('timeout:' + method)); }, 15000);
    ws.addEventListener('message', on);
  });

  // 近似 Playwright 的 :visible（有尺寸、非 hidden、非 display:none）
  const expr = `(() => {
    const vis = el => { const st = getComputedStyle(el); const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && st.visibility !== 'hidden' && st.display !== 'none'; };
    const hits = Array.from(document.querySelectorAll('.upload')).filter(vis);
    return JSON.stringify(hits.map(el => ({
      cls: String(el.className || '').slice(0, 60),
      text: String(el.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 200),
    })));
  })()`;
  const r = await rpc('Runtime.evaluate', { expression: expr, returnByValue: true });
  const raw = r.result?.result?.value || '[]';
  let hits = [];
  try { hits = JSON.parse(raw); } catch { hits = []; }
  hits = hits.map(h => ({ ...h, known: KNOWN.some(k => (h.text || '').includes(k)) }));
  try { ws.close(); } catch { /* noop */ }
  emit({ ...meta, hits, overlays: hits.length, unknownCount: hits.filter(h => !h.known).length });
}

function emit(data) {
  if (JSON_OUT) {
    process.stdout.write(JSON.stringify(data) + '\n');
    return;
  }
  console.log(`金鲨弹窗白名单探针 :${data.port}`);
  if (data.error) { console.log(' 错误:', data.error); return; }
  console.log(' 目标页:', data.title, '|', data.url);
  console.log(' 可见 .upload 元素数:', data.hits.length);
  (data.hits || []).forEach((h, i) => {
    console.log(`  [${i}] known=${h.known ? 'YES' : 'NO '} | cls=${h.cls} | text=${(h.text || '').slice(0, 80) || '(空)'}`);
  });
  console.log(' 结论:', data.hits.length === 0
    ? '无遮罩（常态）'
    : (data.unknownCount === 0 ? '有遮罩但全部命中白名单' : `⚠️ ${data.unknownCount} 个未命中白名单 ⇒ 执行器会静默放过`));
}

if (process.argv[1] && process.argv[1].endsWith('jinsha_popup_probe.mjs')) {
  main().then(() => sleep(50)).then(() => process.exit(0))
    .catch(e => { emit({ port: PORT, error: e.message, hits: [] }); process.exit(1); });
}
