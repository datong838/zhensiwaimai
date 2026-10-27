import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const HERE=path.dirname(fileURLToPath(import.meta.url));
const POST=path.resolve(HERE,'../../../posts/meituan-post');
const ROOT_ORIGIN='https://waimaie.meituan.com';
export const INCOME_ORIGINS=['https://waimaieapp.meituan.com',ROOT_ORIGIN];
export const RANK_REQUEST_PATH='/gw/bizdata/chain/business/rank';
export const compact=v=>String(v??'').replace(/\s+/g,'');
export function yesterday(now=new Date()){const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(now);const d=new Date(day+'T00:00:00+08:00');d.setUTCDate(d.getUTCDate()-1);return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(d);}
export function amount(v){const s=compact(v);if(!/^(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?$/.test(s))throw Error('meituan-income-value-invalid');return Number(s.replaceAll(',',''));}
export function expandHeaders(rows){
 const grid=[];
 for(let r=0;r<rows.length;r++){grid[r]||=[];let col=0;for(const cell of rows[r]){while(grid[r][col]!==undefined)col++;for(let dr=0;dr<cell.rowSpan;dr++){grid[r+dr]||=[];for(let dc=0;dc<cell.colSpan;dc++)grid[r+dr][col+dc]=compact(cell.text);}col+=cell.colSpan;}}
 if(!grid.length)return[];
 return grid[0].map((_,c)=>[...new Set(grid.map(row=>row[c]).filter(Boolean))].join('/'));
}
export function incomeIndex(columns){const indices=columns.flatMap((x,i)=>/^(订单收入|预计订单收入)\/数值$/.test(x)?[i]:[]);if(indices.length!==1)throw Error('meituan-income-column-not-unique');return indices[0];}
export function sortLeafIndex(columns){const income=incomeIndex(columns);return columns.slice(0,income).filter(c=>c.includes('/')).length;}
export function isIncomeDescending(snapshot){const columns=expandHeaders(snapshot.headers);return snapshot.sortOrders[sortLeafIndex(columns)]==='descending';}
export function validateRows(snapshot,{descending=true}={}){
 const columns=expandHeaders(snapshot.headers),index=incomeIndex(columns);
 const rank=columns.indexOf('排名'),store=columns.indexOf('门店名称');
 if(rank<0||store<0||snapshot.matrix.length!==10)throw Error('meituan-top10-shape-invalid');
 const rows=snapshot.matrix.map(c=>({rank:Number(compact(c[rank])),store:String(c[store]||'').trim(),income:amount(c[index])}));
 if(rows.some((r,i)=>r.rank!==i+1||!r.store)||new Set(rows.map(r=>r.store)).size!==10)throw Error('meituan-top10-ranks-invalid');
 if(descending&&(!isIncomeDescending(snapshot)||rows.some((r,i)=>i&&r.income>rows[i-1].income)))throw Error('meituan-income-not-descending');
 return {rows,columns,incomeColumn:index};
}
export function rankSnapshot(element){
 const table=element.querySelector('table');if(!table)throw Error('meituan-ranking-table-missing');
 return {headers:[...table.querySelectorAll('thead tr')].map(r=>[...r.children].map(c=>({text:c.innerText,rowSpan:c.rowSpan||1,colSpan:c.colSpan||1}))),matrix:[...table.querySelectorAll('tbody tr')].filter(r=>r.classList.contains('customRoo-tableNew-row')).map(r=>[...r.cells].map(c=>c.innerText.trim())),sortOrders:[...table.querySelectorAll('thead tr:nth-child(2) th')].map(h=>h.querySelector('.roo-icon-arrow-down-new.on')?'descending':h.querySelector('.roo-icon-arrow-up-new.on')?'ascending':null)};
}
async function wait(fn,page,reason,ms=15000){const end=Date.now()+ms;let cause;while(Date.now()<end){try{const x=await fn();if(x)return x;}catch(e){cause=e.message;}await page.waitForTimeout(250);}throw Error(reason+(cause?':'+cause:''));}
async function postIntegrity(){const m=JSON.parse(await fs.readFile(path.join(POST,'dependencies.json'),'utf8'));for(const [name,sha] of Object.entries(m.files))if(crypto.createHash('sha256').update(await fs.readFile(path.join(POST,name))).digest('hex')!==sha)throw Error('meituan-post-drift:'+name);}
async function stable(panel,page){let previous;return wait(async()=>{const value=await panel.evaluate(rankSnapshot);validateRows(value,{descending:false});const sig=JSON.stringify(value);if(sig===previous)return value;previous=sig;return null;},page,'meituan-ranking-not-stable');}
async function knownNotice(page){
 const modals=page.locator('.roo-modal:visible');const n=await modals.count();if(!n)return false;if(n!==1)throw Error('meituan-unknown-modal');const modal=modals.first();const text=await modal.innerText();
 if(!text.startsWith('会话疑似存在欺诈风险')||!text.includes('请勿脱离平台交易或向未核实身份者转账')||await modal.locator('.danger-notice-modal').count()!==1)throw Error('meituan-unknown-modal');
 const button=modal.getByRole('button',{name:'我知道了',exact:true});if(await button.count()!==1)throw Error('meituan-notice-close-not-unique');await button.click({timeout:4000});return true;
}
export async function collect(output){
 await postIntegrity();
 const {acquirePostLease,releasePostLease}=await import(path.join(POST,'scripts/lease.mjs'));
 const {assertOrigin,assertAuthenticated}=await import(path.join(POST,'scripts/auth.mjs'));
 const taskId='meituan-income-top10-'+crypto.randomUUID();const lease=await acquirePostLease(taskId);if(!lease)throw Error('meituan-post-busy');
 let browser,page,session,targetId,result;const dataDate=yesterday();
 try{
  const connection=await(await import(path.join(POST,'scripts/connect.mjs'))).connectToPost();browser=connection.browser;
  page=await connection.context.newPage();await page.setViewportSize({width:2200,height:1800});
  session=await connection.context.newCDPSession(page);targetId=(await session.send('Target.getTargetInfo')).targetInfo.targetId;
  await session.send('Emulation.setDeviceMetricsOverride',{width:2200,height:1800,deviceScaleFactor:2,mobile:false});
  // Never set window.name: this site owns iframe names such as J-imframe.
  await page.goto(ROOT_ORIGIN+'/?time='+Date.now()+'&ignoreSetRouterProxy=true',{waitUntil:'domcontentloaded',timeout:30000});
  await page.getByText('经营分析',{exact:true}).waitFor({state:'visible',timeout:20000});assertOrigin(page.url());assertAuthenticated(await page.locator('body').innerText());
  let noticeClosed=await knownNotice(page);
  try{await page.getByText('经营分析',{exact:true}).click({timeout:5000});}catch(error){if(!noticeClosed&&await knownNotice(page)){noticeClosed=true;await page.getByText('经营分析',{exact:true}).click({timeout:5000});}else throw error;}await page.getByText('经营数据',{exact:true}).click({timeout:5000});
  let frame=await wait(async()=>{const xs=page.frames().filter(f=>{try{const u=new URL(f.url());return u.origin==='https://waimaieapp.meituan.com'&&u.pathname==='/igate/bizdata/home';}catch{return false;}});if(xs.length>1)throw Error('meituan-business-frame-not-unique');return xs[0];},page,'meituan-business-frame-missing');
  await frame.getByText('营收',{exact:true}).click({timeout:15000});
  frame=await wait(async()=>page.frames().find(f=>{try{const u=new URL(f.url());return u.origin==='https://waimaieapp.meituan.com'&&u.pathname==='/igate/bizdata/business';}catch{return false;}}),page,'meituan-income-frame-missing');
  const yesterdayControl=frame.getByText('昨日',{exact:true});await yesterdayControl.waitFor({state:'visible',timeout:15000});if(!await yesterdayControl.evaluate(e=>e.classList.contains('active')))await yesterdayControl.click({timeout:5000});
  const verifyDate=async()=>{const t=await frame.locator('body').innerText();return (await yesterdayControl.evaluate(e=>e.classList.contains('active')))&&t.includes('已选时间：'+dataDate)&&(await frame.getByText('营收',{exact:true}).evaluate(e=>e.classList.contains('navtabs-wrapper__item--active')));};
  await wait(verifyDate,page,'meituan-yesterday-postcondition-failed');
  const panel=frame.locator('.layout-card-panel.business-renew-rank');if(await panel.count()!==1)throw Error('meituan-income-panel-not-unique');
  let snapshot=await stable(panel,page);const sortEvidence=[];
  for(let i=0;!isIncomeDescending(snapshot)&&i<2;i++){
   const header=panel.locator('thead tr').nth(1).locator('th').nth(sortLeafIndex(expandHeaders(snapshot.headers)));
   if(compact(await header.innerText())!=='数值')throw Error('meituan-income-header-layout-changed');
   const pending=page.waitForResponse(r=>{try{const u=new URL(r.url());return INCOME_ORIGINS.includes(u.origin)&&u.pathname===RANK_REQUEST_PATH&&r.request().method()==='POST';}catch{return false;}},{timeout:15000});
   pending.catch(()=>{});await header.click({timeout:5000});const response=await pending;if(response.status()!==200)throw Error('meituan-sort-response-failed');await response.finished();snapshot=await stable(panel,page);sortEvidence.push({path:RANK_REQUEST_PATH,status:200,domStable:true});
  }
  const parsed=validateRows(snapshot);if(!await verifyDate())throw Error('meituan-date-changed-before-capture');
  await panel.scrollIntoViewIfNeeded({timeout:5000});const box=await panel.boundingBox(),last=await panel.locator('tbody tr.customRoo-tableNew-row').last().boundingBox();
  const view=page.viewportSize();if(!box||!last)throw Error('meituan-capture-geometry-missing');
  const clip={x:Math.floor(box.x),y:Math.floor(box.y),width:Math.ceil(box.width),height:Math.ceil(last.y+last.height-box.y+6)};
  if(clip.x<0||clip.y<0||clip.width<800||clip.height<400||clip.x+clip.width>view.width||clip.y+clip.height>view.height)throw Error('meituan-capture-not-complete');
  if(await page.locator('.roo-modal:visible').count())throw Error('meituan-modal-before-capture');
  await fs.mkdir(output,{recursive:true,mode:0o700});const file=path.join(output,dataDate+'-美团外卖门店收入top10.png');
  const capture=await session.send('Page.captureScreenshot',{format:'png',fromSurface:true,captureBeyondViewport:false,clip:{...clip,scale:1}});const bytes=Buffer.from(capture.data,'base64');await fs.writeFile(file,bytes,{mode:0o600});
  if(JSON.stringify(await panel.evaluate(rankSnapshot))!==JSON.stringify(snapshot)||!await verifyDate())throw Error('meituan-data-changed-during-capture');
  result={ok:true,browserPort:9233,taskId,targetId,dataDate,collectedAt:new Date().toISOString(),sourceRoute:'https://waimaieapp.meituan.com/igate/bizdata/business',sortMetric:'订单收入/数值',sortDirection:'descending',sortEvidence,...parsed,file,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),width:bytes.readUInt32BE(16),height:bytes.readUInt32BE(20),clip,sendAttempts:0,runtimeModelDecisions:0};
 }finally{
  try{if(page&&session&&!page.isClosed()&&(await session.send('Target.getTargetInfo')).targetInfo.targetId===targetId)await page.close();}finally{if(browser)await browser.close();await releasePostLease(lease);}
 }
 await fs.writeFile(path.join(output,'collection.json'),JSON.stringify(result,null,2),{mode:0o600});return result;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{if(process.argv.length!==4||process.argv[2]!=='--output')throw Error('usage: --output DIRECTORY');console.log(JSON.stringify(await collect(path.resolve(process.argv[3]))));}catch(error){console.log(JSON.stringify({ok:false,reason:String(error.message||error).slice(0,500),sendAttempts:0}));process.exitCode=1;}
}
