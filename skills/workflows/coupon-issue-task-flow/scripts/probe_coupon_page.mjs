#!/usr/bin/env node
/**
 * 只读探针：精准营销页（顾客管理 → 精准营销）结构与发券按钮状态
 *
 * 服务 ROADMAP F2 第一块（采集器前置实测）：
 *   ① 路由实证：店铺页 → 左侧菜单 → 精准营销的 URL / iframe 结构（catalog route 待实测项）
 *   ② 7 人群卡片 DOM + 「发券」按钮「可点/置灰」机检判据（Q-R16d 置灰护栏落地基础）
 *   ③ 营销记录 tab 结构（创建成功判据的锚点）
 *   ④ 基线：本店当前是否已有置灰按钮（置灰解除条件的旁证）
 *
 * 纪律（写流特有，红线）：
 *   - 只读：不开发券弹层、不点「立即创建」、不提交任何表单、不改任何参数
 *   - 复用 9230 已登录页，禁新开标签；导航走左侧菜单 SPA（E59 铁律：URL 直达不换 iframe 数据）
 *   - 结束恢复连锁首页，禁留残留 DOM
 *
 * 用法：node probe_coupon_page.mjs [shopId] [port]
 *   shopId 默认 542633444（大同给过 shop-score URL 的店铺）；port 默认 9230
 */
import { session, sleep } from '../../daily-store-metrics-rotation-to-wechat/scripts/lib/cdp.mjs';

const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
const SHOP = process.argv[2] || '542633444';
const PORT = Number(process.argv[3] || 9230);
const L = (...a) => console.log(...a);
const esc = (u) => new RegExp(u.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));

async function allFrames(s) {
  const tree = await s.cdp.send('Page.getFrameTree');
  const frames = [];
  (function walk(n) { frames.push(n.frame); (n.childFrames || []).forEach(walk); })(tree.frameTree);
  return frames.filter((f) => f.url && f.url !== 'about:blank');
}

/** 在每个 frame 里执行同一表达式，收集结果（含 URL 便于定位） */
async function evalInFrames(s, expr) {
  const out = [];
  for (const f of await allFrames(s)) {
    const r = await s.ctxForFrame(esc(f.url));
    if (!r.id) { out.push({ url: f.url.slice(0, 90), err: 'no-ctx' }); continue; }
    try { out.push({ url: f.url.slice(0, 90), val: await s.frameEval(r.id)(expr) }); }
    catch (e) { out.push({ url: f.url.slice(0, 90), err: String(e).slice(0, 100) }); }
  }
  return out;
}

/** 在任意 frame 里找文本匹配的最深可点元素并用真实 click 事件点它（SPA 路由认） */
async function clickText(s, text) {
  const expr = `(()=>{
    const want = ${JSON.stringify(text)};
    const els = [...document.querySelectorAll('a,li,div,span,button')].filter((el)=>{
      const t = (el.innerText||'').trim();
      return t === want || (t.includes(want) && t.length <= want.length + 6);
    });
    els.sort((a,b)=>a.getElementsByTagName('*').length - b.getElementsByTagName('*').length);
    const el = els[0];
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { tag: el.tagName, text: (el.innerText||'').trim().slice(0,30), x: r.x + r.width/2, y: r.y + r.height/2, w: r.width, h: r.height };
  })()`;
  for (const f of await allFrames(s)) {
    const r = await s.ctxForFrame(esc(f.url));
    if (!r.id) continue;
    let info = null;
    try { info = await s.frameEval(r.id)(expr); } catch {}
    if (info && info.w > 0 && info.h > 0) {
      // 优先 JS click（跨 iframe 坐标换算不可靠）；a 标签也会被触发
      try { await s.frameEval(r.id)(`(()=>{const want=${JSON.stringify(text)};const els=[...document.querySelectorAll('a,li,div,span,button')].filter(el=>{const t=(el.innerText||'').trim();return t===want||(t.includes(want)&&t.length<=want.length+6)});els.sort((a,b)=>a.getElementsByTagName('*').length-b.getElementsByTagName('*').length);const el=els[0];if(el){el.click();return true}return false})()`); }
      catch {}
      return { ...info, frame: f.url.slice(0, 90), clicked: true };
    }
  }
  return null;
}

const CROWD_PROBE = `(()=>{
  const names = ['潜在纯新','进店未下单','需促复购','需提客单','潜力高价值','高价值忠诚','流失需挽回'];
  const out = [];
  for (const nm of names) {
    const hits = [...document.querySelectorAll('*')].filter((el)=>{
      const t = el.innerText||'';
      return t.includes(nm) && el.querySelectorAll('*').length <= 60;
    }).sort((a,b)=>a.getElementsByTagName('*').length - b.getElementsByTagName('*').length);
    const el = hits[0];
    if (!el) { out.push({ name: nm, found: false }); continue; }
    let c = el;
    for (let i = 0; i < 8 && c && !c.querySelector('button'); i++) c = c.parentElement;
    const btns = c ? [...c.querySelectorAll('button')] : [];
    out.push({
      name: nm, found: true,
      container_text: ((c||el).innerText||'').replace(/\\s+/g,' ').slice(0, 220),
      buttons: btns.map((b)=>({
        text: (b.innerText||'').trim().slice(0,20),
        disabled_prop: b.disabled,
        aria_disabled: b.getAttribute('aria-disabled'),
        cls: (b.className||'').toString().slice(0, 140),
        html: b.outerHTML.slice(0, 320)
      }))
    });
  }
  return out;
})()`;

