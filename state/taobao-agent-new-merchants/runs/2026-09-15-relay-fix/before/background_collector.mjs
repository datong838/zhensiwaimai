#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';
import {execFile as execFileCb} from 'node:child_process';
import {promisify} from 'node:util';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const {chromium}=require('/Users/ddt/work/projects/ai_agent/aos-platform/plugins/browser/headless-playwright/node_modules/playwright-core');
const execFile=promisify(execFileCb);
const PROFILE_ROOT='/Users/ddt/Library/Application Support/AOS Background Chrome';
const HOME='https://open.shop.ele.me/manager/base/home';
const PREFIX='https://open.shop.ele.me/';
const FIELDS=['商家名称','商家ID','商家地址','商家联系人','是否已告知价格','商家意愿度','意向举证','备注','推荐人'];
const LOGIN_MARKERS=['账号密码','扫码登录','验证码登录','立即登录','无法登录'];

export function stableIncremental(rows,cursor,date){
  const ordered=rows.map((row,index)=>({...row,__index:index})).sort((a,b)=>a.recommendTime.localeCompare(b.recommendTime)||a.__index-b.__index).map(({__index,...row},index)=>({...row,tableOrder:index+1}));
  if(cursor.recommendTime<`${date} 00:00:00`)return ordered;
  const matches=ordered.map((row,index)=>row.merchantId===cursor.merchantId&&row.recommendTime===cursor.recommendTime?index:-1).filter(index=>index>=0);
  if(matches.length!==1)throw Error('same-day-cursor-not-unique');
  return ordered.slice(matches[0]+1);
}

export function messageFor(row){
  const value=(input,missing)=>{const text=String(input||'').trim();return text&&!['-','--','暂无','无'].includes(text)?text:`（${missing}字段缺失）`;};
  return [value(row.city,'城市'),value(row.contact,'商家联系人'),value(row.merchantName,'商家名称'),value(row.address,'商家地址')].join('\n');
}

export function parseLogicalRows(headers, matrices){
  const rows=[];
  for(const [rowIndex,cells] of matrices.entries()){
    if(cells.length!==headers.length)continue;
    const data=Object.fromEntries(headers.map((header,index)=>[header,String(cells[index]||'').trim()]));
    if(!/^\d{7,}$/.test(data['商家ID']||''))continue;
    rows.push({merchantId:data['商家ID'],merchantName:data['商家名称']||'',recommendTime:data['推荐时间']||'',city:data['城市']||'',status:data['状态']||'',rowIndex});
  }
  if(matrices.length>0&&rows.length===0)throw Error(`merchant-row-parse-empty:${matrices.length}`);
  return rows;
}

