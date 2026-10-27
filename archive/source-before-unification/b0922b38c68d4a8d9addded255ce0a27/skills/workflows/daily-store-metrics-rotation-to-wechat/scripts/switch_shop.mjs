#!/usr/bin/env node
/**
 * 切店脚本（9230 淘宝闪购品牌商）
 *
 * 大同亲授 3 步：右上角店铺名 → 搜店铺名/ID → 点候选 → 整页刷新
 *
 * ── 三级降级搜索（2026-10-20 大同拍板 Q-F/Q-G）──
 *   ① id      : 用 wmPoiId 搜（旧 ID 体系，与品牌商 shopId 不互通，实测基本无效）
 *   ② prefix  : 用店名前缀搜（去括号主体名，超 10 字截断）← 主力
 *   ③ full    : 用完整店名搜
 *   每一级都在候选里按 shop_match.judge 判据找唯一目标；命中即停。
 *   全都不能唯一定位 ⇒ exit 5（台账备注「闪购品牌商平台搜不到该店铺」后跳过）
 *
 * ── 铁律：宁可不切，不可错切 ──
 *   错切会把 A 店数据发到 B 店商家群（生产事故）；搜不到只是少发一家。
 *
 * 踩坑固化为规则：
 * 1. 切换器是 toggle：弹层已开时再点店铺名 = 关闭 ⇒ 必须先判开合状态
 * 2. 输入框是受控组件 ⇒ 原生 setter + input 事件（Input.insertText 对中文无效）
 * 3. 下拉里同时有「运营组织」级联树和搜索结果，只认带营业状态后缀的店铺行
 * 4. 搜索有去抖，输入后立刻读会读到上一轮未过滤的全量列表 ⇒ 先静默等 3s
 * 5. **切完必须硬刷新**：外层 URL 变了但 iframe 仍停在上一个店的作用域，
 *    只有 Page.reload 才会按新 shopId 重建 ⇒ 否则会拿 A 店的图当 B 店交出去
 *
 * 退出码：
 *   0 成功
 *   2 参数错
 *   3 无 page target
 *   4 切换器/输入框异常
 *   5 三级搜索都无法唯一定位（= 平台搜不到该店铺）
 *   6 切换后店名不可接受
 *   7 切换后 iframe 作用域不是 /single/
 */
import { session, sleep } from './lib/cdp.mjs';
import {dismissBindReminder} from './lib/known_overlay.mjs';
import { norm, keywordsFor, judge, nameAcceptable } from './lib/shop_match.mjs';

function arg(name, def = null) {
  const i = process.argv.indexOf('--' + name);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : def;
}

const shopId = arg('shop-id');
const shopName = arg('shop-name') || arg('expect-name'); // 兼容旧调用
const expectName = arg('expect-name');
if (!shopId && !shopName) {
  console.error('usage: --shop-id <id> [--shop-name 店名] | --shop-name 店名');
  process.exit(2);
}

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
await dismissBindReminder(s);

const topName = () => s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`);
const popupState = () => s.mainEval(`(()=>{
  const d=[...document.querySelectorAll('.cook-select-dropdown')].map(n=>{const r=n.getBoundingClientRect();return {w:Math.round(r.width),h:Math.round(r.height)}});
  return JSON.stringify({visible:d.some(x=>x.w>100&&x.h>10)});
})()`).then(JSON.parse);

const before = await topName();
console.log('BEFORE=' + before);

let st = await popupState();
if (!st.visible) {
  const SW = JSON.parse(await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');if(!n)return 'nf';const r=n.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})})()`));
  if (SW === 'nf') { console.error('FAIL switcher-not-found'); process.exit(4); }
  await s.clickAt(SW.x, SW.y);
  await sleep(1600);
  st = await popupState();
}
if (!st.visible) { console.error('FAIL popup-not-open'); process.exit(4); }

