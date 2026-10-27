/**
 * 从「切店弹层」的运营组织树里，抓全部店铺（shopId + 店铺名 + 营业状态）
 *
 * 设计要点（实测依据）：
 * 1. 每个候选行 data-value 末尾就是 SHOP:<id>，无需绕接口
 * 2. 展开某个节点后，它的**全部**子节点都渲染进 DOM（实测 2 号组织 293 家全在，无虚拟滚动）
 * 3. 只有带展开箭头(arrow)的节点才需要点击，店铺叶子不用点 ⇒ 点击次数 ≈ 组织节点数（几十次）
 * 4. 递归逐层：点 col[i] 的项 → 新列出现 → 读新列
 * 5. 幂等/可续跑：每扫完一个组织就落一次盘
 *
 * 用法：node scripts/collect_shop_pool_brand.mjs [--max-orgs N] [--out path]
 */
import fs from 'node:fs';
import path from 'node:path';
import { session, sleep } from './lib/cdp.mjs';
import crypto from 'node:crypto';
import {acquirePostLease,releasePostLease} from '../../../posts/taobao-brand-post/scripts/lease.mjs';
import {validRosterRunId} from './release_roster_lease.mjs';

const arg = (k, d = null) => {
  const i = process.argv.indexOf('--' + k);
  return i >= 0 ? process.argv[i + 1] : d;
};
const ROOT = path.resolve(import.meta.dirname, '..');
const OUT = arg('out', path.join(ROOT, '.runtime/store_pool_brand.json'));
const MAX_ORGS = parseInt(arg('max-orgs', '0'), 10);
const CLICK_WAIT = parseInt(arg('click-wait', '2200'), 10);
const MAX_DEPTH = 6;

