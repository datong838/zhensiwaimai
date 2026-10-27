#!/usr/bin/env node
/** 诊断25：在 iframe 内定位 tab 并逐个进入（总览/流量/商品/服务），输出锚点 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR'); process.exit(1); }
const ev = s.frameEval(r.id);
const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));

const findTabs = () => ev(`(()=>{
  const names=['总览','市场','订单','营销','流量','推广','顾客','商品','服务'];
  const out=[];
  for(const t of names){
    const c=[...document.querySelectorAll('*')].filter(n=>{
      const s=(n.innerText||'').trim();
      const r=n.getBoundingClientRect();
      return s===t && n.children.length<=1 && r.width>0 && r.width<140 && r.height>12 && r.y<200;
    }).map(n=>{const r=n.getBoundingClientRect();return {t,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),cls:(n.className||'').toString().split(' ')[0]}});
    if(c.length) out.push(c[0]);
  }
  return JSON.stringify(out);
})()`);

const tabs = JSON.parse(await findTabs());
console.log('TABS=' + JSON.stringify(tabs));

const dump = async (name) => {
  const info = await ev(`(()=>{
    const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
    const titles=[...document.querySelectorAll('[class*=title]')].filter(n=>{
      const t=(n.innerText||'').trim();
      const r=n.getBoundingClientRect();
      return t && t.length<16 && t.indexOf('\\n')<0 && r.width>0 && r.width<320 && !/\\d/.test(t);
    }).map(n=>({t:(n.innerText||'').trim(),cls:(n.className||'').toString().split(' ')[0],docY:docY(n),x:Math.round(n.getBoundingClientRect().x)}));
    const seen=new Set();const uniq=[];
    for(const o of titles){const k=o.t+'|'+o.docY;if(seen.has(k))continue;seen.add(k);uniq.push(o);}
    const ctrls=[...document.querySelectorAll('.ant-select-selection-item,.ant-radio-button-wrapper,.one_option')].filter(n=>n.getBoundingClientRect().width>0)
      .map(n=>({t:(n.innerText||'').trim().slice(0,12),cls:(n.className||'').toString().split(' ')[0],docY:docY(n)}));
    return JSON.stringify({tab:new URLSearchParams(location.hash.split('?')[1]||'').get('tab'),scrollH:document.documentElement.scrollHeight,titles:uniq.slice(0,30),ctrls:ctrls.slice(0,14)},null,1);
  })()`);
  console.log('=== ' + name + ' ===\n' + info);
  const d = await s.cdp.send('Page.captureScreenshot', { format: 'png', clip: { x: box.x, y: box.y, width: box.w, height: 700, scale: 1 } });
  fs.writeFileSync(`.recon/evidence/biz_${name}.png`, Buffer.from(d.data, 'base64'));
};

await dump('总览');
for (const name of ['流量', '商品', '服务']) {
  const t = tabs.find((x) => x.t === name);
  if (!t) { console.log('no-tab ' + name); continue; }
  await s.clickAt(box.x + t.x, box.y + t.y);
  await sleep(4000);
  await dump(name);
}
s.cdp.close();
process.exit(0);
