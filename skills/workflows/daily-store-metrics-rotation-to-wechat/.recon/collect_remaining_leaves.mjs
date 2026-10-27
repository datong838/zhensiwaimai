/**
 * 补收 col0 里的「顶级单店」（dv 末尾是 SHOP:<id> 的行）
 * 这类行点了会切店并关闭弹层，所以不能点，直接读 data-value 收录。
 * 结果 merge 进既有 .runtime/store_pool_brand.json
 */
import fs from 'node:fs';
import path from 'node:path';
import { session, sleep } from '../scripts/lib/cdp.mjs';

const ROOT = path.resolve(import.meta.dirname, '..');
const FILE = process.argv[2] || path.join(ROOT, '.runtime/store_pool_brand.json');

const s = await session({ port: 9230, width: 1440, height: 1600 });
await s.rearm();

const open = await s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`);
if (!open) {
  const sw = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');const r=n.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)})})()`));
  await s.clickAt(sw.x, sw.y);
  await sleep(2500);
}
// 清空搜索
await s.mainEval(`(()=>{const n=[...document.querySelectorAll('input')].find(x=>x.placeholder==='搜索店铺名称/ID');if(!n)return 'nf';const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;n.focus();set.call(n,'');n.dispatchEvent(new Event('input',{bubbles:true}));return 'ok'})()`);
await sleep(2000);

const snap = JSON.parse(await s.mainEval(`(()=>{try{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({ok:false,why:'no-dd'});
  const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
  const items=[...cols[0].querySelectorAll('.cook-cascader-menu-item')];
  return JSON.stringify({ok:true, rows:items.map(n=>{
    const toks=(n.innerText||'').split(/\\n/).map(t=>t.trim()).filter(Boolean);
    return { name:toks[0]||'', status:toks[1]||'', dv:n.getAttribute('data-value')||'', arrow:/expand/.test(String(n.className)) };
  })});
}catch(e){return JSON.stringify({ok:false,why:e.message})}})()`));

if (!snap.ok) { console.log('FAIL', JSON.stringify(snap)); process.exit(4); }

const leaves = snap.rows.filter((r) => /SHOP:(\d+)/.test(r.dv) && !r.arrow);
console.log('COL0_TOTAL=' + snap.rows.length + ' LEAF_SHOPS=' + leaves.length);

const doc = JSON.parse(fs.readFileSync(FILE, 'utf8'));
const have = new Set(doc.shops.map((x) => String(x.shopId)));
const added = [];
for (const r of leaves) {
  const id = /SHOP:(\d+)/.exec(r.dv)[1];
  if (have.has(id)) continue;
  have.add(id);
  added.push({
    shopId: Number(id),
    shopName: r.name,
    status: r.status || '',
    orgPath: r.name,
    orgLabel: r.name,
    acctId: (/ACCOUNT_ROOT:(\d+)/.exec(r.dv) || [])[1] || null,
    branchPath: [],
    source: 'top-level-single-shop',
  });
}
doc.shops.push(...added);
doc.leavesRecovered = added.length;
doc.total = doc.shops.length;
doc.openCount = doc.shops.filter((x) => /营业中/.test(x.status)).length;
fs.writeFileSync(FILE, JSON.stringify(doc, null, 1));
console.log('ADDED=' + added.length + ' TOTAL=' + doc.total + ' OPEN=' + doc.openCount);
console.log(added.slice(0, 3).map((x) => `${x.shopId} ${x.shopName} ${x.status}`).join('\n'));
s.cdp.close();
process.exit(0);
