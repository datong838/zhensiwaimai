#!/usr/bin/env node
/** 诊断26：经营分析四 tab 的模块锚点（含 自然流量 关键字定位） */
import { session, sleep } from '../scripts/lib/cdp.mjs';

const KEYS = ['历史数据概览', '订单分析', '流量分析', '顾客分析', '流量转化', '流量趋势',
  '自然流量', '流量来源', '商品明细', '商品分类', '数据概览', '营业分析', '出餐时效',
  '纠纷单分析', '接单分析', '取消单'];

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR'); process.exit(1); }
const ev = s.frameEval(r.id);
const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));

const findTabs = () => ev(`(()=>{
  const names=['总览','市场','订单','营销','流量','推广','顾客','商品','服务'];
  const out=[];
  for(const t of names){
    const c=[...document.querySelectorAll('*')].filter(n=>{
      const s=(n.innerText||'').trim();const r=n.getBoundingClientRect();
      return s===t && n.children.length<=1 && r.width>0 && r.width<140 && r.height>12 && r.y<200;
    }).map(n=>{const r=n.getBoundingClientRect();return {t,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)}});
    if(c.length) out.push(c[0]);
  }
  return JSON.stringify(out);
})()`);

const dumpKeys = () => ev(`(()=>{
  const K=${JSON.stringify(KEYS)};
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const out=[];
  const seen=new Set();
  document.querySelectorAll('*').forEach(n=>{
    if(n.children.length>2) return;
    const t=(n.innerText||'').trim();
    if(!t||t.length>24) return;
    if(!K.some(k=>t.indexOf(k)>=0)) return;
    const r=n.getBoundingClientRect();
    if(!r.width) return;
    const k=t+'|'+Math.round(r.y+window.scrollY)+'|'+Math.round(r.x);
    if(seen.has(k)) return; seen.add(k);
    out.push({t,docY:Math.round(r.y+window.scrollY),x:Math.round(r.x),w:Math.round(r.width)});
  });
  out.sort((a,b)=>a.docY-b.docY||a.x-b.x);
  const tab=new URLSearchParams(location.hash.split('?')[1]||'').get('tab');
  return JSON.stringify({tab,scrollH:document.documentElement.scrollHeight,hits:out.slice(0,40)});
})()`);

const tabs = JSON.parse(await findTabs());
for (const name of ['总览', '流量', '商品', '服务']) {
  const t = tabs.find((x) => x.t === name);
  if (!t) { console.log('no-tab ' + name); continue; }
  await ev('window.scrollTo(0,0)');
  await s.clickAt(box.x + t.x, box.y + t.y);
  await sleep(4000);
  const d = JSON.parse(await dumpKeys());
  console.log('### ' + name + ' tab=' + d.tab + ' scrollH=' + d.scrollH);
  console.log(d.hits.map((h) => `${h.t}@${h.docY}(x${h.x})`).join(' | '));
}
s.cdp.close();
process.exit(0);
