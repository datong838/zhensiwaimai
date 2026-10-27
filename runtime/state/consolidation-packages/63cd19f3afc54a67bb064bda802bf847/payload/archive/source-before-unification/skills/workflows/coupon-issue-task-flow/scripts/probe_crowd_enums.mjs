#!/usr/bin/env node
/**
 * 只读探针 3：补采 7 个人群的 create-activity 路由枚举（CROWD_ENUM）
 *
 * 背景：E08 已实证高价值忠诚=HIGH_VALUE_CUSTOMERS，其余 6 个人群的枚举值未采，
 * F2 采集器按人群直达表单路由时缺参数。本探针逐个点「发券」（只开表单/弹层、
 * 绝不点立即创建），捕获 create-activity URL 上的 type 参数后关闭，循环 7 人群。
 *
 * 纪律（红线）：
 *   - 只读：不开关联商品选择、不提交、不创建；每轮只点「发券」+「取消/X」
 *   - 复用 9230 已登录页，禁新开标签；掉登录早退（exit 2）
 *   - 结束恢复连锁首页
 *
 * 用法：node probe_crowd_enums.mjs [shopId] [port]
 */
import { session, sleep } from '../../daily-store-metrics-rotation-to-wechat/scripts/lib/cdp.mjs';

const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
const CRM_URL = (shop) => `https://melody.shop.ele.me/app/shop/${shop}/activity__crm#app.shop.activity.crm`;
const SHOP = process.argv[2] || '542633444';
const PORT = Number(process.argv[3] || 9230);
const CROWDS = ['潜在纯新', '进店未下单', '需促复购', '需提客单', '潜力高价值', '高价值忠诚', '流失需挽回'];
const L = (...a) => console.log(...a);
const esc = (u) => new RegExp(u.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));

async function allFrames(s) {
  const tree = await s.cdp.send('Page.getFrameTree');
  const frames = [];
  (function walk(n) { frames.push(n.frame); (n.childFrames || []).forEach(walk); })(tree.frameTree);
  return frames.filter((f) => f.url && f.url !== 'about:blank');
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

/** dismiss「绑定手机号」类骚扰弹窗（点「跳过」，无副作用） */
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

/** 关闭表单/弹层：取消/关闭/X → 兜底 Escape（绝不点立即创建/确定） */
async function closeForm(s) {
  const expr = `(()=>{
    const btns=[...document.querySelectorAll('button')];
    const c=btns.find(b=>{const t=(b.innerText||'').trim();return t==='取消'||t==='关 闭'||t==='关闭';});
    if(c){c.click();return 'clicked-cancel';}
    const x=document.querySelector('[class*=el-dialog__headerbtn]');
    if(x){x.click();return 'clicked-x';}
    return 'no-close-found';
  })()`;
  for (const f of await allFrames(s)) {
    const r = await s.ctxForFrame(esc(f.url));
    if (!r.id) continue;
    try { const v = await s.frameEval(r.id)(expr); if (v && v !== 'no-close-found') return v; } catch {}
  }
  // 兜底：Escape 键（EL 弹层认 Esc）
  try {
    await s.cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 });
    await s.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27, nativeVirtualKeyCode: 27 });
    return 'escape';
  } catch { return 'no-close-found'; }
}

/** 从当前所有帧 URL 里抽 create-activity 的 type 枚举（title 参数须与人群名吻合，防残留误读） */
function extractType(urls, crowd) {
  const want = 'title=' + encodeURIComponent(crowd);
  for (const u of urls) {
    const m = u.match(/create-activity\?type=([A-Za-z_]+)/);
    if (m) return { type: m[1], url: u.slice(0, 130), title_match: u.includes(want) };
  }
  return null;
}

const results = [];
const s = await session({ port: PORT });
try {
  for (const crowd of CROWDS) {
    // 每轮先经连锁首页中转再进店铺 CRM 页：不同 URL ⇒ 主文档全量重载、shop iframe 全新。
    // 教训（02:20/02:2x 两轮实证）：① 同 URL（含 hash）Page.navigate = 同文档导航，
    // 不重置 iframe，上轮 create-activity 残留会被重复抽到；② 在主页面不在店铺路由时
    // 按 frameId 导航会命中连锁壳自己的帧，把页面带去连锁 dashboard。必须整体重载。
    await s.cdp.send('Page.navigate', { url: CHAIN_HOME });
    await sleep(2200);
    await s.cdp.send('Page.navigate', { url: CRM_URL(SHOP) });
    await sleep(4200);
    await s.rearm();
    const href = await s.mainEval('location.href');
    if (String(href).includes('/login')) {
      L('LOGIN_REQUIRED=9230 eleme 会话已过期；需大同有头重登后用同命令重跑本探针');
      process.exit(2);
    }
    L('--- CROWD ' + crowd + ' LAND=' + String(href).slice(0, 80));
    L('  NAG=' + await dismissNag(s));
    await sleep(800);

    const r = await clickCouponButton(s, crowd);
    L('  CLICK=' + JSON.stringify(r));
    await sleep(2600);

    const urls = (await allFrames(s)).map((f) => f.url);
    const main = String(await s.mainEval('location.href'));
    const hit = extractType([main, ...urls], crowd);
    if (hit && hit.title_match) {
      L('  ENUM=' + crowd + ' => ' + hit.type + '  @ ' + hit.url);
      results.push({ crowd, type: hit.type });
    } else {
      L('  ENUM=' + crowd + ' => NOT_FOUND' + (hit ? ' (title-mismatch, stale?)' : '') + '  frames=' + JSON.stringify(urls.map((u) => u.slice(0, 90))));
      results.push({ crowd, type: null });
    }

    L('  CLOSE=' + await closeForm(s));
    await sleep(1500);
  }
  L('=== SUMMARY ===');
  for (const r of results) L('ENUM_ROW ' + r.crowd + ' | ' + (r.type || 'NOT_FOUND'));
  const missing = results.filter((r) => !r.type).length;
  L('ENUM_DONE total=' + results.length + ' missing=' + missing);
} catch (e) {
  L('PROBE_ERROR=' + String(e).slice(0, 300));
} finally {
  await s.cdp.send('Page.navigate', { url: CHAIN_HOME });
  await sleep(3000);
  L('RESTORE=' + await s.mainEval('location.href'));
  process.exit(0);
}
