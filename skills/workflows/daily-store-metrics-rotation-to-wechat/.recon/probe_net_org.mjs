/**
 * 抓「切店弹层」展开时的网络请求，判断店铺树是否走接口拿
 * 目的：避免 1992 家店靠点击 24 次展开，优先找一次性接口
 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
const reqs = new Map();
s.cdp.on('Network.requestWillBeSent', (p) => {
  if (!/XHR|Fetch/.test(p.type || '')) return;
  reqs.set(p.requestId, { url: p.request.url, method: p.request.method, type: p.type, post: p.request.postData || '' });
});
s.cdp.on('Network.responseReceived', (p) => {
  const r = reqs.get(p.requestId);
  if (r) { r.status = p.response.status; r.mime = p.response.mimeType; }
});
await s.cdp.send('Network.enable', { maxTotalBufferSize: 200 * 1024 * 1024, maxResourceBufferSize: 20 * 1024 * 1024 });
await s.rearm();

const isOpen = () => s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`);
if (!(await isOpen())) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  await s.clickAt(SW.x, SW.y);
  await sleep(1800);
}
// 清空搜索
await s.mainEval(`(()=>{
  const n=[...document.querySelectorAll('input')].find(x=>x.placeholder==='搜索店铺名称/ID');
  if(!n) return 'nf';
  const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
  n.focus(); set.call(n,''); n.dispatchEvent(new Event('input',{bubbles:true})); return 'ok';
})()`);
await sleep(1500);

const clickItem = async (depth, want) => {
  const w = JSON.stringify(want);
  const hit = JSON.parse(await s.mainEval(`(()=>{
    const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
    if(!dd) return JSON.stringify({found:false,why:'no-dd'});
    const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
    const col=cols[${depth}];
    if(!col) return JSON.stringify({found:false,why:'no-col',cols:cols.length});
    const items=[...col.querySelectorAll('.cook-cascader-menu-item')];
    const toks=(n)=>(n.innerText||'').split(/\\s+/).map(t=>t.trim()).filter(Boolean);
    const item=items.find(n=>toks(n).some(t=>t===${w}));
    if(!item) return JSON.stringify({found:false,why:'no-match'});
    const r=item.getBoundingClientRect();
    return JSON.stringify({found:true,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)});
  })()`));
  if (!hit.found) throw new Error('click-fail depth=' + depth + ' ' + JSON.stringify(hit));
  await s.clickAt(hit.x, hit.y);
  await sleep(3000);
};

await clickItem(0, '刘欢');
await clickItem(1, '2');
await sleep(2000);

// dump 所有 XHR 响应体里含店铺特征的
const out = [];
for (const [id, r] of reqs) {
  if (!r.status || r.status >= 400) continue;
  let body = '';
  try {
    const b = await s.cdp.send('Network.getResponseBody', { requestId: id }, 15000);
    body = b.base64Encoded ? Buffer.from(b.body, 'base64').toString('utf8') : b.body;
  } catch (e) { continue; }
  const hasShop = /SHOP|shopId|店铺/.test(body);
  out.push({ url: r.url, method: r.method, status: r.status, size: body.length, hasShop, sample: body.slice(0, 300) });
}
fs.writeFileSync('.recon/net_org_dump.json', JSON.stringify(out, null, 1));
console.log('REQ_TOTAL=' + reqs.size + ' DUMP=' + out.length + ' HAS_SHOP=' + out.filter((x) => x.hasShop).length);
for (const x of out) console.log(`${x.hasShop ? '★' : ' '} ${x.status} ${x.size}B ${x.url.slice(0, 150)}`);
s.cdp.close();
process.exit(0);
