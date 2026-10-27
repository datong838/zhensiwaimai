#!/usr/bin/env node
/**
 * 单店单指标截图采集器（9230 淘宝闪购品牌商 · business-analysis 页）
 *
 * 用法：
 *   node capture_metric.mjs --shop-id 694471 --metric M04 --out .runtime/captures
 *   node capture_metric.mjs --shop-id 694471 --metric M02 --expect-name "李当家汉派猪蹄饭(一清路店)"
 *   node capture_metric.mjs --shop-id 694471 --metric M03 --skip-30      # 已确认30日时跳过切换
 *
 * 硬前置（任一不满足即失败，绝不产出「看起来成功」的图）：
 *   1. iframe 作用域必须是 /single/（不是 /chain/）
 *   2. 顶部店名 == --expect-name（给了的话）
 *   3. 模块区间内的真·时间控件必须已是近30日（--skip-30 时才跳过校验）
 *
 * 退出码：
 *   0 成功 / 2 参数 / 3 无 target / 4 iframe 缺 / 5 店名不符
 *   6 锚点缺失 / 7 时间口径未达标 / 8 截图高度异常 / 9 非 single 作用域
 */
import fs from 'node:fs';
import path from 'node:path';
import { session, sleep } from './lib/cdp.mjs';

function arg(n, d = null) { const i = process.argv.indexOf('--' + n); return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : d; }

// 指标 → 模块定位（single 视角实测结构，2026-10-20）
// start: 起点标题；end: 终点标题（该标题之前结束）；col: 'left'|'right'|'full'
const METRICS = {
  M02: { label: '顾客分析(概览+下单顾客趋势)', card: 'customer_analysis', start: null, end: null, col: 'full' },
  M03: { label: '下单行为(下单频次/间隔/单均实付)', card: 'customer_distribution', start: '下单行为', end: '下单热门街区', col: 'left' },
  M04: { label: '下单时段', card: 'customer_distribution', start: '下单时段', end: '下单热门街区', col: 'right' },
  M05: { label: '下单热门街区', card: 'customer_distribution', start: '下单热门街区', end: null, col: 'full' },
  M06: { label: '顾客特征(互动行为+顾客画像)', card: 'customer_feature', start: null, end: '商圈顾客动态', col: 'full' },
};

