#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const ENDPOINT='http://127.0.0.1:9232';
const ORIGIN='https://data.guoshuyufen.com/';
const HOME=`${ORIGIN}#/businessData/realTimeData`;
const NEGATIVE=`${ORIGIN}#/negativeAnalyse`;
const ROOT='/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
const CHANNELS={
  'taobao-flash-sale':{context:'淘宝',platform:'2',label:'淘宝闪购',records:'taobao-flash-sale-negative-review-appeals'},
  'meituan-waimai':{context:'美团',platform:'1',label:'美团外卖',records:'meituan-waimai-negative-review-appeals'},
};
const CHANNEL=process.env.APPEAL_CHANNEL||'taobao-flash-sale';
if(!CHANNELS[CHANNEL])throw Error('appeal-channel-not-registered');
const CONFIG=CHANNELS[CHANNEL];
const RECORDS=path.join(ROOT,'records',CONFIG.records);
const FALLBACK='骑手送餐慢';
const EMPTY_LIST_RETRIES=3;
export const APPEAL_BUTTON_SELECTOR='button,a,[role="button"],div,span';
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const shanghaiDate=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const yesterday=()=>{const d=new Date(`${shanghaiDate()}T00:00:00+08:00`);d.setUTCDate(d.getUTCDate()-1);return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);};
const now=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}).format(new Date()).replace(' ','T')+'+08:00';
const clean=value=>String(value??'').replace(/\s+/g,' ').trim();
const excerpt=value=>clean(value).slice(0,80);
const escapeMd=value=>String(value??'').replaceAll('\n',' ').replaceAll('\r',' ').trim();

export const stableRecordKey=({store,date,comment})=>crypto.createHash('sha256').update([clean(store),clean(date),clean(comment)].join('|')).digest('hex').slice(0,12);
export const parseRecordStatus=text=>(String(text).match(/^- 记录状态：([^\n\r]+)/m)||[])[1]?.trim()||'';
export const eligible=card=>card.auto==='自动申诉已关闭'&&card.hasAppeal===true;
export const shouldRetryEmptyList=(cardCount,attempt)=>cardCount===0&&attempt<EMPTY_LIST_RETRIES;
export const sameCandidateSignature=(previous,signature)=>previous!==null&&signature===previous;
export function buildMarkdown(record){
  return `# ${escapeMd(record.channelLabel||CONFIG.label)}差评申诉临时记录\n\n- 业务日期：${escapeMd(record.businessDate)}\n- 记录键：${escapeMd(record.key)}\n- 门店：${escapeMd(record.store)}\n- 评价日期：${escapeMd(record.date)}\n- 星级：${escapeMd(record.score)} 星\n- 评价最小摘录：${escapeMd(record.commentExcerpt)}\n- 当前页面状态：${escapeMd(record.pageState)}\n- 自动申诉状态：${escapeMd(record.auto)}\n- 平台建议回复：${escapeMd(record.suggestion||'未打开申诉弹窗；不读取、不生成。')}\n- 最终申诉理由：${escapeMd(record.reason||'不适用。')}\n- 申诉类型：${escapeMd(record.appealType||'不适用。')}\n- 剩余次数：${escapeMd(record.remaining||'未读取。')}\n- 页面核验结果：${escapeMd(record.verification)}\n- 记录状态：${escapeMd(record.status)}\n- 创建时间：${escapeMd(record.createdAt)}\n- 提交时间：${escapeMd(record.submittedAt||'不适用')}\n- 核验时间：${escapeMd(record.verifiedAt||'不适用')}\n- 异常原因：${escapeMd(record.error||'无')}\n\n> 记录键由页面可见的门店、评价日期与评价文本生成稳定摘要；本文件不保存账号、Cookie、手机号、订单号或完整评价正文。\n`;
}

class Cdp {
  constructor(ws){this.ws=ws;this.next=0;this.pending=new Map();}
  static async open(){
    const targets=await (await fetch(`${ENDPOINT}/json/list`)).json();
    const pages=targets.filter(x=>x.type==='page'&&x.url.startsWith(ORIGIN));
    if(pages.length!==1)throw Error(`jinsha-page-count:${pages.length}`);
    const ws=new WebSocket(pages[0].webSocketDebuggerUrl);
    await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
    const cdp=new Cdp(ws);
    ws.addEventListener('message',event=>{const message=JSON.parse(event.data);const done=cdp.pending.get(message.id);if(done){cdp.pending.delete(message.id);message.error?done.reject(Error(message.error.message)):done.resolve(message.result);}});
    return cdp;
  }
  call(method,params={}){return new Promise((resolve,reject)=>{const id=++this.next;this.pending.set(id,{resolve,reject});this.ws.send(JSON.stringify({id,method,params}));});}
  async eval(expression){const out=await this.call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(out.exceptionDetails)throw Error(out.exceptionDetails.exception?.description||out.exceptionDetails.text||'cdp-evaluate-failed');return out.result.value;}
  close(){this.ws.close();}
}

