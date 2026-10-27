#!/usr/bin/env node
/**
 * 只读探针 2：发券表单态 + 「已发过是否置灰」实证（dry-run，红线=绝不点立即创建）
 *
 * 背景：probe_coupon_page.mjs 实测发现——营销记录有 6 个「进行中」活动，
 * 但 7 个发券按钮全部 disabled=false。「已发过⇒置灰点不了」（大同 01:23 口径）
 * 在按钮层没有复现。本探针开表单（不提交）验证置灰是否发生在表单层：
 *   - 目标人群（默认高价值忠诚顾客=已有 2 个进行中活动）
 *   - 表单各字段默认值（对照 §3.3 截图口径）
 *   - 「立即创建」按钮是否 disabled / 有无重复创建警告
 *   - 关闭表单（取消/遮罩），不产生任何创建
 *
 * 纪律：禁点「立即创建」；结束恢复连锁首页。
 * 用法：node probe_coupon_form.mjs [shopId] [人群名] [port]
 */
import { session, sleep } from '../../daily-store-metrics-rotation-to-wechat/scripts/lib/cdp.mjs';

const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
const SHOP = process.argv[2] || '542633444';
const CROWD = process.argv[3] || '高价值忠诚顾客';
const PORT = Number(process.argv[4] || 9230);
const L = (...a) => console.log(...a);
const esc = (u) => new RegExp(u.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));

async function allFrames(s) {
  const tree = await s.cdp.send('Page.getFrameTree');
  const frames = [];
  (function walk(n) { frames.push(n.frame); (n.childFrames || []).forEach(walk); })(tree.frameTree);
  return frames.filter((f) => f.url && f.url !== 'about:blank');
}

async function evalInFrames(s, expr) {
  const out = [];
  for (const f of await allFrames(s)) {
    const r = await s.ctxForFrame(esc(f.url));
    if (!r.id) continue;
    try { out.push({ url: f.url.slice(0, 90), val: await s.frameEval(r.id)(expr) }); }
    catch (e) { out.push({ url: f.url.slice(0, 90), err: String(e).slice(0, 100) }); }
  }
  return out;
}

/** 找到含指定人群名卡片的「发券」按钮并点击（只开表单） */
async function clickCouponButton(s, crowd) {
  const expr = `(()=>{
    const want = ${JSON.stringify(crowd)};
    const hits = [...document.querySelectorAll('*')].filter((el)=>{
      const t = el.innerText||'';
      return t.includes(want) && el.querySelectorAll('*').length <= 60;
    }).sort((a,b)=>a.getElementsByTagName('*').length - b.getElementsByTagName('*').length);
    if (!hits.length) return { skip: 'crowd-not-found' };
    let c = hits[0];
    for (let i = 0; i < 8 && c && !c.querySelector('button'); i++) c = c.parentElement;
    if (!c) return { skip: 'no-container' };
    const btn = [...c.querySelectorAll('button')].find(b => (b.innerText||'').trim() === '发券');
    if (!btn) return { skip: 'no-coupon-button' };
    if (btn.disabled) return { err: 'button-disabled', cls: (btn.className||'').toString() };
    btn.click();
    return { ok: true };
  })()`;
  for (const f of await allFrames(s)) {
    const r = await s.ctxForFrame(esc(f.url));
    if (!r.id) continue;
    let v = null;
    try { v = await s.frameEval(r.id)(expr); } catch {}
    if (v && (v.ok || v.err)) return { ...v, frame: f.url.slice(0, 90) };
  }
  return { err: 'no-frame-matched' };
}

/**  dismiss「绑定手机号」类骚扰弹窗（点「跳过」，无副作用） */
async function dismissNag(s) {
  const expr = `(()=>{
    const btns=[...document.querySelectorAll('button')];
    const skip=btns.find(b=>{const t=(b.innerText||'').trim();return t==='跳 过'||t==='跳过';});
    if(skip){skip.click();return 'clicked-skip';}
    return 'no-nag';
  })()`;
  for (const f of await allFrames(s)) {
    const r = await s.ctxForFrame(esc(f.url));
    if (!r.id) continue;
    try { const v = await s.frameEval(r.id)(expr); if (v && v !== 'no-nag') return v; } catch {}
  }
  return 'no-nag';
}

