#!/usr/bin/env node
// 只读探针 v2 · 负反馈列表卡片容器 + 顶部平台/类型 tab + 分页。只读，不点击。
import fs from 'node:fs/promises';
const ENDPOINT = 'http://127.0.0.1:9232';
const OUT = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/probe-feedback/out';
class Cdp {
  constructor(ws){this.ws=ws;this.next=0;this.pending=new Map();}
  static async open(){const t=await(await fetch(`${ENDPOINT}/json/list`)).json();const p=t.filter(x=>x.type==='page'&&x.url.startsWith('https://data.guoshuyufen.com/'));if(p.length!==1)throw Error('page-count:'+p.length);const ws=new WebSocket(p[0].webSocketDebuggerUrl);await new Promise((res,rej)=>{ws.addEventListener('open',res,{once:true});ws.addEventListener('error',rej,{once:true})});const c=new Cdp(ws);ws.addEventListener('message',e=>{const m=JSON.parse(e.data);const d=c.pending.get(m.id);if(d){c.pending.delete(m.id);m.error?d.reject(Error(m.error.message)):d.resolve(m.result)}});return c;}
  call(method,params={},timeoutMs=30000){return new Promise((res,rej)=>{const id=++this.next;const t=setTimeout(()=>{this.pending.delete(id);rej(Error('timeout'))},timeoutMs);this.pending.set(id,{resolve:v=>{clearTimeout(t);res(v)},reject:e=>{clearTimeout(t);rej(e)}});this.ws.send(JSON.stringify({id,method,params}))})}
  async eval(e){const o=await this.call('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:true});if(o.exceptionDetails)throw Error(o.exceptionDetails.exception?.description||o.exceptionDetails.text||'eval-failed');return o.result.value}
  close(){this.ws.close()}
}
const T = v => String(v ?? '').replace(/\s+/g,' ').trim();
const cdp = await Cdp.open();
await cdp.eval(`window.__T = v => String(v ?? '').replace(/\\s+/g,' ').trim()`);
const d = {};
try {
  // 卡片：找 .appeal_btn 的祖先链
  d.ancestorChain = await cdp.eval(`(()=>{
    const btn=[...document.querySelectorAll('.appeal_btn')].filter(x=>x.offsetParent!==null)[0];
    if(!btn) return 'no-appeal-btn';
    const chain=[]; let n=btn;
    for(let i=0;i<8&&n;i++,n=n.parentElement) chain.push({tag:n.tagName,cls:String(n.className)});
    return chain;
  })()`);

  // 卡片容器 class + 数量 + 首卡完整文本与字段 class
  d.cardModel = await cdp.eval(`(()=>{
    const btns=[...document.querySelectorAll('.appeal_btn')].filter(x=>x.offsetParent!==null);
    if(!btns.length) return {count:0};
    let card=btns[0];
    for(let i=0;i<8;i++){ if(card.parentElement && card.parentElement.querySelectorAll('.appeal_btn').length===btns.length) card=card.parentElement; else break; }
    return {
      count: btns.length,
      containerTag: card.tagName, containerCls: String(card.className),
      innerText: __T(card.innerText),
      childClasses: [...new Set([...card.querySelectorAll('*')].map(x=>String(x.className)).filter(Boolean))].slice(0,40),
      orderNo: (card.innerText.match(/订单编号[:：]?\\s*(\\S+)/)||[])[1]||'',
      hasAppealBtn: card.querySelectorAll('.appeal_btn').length,
    };
  })()`);

  // 所有卡片的稳定键候选
  d.cards = await cdp.eval(`(()=>{
    const btns=[...document.querySelectorAll('.appeal_btn')].filter(x=>x.offsetParent!==null);
    const out=[];
    for(const b of btns){
      let card=b;
      for(let i=0;i<8;i++){ if(card.parentElement && card.parentElement.querySelectorAll('.appeal_btn').length===btns.length) card=card.parentElement; else break; }
      const t=__T(card.innerText);
      out.push({store:(t.match(/^(.{2,30}?)\\n/)||[])[1]||'', date:(t.match(/20\\d{2}-\\d{2}-\\d{2}/)||[])[0]||'', order:(t.match(/订单编号[:：]?\\s*(\\S+)/)||[])[1]||'', appealText:__T(b.innerText), text:t.slice(0,220)});
    }
    return out;
  })()`);

  // 顶部平台单选（图1 全部/美团/淘宝）
  d.topRadios = await cdp.eval(`(()=>[...document.querySelectorAll('input[type=radio]')].map(x=>({value:x.value,checked:x.checked,label:__T(x.closest('label')?.innerText||x.parentElement?.innerText)})))()`);
  // radio 可见标签
  d.radioLabels = await cdp.eval(`(()=>[...document.querySelectorAll('.el-radio-button__inner, .radio, [class*=radio]')].filter(x=>x.offsetParent!==null).map(x=>({cls:String(x.className),text:__T(x.innerText)})).slice(0,20))()`);
  // 问题分类 tab（全部/食品安全负反馈/服务员负反馈）
  d.typeTabs = await cdp.eval(`(()=>[...document.querySelectorAll('div,span,li')].filter(x=>x.children.length===0&&x.offsetParent!==null&&/负反馈|全部/.test((x.innerText||'').trim())&&(x.innerText||'').trim().length<15).map(x=>({tag:x.tagName,cls:String(x.className),text:__T(x.innerText)})))()`);
  // 搜索框
  d.searchInputs = await cdp.eval(`(()=>[...document.querySelectorAll('input')].filter(x=>x.offsetParent!==null).map(x=>({type:x.type,ph:x.placeholder||'',cls:String(x.className)})))()`);
  // 分页
  d.pager = await cdp.eval(`(()=>({total:__T(document.querySelector('.el-pagination__total')?.innerText),pages:[...document.querySelectorAll('.el-pager li')].filter(x=>x.offsetParent!==null).map(x=>__T(x.innerText)),sizeSel:__T(document.querySelector('.el-pagination__sizes .el-input__inner')?.value)}))()`);
} finally { cdp.close(); }
await fs.mkdir(OUT,{recursive:true});
await fs.writeFile(`${OUT}/probe2.json`,JSON.stringify(d,null,1),'utf8');
console.log(JSON.stringify(d,null,1));