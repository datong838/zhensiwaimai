#!/usr/bin/env node
/**
 * 统一采集入口：给定「店铺 + 指标」，自动完成「切店 → 落到正确页面 → 调对应采集器」
 *
 * 为什么需要它：11 个指标散在 3 个页面、3 套采集脚本上
 *   M01            → comments 页（iframe melody-comment）      → capture_m01.mjs
 *   M02–M06        → customerStats 页（iframe melody-stats-next）→ capture_metric.mjs
 *   M07–M11        → stats__center 页（同 iframe，靠 tab 区分） → capture_biz.mjs
 * 上层轮转调度只需要说「今天发 M05，给目标店铺池（营业中店铺）」，不需要知道这些细节。
 *
 * 轮转语义提醒：策略是「每天 1 个指标 × 全部店铺」，所以单店每天只采 1 张图；
 * 本脚本的价值是保证「切一次店就对到正确页面」，而不是批量出 11 张。
 *
 * 用法：
 *   node capture_for_metric.mjs --shop-id 694471 --metric M05 --shop-name "李当家汉派猪蹄饭(一清路店)"
 *   node capture_for_metric.mjs --shop-id 694471 --metric M01 --skip-switch     # 已在该店时跳过切店
 *
 * 退出码：透传子脚本退出码；本脚本自身 2=参数错
 */
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import fs from 'node:fs';
import {lastJson,normalizeCapture} from './capture_receipt.mjs';
import { fileURLToPath } from 'node:url';
import { session, sleep } from './lib/cdp.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const NODE = process.execPath;

function arg(n, d = null) { const i = process.argv.indexOf('--' + n); return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : d; }

const shopId = arg('shop-id');
const metric = (arg('metric') || '').toUpperCase();
const shopName = arg('shop-name') || arg('expect-name');
const outDir = arg('out', '.runtime/captures');
const skipSwitch = process.argv.includes('--skip-switch');
const dryRun = process.argv.includes('--dry-run');

// 指标 → 页面路由表
const PAGES = {
  M01: { name: '顾客评价', path: 'comments', hash: '#app.shop.comments', frame: /melody-comment/, cap: 'capture_m01.mjs' },
  M02: { name: '顾客分析', path: 'customerStats', hash: '#app.shop.customerStats', frame: /melody-stats-next/, cap: 'capture_metric.mjs' },
  M03: { name: '顾客分析', path: 'customerStats', hash: '#app.shop.customerStats', frame: /melody-stats-next/, cap: 'capture_metric.mjs' },
  M04: { name: '顾客分析', path: 'customerStats', hash: '#app.shop.customerStats', frame: /melody-stats-next/, cap: 'capture_metric.mjs' },
  M05: { name: '顾客分析', path: 'customerStats', hash: '#app.shop.customerStats', frame: /melody-stats-next/, cap: 'capture_metric.mjs' },
  M06: { name: '顾客分析', path: 'customerStats', hash: '#app.shop.customerStats', frame: /melody-stats-next/, cap: 'capture_metric.mjs' },
  M07: { name: '经营分析', path: 'stats__center', hash: '#app.shop.stats.center', frame: /melody-stats-next/, cap: 'capture_biz.mjs' },
  M08: { name: '经营分析', path: 'stats__center', hash: '#app.shop.stats.center', frame: /melody-stats-next/, cap: 'capture_biz.mjs' },
  M09: { name: '经营分析', path: 'stats__center', hash: '#app.shop.stats.center', frame: /melody-stats-next/, cap: 'capture_biz.mjs' },
  M10: { name: '经营分析', path: 'stats__center', hash: '#app.shop.stats.center', frame: /melody-stats-next/, cap: 'capture_biz.mjs' },
  M11: { name: '经营分析', path: 'stats__center', hash: '#app.shop.stats.center', frame: /melody-stats-next/, cap: 'capture_biz.mjs' },
};

if (!shopId || !PAGES[metric]) {
  console.error('usage: --shop-id <id> --metric M01..M11 [--shop-name 店名] [--out dir] [--skip-switch] [--dry-run]');
  console.error('supported: ' + Object.keys(PAGES).join(', '));
  process.exit(2);
}
const P = PAGES[metric];
const plan = { shopId, metric, page: P.name, path: P.path, capture: P.cap, switchFirst: !skipSwitch };
if (dryRun) { console.log(JSON.stringify({ ok: true, dryRun: true, plan }, null, 1)); process.exit(0); }

let captureRaw=null,lastFailure=null,captureDiagnostic=null;
function run(script, argv, label) {
  console.log(`\n── ${label}: ${script} ${argv.join(' ')}`);
  const r = spawnSync(NODE, [path.join(__dirname, script), ...argv], { encoding:'utf8',timeout:180000,maxBuffer:8*1024*1024 });
  if(script===P.cap&&r.status===0)captureRaw=lastJson(r.stdout||'');
  if(script===P.cap&&r.status!==0){try{const raw=lastJson(r.stdout||'');captureDiagnostic={times:raw.times,shots:raw.shots};}catch{}}
  if(r.status!==0){lastFailure=(r.stderr||'').match(/FAIL ([a-z0-9-]+)/)?.[1]||'child-failed';console.error(`FAIL ${lastFailure} exit=${r.status??'timeout'}`);}
  return r.status == null ? 1 : r.status;
}