async function navigate(cdp,url,waitMs=3500){await cdp.call('Page.enable');await cdp.call('Page.navigate',{url});await sleep(waitMs);}
async function atomicWrite(file,text){await fs.mkdir(path.dirname(file),{recursive:true});const temp=`${file}.${process.pid}.tmp`;await fs.writeFile(temp,text,{mode:0o600});await fs.rename(temp,file);if(await fs.readFile(file,'utf8')!==text)throw Error('record-readback-mismatch');}
async function existingStatus(file){try{return parseRecordStatus(await fs.readFile(file,'utf8'));}catch(error){if(error.code==='ENOENT')return '';throw error;}}

const CARD_SCRIPT=`(()=>[...document.querySelectorAll('.cryptonym')].filter(card=>card.offsetParent!==null).map(card=>{const lines=card.innerText.split('\\n').map(x=>x.trim()).filter(Boolean);const date=(card.innerText.match(/2026-\\d{2}-\\d{2}/)||[])[0]||'';const dateIndex=lines.indexOf(date);const orderIndex=lines.findIndex((x,i)=>i>dateIndex&&x.startsWith('订单详情：'));const comment=dateIndex>=0&&orderIndex>dateIndex?lines.slice(dateIndex+1,orderIndex).join(' '):'';const appealButtons=[...card.querySelectorAll('.btn')].filter(x=>x.offsetParent!==null&&x.innerText.trim()==='立即申诉');return {store:card.querySelector('.shopName')?.innerText.trim()||'',score:(([...card.querySelectorAll('.pointLi')].map(x=>x.innerText.trim()).find(x=>/^总分\\d/.test(x))||'').match(/\\d/)||[])[0]||'',date,comment,auto:(card.innerText.match(/自动申诉已(?:开启|关闭)/)||[])[0]||'',remaining:(card.innerText.match(/本周剩余申诉次数[:：]?[^\\n]*/)||[])[0]||'',hasAppeal:appealButtons.length===1};}))()`;

async function readState(cdp,date){
  const state=await cdp.eval(`(()=>({url:location.href,title:document.title,risk:/验证码|滑块|账号风险|请重新登录|登录失效/.test(document.body.innerText),platform:[...document.querySelectorAll('input[type=radio]')].filter(x=>x.checked).map(x=>x.value),dates:[...document.querySelectorAll('input.el-range-input')].map(x=>x.value),active:[...document.querySelectorAll('.navLi.active')].map(x=>x.innerText.trim()),total:document.querySelector('.el-pagination__total')?.innerText||'',cards:${CARD_SCRIPT}}))()`);
  const total=Number((state.total.match(/共\s*(\d+)\s*条/)||[])[1]);
  if(state.url!==NEGATIVE||state.title!=='臻肆外卖运营'||state.risk)throw Error('jinsha-route-login-or-risk-gate');
  if(state.platform.join(',')!==CONFIG.platform||state.dates.length!==2||state.dates.some(x=>x!==date)||state.active.length!==1||!state.active[0].startsWith('未申诉'))throw Error('filter-readback-mismatch');
  if(!Number.isInteger(total)||state.cards.length>total||(total>0&&state.cards.length===0)||state.cards.some(x=>x.date!==date))throw Error(`page-card-readback-mismatch:${total}:${state.cards.length}`);
  state.totalNumber=total;state.cards=state.cards.map(card=>({...card,key:stableRecordKey(card)}));return state;
}

async function stableState(cdp,date){
  let previous=null,last=null;
  for(let attempt=0;attempt<16;attempt++){
    last=await readState(cdp,date);
    const signature=last.cards.map(card=>card.key).sort().join('|');
    if(sameCandidateSignature(previous,signature))return last;
    previous=signature;
    await sleep(750);
  }
  throw Error('candidate-list-not-stable');
}

