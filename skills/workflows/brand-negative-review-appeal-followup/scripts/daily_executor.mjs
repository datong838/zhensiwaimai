#!/usr/bin/env node
/* Fixed, side-effect-limited collector for the brand appeal workflow.
 * It never sends WeChat messages: delivery remains executor.py's responsibility. */
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const ROOT=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const INPUT=path.join(ROOT,'inputs','品牌表.csv');
const OUTPUT=path.join(ROOT,'outputs');
const ORIGIN='https://data.guoshuyufen.com/';
const HOME='https://data.guoshuyufen.com/#/businessData/realTimeData';
const NEGATIVE='https://data.guoshuyufen.com/#/negativeAnalyse';
const PLATFORMS=[['美团外卖','1','美团'],['淘宝闪购','2','淘宝闪购']];
const FIELDS=['记录键','品牌','平台','门店','评价时间','评价等级','申诉结果','评价内容','通知正文','群检索结果','发送状态','备注'];
// 允许外发的申诉结果集合。必须与 prepare_delivery.py::AUTHORIZED 逐字一致 ——
// 少一个值，新状态就会被判「无法识别」而不外发（静默丢单）。
// 2026-10-06 大同指令新增「未申诉（已开启自动申诉）」。
const SENDABLE_STATUSES=['未申诉','未申诉（已开启自动申诉）','申诉中','申诉成功','差评免责'];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const shanghai=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const yesterday=()=>{const d=new Date(`${shanghai()}T00:00:00+08:00`);d.setUTCDate(d.getUTCDate()-1);return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(d);};
const hash=s=>crypto.createHash('sha256').update(s).digest('hex');
const csv=v=>`"${String(v??'').replaceAll('"','""')}"`;
const csvText=rows=>[FIELDS.join(','),...rows.map(row=>FIELDS.map(key=>csv(row[key])).join(','))].join('\n')+'\n';

class Cdp {
  constructor(ws){this.ws=ws;this.next=0;this.pending=new Map();}
  static async open(){
    const targets=await (await fetch('http://127.0.0.1:9232/json/list')).json();
    const pages=targets.filter(x=>x.type==='page'&&x.url.startsWith(ORIGIN));
    if(pages.length!==1)throw Error(`jinsha-page-count:${pages.length}`);
    const ws=new WebSocket(pages[0].webSocketDebuggerUrl);
    await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true});});
    const cdp=new Cdp(ws);
    ws.addEventListener('message',event=>{const message=JSON.parse(event.data);const done=cdp.pending.get(message.id);if(done){cdp.pending.delete(message.id);done(message);}});
    return cdp;
  }
  call(method,params={}){return new Promise((resolve,reject)=>{const id=++this.next;this.pending.set(id,message=>message.error?reject(Error(message.error.message)):resolve(message.result));this.ws.send(JSON.stringify({id,method,params}));});}
  async eval(expression){const value=await this.call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(value.exceptionDetails)throw Error(value.exceptionDetails.text||'cdp-evaluate-failed');return value.result.value;}
  close(){this.ws.close();}
}