// ── 收尾复位（E55，2026-10-20）：谁弄脏谁恢复 ──
// 采集完页面停在单店 <path> 页，会让保活 shell 判据连续 unknown（2026-10-20 实证 4 轮），
// 也会破坏既有下载流的 chain seed 可恢复性（见 reset_chain_seed.mjs 的先例）。
// 导航回 chain 权威 seed 态（与 auth_keepalive TARGETS[9230] / reset_chain_seed.mjs 同源）。
// 复位失败不拖垮采集结果（只 WARN），不抛错。
const CHAIN_HOME = 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center';
const SHELL_MARKS = ['商家首页', '订单管理', '商品管理', '顾客管理', '门店管理', '数据中心']; // auth_keepalive TARGETS[9230].shell 同源
async function restoreChainHome() {
  let s2;
  try {
    s2 = await session({ port: 9230, width: 0, height: 0 }); // width=0 ⇒ 不覆盖设备尺寸
    await s2.cdp.send('Page.navigate', { url: CHAIN_HOME });
    const hit = await s2.waitFor(
      () => s2.mainEval('document.body ? document.body.innerText : ""').then((t) => SHELL_MARKS.find((m) => String(t).includes(m)) || null),
      { timeout: 15000, interval: 1500, label: 'restore-shell' },
    );
    if (hit) console.log(`RESTORE_OK chain-home (${hit})`);
    else console.error('WARN restore-chain-home: shell 特征 15s 未现（导航已发出，保活会自行复核）');
  } catch (e) {
    console.error(`WARN restore-chain-home failed: ${e.message}`);
  } finally {
    try { s2?.cdp.close(); } catch {}
  }
}

// ── 1) 切店（未指定 --skip-switch 时）──
// 关键：把落点一起交给 switch_shop（--land），避免「切完停在哪个页面全看切之前在哪」的坑
// （2026-10-20 19:55 踩过：切前停在 chain 首页 ⇒ 切完落到单店首页，iframe 完全不对）
async function executeCapture(){
let newShopId = shopId;
let landed = false;
if (!skipSwitch) {
  const argv = ['--shop-id', String(shopId), '--land', P.path];
  if (shopName) argv.push('--shop-name', shopName);
  const code = run('switch_shop.mjs', argv, '切店');
  if (code !== 0) {
    console.error(`FAIL switch_shop exit=${code}`);
    // 切店中途失败页面可能已脏（搜索框已点开/已部分导航）：同样复位后再退出，保留原退出码
    console.error('WARN switch failed, still restoring chain-home');
    throw Error('switch-'+(lastFailure||'failed')+'-'+code);
  }
  landed = true;
}

// switch_shop 成功后 URL 里的 shopId 可能与 wmPoiId（旧 ID 体系）不同（两套 ID 不互通）
// ⇒ 从落点 URL 反取真实 shopId，后续导航与文件名都用它
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const cur = await s.mainEval('location.href');
const m = String(cur).match(/\/app\/shop\/(\d+)\//);
if (m) newShopId = m[1];
console.log(`SHOP_ID_EFFECTIVE=${newShopId} (url=${String(cur).slice(0, 90)})`);

// ── 2) 落到目标页面（switch_shop 已按 --land 落位时跳过，省一次 14s 装载）──
const ctx = await s.ctxForFrame(P.frame);
let curIsTarget = false;
if (!ctx.err) {
  const u = await s.frameEval(ctx.id)('location.href');
  console.log('CURRENT_IFRAME=' + String(u).slice(0, 90));
  // customerStats / stats__center 共用 melody-stats-next，靠外层 path 区分，故以主文档 URL 为准
  curIsTarget = String(cur).includes('/' + P.path + '/') || String(cur).includes('/' + P.path + '#');
}
if (!curIsTarget) {
  const url = `https://melody.shop.ele.me/app/shop/${newShopId}/${P.path}${P.hash}`;
  console.log('NAVIGATE=' + url);
  await s.cdp.send('Page.navigate', { url });
  await sleep(14000);
  await s.rearm();
} else {
  console.log(landed ? 'LANDED_BY_SWITCH' : 'ALREADY_ON_TARGET_PAGE');
}
s.cdp.close();

// ── 3) 调对应采集器 ──
// M02–M06 的顾客分析页默认是近7日，必须先跑 set_all_30（capture_metric 只校验不切换）
if (['M02', 'M03', 'M04', 'M05', 'M06'].includes(metric)) {
  const c30 = run('set_all_30.mjs', [], '全部切30日');
  if(c30!==0)throw Error('time-selection-failed');
}

const capArgv = ['--shop-id', String(newShopId), '--out', outDir];
if (metric !== 'M01') capArgv.push('--metric', metric);
if (shopName) capArgv.push('--expect-name', shopName);
if (metric === 'M01') capArgv.push('--no-nav');

const code = run(P.cap, capArgv, `采集 ${metric}`);
if (code !== 0) {
  // 采集失败也要复位（页面已经脏了），但复位失败不掩盖采集退出码
  console.error('WARN capture failed, still restoring chain-home');
  throw Error('capture-failed-'+code);
}
return normalizeCapture(captureRaw,{metric,shopId:newShopId,shopName});
}
let result,failed=false;
try{result=await executeCapture();}
catch(e){failed=true;result={ok:false,metric,reason:/^[a-z0-9-]+$/.test(e.message)?e.message:'capture-failed',diagnostic:captureDiagnostic};}
finally{await restoreChainHome();}
const receiptPath=arg('receipt');
if(receiptPath){fs.mkdirSync(path.dirname(receiptPath),{recursive:true});fs.writeFileSync(receiptPath,JSON.stringify(result,null,2));}
console.log(JSON.stringify(result));
process.exit(failed?1:0);
