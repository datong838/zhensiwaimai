#!/usr/bin/env node
/**
 * 批量探测：降级搜索策略的真实命中率
 * 用法: probe_batch.mjs <in.json> [out.json] [limit]
 * 输入 JSON: [{shopName, wmPoiId, acctId}, ...]
 *
 * 判据统一走 scripts/lib/shop_match.mjs（与生产 switch_shop 同一份，不许各写一套）
 */
import fs from 'node:fs';
import { session, sleep } from '../scripts/lib/cdp.mjs';
import { keywordsFor, judge } from '../scripts/lib/shop_match.mjs';

const inFile = process.argv[2];
const outFile = process.argv[3] || '.recon/tier_results.json';
const limit = Number(process.argv[4] || 0);
if (!inFile) { console.error('usage: probe_batch.mjs <in.json> [out.json] [limit]'); process.exit(2); }

let rows = JSON.parse(fs.readFileSync(inFile, 'utf8'));
if (limit) rows = rows.slice(0, limit);

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();

const INPUT_SEL = `[...document.querySelectorAll('input')].find(n=>n.placeholder==='搜索店铺名称/ID')`;
const isOpen = () => s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`);

async function ensureOpen() {
  if (await isOpen()) return true;
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');if(!n)return 'nf';const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  if (SW === 'nf') return false;
  await s.clickAt(SW.x, SW.y);
  await sleep(1600);
  return await isOpen();
}

async function search(kw) {
  await s.mainEval(`(()=>{
    const n=${INPUT_SEL}; if(!n) return 'nf';
    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
    n.focus();
    setter.call(n, ${JSON.stringify('')}); n.dispatchEvent(new Event('input',{bubbles:true}));
    setter.call(n, ${JSON.stringify(kw)}); n.dispatchEvent(new Event('input',{bubbles:true}));
    return n.value;
  })()`);
  await sleep(2600);
  const r = await s.mainEval(`(()=>{
    const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
    if(!dd) return JSON.stringify({n:0,rows:[]});
    const STATUS=/营业中|已下线|暂停营业|已打烊/;
    const cands=[...dd.querySelectorAll('div,a,li')].filter(n=>{
      if(/cook-cascader-menu-item/.test((n.className||'').toString())) return false;
      const t=(n.innerText||'').trim();
      const rc=n.getBoundingClientRect();
      if(!t||!STATUS.test(t)) return false;
      if(rc.width<150||rc.height<20||rc.height>90) return false;
      if(n.children.length>5) return false;
      return true;
    });
    const seen=new Set(); const out=[];
    for(const n of cands){
      const t=(n.innerText||'').replace(/\\s+/g,'|').trim().split('|')[0];
      if(seen.has(t)) continue; seen.add(t);
      out.push(t);
    }
    return JSON.stringify({n:out.length, rows:out.slice(0,50)});
  })()`);
  return JSON.parse(r);
}

if (!(await ensureOpen())) { console.error('FAIL popup'); process.exit(4); }

const out = [];
const stat = { id: 0, full: 0, body: 0, brand: 0, miss: 0, weak: 0 };
for (let i = 0; i < rows.length; i++) {
  const r = rows[i];
  const T = r.shopName;
  const rec = { shopName: T, wmPoiId: r.wmPoiId, acctId: r.acctId, layer: r.layer, tiers: [] };

  const tiers = [];
  if (r.wmPoiId) tiers.push(['id', String(r.wmPoiId)]);
  const seen = new Set(tiers.map((x) => x[1]));
  tiers.push(['full', T]);
  seen.add(T);
  keywordsFor(T).forEach((k, idx) => {
    if (seen.has(k)) return;
    seen.add(k);
    tiers.push([idx === 0 ? 'body' : 'brand', k]);
  });

  let hit = null;
  for (const [tier, kw] of tiers) {
    const res = await search(kw);
    const v = judge(T, res.rows);
    rec.tiers.push({ tier, kw, n: res.n, ok: v.ok, why: v.why, pick: v.pick || null });
    if (v.ok) { hit = { tier, kw, ...v }; break; }
  }

  if (hit) {
    rec.verdict = `hit:${hit.tier}:${hit.why}`;
    rec.pick = hit.pick;
    if (hit.weak) stat.weak++;
    stat[hit.tier] = (stat[hit.tier] || 0) + 1;
  } else {
    const last = rec.tiers[rec.tiers.length - 1];
    rec.verdict = `miss:${last ? last.why : 'n/a'}`;
    stat.miss++;
  }

  out.push(rec);
  console.log(`[${i + 1}/${rows.length}] L${r.layer || '?'} ${T} → ${rec.verdict}` + (rec.pick ? ` ⇒ ${rec.pick}` : ` (最后一级 n=${rec.tiers[rec.tiers.length - 1].n}, why=${rec.tiers[rec.tiers.length - 1].why})`));
}

fs.writeFileSync(outFile, JSON.stringify(out, null, 1));
const n = rows.length;
console.log(`\nSUMMARY total=${n} ` + Object.entries(stat).map(([k, v]) => `${k}=${v}`).join(' '));
console.log(`命中率 = ${((n - stat.miss) / n * 100).toFixed(1)}%  (weak=${stat.weak})`);
s.cdp.close();
process.exit(0);
