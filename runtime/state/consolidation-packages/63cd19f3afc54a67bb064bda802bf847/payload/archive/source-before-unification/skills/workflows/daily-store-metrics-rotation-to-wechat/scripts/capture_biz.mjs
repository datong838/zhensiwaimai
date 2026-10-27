#!/usr/bin/env node
/**
 * 经营分析采集器（M07–M11，9230 品牌商 · 数据中心 › 经营分析）
 *
 * 与顾客分析采集器的三点不同：
 * 1. 跨 tab：tab 栏在 iframe 内、不是 antd tabs，只能按坐标点，点完回读 hash 的 tab= 才算切换成功
 * 2. 时间控件是**单选按钮组**（ant-radio-button-wrapper），不是下拉；服务 tab 里还有三套独立控件
 * 3. 一个指标可能出多张图（M11 = 数据概览 + 营业分析 + 出餐时效）
 *
 * 用法：
 *   node capture_biz.mjs --shop-id 694471 --metric M08
 *   node capture_biz.mjs --shop-id 694471 --metric M11 --out .runtime/captures
 *
 * 退出码：
 *   0 成功 / 2 参数 / 3 无 target / 4 iframe 缺 / 5 店名不符
 *   6 锚点缺失 / 7 tab 切换失败 / 8 时间口径未达标 / 9 作用域非 single / 10 截图异常
 */
import fs from 'node:fs';
import path from 'node:path';
import { session, sleep } from './lib/cdp.mjs';
import {uniqueGoodsGroup} from './lib/time_controls.mjs';

function arg(n, d = null) { const i = process.argv.indexOf('--' + n); return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : d; }

// tab 坐标（1440 宽实测）与 hash 值
const TABS = {
  总览: { x: 46, y: 87, key: 'overview' },
  流量: { x: 310, y: 87, key: 'flowmeter' },
  商品: { x: 490, y: 87, key: 'goods' },
  服务: { x: 550, y: 87, key: 'service' },
};

// 时间控件定位器：单选组/下拉 用 y 区间 + x 区间圈定，避免同页多组互相串
const METRICS = {
  M07: {
    label: '历史数据概览', tab: '总览',
    // 只取「历史数据概览」核心（订单分析/流量分析/顾客分析 + 右侧同行洞察），
    // 不吞 服务分析/市场洞察/营销效果/商品分析（那样一张图 1398px 高，且混入别的维度）
    regions: [{ name: '历史数据概览', start: '历史数据概览', end: '服务分析', padTop: 20 }],
    times: [{ kind: 'radio', target: '近30日', yMin: 560, yMax: 760 }],
  },
  M08: {
    label: '流量转化', tab: '流量',
    regions: [{ name: '流量转化', start: '流量转化', end: '流量趋势', padTop: 20 }],
    times: [{ kind: 'radio', target: '近30日', yMin: 90, yMax: 170 }],
  },
  M09: {
    label: '自然流量来源', tab: '流量',
    regions: [{ name: '自然流量来源', start: '自然流量来源', end: '店内流量分布', padTop: 20 }],
    times: [{ kind: 'radio', target: '近30日', yMin: 90, yMax: 170 }],
  },
  M10: {
    label: '销售情况(商品明细)', tab: '商品',
    regions: [{ name: '商品明细', start: '商品明细', end: '淘宝闪购生意参谋', padTop: 6 }],
    times: [{ kind: 'radio', target: '近30日', yMin: 150, yMax: 240 }],
  },
  M11: {
    label: '服务数据', tab: '服务',
    regions: [
      { name: '数据概览', start: '数据概览', end: '营业分析', padTop: 20 },
      { name: '营业分析', start: '营业分析', end: '纠纷单分析', padTop: 20, col: 'left' },
      { name: '出餐时效', start: '出餐时效', end: '纠纷单分析', padTop: 20, col: 'right' },
    ],
    times: [
      { kind: 'select', target: '本周', yMin: 170, yMax: 280, label: '数据概览' },
      // 服务 tab 的两个区间不是 boxed 单选，是**文字式控件** span.activated（橙色 rgb(255,98,0)）
      { kind: 'texttab', target: '近30日', yMin: 500, yMax: 580, xMax: 600, label: '营业分析' },
      { kind: 'texttab', target: '近30日', yMin: 500, yMax: 580, xMin: 600, label: '出餐时效' },
    ],
  },
};