async function preparePage(cdp,date){
  await navigate(cdp,HOME);
  const entry=await cdp.eval(`(()=>({url:location.href,title:document.title,risk:/验证码|滑块|账号风险|请重新登录|登录失效/.test(document.body.innerText)}))()`);
  if(entry.url!==HOME||entry.title!=='臻肆外卖运营'||entry.risk)throw Error('jinsha-entry-or-login-gate');
  let contextSelected=false;
  for(let attempt=0;attempt<20;attempt++){
    const count=await cdp.eval(`(()=>[...document.querySelectorAll('.cutli')].filter(x=>x.offsetParent!==null&&x.innerText.trim()===${JSON.stringify(CONFIG.context)}).length)()`);
    if(count===1){await cdp.eval(`(()=>{const target=[...document.querySelectorAll('.cutli')].find(x=>x.offsetParent!==null&&x.innerText.trim()===${JSON.stringify(CONFIG.context)});target.click();return true})()`);contextSelected=true;break;}
    if(count>1)throw Error(`channel-context-count:${count}`);
    if(attempt===0)await cdp.eval(`(()=>{const menu=[...document.querySelectorAll('.hamburger-container')].filter(x=>x.offsetParent!==null);if(menu.length===1)menu[0].click();return menu.length})()`);
    await sleep(250);
  }
  if(!contextSelected)throw Error('channel-context-not-rendered');
  for(let attempt=0;attempt<20;attempt++){await sleep(250);const selected=await cdp.eval(`(()=>[...document.querySelectorAll('.cutli')].filter(x=>x.offsetParent!==null&&x.classList.contains('pitchOn')).map(x=>x.innerText.trim()))()`);if(selected.join(',')===CONFIG.context)break;if(attempt===19)throw Error('channel-context-readback-mismatch');}
  await navigate(cdp,NEGATIVE);
  await cdp.eval(`(()=>{const radio=document.querySelector('input[type=radio][value=${JSON.stringify(CONFIG.platform)}]');if(!radio)throw Error('platform-radio-missing');radio.click();const inputs=[...document.querySelectorAll('input.el-range-input')];if(inputs.length!==2)throw Error('date-input-count');const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;for(const input of inputs){setter.call(input,${JSON.stringify(date)});input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}document.body.click();return true})()`);
  await sleep(1300);
  await cdp.eval(`(()=>{const tabs=[...document.querySelectorAll('.navLi')].filter(x=>x.innerText.trim().startsWith('未申诉'));if(tabs.length!==1)throw Error('unappealed-tab-count:'+tabs.length);tabs[0].click();return true})()`);
  await sleep(3200);
  return stableState(cdp,date);
}

async function clickCandidate(cdp,target){
  return cdp.eval(`(()=>{const target=${JSON.stringify({store:target.store,date:target.date,comment:target.comment})};const nodes=[...document.querySelectorAll('.cryptonym')].filter(card=>card.offsetParent!==null);const matches=nodes.filter(card=>{const text=card.innerText||'';const buttons=[...card.querySelectorAll('.btn')].filter(x=>x.offsetParent!==null&&x.innerText.trim()==='立即申诉');return text.includes(target.store)&&text.includes(target.date)&&text.includes(target.comment)&&buttons.length===1});if(matches.length!==1)throw Error('candidate-node-count:'+matches.length);const card=matches[0];if(!card.innerText.includes('自动申诉已关闭'))throw Error('candidate-auto-state-drift');const buttons=[...card.querySelectorAll('.btn')].filter(x=>x.offsetParent!==null&&x.innerText.trim()==='立即申诉');buttons[0].click();return true})()`);
}

async function stableModal(cdp){
  let previous='',stable=0,last=null;
  for(let attempt=0;attempt<30;attempt++){
    last=await cdp.eval(`(()=>{const modal=document.querySelector('.representations');if(!modal||getComputedStyle(modal).display==='none')return null;return {text:document.querySelector('.representations textarea')?.value||'',type:document.querySelector('.representations .type_txt .txt')?.innerText.trim()||'',remaining:[...document.querySelectorAll('.representations-content-footer div')].map(x=>x.innerText.trim()).find(x=>x.includes('剩余申诉次数'))||'',confirmCount:[...document.querySelectorAll('.representations .sure_btn')].filter(x=>x.innerText.trim()==='确认申诉').length}})()`);
    if(last){const text=clean(last.text);stable=text&&text===previous?stable+1:0;previous=text;if(stable>=1&&last.type&&last.confirmCount===1)return {...last,text};}
    await sleep(1000);
  }
  if(!last)throw Error('appeal-modal-missing');
  if(clean(last.text))throw Error('appeal-suggestion-not-stable');
  await cdp.eval(`(()=>{const input=document.querySelector('.representations textarea');if(!input)throw Error('appeal-textarea-missing');const setter=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,'value').set;setter.call(input,${JSON.stringify(FALLBACK)});input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));return input.value})()`);
  await sleep(300);const final=await cdp.eval(`(()=>({text:document.querySelector('.representations textarea')?.value||'',type:document.querySelector('.representations .type_txt .txt')?.innerText.trim()||'',remaining:[...document.querySelectorAll('.representations-content-footer div')].map(x=>x.innerText.trim()).find(x=>x.includes('剩余申诉次数'))||'',confirmCount:[...document.querySelectorAll('.representations .sure_btn')].filter(x=>x.innerText.trim()==='确认申诉').length}))()`);
  if(clean(final.text)!==FALLBACK||!final.type||final.confirmCount!==1)throw Error('appeal-fallback-readback-mismatch');return {...final,text:clean(final.text)};
}

