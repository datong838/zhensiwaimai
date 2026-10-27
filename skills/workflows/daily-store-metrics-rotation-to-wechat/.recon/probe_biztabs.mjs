#!/usr/bin/env node
/** 诊断24：经营分析 各 tab 结构（总览/流量/商品/服务），为规则7-11定锚点 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
fs.mkdirSync('.recon/evidence', { recursive: true });
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR'); process.exit(1); }
const ev = s.frameEval(r.id);
const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y})})()`));

// tab 元素的真实 DOM（不是 .ant-tabs-tab）
const tabs = await s.mainEval(`(()=>{
  const names=['总览','市场','订单','营销','流量','推广','顾客','商品','服务'];
  const out=[];
  for(const t of names){
    const cands=[...document.querySelectorAll('*')].filter(n=>{
      const s=(n.innerText||'').trim();
      const r=n.getBoundingClientRect();
      return s===t && n.children.length<=1 && r.width>0 && r.width<120 && r.height>14 && r.y<160;
    }).map(n=>{const r=n.getBoundingClientRect();return {t,x:Math.round(r.x),y:Math.round(r.y),cls:(n.className||'').toString().split(' ')[0]}});
    if(cands.length) out.push(cands[0]);
  }
  return JSON.stringify(out);
})()`);
console.log('TABS=' + tabs);

const TAB = JSON.parse(tabs);
const clickTab = async (name) => {
  const t = TAB.find((x) => x.t === name);
  if (!t) return false;
  // tab 在外层文档里（HTML tab 属于外壳？）——先试外层坐标，失败再试 iframe 内
  await s.clickAt(t.x + 10, t.y + 10);
  await sleep(3500);
  return true;
};

const dumpTab = async (name) => {
  const info = await ev(`(()=>{
    const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
    const titles=[...document.querySelectorAll('.h3,.period_title,[class*=title]')].filter(n=>{
      const t=(n.innerText||'').trim();
      return t && t.length<14 && t.indexOf('\\n')<0 && n.getBoundingClientRect().width>0 && n.getBoundingClientRect().width<300;
    }).map(n=>({t:(n.innerText||'').trim(),cls:(n.className||'').toString().split(' ')[0],docY:docY(n),x:Math.round(n.getBoundingClientRect().x)}));
    const sels=[...document.querySelectorAll('.ant-select-selection-item,.ant-radio-button-wrapper,.one_option')].map(n=>({t:(n.innerText||'').trim(),cls:(n.className||'').toString().split(' ')[0],docY:docY(n)}));
    return JSON.stringify({url:location.href.split('#')[1],scrollH:document.documentElement.scrollHeight,titles:titles.slice(0,25),sels:sels.slice(0,15)},null,1);
  })()`);
  console.log('=== TAB ' + name + ' ===\n' + info);
  const d = await s.cdp.send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(`.recon/evidence/biz_${name}.png`, Buffer.from(d.data, 'base64'));
};

await dumpTab('总览');
for (const t of ['流量', '商品', '服务']) {
  const ok = await clickTab(t);
  if (!ok) { console.log('tab-not-found ' + t); continue; }
  await dumpTab(t);
}
s.cdp.close();
process.exit(0);