function notification(date,row,platformLabel){
  const title=row['评价等级']==='3星'?'中评':'差评';
  return `--- ${date} ${title}申诉进度通知 ---\n${row['门店']}\n【${platformLabel}】\n评价时间: ${date}\n评价等级: ${row['评价等级']}\n申诉结果：---${row['申诉结果']}---\n评价内容: ${row['评价内容']}`;
}
function inScopeScore(card){
  const match=String(card.score||'').match(/总分\s*([1-5])/);
  if(!match)throw Error('review-score-unreadable');
  return Number(match[1])<=3?match[1]:null;
}
function classify(text,counts){
  if(/已拦截评分|免责处理|不计入评分/.test(text))return {status:'差评免责',remark:'页面明确显示平台已拦截评分/免责，不计入评分'};
  // 2026-10-06 大同指令：页面显示「未申诉」且「自动申诉已开启」时，标记必须写成
  // 「未申诉（已开启自动申诉）」。理由：平台自动申诉到点会自己发起，页面此时本就
  // 仍是「未申诉」；若只报「未申诉」，群里看到满屏未申诉会误判成"没人跟进"而焦虑。
  // 卡片原文取证（2026-10-05 李老哈·奉贤宝龙店 实测）：
  //   「…商家自行申诉 / 本差评将于: / 周日 / 12:00 自动申诉 / 自动申诉已开启 /
  //     本周剩余申诉次数:无限次 / 立即申诉」
  const autoAppealOn=/自动申诉已开启/.test(text);
  for(const [label,status] of [['未申诉','未申诉'],['申诉中','申诉中'],['申诉成功','申诉成功']])if(counts[label]>0){
    if(status==='未申诉'&&autoAppealOn)return {status:'未申诉（已开启自动申诉）',remark:'平台已开启自动申诉，将于页面所示时间自动发起，无需人工点击'};
    return {status,remark:''};
  }
  return {status:'未识别',remark:'页面未提供可逐条对应的申诉状态，禁止发送'};
}
async function stableRead(cdp,expression,accept,reason){
  let previous='',stable=0;
  for(let attempt=0;attempt<10;attempt++){
    const value=await cdp.eval(expression);const fingerprint=JSON.stringify(value);
    if(accept(value)&&fingerprint===previous){stable++;if(stable>=1)return value;}else stable=0;
    previous=fingerprint;await sleep(500);
  }
  throw Error(reason);
}
async function ready(cdp,date){
  await cdp.call('Page.enable');await cdp.call('Page.navigate',{url:HOME});
  await stableRead(cdp,`(()=>({url:location.href,title:document.title,login:/验证码|滑块|账号风险|请重新登录/.test(document.body.innerText)}))()`,entry=>entry.url===HOME&&/^(臻肆外卖运营|金鲨数据)$/.test(entry.title)&&!entry.login,'jinsha-entry-or-login-gate');
  await cdp.call('Page.navigate',{url:NEGATIVE});
  await stableRead(cdp,`(()=>({url:location.href,title:document.title,login:/验证码|滑块|账号风险|请重新登录/.test(document.body.innerText),dates:[...document.querySelectorAll('input.el-range-input')].map(x=>x.value)}))()`,state=>state.url===NEGATIVE&&/^(臻肆外卖运营|金鲨数据)$/.test(state.title)&&!state.login&&state.dates.length===2,'jinsha-negative-route-or-login-gate');
  const write=await cdp.eval(`(()=>{const inputs=[...document.querySelectorAll('input.el-range-input')];if(inputs.length!==2)throw Error('date-input-count');for(const input of inputs){const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,'${date}');input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}document.body.click();return inputs.map(x=>x.value)})()`);
  if(write.some(x=>x!==date))throw Error('date-readback-mismatch');
}
async function select(cdp,brand,value,date){
  const searched=await cdp.eval(`(()=>{const input=document.querySelector('input[placeholder="请输入店铺名称或城市"]');if(!input)throw Error('brand-input-missing');const setter=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set;setter.call(input,${JSON.stringify(brand)});input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));const button=input.closest('.selectT')?.querySelector('.points');if(!button)throw Error('brand-search-missing');button.click();return true})()`);
  if(!searched)throw Error('brand-search-write-failed');await sleep(900);
  const selected=await cdp.eval(`(()=>{const radio=document.querySelector('input[type=radio][value="${value}"]');if(!radio)throw Error('platform-control-missing');radio.click();return radio.checked})()`);
  if(!selected)throw Error('platform-write-failed');await sleep(2300);
  const read=()=>cdp.eval(`(()=>({brand:document.querySelector('input[placeholder="请输入店铺名称或城市"]')?.value,selected:[...document.querySelectorAll('input[type=radio]')].filter(x=>x.checked).map(x=>x.value),dates:[...document.querySelectorAll('input.el-range-input')].map(x=>x.value),total:document.querySelector('.el-pagination__total')?.innerText||'',counts:Object.fromEntries([...document.querySelectorAll('.navLi')].map(x=>{const m=x.innerText.match(/(未申诉|申诉中|申诉成功)\\((\\d+)\\)/);return m?[m[1],Number(m[2])]:null}).filter(Boolean)),cards:[...document.querySelectorAll('.cryptonym')].map(card=>({store:card.querySelector('.shopName')?.innerText.trim()||'',text:card.innerText,score:([...card.querySelectorAll('.pointLi')].map(x=>x.innerText.trim()).find(x=>/^总分\\d/.test(x))||'')}))}))()`);
  let data,last='',stable=0;
  for(let attempt=0;attempt<7;attempt++){
    data=await read();
    const total=Number((data.total.match(/共\s*(\d+)\s*条/)||[])[1]);
    const fingerprint=JSON.stringify([data.brand,data.selected,data.dates,data.total,data.counts,data.cards]);
    if(total===data.cards.length&&fingerprint===last){stable++;if(stable>=2)break;}else stable=0;
    last=fingerprint;await sleep(500);
  }
  if(stable<2)throw Error('filter-results-not-stable');
  if(data.brand!==brand||data.selected.join(',')!==value||data.dates.some(x=>x!==date)||data.cards.some(x=>!x.text.includes(date)))throw Error('filter-readback-mismatch');
  const total=Number((data.total.match(/共\s*(\d+)\s*条/)||[])[1]);if(total!==data.cards.length)throw Error(`page-total-card-mismatch:${total}:${data.cards.length}`);
  return data;
}
async function collect(){
  const started=Date.now(),date=yesterday(),review=[];const stage=async(name,fn)=>{const t=Date.now();try{const v=await fn();review.push({stage:name,status:'completed',elapsedMs:Date.now()-t,pitfalls:[]});return v;}catch(error){review.push({stage:name,status:'failed',elapsedMs:Date.now()-t,pitfalls:[String(error.message||error)]});throw error;}};
  // 2026-09-30 大同授权「⑨ 改每日3班」：该业务日期只要已冻结过投递请求
  // （.runtime/delivery-<date>-*/request.json 存在），后续班次禁止重采——
  // 线上申诉状态演变会改写通知正文，与已冻结载荷冲突（ledger-payload-digest-
  // conflict）。后续班次的职责是复用既有请求重试/对账，归 delivery_executor.py。
  const runtime=path.join(ROOT,'.runtime');
  // 只认真正的「冻结请求」产物：目录 delivery-<date>-*/ 且其中存在 request.json。
  // 严禁把交付器每次运行都会写的 delivery-<date>-workflow-summary.json（普通文件）
  // 算进来——那会让采集器把**自己的产物**误判成「已冻结请求」而永久跳过采集，
  // 交付侧因此永远读到 0 行、天天 blocked（自污染死锁）。2026-10-06 实测根因：
  // .runtime 下 10-05 只存在 delivery-2026-10-05-workflow-summary.json，并无
  // request.json，旧判据（仅前缀匹配）却认定已冻结 ⇒ 采集被永久跳过。
  const frozen=[];
  for(const entry of await fs.readdir(runtime,{withFileTypes:true}).catch(()=>[])){
    if(!entry.isDirectory()||!entry.name.startsWith(`delivery-${date}-`))continue;
    try{await fs.stat(path.join(runtime,entry.name,'request.json'));frozen.push(entry.name);}catch{}
  }
  if(frozen.length>0)return {ok:true,businessDate:date,skipped:true,reason:'prior-frozen-request-reuse-mode',frozenEvents:frozen.length,sendAttempts:0,runtimeModelDecisions:0};
  const brands=await stage('读取品牌表',async()=>[...new Set((await fs.readFile(INPUT,'utf8')).split(/\r?\n/).map(x=>x.trim()).filter(Boolean))]);
  const cdp=await stage('连接金鲨专用端口',()=>Cdp.open());const rows=[];
  try {await stage('核验金鲨页面与昨日日期',()=>ready(cdp,date));const seenKeys=new Set();for(const brand of brands)for(const [platform,value,label] of PLATFORMS){const result=await stage(`采集:${brand}:${platform}`,()=>select(cdp,brand,value,date));for(const card of result.cards){const score=inScopeScore(card);if(score===null)continue;const comment=(card.text.split(date)[1]||'').split(/订单详情|预申述语句|AI申诉|商家申诉/)[0].trim();const state=classify(card.text,result.counts);const sendable=SENDABLE_STATUSES.includes(state.status);const row={'品牌':brand,'平台':platform,'门店':card.store,'评价时间':date,'评价等级':`${score}星`,'申诉结果':state.status,'评价内容':comment,'群检索结果':sendable?'待统一微信执行器核验':'未执行：状态无法识别','发送状态':'未发送','备注':state.remark};row['记录键']=hash([brand,platform,row['门店'],date,row['评价等级'],comment].join('|'));row['通知正文']=sendable?notification(date,row,label):'';if(seenKeys.has(row['记录键'])){review.push({stage:`采集:${brand}:${platform}`,status:'skipped',elapsedMs:0,pitfalls:[`duplicate-card-dedup:${row['门店']}`]});continue;}seenKeys.add(row['记录键']);rows.push(row);}}} finally {cdp.close();}
  // 2026-10-19 事故根修（17:55 daemon 重试）：昨日数据在金鲨页面滚走后重采得 0 行，
  // 无条件覆写把 4 行非空 CSV 清成表头壳。0 行属「窗口滚走/页面无差评」两种不可分
  // 情形，一律视为采集不可信：非空 CSV 保留原文件，本轮以 blocked 收口等待人工定性
  // ——绝不把「采不到」静默写成「昨天没有差评」。
  const file=path.join(OUTPUT,`${date}差评申诉跟进.csv`);
  const stageWrite=async()=>{
    await fs.mkdir(OUTPUT,{recursive:true});
    const text=csvText(rows);
    if(rows.length===0){
      let existing='';
      try{existing=await fs.readFile(file,'utf8');}catch{}
      const existingRows=existing.split(/\r?\n/).filter(x=>x.trim()).length-1;
      if(existingRows>0)throw Error(`empty-collection-would-clobber-existing-csv:${existingRows}`);
    }
    await fs.writeFile(file,text,{mode:0o600});
    if((await fs.readFile(file,'utf8'))!==text)throw Error('csv-readback-mismatch');
    return true;
  };
  await stage('写入并回读CSV',stageWrite);
  return {ok:true,businessDate:date,file,records:rows.length,sendable:rows.filter(x=>x['通知正文']).length,elapsedMs:Date.now()-started,review};
}
async function main(){if(process.argv[2]==='--self-test'){const r={记录键:'k',评价等级:'3星',门店:'门店',申诉结果:'申诉中',评价内容:'内容'};if(!notification('2026-09-20',r,'美团').includes('中评申诉进度通知')||classify('已拦截评分',{未申诉:0,申诉中:0,申诉成功:0}).status!=='差评免责'||inScopeScore({score:'总分1'})!=='1'||inScopeScore({score:'总分3'})!=='3'||inScopeScore({score:'总分4'})!==null||inScopeScore({score:'总分5'})!==null)throw Error('self-test-failed');let unknownScoreRejected=false;try{inScopeScore({score:''});}catch(error){unknownScoreRejected=error.message==='review-score-unreadable';}if(!unknownScoreRejected)throw Error('self-test-failed');
  // 状态矩阵正负对照（2026-10-06）：新标记只在「未申诉 且 自动申诉已开启」时出现，
  // 其余状态一律不得被它影响（防止过度改写把申诉中/成功也标歪）。
  const st=(text,counts)=>classify(text,counts).status;
  const AUTO='商家自行申诉\n本差评将于:\n周日\n12:00 自动申诉\n自动申诉已开启\n本周剩余申诉次数:无限次\n立即申诉';
  const MANUAL=AUTO.replace('自动申诉已开启','自动申诉已关闭');
  const MATRIX=[
    ['未申诉+自动申诉已开启',st(AUTO,{未申诉:1,申诉中:0,申诉成功:0}),'未申诉（已开启自动申诉）'],
    ['未申诉+自动申诉已关闭',st(MANUAL,{未申诉:1,申诉中:0,申诉成功:0}),'未申诉'],
    ['未申诉+无自动申诉字样',st('普通卡片内容',{未申诉:1,申诉中:0,申诉成功:0}),'未申诉'],
    ['申诉中+自动申诉已开启',st(AUTO,{未申诉:0,申诉中:1,申诉成功:0}),'申诉中'],
    ['申诉成功+自动申诉已开启',st(AUTO,{未申诉:0,申诉中:0,申诉成功:1}),'申诉成功'],
    ['免责优先于自动申诉标记',st('已拦截评分 '+AUTO,{未申诉:1,申诉中:0,申诉成功:0}),'差评免责'],
  ];
  for(const [name,got,want] of MATRIX)if(got!==want)throw Error(`self-test-failed:${name}:got=${got}:want=${want}`);
  if(!SENDABLE_STATUSES.includes('未申诉（已开启自动申诉）'))throw Error('self-test-failed:sendable-missing-new-status');
  console.log(JSON.stringify({ok:true,classifyMatrix:MATRIX.length,runtimeModelDecisions:0}));return;}console.log(JSON.stringify(await collect()));}
main().catch(error=>{console.log(JSON.stringify({ok:false,reason:String(error.message||error),sendAttempts:0,runtimeModelDecisions:0}));process.exitCode=1;});
