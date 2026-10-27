#!/usr/bin/env node
/**
 * M01 顾客评价采集器（9230 淘宝闪购品牌商 · comments 页）
 *
 * 与其他指标的区别：
 *   - 独立页面（iframe = melody-comment.faas.ele.me），不在 melody-stats-next
 *   - 不做时间切换：评分类是「更新于 10.20 04:56」的日更快照，页面无 30 日选择器
 *   - 区间裁剪：从「顾客评价」标题 → 「评价日期」筛选区之前（= 综合评分 + 评分明细 6 行）
 *     ★实测证据 .recon/evidence/comments_694471.png：这两块合计约 740px，一屏可容纳
 *       早期文档写的「整页长图」是预估，实拍证明不需要
 *
 * 硬判据（任一不满足即失败，绝不产出「看起来成功」的图）：
 *   1. iframe 必须是单店作用域（URL 含 /app/shop/ 或 /single/，不含 /chain/）
 *   2. 「评价详情」tab 必须处于激活态
 *   3. 三个关键分必须都在：最终评分 / 商品质量分 / 服务体验分
 *   4. 评分明细 6 行必须齐全（防止只渲染了一半就截）
 *
 * 退出码：
 *   0 成功 / 2 参数 / 3 无 target / 4 iframe 缺 / 5 店名不符
 *   6 锚点缺失 / 8 截图异常 / 9 非单店作用域 / 10 判据不足
 */
import fs from 'node:fs';
import path from 'node:path';
import { session, sleep } from './lib/cdp.mjs';

function arg(n, d = null) { const i = process.argv.indexOf('--' + n); return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : d; }

const shopId = arg('shop-id');
const outDir = arg('out', '.runtime/captures');
const expectName = arg('expect-name');
const noNav = process.argv.includes('--no-nav'); // 已在 comments 页时跳过导航
if (!shopId) { console.error('usage: --shop-id <id> [--expect-name 店名] [--out dir] [--no-nav]'); process.exit(2); }

const START = '顾客评价';
const END = '评价日期';           // 评价列表筛选区，不属于 M01，作为终点锚点
const KEYS = ['最终评分', '商品质量分', '服务体验分'];
const ROWS = ['口味满意度', '包装满意度', '复购率', '食品安全负反馈', '消息回复率', '服务负反馈'];

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();

// ── 1) 导航到 comments（path 变化会真重载）+ 硬刷新保证 iframe 作用域重建 ──
const want = `https://melody.shop.ele.me/app/shop/${shopId}/comments#app.shop.comments`;
const now = await s.mainEval('location.href');
if (!noNav && !/\/comments/.test(now)) {
  await s.mainEval(`location.href = ${JSON.stringify(want)}`);
  await sleep(9000);
  await s.cdp.send('Page.reload', { ignoreCache: true });
  await sleep(14000);
  await s.rearm();
}

// ── 2) 取 iframe context（按 frameId 绑，不按 origin —— 同源有多个 about:blank）──
const r = await s.waitFor(async () => {
  const x = await s.ctxForFrame(/melody-comment/);
  return x.err ? null : x;
}, { timeout: 30000, interval: 2000, label: 'comment-ctx' });
if (!r) { console.error('FAIL comment-frame-missing'); process.exit(4); }
const ev = s.frameEval(r.id);

