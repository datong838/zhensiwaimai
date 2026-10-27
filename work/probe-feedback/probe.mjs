#!/usr/bin/env node
// 只读 DOM 探针 · 负反馈列表页 · 严禁任何写操作（无 click / 无 input 赋值）
import fs from 'node:fs/promises';

const ENDPOINT = 'http://127.0.0.1:9232';
const OUT = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/probe-feedback/out';

class Cdp {
  constructor(ws) { this.ws = ws; this.next = 0; this.pending = new Map(); }
  static async open() {
    const targets = await (await fetch(`${ENDPOINT}/json/list`)).json();
    const pages = targets.filter(x => x.type === 'page' && x.url.startsWith('https://data.guoshuyufen.com/'));
    if (pages.length !== 1) throw Error(`page-count:${pages.length}`);
    const ws = new WebSocket(pages[0].webSocketDebuggerUrl);
    await new Promise((resolve, reject) => { ws.addEventListener('open', resolve, { once: true }); ws.addEventListener('error', reject, { once: true }); });
    const cdp = new Cdp(ws);
    ws.addEventListener('message', e => { const m = JSON.parse(e.data); const p = cdp.pending.get(m.id); if (p) { cdp.pending.delete(m.id); m.error ? p.reject(Error(m.error.message)) : p.resolve(m.result); } });
    return cdp;
  }
  call(method, params = {}, timeoutMs = 30000) {
    return new Promise((resolve, reject) => { const id = ++this.next; const t = setTimeout(() => { this.pending.delete(id); reject(Error('timeout:' + method)); }, timeoutMs); this.pending.set(id, { resolve: v => { clearTimeout(t); resolve(v); }, reject: er => { clearTimeout(t); reject(er); } }); this.ws.send(JSON.stringify({ id, method, params })); });
  }
  async eval(expression) { const out = await this.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true }); if (out.exceptionDetails) throw Error(out.exceptionDetails.exception?.description || out.exceptionDetails.text || 'eval-failed'); return out.result.value; }
  close() { this.ws.close(); }
}

const cdp = await Cdp.open();
const dump = {};
try {
  dump.overview = await cdp.eval(`(()=>({
    url: location.href,
    title: document.title,
    risk: /验证码|滑块|账号风险|请重新登录|登录失效/.test(document.body.innerText),
    loginMarkers: ['请输入手机号','账号登录','扫码登录'].filter(m=>document.body.innerText.includes(m)),
  }))()`);

  // 左侧菜单结构（找出 评价&负反馈 下的子菜单 + 路由线索）
  dump.leftMenu = await cdp.eval(`(()=>{
    const items=[...document.querySelectorAll('.cutli, .el-menu-item, aside li, .nav-item')].filter(x=>x.offsetParent!==null)
      .map(x=>({cls:x.className, text:(x.innerText||'').trim().slice(0,20)}));
    return items;
  })()`);

  // 顶部平台 tab（全部/美团/淘宝）+ 左侧渠道上下文
  dump.platformTabs = await cdp.eval(`(()=>[...document.querySelectorAll('input[type=radio]')].map(x=>({value:x.value,checked:x.checked,name:x.name})))()`);
  dump.channelContext = await cdp.eval(`(()=>{const v=[...document.querySelectorAll('.cutli')].filter(x=>x.offsetParent!==null);return {visible:v.length, pitch:v.filter(x=>x.classList.contains('pitchOn')).map(x=>(x.innerText||'').trim()), all:v.map(x=>(x.innerText||'').trim())}})()`);

  // 时间范围快捷 tab：昨日 / 近7日 / 近1个月 / 近2个月
  dump.dateQuickTabs = await cdp.eval(`(()=>[...document.querySelectorAll('*')].filter(x=>x.children.length===0&&x.offsetParent!==null&&/^(昨日|近7日|近1个月|近2个月)$/.test((x.innerText||'').trim())).map(x=>({tag:x.tagName,cls:String(x.className),parentCls:String(x.parentElement?.className),text:(x.innerText||'').trim()})))()`);
  dump.dateInputs = await cdp.eval(`(()=>[...document.querySelectorAll('input.el-range-input')].map(x=>x.value))()`);

  // 问题分类 tab：全部 / 食品安全负反馈 / 服务员负反馈
  dump.feedbackTypeTabs = await cdp.eval(`(()=>[...document.querySelectorAll('.navLi, .el-tabs__item, [class*=tab]')].filter(x=>x.offsetParent!==null&&/负反馈|全部\(\d+\)/.test((x.innerText||'').trim())).map(x=>({cls:x.className,text:(x.innerText||'').trim()})))()`);

  // 申诉状态 tab：全部/未申诉/申诉中/申诉成功/申诉失败
  dump.statusTabs = await cdp.eval(`(()=>[...document.querySelectorAll('.navLi')].filter(x=>x.offsetParent!==null).map(x=>({cls:x.className,active:x.classList.contains('active'),text:(x.innerText||'').trim().replace(/\\s+/g,' ')})))()`);

  dump.paginationTotal = await cdp.eval(`(()=>document.querySelector('.el-pagination__total')?.innerText||'')()`);
  dump.activePager = await cdp.eval(`(()=>[...document.querySelectorAll('.el-pager li')].filter(x=>x.offsetParent!==null).map(x=>({text:(x.innerText||'').trim(),active:x.classList.contains('active')})).slice(0,20))()`);

  // 卡片结构（第一张完整 innerText + 关键 class）
  dump.cards = await cdp.eval(`(()=>{
    const sel=['.cryptonym','.feedback-item','.el-card','[class*=item]'];
    let nodes=[], used='';
    for(const s of sel){const f=[...document.querySelectorAll(s)].filter(x=>x.offsetParent!==null&&x.innerText&&x.innerText.includes('订单编号'));if(f.length){nodes=f;used=s;break}}
    return {selectorUsed:used, count:nodes.length, samples:nodes.slice(0,2).map(n=>({
      cls:n.className,
      innerText:(n.innerText||''),
      buttons:[...n.querySelectorAll('button,.btn,[class*=btn]')].filter(b=>b.offsetParent!==null).map(b=>({tag:b.tagName,cls:b.className,text:(b.innerText||'').trim()})),
      shopName:n.querySelector('.shopName')?.innerText.trim()||'',
    }))};
  })()`);

  // 页面里所有可见按钮/链接（找「立即申诉」的真实 DOM 形态）
  dump.allButtons = await cdp.eval(`(()=>[...document.querySelectorAll('button,.btn,[class*=btn],a')].filter(x=>x.offsetParent!==null&&(x.innerText||'').trim()&&(x.innerText||'').trim().length<30).map(x=>({tag:x.tagName,cls:String(x.className).slice(0,60),text:(x.innerText||'').trim()})).slice(0,60))()`);

  // 是否存在弹窗（只读观察，不点）
  dump.modals = await cdp.eval(`(()=>[...document.querySelectorAll('.el-dialog__wrapper,.representations,[class*=dialog],[class*=modal]')].filter(x=>x.offsetParent!==null).map(x=>({cls:String(x.className).slice(0,80), text:(x.innerText||'').trim().slice(0,300)})))()`);
} finally {
  cdp.close();
}
await fs.mkdir(OUT, { recursive: true });
await fs.writeFile(`${OUT}/probe.json`, JSON.stringify(dump, null, 1), 'utf8');
console.log(JSON.stringify(dump, null, 1));