const shopId = arg('shop-id');
const metricId = (arg('metric') || '').toUpperCase();
const outDir = arg('out', '.runtime/captures');
const expectName = arg('expect-name');
if (!shopId || !METRICS[metricId]) { console.error('usage: --shop-id <id> --metric M07..M11 [--expect-name 店名]'); process.exit(2); }
const M = METRICS[metricId];

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.error('FAIL frame ' + JSON.stringify(r)); process.exit(4); }
const ev = s.frameEval(r.id);

const inner0 = await ev('location.href');
if (!/\/single\//.test(inner0)) { console.error('FAIL scope-not-single ' + inner0); process.exit(9); }
if (!/business-analysis/.test(inner0)) { console.error('FAIL not-business-analysis ' + inner0); process.exit(9); }

const topName = await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`);
if (expectName && topName !== expectName) { console.error(`FAIL shop-mismatch expect=${expectName} got=${topName}`); process.exit(5); }

const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));

// ── 1) 切 tab（坐标点 + 回读 hash）──
const curTab = () => ev(`(()=>{const q=location.hash.split('?')[1]||'';return new URLSearchParams(q).get('tab')||''})()`);
const want = TABS[M.tab];
if (await curTab() !== want.key) {
  await ev('window.scrollTo(0,0)');
  await sleep(600);
  await s.clickAt(box.x + want.x, box.y + want.y);
  const okTab = await s.waitFor(async () => (await curTab()) === want.key, { timeout: 12000, interval: 800, label: 'tab' });
  if (!okTab) { console.error(`FAIL tab-switch want=${want.key} got=${await curTab()}`); process.exit(7); }
}
await sleep(2500);

// ── 2) 设定时间口径（逐组，回读校验）──
// 控件有三种形态，实测于 2026-10-20：
//   radio   = antd boxed 单选 label.ant-radio-button-wrapper（checked 类）
//   texttab = 文字式快捷区间 span（激活态类名 activated，橙色 rgb(255,98,0)）
//   select  = antd 下拉（数据概览「本周」）
const timeResults = [];
let goodsGroup=null;
if(metricId==='M10'){
 const groups=await ev(`(()=>[...document.querySelectorAll('.ant-radio-group')].map((g,index)=>({index,visible:g.getBoundingClientRect().width>0&&getComputedStyle(g).visibility!=='hidden',labels:[...g.querySelectorAll('.ant-radio-button-wrapper')].map(n=>n.innerText.trim())})))()`);
 goodsGroup=uniqueGoodsGroup(groups||[]);
}
for (const t of M.times) {
  const SEL = t.kind === 'radio' ? '.ant-radio-button-wrapper' : 'span';
  const CHK = t.kind === 'radio' ? 'checked' : 'activated';
  const TXTF = t.kind === 'texttab'
    ? "&& /^(昨日|近7日|近30日|自定义)$/.test((n.innerText||'').trim()) && n.children.length===0 && n.getBoundingClientRect().width<90"
    : '';
  const bandFn = goodsGroup!==null ? `const group=document.querySelectorAll('.ant-radio-group')[${goodsGroup}];const band=n=>!!group&&group.contains(n)&&n.getBoundingClientRect().width>0;` : `const docY=(n)=>Math.round(n.getBoundingClientRect().y+window.scrollY);
    const band=(n)=>{const y=docY(n);const x=n.getBoundingClientRect().x;
      return y>=${t.yMin}&&y<=${t.yMax} && (${t.xMin == null ? 'true' : `x>=${t.xMin}`}) && (${t.xMax == null ? 'true' : `x<=${t.xMax}`});};`;

  const st = JSON.parse(await ev(`(()=>{
    ${bandFn}
    const out={radios:[],select:null};
    if('${t.kind}'!=='select'){
      out.radios=[...document.querySelectorAll('${SEL}')].filter(band).filter(n=>true ${TXTF}).map(n=>{
        const r=n.getBoundingClientRect();
        return {t:(n.innerText||'').trim(),checked:/${CHK}/.test((n.className||'').toString()),x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};
      });
    } else {
      const n=[...document.querySelectorAll('.ant-select-selection-item')].filter(band)[0];
      if(n){const r=n.getBoundingClientRect();out.select={t:(n.innerText||'').trim(),x:Math.round(r.x+r.width/2),y:Math.round(r.y+r.height/2)};}
    }
    return JSON.stringify(out);
  })()`));

  if (t.kind !== 'select') {
    const tag = t.kind === 'radio' ? 'no-radio-in-band' : 'no-texttab-in-band';
    if (!st.radios.length) { timeResults.push({ ...t, ok: false, note: tag }); continue; }
    const cur = st.radios.find((x) => x.checked);
    if (cur && cur.t === t.target) { timeResults.push({ ...t, before: cur.t, after: cur.t, ok: true, note: 'already' }); continue; }
    const tgt = st.radios.find((x) => x.t === t.target);
    if (!tgt) { timeResults.push({ ...t, ok: false, note: 'target-not-found', have: st.radios.map((x) => x.t) }); continue; }
    await s.clickAt(tgt.x + box.x, tgt.y + box.y);
    await sleep(2600);
    const back = JSON.parse(await ev(`(()=>{
      ${bandFn}
      const c=[...document.querySelectorAll('${SEL}')].filter(band).filter(n=>true ${TXTF}).filter(n=>/${CHK}/.test((n.className||'').toString()));
      return JSON.stringify({cur:c.length?(c[0].innerText||'').trim():''});
    })()`));
    timeResults.push({ ...t, before: cur ? cur.t : '?', after: back.cur, ok: back.cur === t.target, note: back.cur === t.target ? 'switched' : 'readback-mismatch' });
  } else {
    if (!st.select) { timeResults.push({ ...t, ok: false, note: 'no-select-in-band' }); continue; }
    if (st.select.t === t.target) { timeResults.push({ ...t, before: st.select.t, after: st.select.t, ok: true, note: 'already' }); continue; }
    await s.clickAt(st.select.x + box.x, st.select.y + box.y);
    await sleep(1200);
    const opt = await s.waitFor(async () => {
      const o = await ev(`(()=>{
        const dds=[...document.querySelectorAll('.ant-select-dropdown')].filter(d=>{const r=d.getBoundingClientRect();return r.width>30&&r.height>15&&getComputedStyle(d).display!=='none'});
        for(const d of dds){const it=[...d.querySelectorAll('.ant-select-item-option')].find(x=>(x.innerText||'').trim()===${JSON.stringify(t.target)});
          if(it){const r=it.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})}}
        return null;
      })()`);
      return o ? JSON.parse(o) : null;
    }, { timeout: 6000, interval: 400, label: 'opt' });
    if (!opt) { timeResults.push({ ...t, ok: false, note: 'no-option' }); continue; }
    await s.clickAt(opt.x + box.x, opt.y + box.y);
    await sleep(2400);
    const back = await ev(`(()=>{
      const docY=(n)=>Math.round(n.getBoundingClientRect().y+window.scrollY);
      const band=(n)=>{const y=docY(n);const x=n.getBoundingClientRect().x;
        return y>=${t.yMin}&&y<=${t.yMax} && (${t.xMin == null ? 'true' : `x>=${t.xMin}`}) && (${t.xMax == null ? 'true' : `x<=${t.xMax}`});};
      const n=[...document.querySelectorAll('.ant-select-selection-item')].filter(band)[0];
      return n?(n.innerText||'').trim():'';
    })()`);
    timeResults.push({ ...t, before: st.select.t, after: back, ok: back === t.target, note: back === t.target ? 'switched' : 'readback-mismatch' });
  }
}
const timeOk = timeResults.every((x) => x.ok);

// ── 3) 逐区间截图 ──
fs.mkdirSync(outDir, { recursive: true });
const stamp = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
const files = [];
const shots = [];

// ★sticky 表头高度：经营分析页的 tab 栏 + 时间条是 sticky，滚动后会盖住模块首行
// （M07 首版就是因为这个把「历史数据概览」标题压在下面 → 图里看不到标题）
const stickyH = Number(await ev(`(()=>{
  let h=0;
  for(const n of document.querySelectorAll('*')){
    const cs=getComputedStyle(n);
    if(cs.position!=='sticky'&&cs.position!=='fixed') continue;
    const r=n.getBoundingClientRect();
    if(r.width<600||r.height<=0) continue;
    if(r.bottom>0&&r.bottom<220) h=Math.max(h,r.bottom);
  }
  return h||112;
})()`));

for (const reg of M.regions) {
  const geo = JSON.parse(await ev(`(()=>{
    const docY=(n)=>Math.round(n.getBoundingClientRect().y+window.scrollY);
    const find=(t, root)=>{
      const scope=root||document;
      // 标题常带「?」提示图标 ⇒ 子元素可能 2~4 个，放宽到 4；先精确匹配，再退化到包含匹配
      const ok=(x)=>{const r=x.getBoundingClientRect();return (x.innerText||'').trim();};
      let n=[...scope.querySelectorAll('*')].find(x=>ok(x)===t && x.children.length<=4 && x.getBoundingClientRect().width>0 && x.getBoundingClientRect().width<1250);
      if(!n) n=[...scope.querySelectorAll('*')].find(x=>ok(x).indexOf(t)===0 && x.children.length<=4 && x.getBoundingClientRect().width>0 && x.getBoundingClientRect().width<1250);
      if(!n) return null;
      const r=n.getBoundingClientRect();
      return {docY:docY(n),x:Math.round(r.x),el:n};
    };
    const st=find(${JSON.stringify(reg.start)});
    if(!st) return JSON.stringify({err:'start-not-found'});
    // 容器模式：向上找同时含 mustContain 的最小祖先
    let top=st.docY-${reg.padTop || 20}, bottom=null, x=null, w=null;
    if(${JSON.stringify(reg.containerContains || null)}){
      const must=${JSON.stringify(reg.containerContains || [])};
      let p=st.el, hit=null;
      for(let i=0;i<10&&p;i++,p=p.parentElement){
        const txt=p.innerText||'';
        if(must.every(m=>txt.indexOf(m)>=0)){hit=p;break;}
      }
      if(hit){const r=hit.getBoundingClientRect();top=docY(hit)-6;bottom=docY(hit)+Math.round(r.height)+6;x=Math.round(r.x);w=Math.round(r.width);}
    }
    const en=${JSON.stringify(reg.end)}?find(${JSON.stringify(reg.end)}):null;
    if(bottom===null){ bottom = en ? en.docY-12 : document.documentElement.scrollHeight-8; }
    if(x===null){
      // 默认按主内容区：取页面主容器
      const main=[...document.querySelectorAll('div')].find(n=>{const r=n.getBoundingClientRect();return r.width>1000&&r.width<1250&&r.x<80&&r.x>0});
      const r=main?main.getBoundingClientRect():{x:32,width:1152};
      x=Math.round(r.x); w=Math.round(r.width);
    }
    if('${reg.col || ''}'==='left'){ w=Math.round(w/2)-4; }
    if('${reg.col || ''}'==='right'){ x=x+Math.round(w/2); w=Math.round(w/2); }
    return JSON.stringify({top,bottom,x,w});
  })()`));

  if (geo.err) { shots.push({ name: reg.name, ok: false, reason: geo.err }); continue; }
  const height = geo.bottom - geo.top;
  if (height < 80) { shots.push({ name: reg.name, ok: false, reason: 'region-too-short', height }); continue; }

  await ev('window.scrollTo(0, Math.max(0, ' + geo.top + ' - ' + stickyH + ' - 8))');
  await sleep(1600);
  const scrollY = Number(await ev('window.scrollY'));
  const clipY = box.y + (geo.top - scrollY);
  const maxH = box.y + box.h - clipY - 4;
  const clipH = Math.min(height, maxH);
  if (clipH < 120) { shots.push({ name: reg.name, ok: false, reason: 'clip-too-short', clipH, geo, scrollY }); continue; }

  const clip = { x: box.x + geo.x, y: clipY, width: geo.w, height: clipH, scale: 1 };
  const png = await s.cdp.send('Page.captureScreenshot', { format: 'png', clip });
  const suffix = M.regions.length > 1 ? '_' + reg.name : '';
  const file = path.join(outDir, `${metricId}${suffix}_shop${shopId}_${stamp}.png`);
  fs.writeFileSync(file, Buffer.from(png.data, 'base64'));
  const bytes = fs.statSync(file).size;
  files.push(file);
  shots.push({ name: reg.name, ok: bytes > 8000, file, bytes, clip, truncated: clipH < height });
}

const allOk = timeOk && shots.every((x) => x.ok) && shots.length === M.regions.length;
console.log(JSON.stringify({
  ok: allOk, metric: metricId, label: M.label, shopId, topName,
  tab: await curTab(), innerUrl: (await ev('location.href')),
  times: timeResults, shots, files,
}, null, 1));
s.cdp.close();
process.exit(allOk ? 0 : (timeOk ? 10 : 8));