const FORM_DUMP = `(()=>{
  const dlg = document.querySelector('[class*=el-dialog]:not([style*="display: none"])') || document.querySelector('[class*=modal]');
  if (!dlg) return { dialog: false };
  const txt = (dlg.innerText||'').replace(/\\s+/g,' ').slice(0, 500);
  const btns = [...dlg.querySelectorAll('button')].map((b)=>({
    text: (b.innerText||'').trim().slice(0,16),
    disabled: b.disabled,
    cls: (b.className||'').toString().slice(0,100)
  }));
  // 单选/勾选态
  const radios = [...dlg.querySelectorAll('[class*=radio],[class*=checked]')].slice(0,10).map(e=>({
    text: (e.innerText||'').trim().slice(0,24),
    cls: (e.className||'').toString().slice(0,80)
  }));
  const inputs = [...dlg.querySelectorAll('input')].slice(0,10).map((i)=>({
    ph: (i.placeholder||'').slice(0,20), val: (i.value||'').slice(0,20), disabled: i.disabled
  }));
  const warns = [...dlg.querySelectorAll('[class*=warn],[class*=error],[class*=tip]')].map(e=>(e.innerText||'').trim().slice(0,60)).filter(Boolean).slice(0,5);
  return { dialog: true, text: txt, buttons: btns, radios, inputs, warns };
})()`;

const s = await session({ port: PORT });
try {
  await s.cdp.send('Page.navigate', { url: `https://melody.shop.ele.me/app/shop/${SHOP}/activity__crm#app.shop.activity.crm` });
  await sleep(5000);
  await s.rearm();
  const href = await s.mainEval('location.href');
  L('LAND=' + href);
  if (String(href).includes('/login')) { L('LOGIN_REQUIRED'); process.exit(2); }

  L('NAG=' + await dismissNag(s));
  await sleep(1000);

  const r1 = await clickCouponButton(s, CROWD);
  L('CLICK_COUPON(' + CROWD + ')=' + JSON.stringify(r1));
  await sleep(2500);

  const forms = await evalInFrames(s, FORM_DUMP);
  for (const f of forms) {
    if (!f.val || !f.val.dialog) continue;
    L('FORM_FRAME=' + f.url);
    L('FORM_TEXT=' + f.val.text);
    L('FORM_BUTTONS=' + JSON.stringify(f.val.buttons));
    L('FORM_RADIOS=' + JSON.stringify(f.val.radios));
    L('FORM_INPUTS=' + JSON.stringify(f.val.inputs));
    L('FORM_WARNS=' + JSON.stringify(f.val.warns));
  }

  // 关闭表单：找「取消」按钮点（绝不点立即创建）
  const closeExpr = `(()=>{
    const btns=[...document.querySelectorAll('button')];
    const c=btns.find(b=>{const t=(b.innerText||'').trim();return t==='取消'||t==='关 闭'||t==='关闭';});
    if(c){c.click();return 'clicked-cancel';}
    const x=document.querySelector('[class*=el-dialog__headerbtn]');
    if(x){x.click();return 'clicked-x';}
    return 'no-close-found';
  })()`;
  let closed = 'n/a';
  for (const f of await allFrames(s)) {
    const r = await s.ctxForFrame(esc(f.url));
    if (!r.id) continue;
    try { const v = await s.frameEval(r.id)(closeExpr); if (v && v !== 'no-close-found') { closed = v; break; } } catch {}
  }
  L('CLOSE=' + closed);
  await sleep(1200);
  // 复核表单已消失、无新增活动（营销记录进行中数应不变）
  const after = await evalInFrames(s, `(()=>{
    const t=(document.body.innerText||'');
    const m=t.match(/进行中\\s*(\\d+)/);
    return { dialog_open: !!document.querySelector('[class*=el-dialog]:not([style*="display: none"])'), doing: m?m[1]:null };
  })()`);
  for (const f of after) if (f.val) L('AFTER[' + f.url.slice(0, 50) + ']=' + JSON.stringify(f.val));
} catch (e) {
  L('PROBE_ERROR=' + String(e).slice(0, 300));
} finally {
  await s.cdp.send('Page.navigate', { url: CHAIN_HOME });
  await sleep(3000);
  L('RESTORE=' + await s.mainEval('location.href'));
  process.exit(0);
}