// 输入框：页面上有多个 input.cook-input（顶部订单号框也是），必须按 placeholder 精确定位
// 弹层关闭时该输入框是 0×0，点它会点到 (0,0) 把值送进「订单号」框 ⇒ 必须等可见
const INPUT_SEL = `[...document.querySelectorAll('input')].find(n=>n.placeholder==='搜索店铺名称/ID')`;
const ipRect = await s.waitFor(async () => {
  const r = await s.mainEval(`(()=>{const n=${INPUT_SEL};if(!n)return null;const r=n.getBoundingClientRect();return r.width>100?JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2,w:Math.round(r.width)}):null})()`);
  return r ? JSON.parse(r) : null;
}, { timeout: 10000, interval: 500, label: 'input-visible' });
if (!ipRect) { console.error('FAIL search-input-not-visible'); process.exit(4); }
const IP = ipRect;

async function typeKw(kw) {
  await s.clickAt(IP.x, IP.y);
  await sleep(300);
  const v = await s.mainEval(`(()=>{
    const n=${INPUT_SEL};
    const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
    n.focus();
    setter.call(n, ${JSON.stringify('')});
    n.dispatchEvent(new Event('input',{bubbles:true}));
    setter.call(n, ${JSON.stringify(String(kw))});
    n.dispatchEvent(new Event('input',{bubbles:true}));
    return n.value;
  })()`);
  if (String(v).trim() !== String(kw).trim()) return { err: 'type-mismatch', got: v };
  return { ok: true, got: v };
}

/** 读候选（已过滤运营组织级联树，只留带营业状态的店铺行） */
async function readRows() {
  const r = await s.mainEval(`(()=>{
    const dd=[...document.querySelectorAll('.cook-select-dropdown')].find(n=>n.getBoundingClientRect().height>10);
    if(!dd) return JSON.stringify({err:'no-dd', rows:[]});
    const STATUS=/营业中|已下线|暂停营业|已打烊/;
    const cands=[...dd.querySelectorAll('div,a,li')].filter(n=>{
      if(/cook-cascader-menu-item/.test((n.className||'').toString())) return false;
      const t=(n.innerText||'').trim();
      const rc=n.getBoundingClientRect();
      if(!t || !STATUS.test(t)) return false;
      if(rc.width<150 || rc.height<20 || rc.height>90) return false;
      if(n.children.length>5) return false;
      return true;
    });
    const map=new Map();
    for(const n of cands){
      const raw=(n.innerText||'').replace(/\\s+/g,'|').trim();
      const name=raw.split('|')[0];
      const rc=n.getBoundingClientRect();
      if(!map.has(name) || map.get(name).h > rc.height){
        map.set(name,{name, raw, x:rc.x+rc.width/2, y:rc.y+rc.height/2, h:Math.round(rc.height)});
      }
    }
    return JSON.stringify({rows:[...map.values()].slice(0,50)});
  })()`);
  const d = JSON.parse(r);
  return d.rows || [];
}

// ── 降级搜索：id → 全名 → 去括号主体 → 品牌词 → 品牌词截断 ──
const tries = [];
const seenKw = new Set();
const addT = (tier, kw) => {
  const k = String(kw == null ? '' : kw).trim();
  if (!k || seenKw.has(k)) return;
  seenKw.add(k);
  tries.push({ tier, kw: k });
};
if (shopId) addT('id', shopId);
if (shopName) {
  addT('full', shopName);
  keywordsFor(shopName).forEach((k, i) => addT(i === 0 ? 'body' : 'brand', k));
}

let picked = null;
const trail = [];
for (const t of tries) {
  const typed = await typeKw(t.kw);
  if (typed.err) { trail.push({ tier: t.tier, kw: t.kw, err: typed.err }); continue; }
  await sleep(3000); // 去抖：不睡会读到上一轮未过滤的全量列表
  const rows = await readRows();
  const cands = rows.map((x) => x.name);
  const v = judge(shopName, cands);
  trail.push({ tier: t.tier, kw: t.kw, n: cands.length, ok: v.ok, why: v.why, cands: cands.slice(0, 6) });
  if (v.ok) {
    const row = rows.find((x) => x.name === v.pick) || rows[0];
    picked = { ...v, tier: t.tier, kw: t.kw, row };
    break;
  }
}
console.log('TRAIL=' + JSON.stringify(trail));

if (!picked) {
  const last = trail[trail.length - 1] || {};
  console.error('FAIL no-confident-match (平台搜不到该店铺) name=' + shopName + ' id=' + shopId + ' trail=' + JSON.stringify(trail));
  process.exit(5);
}
console.log('PICK=' + JSON.stringify({ name: picked.pick, tier: picked.tier, kw: picked.kw, why: picked.why, weak: !!picked.weak }));

