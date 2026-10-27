import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFile as execFileCb} from 'node:child_process';
import {promisify} from 'node:util';
import {withTaskPage} from '../../aos-platform/plugins/browser/control-background-dedicated-chrome/scripts/run_task.mjs';

const execFile=promisify(execFileCb);
const root=path.dirname(new URL(import.meta.url).pathname);
const raw=path.join(root,'raw','差评分析数据_2026-09-14_2026-09-14.xlsx');
const staging=path.join(root,'raw','.download-staging');
const options={profile:'jinsha-business',port:'9232',instance:'04304cc1-7979-4f53-b14c-6008605c4c87','task-id':'negative-daily-20260914'};
const platforms=[['美团外卖','1'],['淘宝闪购','2'],['京东外卖','4']];
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const sha256=async file=>crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
async function closeDrawer(page){
 const app=page.locator('.app-wrapper');const classes=String(await app.getAttribute('class')||'');if(!classes.split(/\s+/).includes('openSidebar'))return;
 const overlay=page.locator('.drawer-bg:visible');if(await overlay.count()!==1)throw Error(`drawer-overlay-count:${await overlay.count()}`);await overlay.evaluate(el=>el.click());
 const end=Date.now()+3000;while(Date.now()<end){if(String(await app.getAttribute('class')||'').split(/\s+/).includes('hideSidebar'))return;await sleep(100);}throw Error('sidebar-close-readback-failed');
}

async function waitReady(page){
 const end=Date.now()+20000;let stable=0,last='';
 while(Date.now()<end){
  if(page.url().includes('#/login'))throw Error('jinsha-login-required');
  const totalText=(await page.locator('.el-pagination__total').first().innerText().catch(()=>''));
  const match=totalText.match(/共\s*(\d+)\s*条/);const count=await page.locator('.cryptonymText').count();
  const now=`${match?.[1]||''}:${count}`;stable=now===last?stable+1:1;last=now;
  if(match&&Number(match[1])===count&&stable>=2)return count;
  await sleep(300);
 }
 throw Error('negative-list-not-stable');
}
async function ensurePageSize(page){
 const input=page.locator('input[placeholder="请选择"]:visible');if(await input.count()!==1)throw Error(`page-size-input-count:${await input.count()}`);
 if(await input.inputValue()==='200条/页')return;
 await input.click();await sleep(300);const options=page.getByText('200条/页',{exact:true});const visible=[];
 for(let i=0;i<await options.count();i++){const item=options.nth(i);if(await item.isVisible().catch(()=>false))visible.push(item);}
 if(visible.length!==1)throw Error(`page-size-option-count:${visible.length}`);await visible[0].click();
 const end=Date.now()+5000;while(Date.now()<end){if(await input.inputValue()==='200条/页')return;await sleep(150);}throw Error('page-size-readback-failed');
}
async function choose(page,value){
 const radio=page.locator(`input[type="radio"][value="${value}"]`);
 if(await radio.count()!==1)throw Error(`platform-radio-count:${value}:${await radio.count()}`);
 await radio.evaluate(el=>el.click());await sleep(800);await ensurePageSize(page);
 if(!await radio.isChecked())throw Error(`platform-readback-failed:${value}`);
 return waitReady(page);
}
async function downloadAll(page){
 await fs.mkdir(path.dirname(raw),{recursive:true});
 try{await fs.access(raw);throw Error('raw-destination-exists');}catch(e){if(e.code!=='ENOENT')throw e;}
 await fs.rm(staging,{recursive:true,force:true});await fs.mkdir(staging,{recursive:true});
 const button=page.locator('button.download_btn:visible');if(await button.count()!==1)throw Error(`download-button-count:${await button.count()}`);
 const cdp=await page.context().newCDPSession(page);let captured=false,captureMode='playwright-save-as';
 try{
  await cdp.send('Page.setDownloadBehavior',{behavior:'allow',downloadPath:staging});
  const [download]=await Promise.all([page.waitForEvent('download',{timeout:60000}),button.click({timeout:5000})]);
  if(!/\.xlsx$/i.test(download.suggestedFilename()))throw Error('download-filename-invalid');
  try{await download.saveAs(raw);}catch{
   captureMode='task-page-staging-recovery';const end=Date.now()+60000;let stable=0,lastName='',lastSize=-1,found='';
   while(Date.now()<end){const names=(await fs.readdir(staging)).filter(x=>!x.endsWith('.crdownload'));if(names.length>1)throw Error(`download-staging-ambiguous:${names.length}`);if(names.length===1){const file=path.join(staging,names[0]),info=await fs.stat(file);if(info.size>0&&names[0]===lastName&&info.size===lastSize)stable++;else stable=1;lastName=names[0];lastSize=info.size;if(stable>=2){found=file;break;}}else{stable=0;lastName='';lastSize=-1;}await sleep(300);}if(!found)throw Error('download-staging-timeout');await fs.rename(found,raw);
  }
  const failure=await download.failure();if(failure)throw Error(`download-failed:${failure}`);captured=true;
  const info=await fs.stat(raw);if(info.size<=0)throw Error('download-empty');await execFile('/usr/bin/unzip',['-t',raw]);
  return {file:raw,size:info.size,sha256:await sha256(raw),suggestedFilename:download.suggestedFilename(),clicks:2,recovery:'first-local-capture-failed-no-artifact',captureMode};
 }finally{await cdp.detach().catch(()=>{});if(captured)await fs.rm(staging,{recursive:true,force:true});}
}
async function extract(page,platform){
 const cards=page.locator('.cryptonym');const rows=[];
 for(let i=0;i<await cards.count();i++){
  const card=cards.nth(i),store=(await card.locator('.shopName').first().innerText()).trim();
  const dimensions=(await card.locator('.pointLi').allInnerTexts()).map(x=>x.trim()).filter(Boolean);
  const score=dimensions.find(x=>/^总分\s*\d/.test(x))||'';
  const text=(await card.innerText()).trim(),date=(text.match(/20\d{2}-\d{2}-\d{2}/)||[])[0]||'';
  const comment=(await card.locator('.cryptonymText').first().innerText().catch(()=>'' )).trim();
  const status=(await card.locator('.txt').allInnerTexts()).map(x=>x.trim()).filter(Boolean).join('；');
  rows.push({store,score,date,comment,dimensions,status,platform});
 }
 return rows;
}

const started=Date.now();
const result=await withTaskPage(options,async({page,state})=>{
 await page.goto('https://data.guoshuyufen.com/#/negativeAnalyse',{waitUntil:'domcontentloaded',timeout:30000});await sleep(4000);
 await closeDrawer(page);
 const dates=page.locator('input.el-range-input');if(await dates.count()!==2)throw Error(`date-input-count:${await dates.count()}`);
 for(let i=0;i<2;i++)if(await dates.nth(i).inputValue()!=='2026-09-14')throw Error(`date-readback-mismatch:${i}`);
 await choose(page,'0');const download=await downloadAll(page);
 const rows=[];const counts={};for(const [name,value] of platforms){counts[name]=await choose(page,value);rows.push(...await extract(page,name));}
 if(rows.length!==Object.values(counts).reduce((a,b)=>a+b,0))throw Error('ui-count-sum-mismatch');
 await fs.writeFile(path.join(root,'ui-status.json'),JSON.stringify({readAt:new Date().toISOString(),date:'2026-09-14',url:page.url(),counts,rows},null,2),{mode:0o600});
 return {ok:true,date:'2026-09-14',context:state.context,counts,total:rows.length,download,elapsedMs:Date.now()-started};
});
console.log(JSON.stringify(result));
