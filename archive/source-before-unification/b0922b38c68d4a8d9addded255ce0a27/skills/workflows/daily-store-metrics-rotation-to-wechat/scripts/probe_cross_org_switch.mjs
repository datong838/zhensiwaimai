#!/usr/bin/env node
/**
 * Q-I 实验：跨组织切店是否会踢掉 9230 登录态
 *
 * 背景：2026-10-20 18:50 切到 shopId=1258934689（湘霸王·老坛剁椒鱼头(平凉路店)）后，
 *      页面跳 /login?from=/app/shop/1258934689/，Page.navigate 到 dashboard 仍被弹回。
 *      取证排除「Chrome 重启」⇒ 疑服务端会话失效。
 *      若成立，店铺池里跨组织的店一律不能自动切，否则工位一轮就跑废。
 *
 * 做法：从店铺池里挑 3 家 acctId 各不相同的店（能在品牌商精确匹配到），依次切，
 *      每切一次就探一次登录态。任一步掉登录立即停下并判定「跨组织切店会踢」。
 *
 * 判据（三判据齐才算真掉登录，避免单次跳转误判）：
 *   ① 当前 URL 含 /login
 *   ② Page.navigate 到 dashboard 后仍含 /login
 *   ③ 页面出现登录表单特征（手机号 / 扫码登录 / 账号密码 任一）
 *
 * 退出码：
 *   0 全流程无掉登录（跨组织切店安全）
 *   3 任意一步掉登录（跨组织切店危险，禁止自动切跨组织店）
 *   4 前置条件不满足（无登录态 / 无法切换）
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { session, sleep } from './lib/cdp.mjs';
import { norm } from './lib/shop_match.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const NODE = process.execPath;

function arg(n, d = null) { const i = process.argv.indexOf('--' + n); return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : d; }

const poolFile = arg('pool', '.runtime/store_pool_20261020.json');
const treeFile = arg('tree', '.recon/shopTree_flat.json');
const outFile = arg('out', '.runtime/q_i_cross_org_result.json');
const count = Number(arg('count', '3'));

// ── 1) 挑样本：精确匹配成功 + acctId 互不相同 ──
const pool = JSON.parse(fs.readFileSync(poolFile, 'utf8')).rows;
const tree = JSON.parse(fs.readFileSync(treeFile, 'utf8')).filter((x) => x.menuType === 'SHOP');
const treeNames = new Set(tree.map((x) => norm(x.name)));

const seenAcct = new Set();
const picks = [];
for (const r of pool) {
  const acct = String(r.acctId || '');
  if (!acct || seenAcct.has(acct)) continue;
  if (!treeNames.has(norm(r.shopName))) continue;   // 只挑能精确匹配的，确保切得动
  seenAcct.add(acct);
  picks.push({ shopName: r.shopName, wmPoiId: r.wmPoiId, acctId: acct });
  if (picks.length >= count) break;
}
if (picks.length < count) { console.error(`FAIL sample-too-few got=${picks.length}`); process.exit(4); }
console.log('PICKS=' + JSON.stringify(picks, null, 1));

// ── 2) 三判据探活 ──
async function checkLogin() {
  const s = await session({ port: 9230, width: 1440, height: 1500 });
  await s.rearm();
  const u1 = await s.mainEval('location.href');
  await s.cdp.send('Page.navigate', { url: 'https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard' });
  await sleep(9000);
  await s.rearm();
  const u2 = await s.mainEval('location.href');
  const text = await s.mainEval(`(()=>{const b=document.body;return b?(b.innerText||'').replace(/\\s+/g,' ').slice(0,300):''})()`);
  s.cdp.close();
  const c1 = /\/login/.test(u1);
  const c2 = /\/login/.test(u2);
  const c3 = /手机号|扫码登录|账号密码/.test(String(text));
  return { u1, u2, c1, c2, c3, dead: c1 && c2 && c3, text: String(text).slice(0, 120) };
}

// 前置：必须已登录
const pre = await checkLogin();
console.log('PRE=' + JSON.stringify(pre));
if (pre.dead) { console.error('FAIL 当前未登录，先扫码再跑本实验'); process.exit(4); }

// ── 3) 逐家切 + 每步探活 ──
const steps = [];
let kicked = null;
for (let i = 0; i < picks.length; i++) {
  const p = picks[i];
  console.log(`\n=== [${i + 1}/${picks.length}] ${p.shopName} acct=${p.acctId} ===`);
  const r = spawnSync(NODE, [path.join(__dirname, 'switch_shop.mjs'), '--shop-id', String(p.wmPoiId), '--shop-name', p.shopName], { encoding: 'utf8' });
  const exit = r.status == null ? 1 : r.status;
  const tail = String(r.stdout || '').split('\n').filter(Boolean).slice(-3).join(' | ');
  console.log(`switch exit=${exit} :: ${tail.slice(0, 220)}`);

  const login = await checkLogin();
  const step = { idx: i + 1, ...p, switchExit: exit, switchTail: tail.slice(0, 300), login: { u1: login.u1, u2: login.u2, c1: login.c1, c2: login.c2, c3: login.c3, dead: login.dead } };
  steps.push(step);
  console.log(`  登录态: ${login.dead ? '❌ 掉了' : '✅ 正常'} (url=${String(login.u1).slice(0, 70)})`);

  if (login.dead) { kicked = step; break; }
}

// ── 4) 结论 ──
const verdict = kicked ? 'cross-org-switch-kicks-login' : 'cross-org-switch-safe';
const result = {
  tested_at: new Date().toISOString(),
  verdict,
  picks: picks.length,
  steps,
  kickedAt: kicked ? kicked.idx : null,
  advice: kicked
    ? '跨组织切店会踢登录 ⇒ 禁止自动跨组织切；只跑与当前登录根同组织的店，其余人工处理'
    : `连续 ${steps.length} 家跨组织切换未掉登录 ⇒ 可自动放量（仍需每店后置探活兜底）`,
};
fs.mkdirSync(path.dirname(outFile), { recursive: true });
fs.writeFileSync(outFile, JSON.stringify(result, null, 1));
console.log('\n' + JSON.stringify({ verdict, tested: steps.length, kickedAt: result.kickedAt, advice: result.advice }, null, 1));
process.exit(kicked ? 3 : 0);
