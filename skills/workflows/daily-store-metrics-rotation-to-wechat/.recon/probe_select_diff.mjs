#!/usr/bin/env node
/** 诊断20：对比 下单行为(可切) 与 互动行为(疑似静态) 的 .select 结构 */
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
const ev = s.frameEval(r.id);

const out = await ev(`(()=>{
  const pick=(scope)=>{const c=document.querySelector(scope);return c?[...c.querySelectorAll('.select')].map(n=>n.outerHTML.slice(0,300)):null};
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const list=[...document.querySelectorAll('.select')].map(n=>({docY:docY(n),html:n.outerHTML.slice(0,260),cls:(n.className||'').toString()}));
  return JSON.stringify({all:list,ob:pick('.order_behavior'),ib:pick('.interactive_behavior')},null,1);
})()`);
console.log(out);
s.cdp.close();
process.exit(0);
