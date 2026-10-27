/** 页面加载期抓全部请求，定位「店铺树」接口（一次性拿全 52 组织 + 1992 店） */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
const reqs = new Map();
s.cdp.on('Network.requestWillBeSent', (p) => reqs.set(p.requestId, { url: p.request.url, method: p.request.method, type: p.type, post: p.request.postData || '' }));
s.cdp.on('Network.responseReceived', (p) => { const r = reqs.get(p.requestId); if (r) { r.status = p.response.status; r.mime = p.response.mimeType; } });
await s.cdp.send('Network.enable', { maxTotalBufferSize: 400 * 1024 * 1024, maxResourceBufferSize: 40 * 1024 * 1024 });
await s.rearm();
reqs.clear();

await s.cdp.send('Page.reload', { ignoreCache: false });
await sleep(12000);
try { await s.rearm(); } catch {}
await sleep(3000);

const dump = [];
for (const [id, r] of reqs) {
  if (!r.status || r.status >= 400) continue;
  if (!/json|javascript|text/i.test(r.mime || '')) continue;
  let body = '';
  try { const b = await s.cdp.send('Network.getResponseBody', { requestId: id }, 20000); body = b.base64Encoded ? Buffer.from(b.body, 'base64').toString('utf8') : b.body; } catch { continue; }
  const hasShopWord = /"shopId"|"shopName"|SHOP|店铺/.test(body);
  dump.push({ url: r.url, method: r.method, status: r.status, size: body.length, hasShopWord, keep: hasShopWord ? body : body.slice(0, 300) });
}
fs.writeFileSync('.recon/net_reload_dump.json', JSON.stringify(dump, null, 1));
const hits = dump.filter((x) => x.hasShopWord).sort((a, b) => b.size - a.size);
console.log('REQ=' + reqs.size + ' JSON_DUMP=' + dump.length + ' SHOP_HITS=' + hits.length);
for (const x of hits.slice(0, 20)) console.log(`★ ${x.status} ${x.size}B ${x.method} ${x.url.slice(0, 170)}`);
console.log('--- 无店铺特征但体积>5KB 的 ---');
for (const x of dump.filter((y) => !y.hasShopWord && y.size > 5000).slice(0, 20)) console.log(`  ${x.status} ${x.size}B ${x.url.slice(0, 170)}`);
s.cdp.close();
process.exit(0);
