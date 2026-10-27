/** 抓「打开切店弹层」那一次的接口（树数据可能是打开时一次性拉全） */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
const reqs = new Map();
s.cdp.on('Network.requestWillBeSent', (p) => reqs.set(p.requestId, { url: p.request.url, method: p.request.method, type: p.type, post: p.request.postData || '' }));
s.cdp.on('Network.responseReceived', (p) => { const r = reqs.get(p.requestId); if (r) { r.status = p.response.status; r.mime = p.response.mimeType; } });
await s.cdp.send('Network.enable', { maxTotalBufferSize: 300 * 1024 * 1024, maxResourceBufferSize: 30 * 1024 * 1024 });
await s.rearm();

// 1) 先关掉已开的弹层
await s.mainEval(`document.body.click()`);
await sleep(800);
const stillOpen = await s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`);
if (stillOpen) { await s.mainEval(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',keyCode:27,bubbles:true}))`); await sleep(800); }
console.log('OPEN_BEFORE=' + (await s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`)));

reqs.clear();
// 2) 重新打开弹层
const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
await s.clickAt(SW.x, SW.y);
await sleep(3500);
console.log('OPEN_AFTER=' + (await s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`)));

const dump = [];
for (const [id, r] of reqs) {
  if (!r.status) continue;
  let body = '';
  try { const b = await s.cdp.send('Network.getResponseBody', { requestId: id }, 15000); body = b.base64Encoded ? Buffer.from(b.body, 'base64').toString('utf8') : b.body; } catch {}
  dump.push({ url: r.url, method: r.method, status: r.status, size: body.length, hasShop: /shop|SHOP|店铺/.test(body), body: body.length < 200000 ? body : body.slice(0, 1000) });
}
fs.writeFileSync('.recon/net_open_dump.json', JSON.stringify(dump, null, 1));
console.log('REQ=' + reqs.size + ' DUMP=' + dump.length);
for (const x of dump) console.log(`${x.hasShop ? '★' : ' '} ${x.status} ${x.size}B ${x.method} ${x.url.slice(0, 160)}`);
s.cdp.close();
process.exit(0);