// 幂等：目标店就是当前店时跳过点击（否则「店名必须变化」会把自己判失败）
// 2026-10-20 20:04 踩到：同一家店连跑 M05→M09，第二次切店 exit 6
let afterName = before;
if (norm(picked.pick) === norm(before)) {
  console.log('SKIP_SWITCH_ALREADY_HERE=' + before);
} else {
  await s.clickAt(picked.row.x, picked.row.y);
  await sleep(3000);

  const changed = await s.waitFor(async () => {
    const n = await topName();
    return n && n !== before ? n : null;
  }, { timeout: 25000, interval: 1000, label: 'name-change' });

  afterName = await topName();
  if (!changed) { console.error(`FAIL name-not-changed before=${before} after=${afterName}`); process.exit(6); }
  console.log('AFTER=' + afterName);

  // 店名校验：exact 命中要求严格相等；其余按品牌/分店名模糊接受
  const targetForCheck = expectName || shopName;
  if (targetForCheck && !nameAcceptable(targetForCheck, afterName, picked.why)) {
    console.error(`FAIL name-mismatch expect=${targetForCheck} got=${afterName} why=${picked.why}`);
    process.exit(6);
  }
}

// ── 落到目标页并硬刷新 ──
// 关键教训（2026-10-20 19:55 踩到）：切店只改 shopId，**hash 会被沿用**。
//   若切之前停在 `/app/chain/95708808/dashboard#app.chainshop.dashboard`，
//   切完就落到 `/app/shop/<id>/dashboard#app.shop.dashboard`（单店首页，iframe=napos-dashboard-pc），
//   而不是经营分析页 ⇒ 后面按 melody-stats-next 找 iframe 必然 no ctx。
// 所以必须显式指定落点，不能指望「切完还在原页面」。
const LANDS = {
  stats__center: '#app.shop.stats.center',
  customerStats: '#app.shop.customerStats',
  comments: '#app.shop.comments',
  dashboard: '#app.shop.dashboard',
};
const land = arg('land', 'stats__center');
if (!LANDS[land]) { console.error('FAIL unknown-land ' + land + ' (support: ' + Object.keys(LANDS).join(',') + ')'); process.exit(2); }

const curUrl = await s.mainEval('location.href');
const shopIdNow = (String(curUrl).match(/\/app\/shop\/(\d+)\//) || [])[1] || shopId;
const wantUrl = `https://melody.shop.ele.me/app/shop/${shopIdNow}/${land}${LANDS[land]}`;
if (String(curUrl).includes('/' + land)) {
  await s.cdp.send('Page.reload', { ignoreCache: true });
} else {
  console.log('LAND=' + wantUrl);
  await s.cdp.send('Page.navigate', { url: wantUrl });
}
await sleep(14000);
await s.rearm();

// 期望的 iframe 与作用域判据（按落点决定，不能一律 melody-stats-next）
const isComments = land === 'comments';
const frameRe = isComments ? /melody-comment/ : /melody-stats-next/;

const scope = await s.waitFor(async () => {
  const r = await s.ctxForFrame(frameRe);
  if (r.err) return null;
  const url = await s.frameEval(r.id)('location.href');
  if (!url) return null;
  // 单店判据：stats 系看 /single/，comments 系看「不是 /chain/」
  return isComments ? (!/\/chain\//.test(url) ? url : null) : (/\/single\//.test(url) ? url : null);
}, { timeout: 30000, interval: 2000, label: 'scope' });

if (!scope) {
  const r = await s.ctxForFrame(frameRe);
  const url = r.err ? '(no ctx)' : await s.frameEval(r.id)('location.href');
  console.error(`FAIL scope-not-single land=${land} inner=` + url);
  process.exit(7);
}

const finalName = await topName();
console.log(JSON.stringify({
  ok: true, before, after: finalName, shopId, shopIdEffective: shopIdNow, shopName, land,
  match: { tier: picked.tier, kw: picked.kw, why: picked.why, weak: !!picked.weak, picked: picked.pick },
  trail, innerUrl: scope,
}, null, 1));
s.cdp.close();
process.exit(0);