const shopId = arg('shop-id');
const metricId = (arg('metric') || '').toUpperCase();
const outDir = arg('out', '.runtime/captures');
const expectName = arg('expect-name');
const skip30 = process.argv.includes('--skip-30');
if (!shopId || !METRICS[metricId]) { console.error('usage: --shop-id <id> --metric M02..M06 [--expect-name 店名] [--skip-30]'); process.exit(2); }
const M = METRICS[metricId];

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.error('FAIL frame ' + JSON.stringify(r)); process.exit(4); }
const ev = s.frameEval(r.id);
const inner = await ev('location.href');
if (!/\/single\//.test(inner)) { console.error('FAIL scope-not-single ' + inner); process.exit(9); }

const topName = await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`);
if (expectName && topName !== expectName) { console.error(`FAIL shop-mismatch expect=${expectName} got=${topName}`); process.exit(5); }

const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));

// ── 定位卡片与锚点（iframe 文档坐标）──
const geo = JSON.parse(await ev(`(()=>{
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const cards=[...document.querySelectorAll('.card-border')];
  const card=cards.find(c=>((c.className||'').toString()).indexOf(${JSON.stringify(M.card)})>=0);
  if(!card) return JSON.stringify({err:'card-not-found',have:cards.map(c=>(c.className||'').toString().replace('card-border','').trim())});
  const cr=card.getBoundingClientRect();
  const find=(t)=>{
    const n=[...card.querySelectorAll('*')].find(x=>(x.innerText||'').trim()===t && x.children.length<=1 && x.getBoundingClientRect().width>0);
    if(!n) return null;
    const rr=n.getBoundingClientRect();
    return {docY:Math.round(rr.y+window.scrollY),x:Math.round(rr.x),w:Math.round(rr.width)};
  };
  // 终点锚点常在下游卡片里（如「商圈顾客动态」不在 customer_feature 内）⇒ 全文找，取卡片下方的第一个
  const findAfter=(t, minY)=>{
    const cands=[...document.querySelectorAll('*')].filter(x=>(x.innerText||'').trim()===t && x.children.length<=1 && x.getBoundingClientRect().width>0)
      .map(x=>{const rr=x.getBoundingClientRect();return {docY:Math.round(rr.y+window.scrollY),x:Math.round(rr.x),w:Math.round(rr.width)}})
      .filter(o=>o.docY>minY).sort((a,b)=>a.docY-b.docY);
    return cands[0]||null;
  };
  const cardTopY=Math.round(cr.y+window.scrollY);
  return JSON.stringify({
    cardTop:cardTopY, cardH:Math.round(cr.height), cardX:Math.round(cr.x), cardW:Math.round(cr.width),
    start: ${JSON.stringify(M.start)} ? find(${JSON.stringify(M.start)}) : null,
    end: ${JSON.stringify(M.end)} ? (find(${JSON.stringify(M.end)}) || findAfter(${JSON.stringify(M.end)}, cardTopY)) : null,
    nextCard: (()=>{const i=cards.indexOf(card);const n=cards[i+1];return n?Math.round(n.getBoundingClientRect().y+window.scrollY):null})(),
  });
})()`));
if (geo.err) { console.error('FAIL ' + JSON.stringify(geo)); process.exit(6); }

// 计算截取区域（iframe 文档坐标）
// padTop：模块标题上方留白。-42 会切到上一行标题的残字（2026-10-20 踩过），改 20
let top = M.start ? (geo.start ? geo.start.docY - (M.padTop || 20) : null) : geo.cardTop - 8;
if (top === null) { console.error('FAIL start-anchor-missing:' + M.start); process.exit(6); }
let bottom;
if (M.end) { bottom = geo.end ? geo.end.docY - 12 : geo.nextCard; }
else { bottom = (geo.nextCard || geo.cardTop + geo.cardH) - 8; }
if (!bottom || bottom <= top) { console.error(`FAIL range-invalid top=${top} bottom=${bottom}`); process.exit(6); }

let x = geo.cardX, w = geo.cardW;
if (M.col === 'left') { w = Math.round(geo.cardW / 2) - 4; }
if (M.col === 'right') { x = geo.cardX + Math.round(geo.cardW / 2); w = Math.round(geo.cardW / 2); }

const region = { x, top, width: w, height: bottom - top };

// ── 时间口径校验：区域内真·时间控件须为近30日 ──
let timeCheck = null;
if (!skip30) {
  timeCheck = JSON.parse(await ev(`(()=>{
    const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
    const bad=[],good=[];
    document.querySelectorAll('.ant-select').forEach(n=>{
      const it=n.querySelector('.ant-select-selection-item');
      const t=it?(it.innerText||'').trim():'';
      if(!/^近\\d+日$/.test(t)) return;
      const y=docY(n);
      if(y<${region.top}-10||y>${region.top + region.height}+10) return;
      (t==='近30日'?good:bad).push({t,y});
    });
    const static30=${JSON.stringify(metricId)}==='M03' && [...document.querySelectorAll('.customer_distribution .one_option')].some(e=>(e.innerText||'').trim()==='近30日');
    return JSON.stringify({good,bad,static30});
  })()`));
  if (timeCheck.bad.length) { console.error('FAIL time-not-30 ' + JSON.stringify(timeCheck.bad)); process.exit(7); }
}

// ── 滚动到区域顶部并截图 ──
await ev(`window.scrollTo(0, Math.max(0, ${region.top} - 8))`);
await sleep(1800);
const scrollY = Number(await ev('window.scrollY'));

// 区域内可视高度（iframe 视口底部截断）
const clipY = box.y + (region.top - scrollY);
const maxH = box.y + box.h - clipY - 4;
const clipH = Math.min(region.height, maxH);
if (clipH < 120) {
  console.error(`FAIL clip-too-short h=${clipH} geo=${JSON.stringify(geo)} region=${JSON.stringify(region)} scrollY=${scrollY} box=${JSON.stringify(box)}`);
  process.exit(8);
}

const clip = { x: box.x + region.x, y: clipY, width: region.width, height: clipH, scale: 1 };
const png = await s.cdp.send('Page.captureScreenshot', { format: 'png', clip });
fs.mkdirSync(outDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
const file = path.join(outDir, `${metricId}_shop${shopId}_${stamp}.png`);
fs.writeFileSync(file, Buffer.from(png.data, 'base64'));
const bytes = fs.statSync(file).size;
if (bytes < 8000) { console.error('FAIL tiny-image ' + bytes); process.exit(8); }

console.log(JSON.stringify({
  ok: true, metric: metricId, label: M.label, shopId, topName,
  inner, region, scrollY, clip, file, bytes,
  truncated: clipH < region.height,
  timeCheck,
}, null, 1));
s.cdp.close();
process.exit(0);