async function main() {
let lease=null,s;
try {
 try {const owner=JSON.parse(fs.readFileSync('/tmp/zhensi-post-9230.lock','utf8'));if(!Number.isInteger(owner.pid)||owner.pid<=0)throw Error('post-9230-owner-invalid');try{process.kill(owner.pid,0);throw Error('post-9230-live-owner-busy');}catch(e){if(e.code!=='ESRCH')throw e;}}catch(e){if(e.code!=='ENOENT')throw e;}
 const leaseRunId=arg('lease-run-id','monthly-roster-'+crypto.randomUUID());
 if(!validRosterRunId(leaseRunId))throw Error('roster-lease-run-id-invalid');
 lease=await acquirePostLease(leaseRunId);if(!lease)throw Error('post-9230-lease-busy');
s = await session({ port: 9230, width: 0 });
await s.rearm();
if(!await s.mainEval(`location.origin==='https://melody.shop.ele.me' && location.pathname.startsWith('/app/') && document.body.innerText.includes('gmfmmZH')`))throw Error('brand-account-not-confirmed');

const log = (...a) => console.log(...a);

/** 页面求值 + JSON 解析，带重试（SPA 重渲染瞬间可能拿到 undefined） */
const evalJson = async (expr, { tries = 3, wait = 1200 } = {}) => {
  let last = null;
  for (let k = 0; k < tries; k++) {
    const r = await s.cdp.send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
    const raw = r.result?.value;
    if (process.env.DBG && r.exceptionDetails) log('  [dbg ex]', JSON.stringify(r.exceptionDetails).slice(0, 400));
    if (typeof raw === 'string' && raw.trim().startsWith('{')) {
      try { return JSON.parse(raw); } catch (e) { last = 'parse:' + e.message; }
    } else {
      last = 'raw:' + typeof raw + ':' + String(raw).slice(0, 120);
      if (process.env.DBG) log('  [dbg eval]', last, '| exprHead=', expr.slice(0, 80).replace(/\n/g, ' '));
    }
    await sleep(wait);
  }
  return { ok: false, why: 'eval-fail', detail: last };
};

/* ---------- 基础动作 ---------- */

const dropdownOpen = () => s.mainEval(`(()=>[...document.querySelectorAll('.cook-select-dropdown')].some(n=>n.getBoundingClientRect().height>10))()`);

const openSwitcher = async () => {
  if (await dropdownOpen()) return;
  const sw = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');if(!n)return 'null';const r=n.getBoundingClientRect();return JSON.stringify({x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)})})()`));
  if (!sw) throw new Error('no-shop-switcher');
  await s.clickAt(sw.x, sw.y);
  await sleep(2200);
};

const clearSearch = async () => {
  await s.mainEval(`(()=>{
    const n=[...document.querySelectorAll('input')].find(x=>x.placeholder==='搜索店铺名称/ID');
    if(!n) return 'nf';
    const set=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
    n.focus(); set.call(n,''); n.dispatchEvent(new Event('input',{bubbles:true}));
    return 'ok';
  })()`);
  await sleep(1800);
};

/** 读第 colIdx 列的全部项快照 */
const readCol = async (colIdx) => evalJson(`(()=>{try{
  const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
  if(!dd) return JSON.stringify({ok:false,why:'no-dropdown'});
  const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
  const col=cols[${colIdx}];
  if(!col) return JSON.stringify({ok:false,why:'no-col',cols:cols.length});
  const items=[...col.querySelectorAll('.cook-cascader-menu-item')];
  const rows=items.map((n,i)=>{
    const toks=(n.innerText||'').split(/\\n|\\s{2,}/).map(t=>t.trim()).filter(Boolean);
    // 组织行文本形如「运营组织 换行 刘欢」；店铺行形如「李当家汉派猪蹄饭(一清路店) 换行 营业中」
    // 注意：这里是模板字符串，注释里绝对不能写反斜杠 n，会被转成真换行导致语法错误
    const isOrg = toks[0] === '运营组织';
    return {
      i,
      name: (isOrg ? toks.slice(1).join(' ') : toks[0] || '').trim(),
      status: (isOrg ? '' : (toks[1] || '')).trim(),
      dv:n.getAttribute('data-value')||'',
      arrow: /expand/.test(String(n.className)) || !!n.querySelector('[class*=arrow],[class*=Arrow]'),
      checked: n.getAttribute('aria-checked')==='true'
    };
  });
  return JSON.stringify({ok:true, cols:cols.length, rows});
}catch(e){return JSON.stringify({ok:false,why:'page-ex',detail:e.message})}})()`);

/** 把第 colIdx 列第 i 项滚进可视区并点击 */
const clickItem = async (colIdx, i) => {
  const pos = await evalJson(`(()=>{try{
    const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
    if(!dd) return JSON.stringify({ok:false,why:'no-dd'});
    const cols=[...dd.querySelectorAll('.cook-cascader-menu')];
    const col=cols[${colIdx}];
    if(!col) return JSON.stringify({ok:false,why:'no-col'});
    const items=[...col.querySelectorAll('.cook-cascader-menu-item')];
    const n=items[${i}];
    if(!n) return JSON.stringify({ok:false,why:'no-item'});
    n.scrollIntoView({block:'center'});
    const r=n.getBoundingClientRect();
    return JSON.stringify({ok:true,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),h:Math.round(r.height),name:(n.innerText||'').split(/\\n/)[0]});
  }catch(e){return JSON.stringify({ok:false,why:'page-ex',detail:e.message})}})()`);
  if (!pos.ok) return pos;
  await s.clickAt(pos.x, pos.y);
  await sleep(CLICK_WAIT);
  return pos;
};

const parseDv = (dv) => {
  const shop = /SHOP:(\d+)/.exec(dv);
  const branches = [...dv.matchAll(/BRANCH:(\d+)/g)].map((m) => m[1]);
  const acct = /ACCOUNT_ROOT:(\d+)/.exec(dv);
  return { shopId: shop ? shop[1] : null, branches, acctId: acct ? acct[1] : null };
};

/* ---------- 递归遍历 ---------- */

const shops = new Map();   // shopId -> record
const failures = [];
const orgs = [];           // 组织清单
let clicks = 0;

async function walk(colIdx, ancestors, orgLabel) {
  if (colIdx > MAX_DEPTH) {failures.push('maximum-depth');return;}
  const snap = await readCol(colIdx);
  if (!snap.ok) { failures.push('column-read:'+colIdx);log('  !! readCol fail', JSON.stringify(snap)); return; }
  const rows = snap.rows || [];
  log(`  col${colIdx} rows=${rows.length}`);

  for (const row of rows) {
    const dv = parseDv(row.dv);
    if (dv.shopId) {
      const previous=shops.get(dv.shopId);
      if(!row.name)failures.push('shop-name-missing:'+dv.shopId);
      if(previous&&(previous.shopName!==row.name||previous.status!==row.status))failures.push('conflicting-shop-identity:'+dv.shopId);
      if (!shops.has(dv.shopId)) {
        shops.set(dv.shopId, {
          shopId: Number(dv.shopId),
          shopName: row.name,
          status: row.status || '',
          orgPath: ancestors.join(' / ') || '顶级单店',
          orgLabel,
          acctId: dv.acctId,
          branchPath: dv.branches,
        });
      }
      continue;
    }
    if (row.arrow && colIdx + 1 > MAX_DEPTH) failures.push('unvisited-depth:'+row.dv);
    if (row.arrow && colIdx + 1 <= MAX_DEPTH) {
      const p = await clickItem(colIdx, row.i);
      clicks++;
      if (!p.ok) {failures.push('branch-click:'+row.dv);log('  !! click fail', row.name, JSON.stringify(p)); continue;}
      await walk(colIdx + 1, [...ancestors, row.name], orgLabel);
    }
  }
}

/* ---------- 主流程 ---------- */

await openSwitcher();
await clearSearch();

const c0 = await readCol(0);
if (!c0.ok) throw Error('brand-roster-root-column-unavailable');
const expectedOrgs=c0.rows.filter(r=>!parseDv(r.dv).shopId&&!/^全部$/.test(r.name)).length;
log('ORG_COUNT=' + c0.rows.length);

const save = (done, complete=false) => {
  const recs = [...shops.values()];
  const open = recs.filter((r) => r.status.trim()==='营业中');
  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  const destination=complete?OUT:OUT+'.partial.json';
  const temporary=destination+'.'+process.pid+'.tmp';
  fs.writeFileSync(temporary, JSON.stringify({
    complete, account:'gmfmmZH', source:'brand-shop-switcher-organisation-tree', expectedOrgs, failures,
    collectedAt: new Date().toISOString(),
    orgsDone: done,
    clicks,
    total: recs.length,
    openCount: open.length,
    shops: recs,
  }, null, 1));
  fs.renameSync(temporary,destination);
  log(`  [save] total=${recs.length} open=${open.length} orgsDone=${done}/${c0.rows.length}`);
};

let done = 0;
for (const org of c0.rows) {
  if (MAX_ORGS && done >= MAX_ORGS) break;
  if (/^全部$/.test(org.name)) continue;

  // col0 里的「顶级单店」：dv 直接是 SHOP:<id>，点了会切店并关闭弹层 ⇒ 只读不点
  const leaf = parseDv(org.dv);
  if (leaf.shopId) {
    if (!shops.has(leaf.shopId)) {
      shops.set(leaf.shopId, {
        shopId: Number(leaf.shopId),
        shopName: org.name,
        status: org.status || '',
        orgPath: '顶级单店',
        orgLabel: '顶级单店',
        acctId: leaf.acctId,
        branchPath: leaf.branches,
        source: 'top-level-single-shop',
      });
    }
    continue;
  }

  log(`\n=== ORG ${org.name} (${org.dv.slice(-40)}) ===`);
  // 上一轮展开/滚动可能把弹层关掉，每轮开跑前兜底重开
  if (!(await dropdownOpen())) {
    log('  (popup closed, reopening)');
    await openSwitcher();
    await clearSearch();
  }
  const p = await clickItem(0, org.i);
  clicks++;
  if (!p.ok) {failures.push('organisation-click:'+org.dv);log('!! org click fail', JSON.stringify(p));continue;}
  await walk(1, [org.name], org.name);
  done++;
  save(done);
}

if(MAX_ORGS||done!==expectedOrgs||failures.length||expectedOrgs<1||shops.size<1)throw Error('brand-roster-incomplete');
save(done,true);
log(`\nDONE orgs=${done} clicks=${clicks} shops=${shops.size} open=${[...shops.values()].filter((r) => r.status.trim()==='营业中').length}`);
} finally {
 if(s){try{if(await s.mainEval(`(()=>{const d=document.querySelector('.cook-select-dropdown');return !!d&&d.getBoundingClientRect().height>10})()`)){const pos=JSON.parse(await s.mainEval(`(()=>{const e=document.querySelector('[class*=shop-name__]');if(!e)return 'null';const r=e.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));if(pos)await s.clickAt(pos.x,pos.y);}}catch{}s.cdp.close();}
 if(lease)await releasePostLease(lease);
}
}
main().catch(e=>{console.error(JSON.stringify({ok:false,reason:e.message}));process.exitCode=1;});
