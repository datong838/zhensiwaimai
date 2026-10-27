#!/usr/bin/env node
/**
 * 把 business-analysis 页所有「真·时间控件」切到「近30日」
 *
 * 目标定义（2026-10-20 实测，大同明确「全部都选30日」）：
 *   真控件 = .ant-select（有 show-arrow，点开有 .ant-select-item-option）
 *   静态标签 = .select > .one_option 单子元素（下单行为 / 互动行为），不可切，只记录
 *
 * 关键修正（踩过）：回读**必须校验同一个元素**，不能按 docY 邻近找 ——
 *   同一行有两个控件时（下单行为静态30日 + 下单时段7日）会读错，误判成功。
 *   做法：给 .ant-select 打 data-wb 标记，回读时按标记取同一个容器内的 selection-item。
 *
 * 退出码：0 全部达标 / 1 有真控件未达标 / 3 无 target / 4 iframe 缺 / 7 非 single 作用域
 */
import { session, sleep } from './lib/cdp.mjs';

function arg(n, d = null) { const i = process.argv.indexOf('--' + n); return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : d; }
const TARGET = arg('target', '近30日');

const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const r = await s.ctxForFrame(/melody-stats-next/);
if (r.err) { console.error('FAIL frame ' + JSON.stringify(r)); process.exit(4); }
const ev = s.frameEval(r.id);
const inner = await ev('location.href');
if (!/\/single\//.test(inner)) { console.error('FAIL scope-not-single ' + inner); process.exit(7); }

const box = JSON.parse(await s.mainEval(`(()=>{const f=[...document.querySelectorAll('iframe')].find(i=>i.clientWidth>300);const b=f.getBoundingClientRect();return JSON.stringify({x:b.x,y:b.y,w:b.width,h:b.height})})()`));

// 打标记 + 枚举（只标记真控件：.ant-select）
const enumerate = () => ev(`(()=>{
  const docY=(n)=>{const r=n.getBoundingClientRect();return Math.round(r.y+window.scrollY)};
  const cards=[...document.querySelectorAll('.card-border')];
  const owner=(n)=>{for(const c of cards){if(c.contains(n))return (c.className||'').toString().replace('card-border','').trim()}return '?'};
  // 找控件所属模块名：向上找最近的 .period_title/.h3，或卡片名
  const moduleOf=(n)=>{
    let p=n;
    for(let i=0;i<8&&p;i++,p=p.parentElement){
      const t=[...p.querySelectorAll('.period_title,.h3')].map(x=>(x.innerText||'').trim()).filter(Boolean);
      if(t.length) return t[0];
    }
    return owner(n);
  };
  const out=[];
  let i=0;
  document.querySelectorAll('.ant-select').forEach(n=>{
    const it=n.querySelector('.ant-select-selection-item');
    const t=it?(it.innerText||'').trim():'';
    if(!/^近\\d+日$/.test(t)) return;
    const rc=n.getBoundingClientRect();
    if(!rc.width) return;
    n.setAttribute('data-wb', String(i));
    out.push({idx:i,kind:'antd',value:t,card:owner(n),module:moduleOf(n),docY:docY(n),x:rc.x+rc.width/2,y:rc.y+rc.height/2});
    i++;
  });
  // 静态标签
  const statics=[];
  document.querySelectorAll('.one_option').forEach(n=>{
    const t=(n.innerText||'').trim();
    if(!/^近\\d+日$/.test(t)) return;
    const rc=n.getBoundingClientRect();
    if(!rc.width) return;
    const only=n.parentElement && n.parentElement.children.length===1 && !n.parentElement.querySelector('.ant-select');
    if(only) statics.push({value:t,card:owner(n),docY:docY(n),note:'static-label'});
  });
  return JSON.stringify({controls:out,statics});
})()`);

const first = JSON.parse(await enumerate());
const controls = first.controls;
const results = [];

for (const c of controls) {
  // 滚到视野
  await ev(`window.scrollTo(0, Math.max(0, ${c.docY} - 400))`);
  await sleep(900);
  const cur = JSON.parse(await ev(`(()=>{
    const n=document.querySelector('[data-wb="${c.idx}"]');
    if(!n) return JSON.stringify({err:'marker-lost'});
    const it=n.querySelector('.ant-select-selection-item');
    const rc=n.getBoundingClientRect();
    return JSON.stringify({value:it?(it.innerText||'').trim():'',x:rc.x+rc.width/2,y:rc.y+rc.height/2,docY:Math.round(rc.y+window.scrollY)});
  })()`));
  if (cur.err) { results.push({ ...c, before: c.value, after: '', ok: false, note: 'marker-lost(dom-replaced)' }); continue; }
  if (cur.value === TARGET) { results.push({ ...c, before: cur.value, after: cur.value, ok: true, note: 'already' }); continue; }

  await s.clickAt(cur.x + box.x, cur.y + box.y);
  await sleep(1200);
  const opt = await s.waitFor(async () => {
    const o = await ev(`(()=>{
      const dds=[...document.querySelectorAll('.ant-select-dropdown')].filter(d=>{
        const r=d.getBoundingClientRect();
        return r.width>40&&r.height>20&&getComputedStyle(d).display!=='none';
      });
      for(const d of dds){
        const it=[...d.querySelectorAll('.ant-select-item-option')].find(x=>(x.innerText||'').trim()===${JSON.stringify(TARGET)});
        if(it){const r=it.getBoundingClientRect();return JSON.stringify({x:r.x+r.width/2,y:r.y+r.height/2})}
      }
      return null;
    })()`);
    return o ? JSON.parse(o) : null;
  }, { timeout: 6000, interval: 400, label: 'option' });

  if (!opt) {
    await s.cdp.send('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    await s.cdp.send('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Escape', code: 'Escape', windowsVirtualKeyCode: 27 });
    results.push({ ...c, before: cur.value, after: cur.value, ok: false, note: 'no-visible-option' });
    continue;
  }
  await s.clickAt(opt.x + box.x, opt.y + box.y);
  await sleep(2600);

  // 回读同一个元素（按 data-wb 标记）
  const after = await ev(`(()=>{
    const n=document.querySelector('[data-wb="${c.idx}"]');
    if(!n) return 'marker-lost';
    const it=n.querySelector('.ant-select-selection-item');
    return it?(it.innerText||'').trim():'';
  })()`);
  results.push({ ...c, before: cur.value, after, ok: after === TARGET, note: after === TARGET ? 'switched' : 'readback-mismatch' });
}

const allOk = results.every((x) => x.ok);
const out = {
  shopTop: await s.mainEval(`(()=>{const n=document.querySelector('[class*=shop-name__]');return n?n.innerText.trim():''})()`),
  target: TARGET, innerUrl: inner, controls: results, statics: first.statics, allOk,
};
console.log(JSON.stringify(out, null, 1));
s.cdp.close();
process.exit(allOk ? 0 : 1);
