#!/usr/bin/env node
// 只读探针 v3 · 按已确认的 .feedback 卡片容器取全字段（不点击）
import fs from 'node:fs/promises';
const ENDPOINT='http://127.0.0.1:9232';
const OUT='/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/work/probe-feedback/out';
class Cdp{
  constructor(ws){this.ws=ws;this.next=0;this.pending=new Map();}
  static async open(){const t=await(await fetch(`${ENDPOINT}/json/list`)).json();const p=t.filter(x=>x.type==='page'&&x.url.startsWith('https://data.guoshuyufen.com/'));if(p.length!==1)throw Error('page-count:'+p.length);const ws=new WebSocket(p[0].webSocketDebuggerUrl);await new Promise((res,rej)=>{ws.addEventListener('open',res,{once:true});ws.addEventListener('error',rej,{once:true})});const c=new Cdp(ws);ws.addEventListener('message',e=>{const m=JSON.parse(e.data);const d=c.pending.get(m.id);if(d){c.pending.delete(m.id);m.error?d.reject(Error(m.error.message)):d.resolve(m.result)}});return c;}
  call(m,p={},to=30000){return new Promise((res,rej)=>{const id=++this.next;const t=setTimeout(()=>{this.pending.delete(id);rej(Error('timeout'))},to);this.pending.set(id,{resolve:v=>{clearTimeout(t);res(v)},reject:e=>{clearTimeout(t);rej(e)}});this.ws.send(JSON.stringify({id,method:m,params:p}))})}
  async eval(e){const o=await this.call('Runtime.evaluate',{expression:e,returnByValue:true,awaitPromise:true});if(o.exceptionDetails)throw Error(o.exceptionDetails.exception?.description||o.exceptionDetails.text||'ev');return o.result.value}
  close(){this.ws.close()}
}
const cdp=await Cdp.open();
const d={};
try{
  d.feedbackCount=await cdp.eval(`document.querySelectorAll('.feedback').length`);
  // 单卡完整结构
  d.oneCard=await cdp.eval(`(()=>{
    const c=document.querySelectorAll('.feedback')[0]; if(!c) return null;
    return {
      fullText: c.innerText,
      classes: [...new Set([...c.querySelectorAll('*')].map(x=>String(x.className)).filter(Boolean))],
      appealBtns: [...c.querySelectorAll('.appeal_btn')].map(b=>({text:b.innerText.trim(),visible:b.offsetParent!==null})),
      topLevelChildren: [...c.children].map(x=>({cls:String(x.className),text:x.innerText.trim().slice(0,80)})),
    };
  })()`);
  // 全部 9 条的稳定字段
  d.rows=await cdp.eval(`(()=>[...document.querySelectorAll('.feedback')].map(c=>{
    const t=c.innerText||'';
    return {
      store: (t.match(/^(.+?)\\n\\s*\\d/)||[])[1]||'',
      date: (t.match(/20\\d{2}-\\d{2}-\\d{2}/)||[])[0]||'',
      order: (t.match(/订单编号[:：]?\\s*(\\S+)/)||[])[1]||'',
      channel: (t.match(/反馈渠道[:：]?\\s*(\\S+)/)||[])[1]||'',
      category: (t.match(/问题分类[:：]?\\s*([^\\n]+)/)||[])[1]||'',
      appealBtn: (([...c.querySelectorAll('.appeal_btn')].filter(b=>b.offsetParent!==null).map(b=>b.innerText.trim())[0])||''),
      text: t.slice(0,300),
    };
  }))()`);
  // 状态 tab 完整清单
  d.statusBtns=await cdp.eval(`(()=>[...document.querySelectorAll('.status-btn')].map(x=>({text:x.innerText.trim(),active:x.classList.contains('active')})))()`);
  // 顶部平台 tab（图1 全部/美团/淘宝）
  d.platformTabs=await cdp.eval(`(()=>[...document.querySelectorAll('.optionli, [class*=option]')].filter(x=>x.offsetParent!==null).map(x=>({cls:String(x.className),text:x.innerText.trim()})))()`);
  // 类型 tab：全部/食品安全负反馈/服务员负反馈
  d.fbTypeTabs=await cdp.eval(`(()=>[...document.querySelectorAll('div,li,span')].filter(x=>x.children.length===0&&x.offsetParent!==null&&/负反馈/.test((x.innerText||'').trim())).map(x=>({cls:String(x.className),text:x.innerText.trim()})))()`);
  // 顶部平台切换控件（含全部/美团/淘宝）
  d.topSwitch=await cdp.eval(`(()=>[...document.querySelectorAll('*')].filter(x=>x.children.length===0&&x.offsetParent!==null&&/^(全部|美团|淘宝|京东)$/.test((x.innerText||'').trim())).map(x=>({tag:x.tagName,cls:String(x.className),parent:String(x.parentElement?.className),text:x.innerText.trim()})))()`);
  d.pager=await cdp.eval(`(()=>({total:(document.querySelector('.el-pagination__total')?.innerText||'').trim(),pagers:[...document.querySelectorAll('.el-pager li')].filter(x=>x.offsetParent!==null).map(x=>x.innerText.trim())}))()`);
}finally{cdp.close()}
await fs.mkdir(OUT,{recursive:true});
await fs.writeFile(`${OUT}/probe3.json`,JSON.stringify(d,null,1),'utf8');
console.log(JSON.stringify(d,null,1));