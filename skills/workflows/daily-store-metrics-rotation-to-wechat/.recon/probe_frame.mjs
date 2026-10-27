#!/usr/bin/env node
/** 诊断7：用 frameId 绑定的 context 读 customerStats 真实内容 */
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.log('CTX_ERR=' + JSON.stringify(r)); process.exit(1); }
const ev = s.frameEval(r.id);
console.log('FRAME_URL=' + r.url);
console.log('INNER_URL=' + await ev('location.href'));
console.log('READY=' + await ev(`String(document.readyState)+' cards='+document.querySelectorAll('.card-border').length`));
console.log('CARDS=' + await ev(`JSON.stringify([...document.querySelectorAll('.card-border')].map(n=>(n.className||'').toString().replace('card-border','').trim()+'|h='+Math.round(n.getBoundingClientRect().height)+'|'+((n.innerText||'').trim().replace(/\\s+/g,' ').slice(0,16))))`));
console.log('BLOCK_CNT=' + await ev(`String((document.body.innerText.match(/街区/g)||[]).length)`));
console.log('OVERVIEW_HEAD=' + await ev(`(()=>{const n=document.querySelector('.customer_analysis');if(!n)return 'nf';return n.innerText.replace(/\\s+/g,' ').slice(0,150)})()`));
console.log('LIST_ROWS=' + await ev(`String(document.querySelectorAll('.customer_list .ant-table-row').length)`));
console.log('TOPNAME=' + await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`));
s.cdp.close();
process.exit(0);