function parseArgs(argv){const out={};for(let i=0;i<argv.length;i+=2){if(!argv[i]?.startsWith('--')||argv[i+1]===undefined)throw Error('invalid-arguments');out[argv[i].slice(2)]=argv[i+1];}return out;}
function safeId(value){return /^[a-z0-9][a-z0-9-]{0,62}$/.test(value||'');}
async function frontmost(){try{return (await execFile('/usr/bin/osascript',['-e','tell application "System Events" to get bundle identifier of first application process whose frontmost is true'])).stdout.trim();}catch{return 'unavailable';}}
async function allText(page){const values=[];for(const frame of page.frames()){try{const text=(await frame.locator('body').innerText()).trim();if(text)values.push(text);}catch{}}return [...new Set(values)].join('\n');}
async function visibleExact(page,text){const hits=[];for(const frame of page.frames()){const locator=frame.getByText(text,{exact:true});for(let i=0;i<await locator.count();i++){const item=locator.nth(i);if(await item.isVisible().catch(()=>false)&&await item.evaluate((node,value)=>![...node.children].some(child=>(child.innerText||'').trim()===value),text).catch(()=>false))hits.push(item);}}return hits;}
async function visibleRawExact(page,text){const hits=[];for(const frame of page.frames()){const locator=frame.getByText(text,{exact:true});for(let i=0;i<await locator.count();i++){const item=locator.nth(i);if(await item.isVisible().catch(()=>false))hits.push(item);}}return hits;}
async function clickUnique(page,text){const hits=await visibleExact(page,text);if(hits.length!==1)throw Error(`visible-text-count:${text}:${hits.length}`);await hits[0].click({timeout:5000});}
async function waitUniqueExact(page,text,timeout=5000){return waitFor(page,async()=>{const hits=await visibleExact(page,text);if(hits.length>1)throw Error(`visible-text-count:${text}:${hits.length}`);return hits[0]||null;},`visible-text-missing:${text}`,timeout);}
async function waitFor(page,predicate,reason,timeout=10000){const end=Date.now()+timeout;let last;while(Date.now()<end){try{last=await predicate();if(last)return last;}catch(error){last=error;}await page.waitForTimeout(200);}throw Error(reason+(last instanceof Error?':'+last.message:''));}
async function tableTarget(page){const found=[];for(const frame of page.frames()){const tables=frame.locator('table');for(let i=0;i<await tables.count();i++){const headerTable=tables.nth(i);if(!await headerTable.isVisible().catch(()=>false))continue;const headers=(await headerTable.locator('thead th').allInnerTexts()).map(value=>value.trim());if(headers.includes('商家ID')&&headers.includes('推荐时间'))found.push({frame,headerTable,headers,rows:frame.locator('tbody tr.ant-table-row')});}}if(found.length!==1)throw Error(`merchant-table-count:${found.length}`);return found[0];}
async function pageReady(page){if(!page.url().startsWith(PREFIX))return false;const text=await allText(page);if(LOGIN_MARKERS.some(marker=>text.includes(marker)))throw Error('service-login-required');try{const target=await tableTarget(page);return text.includes('意向商户管理')&&text.includes('商家意向列表')&&target;}catch{return false;}}
async function route(page){
  if(!page.url().startsWith(PREFIX))throw Error('service-origin-changed');
  await waitFor(page,async()=>{const body=await allText(page);if(LOGIN_MARKERS.some(marker=>body.includes(marker)))throw Error('service-login-required');return ['appstore 控制台','代运营','客户管理','意向商户管理','商家意向列表'].some(marker=>body.includes(marker));},'service-shell-not-ready');
  if(await pageReady(page))return true;
  const text=await allText(page);if(LOGIN_MARKERS.some(marker=>text.includes(marker)))throw Error('service-login-required');
  if(page.url()===PREFIX+'home'||page.url()===PREFIX.slice(0,-1)){await clickUnique(page,'appstore 控制台');await waitFor(page,()=>page.url().startsWith(PREFIX+'manager/'),'manager-console-not-open');}
  let customer=await waitFor(page,async()=>{const hits=await visibleExact(page,'客户管理');return hits.length===1?hits[0]:null;},'customer-menu-not-ready',2500).catch(()=>null);
  if(!customer){
    const positioned=[];for(const item of await visibleRawExact(page,'代运营')){const box=await item.boundingBox();if(box)positioned.push({item,box});}
    positioned.sort((a,b)=>a.box.x-b.box.x);
    if(positioned.length===0||positioned.length>2||positioned[0].box.x>=100)throw Error(`agent-menu-count:${positioned.length}`);
    await positioned[0].item.click({timeout:5000});customer=await waitUniqueExact(page,'客户管理');
  }
  if((await visibleExact(page,'意向商户管理')).length===0){await clickUnique(page,'客户管理');await waitUniqueExact(page,'意向商户管理');}
  await clickUnique(page,'意向商户管理');
  await waitFor(page,()=>pageReady(page),'intention-list-not-open');return true;
}
async function visibleDateCell(page,date){const hits=[];for(const frame of page.frames()){const locator=frame.locator(`[title="${date}"]:not(.ant-picker-cell-disabled)`);for(let i=0;i<await locator.count();i++){const item=locator.nth(i);if(await item.isVisible().catch(()=>false))hits.push(item);}}if(hits.length!==1)throw Error(`calendar-day-count:${date}:${hits.length}`);return hits[0];}
async function dateInput(page,placeholder){const hits=[];for(const frame of page.frames()){const locator=frame.locator(`input[placeholder="${placeholder}"]`);for(let i=0;i<await locator.count();i++){const item=locator.nth(i);if(await item.isVisible().catch(()=>false))hits.push(item);}}if(hits.length!==1)throw Error(`date-input-count:${placeholder}:${hits.length}`);return hits[0];}
export function datePairMatches(values,startDate,endDate){return Array.isArray(values)&&values.length===2&&values[0]===startDate&&values[1]===endDate;}
async function dateValues(page){return Promise.all(['开始日期','结束日期'].map(async placeholder=>(await dateInput(page,placeholder)).inputValue()));}
async function setDateEndpoint(page,placeholder,date){for(let attempt=0;attempt<2;attempt++){const input=await dateInput(page,placeholder);await input.click();await (await visibleDateCell(page,date)).click();try{await waitFor(page,async()=>(await (await dateInput(page,placeholder)).inputValue())===date,`date-readback-mismatch:${placeholder}`,2500);return;}catch(error){if(attempt===1)throw error;await page.keyboard.press('Escape').catch(()=>{});await page.waitForTimeout(200);}}}
async function filterDate(page,startDate,endDate){await setDateEndpoint(page,'开始日期',startDate);await setDateEndpoint(page,'结束日期',endDate);let previous=null;await waitFor(page,async()=>{const values=await dateValues(page);const stable=previous!==null&&JSON.stringify(previous)===JSON.stringify(values);previous=values;return stable&&datePairMatches(values,startDate,endDate);},'date-range-readback-not-stable',5000);await clickUnique(page,'查询');previous=null;await waitFor(page,async()=>{const text=await allText(page);if(text.includes('加载中'))return false;const {rows}=await tableRows(page);const signature=JSON.stringify(rows.map(row=>[row.merchantId,row.recommendTime,row.status]));const stable=previous===signature;previous=signature;return stable&&rows.every(row=>row.recommendTime.slice(0,10)>=startDate&&row.recommendTime.slice(0,10)<=endDate);},'filtered-table-not-stable',12000);}
async function tableRows(page){const {frame,headers,rows:loc}=await tableTarget(page);const matrices=[];for(let i=0;i<await loc.count();i++)matrices.push((await loc.nth(i).locator('td').allInnerTexts()).map(value=>value.trim()));return {frame,loc,rows:parseLogicalRows(headers,matrices)};}
async function pager(page){let active=[],prev=[],next=[];for(const frame of page.frames()){for(const item of await frame.locator('.ant-pagination-item-active').all())if(await item.isVisible().catch(()=>false))active.push(item);for(const item of await frame.locator('.ant-pagination-prev').all())if(await item.isVisible().catch(()=>false))prev.push(item);for(const item of await frame.locator('.ant-pagination-next').all())if(await item.isVisible().catch(()=>false))next.push(item);}if(active.length!==1||prev.length!==1||next.length!==1)throw Error(`pagination-state:${active.length}:${prev.length}:${next.length}`);const pageNumber=Number((await active[0].innerText()).trim());const disabled=await next[0].evaluate(node=>node.classList.contains('ant-pagination-disabled')||node.getAttribute('aria-disabled')==='true');return {page:pageNumber,prev:prev[0],next:next[0],nextEnabled:!disabled};}
async function stablePage(page,expected,priorSignature){let previous=null;return waitFor(page,async()=>{const {rows}=await tableRows(page),state=await pager(page);const signature=JSON.stringify(rows.map(row=>[row.merchantId,row.recommendTime,row.status]));if(state.page!==expected||signature===priorSignature){previous=null;return false;}const stable=previous===signature;previous=signature;return stable?{rows,state,signature}:false;},`pagination-page-not-stable:${expected}`,12000);}
async function exactPage(page,expected,wantedSignature){let previous=null;return waitFor(page,async()=>{const {rows}=await tableRows(page),state=await pager(page);const signature=JSON.stringify(rows.map(row=>[row.merchantId,row.recommendTime,row.status]));if(state.page!==expected||signature!==wantedSignature){previous=null;return false;}const stable=previous===signature;previous=signature;return stable?{rows,state,signature}:false;},`pagination-page-signature-mismatch:${expected}`,12000);}
function fieldFromLines(lines,name){const start=lines.findIndex(value=>value===name);if(start<0)throw Error('detail-label-missing:'+name);let end=lines.length;for(let i=start+1;i<lines.length;i++)if(FIELDS.includes(lines[i])){end=i;break;}return lines.slice(start+1,end).join('').trim();}
async function readDetail(page,row){const {loc}=await tableRows(page);const tr=loc.nth(row.rowIndex);const buttons=tr.getByText('详情',{exact:true});if(await buttons.count()!==1)throw Error('detail-action-not-unique:'+row.merchantId);await buttons.click();const modal=await waitFor(page,async()=>{const found=[];for(const frame of page.frames()){let candidates=frame.locator('.ant-modal-wrap:visible');if(await candidates.count()===0)candidates=frame.locator('[role="dialog"]:visible');for(let i=0;i<await candidates.count();i++){const item=candidates.nth(i);if((await item.innerText()).includes('推荐商家详情'))found.push(item);}}if(found.length>1)throw Error('detail-modal-multiple');return found[0]||null;},'detail-modal-missing');const detail=await waitFor(page,async()=>{const lines=(await modal.innerText()).split('\n').map(value=>value.trim()).filter(Boolean);const value={merchantName:fieldFromLines(lines,'商家名称'),merchantId:fieldFromLines(lines,'商家ID').replace(/\D/g,''),address:fieldFromLines(lines,'商家地址'),contact:fieldFromLines(lines,'商家联系人')};return value.merchantId===row.merchantId&&value.merchantName===row.merchantName?value:null;},`detail-content-not-stable:${row.merchantId}`,10000);const close=modal.locator('.ant-modal-close,button[aria-label="Close"]');if(await close.count()!==1)throw Error('detail-close-not-unique');await close.click();await waitFor(page,async()=>!await modal.isVisible().catch(()=>false),'detail-not-closed');return {...row,...detail,detailVerified:true};}