const s = await session({ port: PORT });
try {
  // ① 落到目标店铺（shop-score 是大同给过 URL 的已知页，避开 E59 直达陷阱前先验店名）
  await s.cdp.send('Page.navigate', { url: `https://melody.shop.ele.me/app/shop/${SHOP}/shop-score#app.shop.shop-score` });
  await sleep(4500);
  await s.rearm();
  L('=== PHASE1 落地 shop=' + SHOP + ' ===');
  L('MAIN_URL=' + await s.mainEval('location.href'));
  L('SHOP_NAME=' + await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`));
  L('FRAMES=' + JSON.stringify((await allFrames(s)).map((f) => f.url.slice(0, 110)), null, 0));

  // ①b 掉登录早退：eleme 会话（localStorage ksid+token 固定 TTL）过期会整页跳 /login，
  // 此时后续菜单/卡片查询必然全空——早退并明确报信，不做无谓猜测（#63 铁律：掉后人工有头重登）。
  const landUrl = await s.mainEval('location.href');
  if (String(landUrl).includes('/login')) {
    L('LOGIN_REQUIRED=9230 eleme 会话已过期（导航即跳 /login）；需大同有头重登后用同命令重跑本探针');
    process.exit(2);
  }

  // ② 左侧菜单结构（找 顾客管理 / 精准营销 入口）
  L('=== PHASE2 左侧菜单 ===');
  const menu = await evalInFrames(s, `(()=>{
    const seen = new Set(); const out = [];
    document.querySelectorAll('a,li,[role=menuitem],div[class*=menu]').forEach((el)=>{
      const t = (el.innerText||'').trim().replace(/\\s+/g,' ');
      if (!t || t.length > 14 || seen.has(t)) return;
      if (el.querySelectorAll('*').length > 4) return;
      seen.add(t);
      out.push(el.tagName + '|' + (el.className||'').toString().slice(0,50) + '|' + t);
    });
    return out.slice(0, 50);
  })()`);
  for (const m of menu) L('MENU[' + m.url.slice(0, 60) + '] ' + (m.val ? JSON.stringify(m.val) : 'ERR ' + m.err));

  // ③ 顾客管理 → 精准营销
  L('=== PHASE3 菜单导航 ===');
  const g1 = await clickText(s, '顾客管理');
  L('CLICK 顾客管理 => ' + JSON.stringify(g1));
  await sleep(2500);
  const g2 = await clickText(s, '精准营销');
  L('CLICK 精准营销 => ' + JSON.stringify(g2));
  await sleep(4000);
  await s.rearm();
  L('AFTER_NAV MAIN_URL=' + await s.mainEval('location.href'));
  L('AFTER_NAV FRAMES=' + JSON.stringify((await allFrames(s)).map((f) => f.url.slice(0, 110)), null, 0));

  // ④ 7 人群卡片 + 发券按钮状态
  L('=== PHASE4 人群卡片 ===');
  const crowds = await evalInFrames(s, CROWD_PROBE);
  for (const c of crowds) {
    if (c.err) { L('CROWD[' + c.url.slice(0, 60) + '] ERR ' + c.err); continue; }
    if (!Array.isArray(c.val)) continue;
    const found = c.val.filter((x) => x.found).length;
    if (!found) continue;
    L('CROWD_FRAME=' + c.url);
    for (const x of c.val) {
      L('  CARD ' + x.name + ' found=' + x.found);
      if (x.found) {
        L('    TEXT=' + x.container_text);
        for (const b of x.buttons) L('    BTN text=' + b.text + ' disabled=' + b.disabled_prop + ' aria=' + b.aria_disabled + ' cls=' + b.cls);
      }
    }
  }

  // ⑤ 营销记录 tab（只读切换，看结构）
  L('=== PHASE5 营销记录 tab ===');
  const g3 = await clickText(s, '营销记录');
  L('CLICK 营销记录 => ' + JSON.stringify(g3));
  await sleep(3500);
  const rec = await evalInFrames(s, `(()=>{
    const tables = [...document.querySelectorAll('table')].map(t=>({
      headers: [...t.querySelectorAll('th')].map(h=>(h.innerText||'').trim()).slice(0,12),
      rows: t.querySelectorAll('tbody tr').length
    }));
    return { tables, body_text: (document.body.innerText||'').replace(/\\s+/g,' ').slice(0, 400) };
  })()`);
  for (const r of rec) if (r.val && r.val.tables && r.val.tables.length) L('RECORD[' + r.url.slice(0, 60) + '] ' + JSON.stringify(r.val).slice(0, 600));
} catch (e) {
  L('PROBE_ERROR=' + String(e).slice(0, 300));
} finally {
  await s.cdp.send('Page.navigate', { url: CHAIN_HOME });
  await sleep(3000);
  L('RESTORE=' + await s.mainEval('location.href'));
  process.exit(0);
}