async function confirmOnce(cdp){const clicked=await cdp.eval(`(()=>{const buttons=[...document.querySelectorAll('.representations .sure_btn')].filter(x=>x.innerText.trim()==='确认申诉');if(buttons.length!==1)throw Error('confirm-button-count:'+buttons.length);buttons[0].click();return 1})()`);if(clicked!==1)throw Error('confirm-click-count');}

async function execute(){
  const businessDate=yesterday(),startedAt=now(),receipt={ok:false,businessDate,startedAt,endpoint:ENDPOINT,runtimeModelDecisions:0,verified_submitted:[],skipped:[],blocked:[],unknown:[],warnings:[]};
  const cdp=await Cdp.open();
  try {
    let state;
    for(let attempt=1;attempt<=EMPTY_LIST_RETRIES;attempt++){
      state=await preparePage(cdp,businessDate);
      if(!shouldRetryEmptyList(state.cards.length,attempt))break;
      receipt.warnings.push(`empty-list-readback-retry:${attempt}`);
    }
    receipt.discovered=state.cards.length;receipt.closedCandidates=state.cards.filter(eligible).length;receipt.autoEnabled=state.cards.filter(x=>x.auto==='自动申诉已开启').length;
    for(const initial of state.cards.filter(x=>x.auto==='自动申诉已开启')){
      const file=path.join(RECORDS,businessDate,`${initial.key}.md`),status=await existingStatus(file);if(status==='skipped'){receipt.skipped.push(initial.key);continue;}
      const createdAt=now();await atomicWrite(file,buildMarkdown({businessDate,key:initial.key,store:initial.store,date:initial.date,score:initial.score,commentExcerpt:excerpt(initial.comment),pageState:`${CONFIG.label} / 昨日 / 未申诉；页面共 ${state.totalNumber} 条。`,auto:'已开启',verification:'条目明确显示“自动申诉已开启”，按规则跳过；未点击“立即申诉”。',status:'skipped',createdAt,verifiedAt:createdAt}));receipt.skipped.push(initial.key);
    }
    for(const initial of state.cards.filter(eligible)){
      state=await readState(cdp,businessDate);const target=state.cards.find(x=>x.key===initial.key);if(!target){receipt.warnings.push(`candidate-no-longer-unappealed:${initial.key}`);continue;}if(!eligible(target))throw Error(`candidate-state-drift:${initial.key}`);
      const file=path.join(RECORDS,businessDate,`${target.key}.md`),prior=await existingStatus(file);if(['verified_submitted','unknown','blocked'].includes(prior)){receipt[prior].push(target.key);continue;}if(prior==='submitted_once'){const createdAt=now();await atomicWrite(file,buildMarkdown({businessDate,key:target.key,store:target.store,date:target.date,score:target.score,commentExcerpt:excerpt(target.comment),pageState:`${CONFIG.label} / 昨日 / 未申诉；页面共 ${state.totalNumber} 条。`,auto:'已关闭',verification:'检测到上次记录已进入 submitted_once，无法排除确认动作已发生。',status:'unknown',createdAt,error:'防重门禁：禁止再次确认申诉。'}));receipt.unknown.push(target.key);break;}
      const createdAt=now(),base={businessDate,key:target.key,store:target.store,date:target.date,score:target.score,commentExcerpt:excerpt(target.comment),pageState:`${CONFIG.label} / 昨日 / 未申诉；页面共 ${state.totalNumber} 条。`,auto:'已关闭',createdAt};
      await atomicWrite(file,buildMarkdown({...base,verification:'已创建临时记录，尚未打开申诉弹窗。',status:'prepared'}));
      await clickCandidate(cdp,target);const modal=await stableModal(cdp);const suggestion=clean(modal.text),appealType=clean(modal.type),remaining=clean(modal.remaining);
      await atomicWrite(file,buildMarkdown({...base,suggestion,reason:suggestion,appealType,remaining,verification:'弹窗申诉内容已连续两次稳定读取；条目、自动申诉状态、类型与剩余次数已复核。',status:'ready_for_confirmation'}));
      const beforeTotal=state.totalNumber,submittedAt=now();await atomicWrite(file,buildMarkdown({...base,suggestion,reason:suggestion,appealType,remaining,verification:'确认前门禁已通过；即将执行唯一一次确认申诉。',status:'submitted_once',submittedAt}));
      await confirmOnce(cdp);
      let after=null;for(let attempt=0;attempt<20;attempt++){await sleep(750);try{after=await readState(cdp,businessDate);if(!after.cards.some(x=>x.key===target.key)&&after.totalNumber<beforeTotal)break;}catch{} }
      const verified=after&&!after.cards.some(x=>x.key===target.key)&&after.totalNumber<beforeTotal,verifiedAt=now();
      if(!verified){await atomicWrite(file,buildMarkdown({...base,suggestion,reason:suggestion,appealType,remaining,verification:'确认后未能以同条目移除且未申诉总数减少完成权威回读。',status:'unknown',submittedAt,verifiedAt,error:'提交结果未知；按防重规则停止批次，不重试。'}));receipt.unknown.push(target.key);break;}
      await atomicWrite(file,buildMarkdown({...base,suggestion,reason:suggestion,appealType,remaining,pageState:`${CONFIG.label} / 昨日 / 未申诉；确认前 ${beforeTotal} 条，确认后 ${after.totalNumber} 条。`,verification:'同条目已从未申诉列表移除，且未申诉总数同步减少。',status:'verified_submitted',submittedAt,verifiedAt}));receipt.verified_submitted.push(target.key);
    }
    receipt.ok=receipt.unknown.length===0&&receipt.blocked.length===0;receipt.finishedAt=now();return receipt;
  } catch(error){receipt.error=String(error.message||error);receipt.finishedAt=now();return receipt;} finally {try{await navigate(cdp,HOME,1200);}catch(error){receipt.warnings.push(`home-restore-failed:${String(error.message||error)}`);}cdp.close();}
}