export async function run(input){
  const started=Date.now(),stageMs={},stageResults={};let browser,page;const result={ok:false,executor:'merchant-collector',browserController:'control-background-dedicated-chrome',profile:input.profile,port:input.port,groupName:input.group,businessDate:input.businessDate,runtimeModelDecisions:0,stageMs,stageResults,messages:[],frontmostBefore:await frontmost()};
  const stage=async(name,fn)=>{const t=Date.now();try{const value=await fn();stageResults[name]='PASS';return value;}catch(error){stageResults[name]='FAIL';throw error;}finally{stageMs[name]=Date.now()-t;}};
  try{
    if(!safeId(input.profile)||!Number.isInteger(input.port)||input.port!==9231)throw Error('background-browser-binding-mismatch');
    const state=JSON.parse(await fs.readFile(path.join(PROFILE_ROOT,input.profile,'.aos-background-chrome/state.json'),'utf8'));if(state.profile!==input.profile||state.mode!=='headless'||state.port!==input.port)throw Error('background-profile-state-mismatch');try{process.kill(state.pid,0);}catch{throw Error('background-profile-process-not-alive');}
    browser=await stage('background_preflight',()=>chromium.connectOverCDP(`http://127.0.0.1:${input.port}`));const context=browser.contexts()[0];if(!context)throw Error('browser-context-missing');
    page=await stage('task_page',async()=>{const value=await context.newPage();await value.addInitScript(id=>window.name=`aos-background-task:${id}`,input.taskId);await value.goto(HOME,{waitUntil:'domcontentloaded',timeout:30000});await value.evaluate(id=>window.name=`aos-background-task:${id}`,input.taskId);return value;});
    const startDate=input.cursor.recommendTime.slice(0,10),endDate=input.businessDate;if(startDate>endDate)throw Error('cursor-date-after-business-date');
    await stage('navigation',()=>route(page));await stage('date_filter',()=>filterDate(page,startDate,endDate));
    const allRows=[],pages=[],seen=new Set(),pageSignatures=new Map();let priorSignature=null;for(let expected=1;expected<=50;expected++){const stable=await stage(`page_${expected}_read`,()=>stablePage(page,expected,priorSignature));const {rows,state,signature}=stable;priorSignature=signature;pageSignatures.set(expected,signature);if(rows.some(row=>!new RegExp(`^\\d{4}-\\d{2}-\\d{2} \\d{2}:\\d{2}:\\d{2}$`).test(row.recommendTime)||row.recommendTime.slice(0,10)<startDate||row.recommendTime.slice(0,10)>endDate))throw Error('row-outside-filter-range');for(const row of rows){const identity=`${row.merchantId}\n${row.recommendTime}`;if(seen.has(identity))throw Error('duplicate-pagination-row-identity');seen.add(identity);row.sourcePage=expected;allRows.push(row);}pages.push({page:expected,rowCount:rows.length,nextEnabled:state.nextEnabled});if(!state.nextEnabled)break;await stage(`page_${expected}_next`,()=>state.next.click());if(expected===50)throw Error('pagination-budget-exceeded');}
    const pending=allRows.filter(row=>row.status==='待处理');const targets=stableIncremental(allRows,input.cursor,startDate).filter(row=>row.status==='待处理');for(const target of targets){let state=await pager(page),currentPage=state.page;while(currentPage>target.sourcePage){state=await pager(page);await state.prev.click();currentPage-=1;await exactPage(page,currentPage,pageSignatures.get(currentPage));}while(currentPage<target.sourcePage){state=await pager(page);await state.next.click();currentPage+=1;await exactPage(page,currentPage,pageSignatures.get(currentPage));}const current=(await tableRows(page)).rows.filter(row=>row.merchantId===target.merchantId&&row.merchantName===target.merchantName&&row.recommendTime===target.recommendTime);if(current.length!==1)throw Error('detail-row-not-unique');const detail=await stage('detail_'+target.merchantId,()=>readDetail(page,{...target,rowIndex:current[0].rowIndex}));const text=messageFor(detail);result.messages.push({...detail,text,sha256:crypto.createHash('sha256').update(text).digest('hex')});}
    result.ok=true;Object.assign(result,{createdAt:new Date().toISOString(),cursor:input.cursor,cursorSource:input.cursorSource,filterStartDate:startDate,filterEndDate:endDate,dateFilter:`${startDate}..${endDate}`,dateFilterVerified:true,pages,paginationComplete:true,totalRows:allRows.length,pendingRows:pending.length,targetCount:targets.length,ascending:true,detailsVerified:true,url:page.url()});
  }catch(error){result.error=String(error.message||error);}finally{if(page)await page.close().catch(()=>{});if(browser)await browser.close().catch(()=>{});result.elapsedMs=Date.now()-started;result.frontmostAfter=await frontmost();}
  return result;
}

if(import.meta.url===`file://${process.argv[1]}`){const args=parseArgs(process.argv.slice(2));const input=JSON.parse(await fs.readFile(args.input,'utf8'));const receipt=await run(input);await fs.writeFile(args.out,JSON.stringify(receipt,null,2),{mode:0o600});console.log(JSON.stringify({ok:receipt.ok,executor:receipt.executor,error:receipt.error,elapsedMs:receipt.elapsedMs,runtimeModelDecisions:0}));if(!receipt.ok)process.exitCode=1;}
