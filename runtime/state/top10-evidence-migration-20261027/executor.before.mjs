#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFile as execFileCb} from 'node:child_process';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {promisify} from 'node:util';
import {yesterdayInShanghai,isNonIncreasing} from './desktop_executor.mjs';

const require=createRequire(import.meta.url);
const {chromium}=require('/Users/ddt/work/projects/ai_agent/browser/headless-playwright/node_modules/playwright-core');
const execFile=promisify(execFileCb);
const dir=path.dirname(fileURLToPath(import.meta.url));
const HOME_URL='https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard';
const URL_PREFIX='https://melody.shop.ele.me/app/chain/95708808/';
const PROFILE_ROOT='/Users/ddt/Library/Application Support/AOS Background Chrome';
const LOGIN_MARKERS=['账号密码','扫码登录','没有账号，去开店','无法登录？'];
const SIGNED_MARKERS=['商家首页','今日营业概况','数据中心','订单管理','门店管理'];
const REQUIRED_HEADERS=['有效订单量','曝光人数'];
export const normalizeHeader=value=>String(value).replace(/\s+/g,'').replace(/\(元\)/g,'（元）');
export function incomeColumn(headers){const matches=headers.map((h,i)=>({h:normalizeHeader(h),i})).filter(x=>/^(预计收入|收入)(（元）)?$/.test(x.h));if(matches.length!==1)throw Error('income-header-not-unique');return matches[0].i;}
export function incomeMoney(value){const text=String(value||'').trim().split('\n')[0].trim().replace(/^[¥￥]\s*/, '').replace(/元$/, '').trim();if(!/^(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?$/.test(text))return NaN;return Number(text.replaceAll(',',''));}
export const incomeDescending=snapshot=>snapshot.sortOrders?.[incomeColumn(snapshot.headers)]==='descending';
export function leafHeaderCells(rows){
  if(!rows.length)throw Error('header-grid-empty');
  const grid=Array.from({length:rows.length},()=>[]);
  for(let r=0;r<rows.length;r++){let col=0;for(const cell of rows[r]){
    while(grid[r][col])col++;
    const height=cell.rowSpan||1,width=cell.colSpan||1;
    if(!Number.isInteger(height)||!Number.isInteger(width)||height<1||width<1||r+height>rows.length)throw Error('header-grid-span');
    for(let y=r;y<r+height;y++)for(let x=col;x<col+width;x++){if(grid[y][x])throw Error('header-grid-overlap');grid[y][x]=cell;}
    col+=width;
  }}
  const width=grid[0].length;
  if(!width||grid.some(row=>row.length!==width||Array.from({length:width},(_,i)=>row[i]).some(x=>!x)))throw Error('header-grid-incomplete');
  const leaves=grid.at(-1);if(leaves.some(x=>(x.colSpan||1)!==1))throw Error('header-grid-nonleaf');return leaves;
}
const BANNED_OCR=/(顾客|手机号|已下\d*单|补充备注|催单|投诉|发票申请)/;
export const CANONICAL_PROFILE='taobao-brand';
export const CANONICAL_PORT=9230;

function parseArgs(argv){const out={profile:'taobao-brand',port:'9230'};for(let i=0;i<argv.length;i++){if(argv[i]==='--self-test')out.selfTest=true;else if(argv[i].startsWith('--'))out[argv[i].slice(2)]=argv[++i];}return out;}
export const safeId=value=>/^[a-z0-9][a-z0-9-]{0,62}$/.test(value||'');
export function ownsTaskMarker(marker,taskId){
  if(typeof marker!=='string'||!safeId(taskId))return false;
  const expected=`aos-background-task:${taskId}`;
  if(marker===expected)return true;
  if(!marker.startsWith('nameStorage:'))return false;
  const split=marker.indexOf('?');if(split<0)return false;
  try{
    if(decodeURIComponent(marker.slice('nameStorage:'.length,split))!==expected)return false;
    const entries=[...new URLSearchParams(marker.slice(split+1))];
    const allowed=new Set(['TRACERT_REF_referPageId','TRACERT_REF_referO2oPageId']);
    return entries.length>0&&entries.length<=2&&new Set(entries.map(([key])=>key)).size===entries.length&&entries.every(([key,value])=>allowed.has(key)&&/^[a-zA-Z0-9._-]+$/.test(value));
  }catch{return false;}
}
const firstLine=value=>(value||'').trim().split('\n')[0].trim();
const money=value=>{const match=firstLine(value).match(/^([\d,]+(?:\.\d{1,2})?)/);return match?Number(match[1].replaceAll(',','')):NaN;};
export function rowsFromCellMatrix(matrix,headers){
  if(!headers)return matrix.filter(cells=>firstLine(cells[0])).map(cells=>({store:firstLine(cells[0]).replace(/^新店/,''),rank:firstLine(cells[2]),revenue:money(cells[3]),orders:money(cells[5])}));
  const normalized=headers.map(normalizeHeader),income=incomeColumn(headers);
  const unique=names=>{const indices=normalized.flatMap((h,i)=>names.includes(h)?[i]:[]);if(indices.length!==1)throw Error('business-header-not-unique:'+names[0]);return indices[0];};
  const store=unique(['门店名称','店铺名称']),orders=unique(['有效订单量']),revenue=normalized.indexOf('营业额'),rank=normalized.indexOf('商圈收入排名');
  return matrix.filter(cells=>firstLine(cells[store])).map(cells=>({store:firstLine(cells[store]).replace(/^新店/,''),income:incomeMoney(cells[income]),revenue:revenue<0?null:money(cells[revenue]),rank:rank<0?null:firstLine(cells[rank]),orders:money(cells[orders])}));
}
export function loginAssessment(text){const loginPage=LOGIN_MARKERS.filter(x=>text.includes(x));const signedIn=SIGNED_MARKERS.filter(x=>text.includes(x));return {loginPage,signedIn,authenticated:loginPage.length===0&&signedIn.length>=3};}
export function validateProfileState(state,profile,port){return Boolean(state&&state.profile===profile&&state.mode==='headless'&&state.port===port&&Number.isInteger(state.pid)&&state.pid>1);}
export function yesterdayDataState(text,spinning=0){if(spinning>0)return 'LOADING';if(text.includes('暂无数据')&&(text.match(/--/g)||[]).length>=6)return 'NOT_READY';return 'READY_OR_PARTIAL';}
export function assertCanonicalBrowser(profile,port){
  if(profile!==CANONICAL_PROFILE)throw Error('runtime-policy-browser-profile-mismatch');
  if(Number(port)!==CANONICAL_PORT)throw Error('runtime-policy-browser-port-mismatch');
}

async function allFrameText(page){const bodies=[];for(const frame of page.frames()){try{const value=(await frame.locator('body').first().innerText()).trim();if(value)bodies.push(value);}catch{}}return [...new Set(bodies)].join('\n');}
async function waitUntil(fn,timeoutMs,page,reason){const end=Date.now()+timeoutMs;let last;while(Date.now()<end){try{last=await fn();if(last)return last;}catch(error){last=error;}await page.waitForTimeout(200);}throw Error(reason+(last instanceof Error?':'+last.message:''));}
async function uniqueVisibleText(page,text,timeoutMs){return waitUntil(async()=>{const found=[];for(const frame of page.frames()){const items=frame.getByText(text,{exact:true});for(let i=0;i<await items.count();i++){const item=items.nth(i);if(await item.isVisible())found.push(item);}}if(found.length>1)throw Error('visible-text-not-unique:'+text);return found[0]||null;},timeoutMs,page,'visible-text-missing:'+text);}
async function tableSnapshot(frame){
  const raw=await frame.locator('table').evaluateAll(tables=>tables.map(table=>({headerRows:[...table.querySelectorAll('thead tr')].map(row=>[...row.querySelectorAll('th')].map(x=>({text:(x.innerText||'').trim(),rowSpan:x.rowSpan,colSpan:x.colSpan,sortOrder:x.getAttribute('aria-sort')||(x.querySelector('.ant-table-column-sorter-down.active')?'descending':x.querySelector('.ant-table-column-sorter-up.active')?'ascending':null)}))),matrix:[...table.querySelectorAll('tbody tr')].map(row=>[...row.querySelectorAll('td')].map(cell=>(cell.innerText||'').trim()))})));
  const tables=raw.filter(x=>x.headerRows.length).map(x=>{const leaves=leafHeaderCells(x.headerRows);return {headers:leaves.map(x=>x.text),sortOrders:leaves.map(x=>x.sortOrder),matrix:x.matrix};});
  const candidates=tables.filter(x=>x.headers.some(h=>['门店名称','店铺名称'].includes(normalizeHeader(h)))&&x.headers.some(h=>normalizeHeader(h)==='有效订单量'));
  if(candidates.length!==1)return null;incomeColumn(candidates[0].headers);return candidates[0];
}
async function ensureIncomeMetric(frame,page){
  const headers=await frame.locator('thead th').allInnerTexts();
  const existing=headers.filter(h=>/^(预计收入|收入)(（元）)?$/.test(normalizeHeader(h)));
  if(existing.length){incomeColumn(headers);return 'ALREADY_VISIBLE';}
  const select=frame.getByRole('button',{name:/^选择指标\s*\(\d+\)$/});
  if(await select.count()!==1)throw Error('metric-selector-not-unique');await select.click({timeout:5000});
  const modal=frame.locator('.ant-modal-wrap:visible');
  if(await modal.count()!==1||!(await modal.innerText()).includes('营收指标组'))throw Error('income-metric-modal-mismatch');
  const labels=modal.locator('label.ant-checkbox-wrapper');
  const chosen=()=>labels.evaluateAll(xs=>xs.filter(x=>x.querySelector('input[type=checkbox]')?.checked).map(x=>(x.innerText||'').replace(/\s+/g,'')));
  const before=await chosen(),options=[];
  for(let i=0;i<await labels.count();i++){const label=labels.nth(i);if(/^(预计收入|收入)$/.test(normalizeHeader(await label.innerText())))options.push(label);}
  if(options.length!==1)throw Error('income-metric-option-not-unique');
  const label=normalizeHeader(await options[0].innerText());
  if(await options[0].locator('input').isChecked())throw Error('income-selected-but-column-missing');
  await options[0].click({timeout:5000});const after=await chosen();
  if(after.length!==before.length+1||!after.includes(label)||before.some(x=>!after.includes(x))||after.some(x=>x!==label&&!before.includes(x)))throw Error('income-metric-selection-drift');
  const confirm=modal.getByRole('button',{name:/^确认\s*\(\d+\)$/});
  if(await confirm.count()!==1)throw Error('income-metric-confirm-not-unique');await confirm.click({timeout:5000});
  await waitUntil(async()=>{if(await modal.isVisible())return null;const hs=await frame.locator('thead th').allInnerTexts();return hs.some(h=>normalizeHeader(h)===label);},10000,page,'income-metric-not-visible');
  return 'ADDED_INCOME_ONLY';
}
async function pagerSnapshot(frame){return frame.evaluate(()=>({active:[...document.querySelectorAll('.ant-pagination-item-active')].map(x=>(x.textContent||'').trim()),pageSizes:[...document.querySelectorAll('.ant-select-selection-item')].map(x=>(x.textContent||'').replace(/\s+/g,' ').trim()).filter(x=>x.includes('条/页'))}));}
async function dismissKnownNotice(page){
  const visible=[];for(const frame of page.frames()){const modals=frame.locator('.ant-modal-wrap:visible');for(let i=0;i<await modals.count();i++)visible.push(modals.nth(i));}
  if(visible.length===0)return 'ABSENT';if(visible.length!==1)throw Error('visible-modal-not-unique');
  const modal=visible[0],text=(await modal.innerText()).replace(/\s+/g,'');
  if(!text.includes('绑定手机号提醒')||!text.includes('为保障您的账号与资产安全，建议绑定手机号。')||!text.includes('跳过')||!text.includes('去绑定'))throw Error('unexpected-visible-modal');
  const buttons=modal.locator('button');const skip=[];for(let i=0;i<await buttons.count();i++)if((await buttons.nth(i).innerText()).replace(/\s+/g,'')==='跳过'&&await buttons.nth(i).isVisible())skip.push(buttons.nth(i));
  if(skip.length!==1)throw Error('skip-button-not-unique');await skip[0].click({timeout:5000});
  await waitUntil(async()=>await modal.isVisible().catch(()=>false)?null:true,3000,page,'known-notice-not-dismissed');return 'DISMISSED';
}
async function ocr(file){const {stdout}=await execFile(path.join(dir,'ocr_vision'),[file,'zh-Hans'],{timeout:15000,maxBuffer:4e6});return stdout.split('\n').flatMap(record=>{const [box,confidence,text]=record.split('\t');if(!text)return[];const [x,y,w,h]=(box||'').split(',').map(Number);return Number.isFinite(x)?[{x,y,w,h,confidence:Number(confidence),text}]:[];});}
async function dimensions(file){const {stdout}=await execFile('/usr/bin/sips',['-g','pixelWidth','-g','pixelHeight',file]);return {width:Number(stdout.match(/pixelWidth:\s*(\d+)/)?.[1]),height:Number(stdout.match(/pixelHeight:\s*(\d+)/)?.[1])};}

export function selfTest(){
  const rows=rowsFromCellMatrix([['','',''],['新店门店甲','99','第1名/20名','10,200.30','1','88'],['门店乙','98','第2名/20名','9,100.00','1','77']]);
  if(rows.length!==2||rows[0].store!=='门店甲'||rows[0].revenue!==10200.3||rows[1].orders!==77)throw Error('row-parser-self-test');
  if(!isNonIncreasing(rows.map(x=>x.revenue))||isNonIncreasing([1,2]))throw Error('sort-self-test');
  if(!loginAssessment('商家首页 今日营业概况 数据中心 建议绑定手机号').authenticated)throw Error('login-reminder-self-test');
  if(loginAssessment('商家首页 今日营业概况 数据中心 扫码登录').authenticated)throw Error('login-page-self-test');
  if(!validateProfileState({profile:'taobao-brand',mode:'headless',port:9230,pid:2},'taobao-brand',9230))throw Error('profile-state-self-test');
  if(yesterdayDataState('暂无数据 -- -- -- -- -- --',0)!=='NOT_READY'||yesterdayDataState('暂无数据 -- --',1)!=='LOADING')throw Error('data-readiness-self-test');
  assertCanonicalBrowser('taobao-brand',9230);
  for(const [profile,port] of [['other-profile',9230],['taobao-brand',9222]]){let rejected=false;try{assertCanonicalBrowser(profile,port);}catch{rejected=true;}if(!rejected)throw Error('canonical-browser-self-test');}
  return {ok:true,tests:7,runtimeModelDecisions:0};
}

export async function runBackgroundDesktop({profile='taobao-brand',port=9230,outputRoot='/tmp/zhensi_top10',runId=crypto.randomUUID()}={}){
  assertCanonicalBrowser(profile,port);
  const taskId=`top10-${runId}`;const outputDir=path.join(outputRoot,runId);await fs.mkdir(outputDir,{recursive:true,mode:0o700});
  const receiptFile=path.join(outputDir,'desktop_receipt.json');
  const receipt={ok:false,executor:'desktop',browserController:'control-background-dedicated-chrome',profile,port,taskId,runId,stageMs:{},stageResults:{},retryCount:0,sendAttempts:0,runtimeModelDecisions:0,receiptFile};
  let browser,page,cdpSession,started=0,deadline=0;
  const stage=async(name,fn)=>{receipt.stage=name;const t=performance.now();try{const value=await fn();receipt.stageResults[name]='PASS';return value;}catch(error){receipt.stageResults[name]='FAIL';throw error;}finally{receipt.stageMs[name]=Math.round(performance.now()-t);}};
  try{
    if(!safeId(profile)||!safeId(taskId))throw Error('invalid-profile-or-task-id');
    port=Number(port);if(!Number.isInteger(port)||port<1024||port>65535)throw Error('invalid-port');
    await stage('background_preflight',async()=>{
      const statePath=path.join(PROFILE_ROOT,profile,'.aos-background-chrome','state.json');const state=JSON.parse(await fs.readFile(statePath,'utf8'));
      if(!validateProfileState(state,profile,port))throw Error('background-profile-state-mismatch');
      try{process.kill(state.pid,0);}catch{throw Error('background-profile-process-not-alive');}
      browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
      const context=browser.contexts()[0];if(!context)throw Error('background-context-missing');
      let owned=0;for(const candidate of context.pages()){try{if(await candidate.evaluate(()=>window.name)===`aos-background-task:${taskId}`)owned++;}catch{}}
      if(owned!==0)throw Error('task-page-already-exists');
    });
    started=Date.now();deadline=started+180000;Object.assign(receipt,{startedAt:started,deadlineAt:deadline,dataDate:yesterdayInShanghai()});
    await stage('open_home',async()=>{
      const context=browser.contexts()[0];page=await context.newPage();await page.setViewportSize({width:2200,height:1800});
      cdpSession=await context.newCDPSession(page);await cdpSession.send('Emulation.setDeviceMetricsOverride',{width:2200,height:1800,deviceScaleFactor:2,mobile:false});receipt.deviceScaleFactor=2;
      await page.addInitScript(id=>{window.name=`aos-background-task:${id}`;},taskId);
      await page.goto(HOME_URL,{waitUntil:'domcontentloaded',timeout:30000});await page.evaluate(id=>{window.name=`aos-background-task:${id}`;},taskId);
      await waitUntil(async()=>{if(!page.url().startsWith(URL_PREFIX))throw Error('unexpected-page-url');const assessment=loginAssessment(await allFrameText(page));if(assessment.loginPage.length)throw Error('login-required');return assessment.authenticated?assessment:null;},12000,page,'merchant-home-not-ready');
      receipt.homeUrl=page.url();
    });
    await stage('dismiss_known_notice',async()=>{receipt.knownNotice=await dismissKnownNotice(page);});
    let frame;
    await stage('navigate_store_analysis',async()=>{
      const link=await uniqueVisibleText(page,'门店分析',10000);await link.click({timeout:5000});
      frame=await waitUntil(async()=>{if(!page.url().startsWith(URL_PREFIX))throw Error('unexpected-page-url');const matches=page.frames().filter(x=>x.url().includes('/storeAnalysisDetail?'));if(matches.length>1)throw Error('store-frame-not-unique');return matches[0]||null;},12000,page,'store-analysis-frame-missing');
      receipt.storeUrl=page.url();
    });
    await stage('select_yesterday',async()=>{
      const item=await uniqueVisibleText(page,'昨日',8000);
      const selected=await item.evaluate(e=>e.closest('label')?.classList.contains('ant-radio-button-wrapper-checked')||false);
      if(!selected)await item.click({timeout:5000});
      const short=receipt.dataDate.slice(5);
      await waitUntil(async()=>{const current=frame.getByText('昨日',{exact:true}).first();const checked=await current.evaluate(e=>e.closest('label')?.classList.contains('ant-radio-button-wrapper-checked')||false);const text=await frame.locator('body').innerText();return checked&&text.includes(`已选时间：${short}`);},10000,page,'yesterday-postcondition-failed');
    });
    let rows,wrapper,pagination;
    await stage('ensure_income_metric',async()=>{receipt.incomeMetricSelection=await ensureIncomeMetric(frame,page);});
    await stage('verify_sort',async()=>{
      let snapshot=await waitUntil(async()=>{const body=await frame.locator('body').innerText(),spinning=await frame.locator('.ant-spin-spinning').count();if(yesterdayDataState(body,spinning)==='NOT_READY')throw Error('yesterday-data-not-ready');const value=await tableSnapshot(frame);if(!value)return null;const parsed=rowsFromCellMatrix(value.matrix,value.headers);return parsed.length===10&&parsed.every(x=>x.store&&Number.isFinite(x.income)&&Number.isFinite(x.orders))?{value,parsed}:null;},15000,page,'ten-business-rows-not-ready');
      for(const header of REQUIRED_HEADERS)if(!snapshot.value.headers.includes(header)&&!(header==='门店名称'&&snapshot.value.headers.includes('店铺名称')))throw Error('table-header-missing:'+header);
      rows=snapshot.parsed;
      const incomeHeader=snapshot.value.headers[incomeColumn(snapshot.value.headers)];
      for(let attempt=0;!incomeDescending(snapshot.value)&&attempt<2;attempt++){
        const matches=[];const headers=frame.locator('th');for(let i=0;i<await headers.count();i++){const h=headers.nth(i);if(normalizeHeader(await h.innerText())===normalizeHeader(incomeHeader)&&await h.isVisible())matches.push(h);}
        if(matches.length!==1)throw Error('income-header-not-unique');
        const previous=JSON.stringify(snapshot.value);await matches[0].click({timeout:5000});receipt.retryCount++;
        snapshot=await waitUntil(async()=>{if(await frame.locator('.ant-spin-spinning').count())return null;const value=await tableSnapshot(frame);if(!value||JSON.stringify(value)===previous)return null;const parsed=rowsFromCellMatrix(value.matrix,value.headers);return parsed.length===10&&parsed.every(x=>Number.isFinite(x.income)&&Number.isFinite(x.orders))?{value,parsed}:null;},8000,page,'income-sort-transition-failed');
      }
      rows=snapshot.parsed;
      if(!incomeDescending(snapshot.value)||!isNonIncreasing(rows.map(x=>x.income)))throw Error('income-sort-failed');
      Object.assign(receipt,{incomeHeader,sortMetric:'income-amount',sortDirection:'descending'});
      const pager=await pagerSnapshot(frame);if(pager.active.length!==1||pager.active[0]!=='1'||pager.pageSizes.length!==1||!/^10\s*条\/页$/.test(pager.pageSizes[0]))throw Error('page-one-ten-rows-required');
      const wrappers=frame.locator('.ant-table-wrapper');const visible=[];for(let i=0;i<await wrappers.count();i++)if(await wrappers.nth(i).isVisible()&&(await wrappers.nth(i).innerText()).includes(receipt.incomeHeader))visible.push(wrappers.nth(i));
      if(visible.length!==1)throw Error('table-wrapper-not-unique');wrapper=visible[0];
      const pagers=frame.locator('.ant-pagination');const shown=[];for(let i=0;i<await pagers.count();i++)if(await pagers.nth(i).isVisible())shown.push(pagers.nth(i));
      if(shown.length!==1)throw Error('pagination-not-unique');pagination=shown[0];
      const incomeCell=frame.locator('th').filter({hasText:new RegExp(`^${incomeHeader}$`)});
      if(await incomeCell.count()!==1)throw Error('capture-income-header-not-unique');
      receipt.incomeVisibility=await incomeCell.evaluate(e=>{
        const wrapper=e.closest('.ant-table-wrapper');let scroller=e.parentElement;
        while(scroller&&!(scroller.scrollWidth>scroller.clientWidth&&['auto','scroll'].includes(getComputedStyle(scroller).overflowX)))scroller=scroller.parentElement;
        const bounds=()=>{const outer=wrapper.getBoundingClientRect();const left=[...wrapper.querySelectorAll('th.ant-table-cell-fix-left')].map(x=>x.getBoundingClientRect().right);const right=[...wrapper.querySelectorAll('th.ant-table-cell-fix-right')].map(x=>x.getBoundingClientRect().left);return {left:Math.max(outer.left,...left),right:Math.min(outer.right,...right)};};
        let box=e.getBoundingClientRect(),visible=bounds();
        if(scroller&&box.right>visible.right-8)scroller.scrollLeft+=box.right-visible.right+16;
        box=e.getBoundingClientRect();visible=bounds();
        return {ok:box.left>=visible.left&&box.right<=visible.right-8,left:box.left,right:box.right,visible,scrollLeft:scroller?.scrollLeft??null};
      });
      if(!receipt.incomeVisibility.ok)throw Error('capture-income-column-obscured');
    });
    await stage('capture_self_check',async()=>{
      const tableBox=await wrapper.boundingBox(),pagerBox=await pagination.boundingBox();
      if(!tableBox||!pagerBox)throw Error('capture-geometry-missing');
      const viewport=page.viewportSize();const x=Math.max(0,Math.min(tableBox.x,pagerBox.x));const y=Math.max(0,tableBox.y);
      const right=Math.min(viewport.width,Math.max(tableBox.x+tableBox.width,pagerBox.x+pagerBox.width));const bottom=Math.min(viewport.height,pagerBox.y+pagerBox.height+8);
      const clip={x:Math.floor(x),y:Math.floor(y),width:Math.floor(right-x),height:Math.floor(bottom-y)};
      receipt.captureGeometry={viewport,tableBox,pagerBox,clip};
      if(clip.width*receipt.deviceScaleFactor<1500||clip.height<400||clip.x+clip.width>viewport.width||clip.y+clip.height>viewport.height)throw Error('capture-geometry-invalid');
      const file=path.join(outputDir,`${receipt.dataDate}_top10seller.png`);const captured=await cdpSession.send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false,clip:{...clip,scale:1}});receipt.captureScale=1;await fs.writeFile(file,Buffer.from(captured.data,'base64'),{mode:0o600});
      const size=await dimensions(file);
      // 2026-10-10 大同授权「发现卡了立即解决」：Apple Vision 对 CJK 表头 token 的识别
      // 随图像重采样非确定性漂移（实测同一张图 2240px 漏识「营业额」、2400px 命中、
      // 3600px 又漏），致 capture_self_check 偶发 crop-field-missing 假失败（10-09 成功、
      // 10-10 失败，图内其实清晰含「营业额」）。改为对同一裁剪图做多尺度 OCR 并集
      // （18 张历史图实测：单尺度各 17/18 命中，并集 18/18），保持「图内须含
      // REQUIRED_HEADERS」的语义不变，仅消除重采样抖动，不放宽任何隐私/尺寸/几何门禁。
      let entries=[...await ocr(file)];
      for(const wide of [2400,3200]){
        const scaled=`${file}.w${wide}.png`;
        try{await execFile('/usr/bin/sips',['-Z',String(wide),file,'--out',scaled],{timeout:15000});entries.push(...await ocr(scaled));}
        catch{}
        finally{try{await fs.unlink(scaled);}catch{}}
      }
      // 2026-10-22：Apple Vision 整图版面分析会把「营业额/商圈收入排名」两列表头并入
      // 相邻单元格漏掉（同一张裁剪图实测：整图 OCR 0 命中，表头带 100% 命中；
      // 3 张今日失败图 + 1 张 10-21 成功图正负对照 4/4），多尺度并集也救不回来。
      // 补做一次「同一裁剪内表头带」OCR 并入证据池：图像来源仍是本张裁剪图，
      // 语义（图内须含 REQUIRED_HEADERS）不变，隐私扫描仍跑整图文本，不放宽任何门禁。
      try{
        const bandHeight=Math.min(220,clip.height);
        const band=await cdpSession.send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false,clip:{x:clip.x,y:clip.y,width:clip.width,height:bandHeight,scale:1}});
        const bandFile=`${file}.header.png`;
        await fs.writeFile(bandFile,Buffer.from(band.data,'base64'),{mode:0o600});
        try{entries.push(...await ocr(bandFile));}finally{try{await fs.unlink(bandFile);}catch{}}
      }catch{}
      const texts=entries.map(x=>x.text.replaceAll(' ','')).join('\n');
      if(size.width<1500||size.height<400)throw Error('image-size-invalid');if(BANNED_OCR.test(texts))throw Error('privacy-ocr-hit');
      for(const token of [normalizeHeader(receipt.incomeHeader),'有效订单'])if(!texts.includes(token))throw Error('crop-field-missing:'+token);
      // Store names are already validated from the live DOM table (10 rows,
      // yesterday, sorted revenue, page 1 / 10 rows). OCR is intentionally
      // limited to stable headers and privacy checks because Chinese store
      // names are not deterministic under OCR.
      Object.assign(receipt,{file,...size,sha256:crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex'),stores:rows.map(x=>x.store),incomes:rows.map(x=>x.income),revenues:rows.map(x=>x.revenue),page:1,pageSize:10,layout:'background-table-and-pagination',capture:clip});
    });
    receipt.ok=true;
  }catch(error){receipt.reason=error.message;}
  finally{
    if(page){try{if(ownsTaskMarker(await page.evaluate(()=>window.name),taskId)){await page.close();receipt.cleanupStatus='completed';}else receipt.cleanupStatus='preserved-marker-mismatch';}catch(error){receipt.cleanupStatus='failed';receipt.cleanupReason=String(error.message||error);}}
    if(browser)try{await browser.close();}catch{}
    receipt.elapsedMs=started?Date.now()-started:0;await fs.writeFile(receiptFile,JSON.stringify(receipt,null,2),{mode:0o600});
  }
  return receipt;
}

const args=parseArgs(process.argv.slice(2));
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){if(args.selfTest)console.log(JSON.stringify(selfTest()));else{const result=await runBackgroundDesktop({profile:args.profile,port:Number(args.port)});console.log(JSON.stringify(result));process.exitCode=result.ok?0:1;}}