async function inspect(){const businessDate=yesterday(),cdp=await Cdp.open();try{const state=await preparePage(cdp,businessDate);return {ok:true,businessDate,total:state.totalNumber,closedCandidates:state.cards.filter(eligible).map(x=>({key:x.key,store:x.store})),autoEnabled:state.cards.filter(x=>x.auto==='自动申诉已开启').map(x=>({key:x.key,store:x.store})),runtimeModelDecisions:0};}finally{try{await navigate(cdp,HOME,1200);}catch{}cdp.close();}}
function selfTest(){
  const card={store:'门店A',date:'2026-09-21',score:'1',comment:'差评内容',auto:'自动申诉已关闭',hasAppeal:true};
  if(!CONFIG.context||stableRecordKey(card)!==stableRecordKey({...card,score:'2'}))throw Error('stable-key-contract');
  if(!eligible(card)||eligible({...card,auto:'自动申诉已开启'}))throw Error('eligibility-contract');
  if(!shouldRetryEmptyList(0,1)||shouldRetryEmptyList(1,1)||shouldRetryEmptyList(0,EMPTY_LIST_RETRIES))throw Error('empty-list-retry-contract');
  if(!sameCandidateSignature('', '')||sameCandidateSignature(null, ''))throw Error('empty-list-stability-contract');
  const md=buildMarkdown({businessDate:card.date,key:stableRecordKey(card),store:card.store,date:card.date,score:card.score,commentExcerpt:card.comment,pageState:'淘宝闪购 / 昨日 / 未申诉',auto:'已关闭',verification:'ok',status:'prepared',createdAt:'2026-09-22T00:00:00+08:00'});
  if(parseRecordStatus(md)!=='prepared'||!md.includes('记录键：')||!md.includes('异常原因：无'))throw Error('markdown-contract');
  return {ok:true,tests:6,endpoint:ENDPOINT,runtimeModelDecisions:0};
}

async function main(){const mode=process.argv[2];if(mode==='--self-test')console.log(JSON.stringify(selfTest()));else if(mode==='--inspect')console.log(JSON.stringify(await inspect()));else if(mode==='--execute'){const out=await execute();console.log(JSON.stringify(out));if(!out.ok)process.exitCode=1;}else throw Error('usage: appeal_executor.mjs --self-test|--inspect|--execute');}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url))main().catch(error=>{console.log(JSON.stringify({ok:false,error:String(error.message||error),runtimeModelDecisions:0}));process.exitCode=1;});