const inner = await ev('location.href');
if (/\/chain\//.test(inner)) { console.error('FAIL scope-is-chain ' + inner); process.exit(9); }

const topName = await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`);
if (expectName && topName !== expectName) { console.error(`FAIL shop-mismatch expect=${expectName} got=${topName}`); process.exit(5); }

// iframe 在主文档中的位置（点击与裁剪都要用）
const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);if(!f)return '{}';const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));
if (!box.w) { console.error('FAIL iframe-box'); process.exit(4); }

// ── 3) 关引导弹窗（「评价共享」等），幂等 ──
const popup = await ev(`(()=>{
  const btn=[...document.querySelectorAll('button,.ant-btn,a,span')].find(x=>{
    const t=(x.innerText||'').trim();
    return (t==='知道了'||t==='我知道了'||t==='关闭') && x.getBoundingClientRect().width>0 && x.getBoundingClientRect().width<120;
  });
  if(btn){btn.click(); return (btn.innerText||'').trim();}
  return 'none';
})()`);
console.log('POPUP=' + popup);
await sleep(1200);

// ── 4) 确保「评价详情」tab 激活 ──
const tab = JSON.parse(await ev(`(()=>{
  const cands=[...document.querySelectorAll('*')].filter(n=>{
    const t=(n.innerText||'').trim();
    if(!/^评价详情$/.test(t)) return false;
    const r=n.getBoundingClientRect();
    return r.width>0 && r.width<200 && r.height<70 && n.children.length<=2;
  });
  if(!cands.length) return JSON.stringify({found:false});
  // 取最靠上的（tab 栏在页面顶部）
  const n=cands.sort((a,b)=>a.getBoundingClientRect().y-b.getBoundingClientRect().y)[0];
  const r=n.getBoundingClientRect();
  const cls=(n.className||'').toString()+' '+(n.parentElement?(n.parentElement.className||'').toString():'');
  return JSON.stringify({found:true,x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2),active:/active|selected|current|on/i.test(cls),cls:cls.slice(0,120)});
})()`));
if (!tab.found) { console.error('FAIL tab-评价详情-not-found'); process.exit(6); }
if (!tab.active) {
  await s.clickAt(box.x + tab.x, box.y + tab.y);
  await sleep(2200);
  tab.active=await ev(`(()=>{const ns=[...document.querySelectorAll('*')].filter(n=>(n.innerText||'').trim()==='评价详情'&&n.getBoundingClientRect().width>0&&n.getBoundingClientRect().width<200&&n.children.length<=2);return ns.some(n=>/active|selected|current|on/i.test(String(n.className)+' '+String(n.parentElement?.className)));})()`);
  if(!tab.active){console.error('FAIL tab-not-active');process.exit(6);}
  console.log('TAB_CLICKED');
} else {
  console.log('TAB_ALREADY_ACTIVE');
}

// ── 5) 定位锚点 + 判据校验 ──
const geo = JSON.parse(await ev(`(()=>{
  const docY=(n)=>Math.round(n.getBoundingClientRect().y+window.scrollY);
  const find=(t)=>{
    const n=[...document.querySelectorAll('*')].find(x=>{
      const s=(x.innerText||'').trim();
      return s===t && x.children.length<=2 && x.getBoundingClientRect().width>0 && x.getBoundingClientRect().width<400;
    });
    if(!n) return null;
    const r=n.getBoundingClientRect();
    return {docY:docY(n),x:Math.round(r.x),w:Math.round(r.width)};
  };
  const start=find(${JSON.stringify(START)});
  const end=find(${JSON.stringify(END)});
  const keys={};
  for(const k of ${JSON.stringify(KEYS)}) keys[k]=!!find(k);
  const rows={};
  for(const k of ${JSON.stringify(ROWS)}) rows[k]=!!find(k);
  return JSON.stringify({start,end,keys,rows,docH:document.documentElement.scrollHeight,vpH:window.innerHeight});
})()`));

if (!geo.start) { console.error('FAIL start-anchor-missing ' + JSON.stringify(geo)); process.exit(6); }
if (!geo.end) { console.error('FAIL end-anchor-missing ' + JSON.stringify(geo)); process.exit(6); }

const missingKeys = KEYS.filter((k) => !geo.keys[k]);
const missingRows = ROWS.filter((k) => !geo.rows[k]);
if (missingKeys.length) { console.error('FAIL key-scores-missing ' + JSON.stringify(missingKeys)); process.exit(10); }
if (missingRows.length) { console.error('FAIL detail-rows-missing ' + JSON.stringify(missingRows)); process.exit(10); }

// 裁剪区间：标题上方留 8，终点锚点上方 16（不要把评价列表的头带进来）
const top = geo.start.docY - 8;
const bottom = geo.end.docY - 16;
if (bottom <= top + 200) { console.error(`FAIL range-too-small top=${top} bottom=${bottom}`); process.exit(6); }

const docW = Number(await ev('document.documentElement.clientWidth'));
const region = { x: 0, top, width: docW, height: bottom - top };

// ── 6) 滚动到区域顶部再截（M01 内容在页面顶部，通常 scrollY=0）──
await ev(`window.scrollTo(0, Math.max(0, ${top} - 8))`);
await sleep(1500);
const scrollY = Number(await ev('window.scrollY'));

const clipY = box.y + (top - scrollY);
const maxH = box.y + box.h - clipY - 4;
const clipH = Math.min(region.height, maxH);
if (clipH < 300) {
  console.error(`FAIL clip-too-short h=${clipH} region=${JSON.stringify(region)} scrollY=${scrollY} box=${JSON.stringify(box)}`);
  process.exit(8);
}

const clip = { x: box.x + region.x, y: clipY, width: region.width, height: clipH, scale: 1 };
const png = await s.cdp.send('Page.captureScreenshot', { format: 'png', clip });
fs.mkdirSync(outDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
const file = path.join(outDir, `M01_shop${shopId}_${stamp}.png`);
fs.writeFileSync(file, Buffer.from(png.data, 'base64'));
const bytes = fs.statSync(file).size;
if (bytes < 8000) { console.error('FAIL tiny-image ' + bytes); process.exit(8); }

// 顺带把三个关键分读出来，供事后核对（截图无法机器校验数值；读不到只记 null，不作判据）
const nums = JSON.parse(await ev(`(()=>{
  const out={};
  const grab=(label)=>{
    const cands=[...document.querySelectorAll('*')].filter(x=>{
      const t=(x.innerText||'').trim();
      const r=x.getBoundingClientRect();
      return t===label && r.width>0 && r.width<220;
    });
    if(!cands.length) return null;
    // 取最内层（innerHTML 最短）那个，避免拿到整块容器的合并文本
    const n=cands.sort((a,b)=>a.innerHTML.length-b.innerHTML.length)[0];
    let p=n;
    for(let i=0;i<8&&p;i++){
      const m=(p.innerText||'').match(/(\\d+\\.\\d+)/);
      if(m) return m[1];
      p=p.parentElement;
    }
    return null;
  };
  for(const k of ${JSON.stringify(KEYS)}) out[k]=grab(k);
  // 「最终评分」卡片带星级图标和「=」，祖先里没有干净的小数文本 ⇒ 改用「字号最大的小数」定位
  // （实测：最终评分 32px，商品/服务体验分 28px，其余明细行 14px）
  if(!out['最终评分']){
    const big=[...document.querySelectorAll('*')].filter(x=>{
      const t=(x.innerText||'').trim();
      const r=x.getBoundingClientRect();
      return /^\\d+\\.\\d+$/.test(t) && x.children.length<=1 && r.width>0 && r.top>=0 && r.top<600;
    }).map(x=>({t:(x.innerText||'').trim(),fs:parseFloat(getComputedStyle(x).fontSize)||0,y:x.getBoundingClientRect().top}))
     .sort((a,b)=>b.fs-a.fs||a.y-b.y);
    if(big.length) out['最终评分']=big[0].t;
  }
  return JSON.stringify(out);
})()`));

console.log(JSON.stringify({
  ok: true, metric: 'M01', label: '顾客评价（综合评分）', shopId, topName,
  inner, tabActive: tab.active, region, scrollY, clip, file, bytes,
  truncated: clipH < region.height,
  keyScores: nums,
  docH: geo.docH, vpH: geo.vpH,
}, null, 1));
s.cdp.close();
process.exit(0);
