// Original Jinsha visible roster UI only. No auth API, credentials, or business writes.
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {connectJinsha,assertAuthenticated} from '../../../posts/jinsha-post/scripts/connect.mjs';
import {acquireJinshaLease,releaseJinshaLease} from '../../../posts/jinsha-post/scripts/lease.mjs';
import {selectExistingJinshaTarget} from '../../../posts/jinsha-post/scripts/existing_owned_target.mjs';
import {waitPaginationStable,collectAllPages} from '../../../posts/jinsha-post/scripts/pagination.mjs';
import {headerIndices,parseRosterRows,validateRoster,validateObservedCounts,matchesFilterLabel} from './monthly_roster_contract.mjs';

const rowSelector='.el-table__body-wrapper:visible tbody > tr:visible';
const fields=[['是会员','请选择会员状态'],['营业中','请选择'],['授权中','请选择授权状态']];
async function filterInput(page,label,placeholder){
 const matches=[];
 for(const x of await page.locator(`input[placeholder="${placeholder}"]:visible`).all()){
  if(placeholder!=='请选择'||!/条\/页$/.test(await x.inputValue()))matches.push(x);
 }
 if(matches.length!==1)throw Error('roster-filter-input-not-unique:'+label);
 return matches[0];
}
const selectedMatches=matchesFilterLabel;
async function verifyFilters(page,platform){
 const radio=page.locator('label.el-radio-button').filter({hasText:new RegExp('^'+platform+'$')});
 if(await radio.count()!==1||!await radio.locator('input').isChecked())throw Error('roster-platform-not-confirmed');
 for(const [label,placeholder] of fields)if(!selectedMatches(await (await filterInput(page,label,placeholder)).inputValue(),label))throw Error('roster-filter-not-confirmed:'+label);
}
async function collect(page){
 const records=[],platformProof={};
 // Existing post pagination contract, narrowed only where this roster also has a status select.
 const paginationPage={locator:s=>page.locator(s==='input[placeholder="请选择"]:visible'?'.el-pagination input[placeholder="请选择"]:visible':s)};
 for(const platform of ['美团外卖','淘宝闪购']){
  const radio=page.locator('label.el-radio-button').filter({hasText:new RegExp('^'+platform+'$')});
  if(await radio.count()!==1)throw Error('roster-platform-not-unique');
  if(!await radio.locator('input').isChecked()){await radio.click();await page.waitForTimeout(700);}
  await assertAuthenticated(page);
  for(const [label,placeholder] of fields){
   const input=await filterInput(page,label,placeholder);
   if(!selectedMatches(await input.inputValue(),label)){
    await input.click();
    const options=page.locator('.el-select-dropdown__item:visible');
    let matches=[];
    for(let observation=0;observation<30;observation++){
     matches=[];for(const candidate of await options.all())if(matchesFilterLabel(await candidate.textContent(),label))matches.push(candidate);
     if(matches.length>1)throw Error('roster-filter-option-not-unique:'+label+':'+matches.length);
     if(matches.length===1)break;
     await page.waitForTimeout(100);
    }
    if(matches.length!==1)throw Error('roster-filter-option-not-ready:'+label);
    const option=matches[0];
    await option.click();await page.waitForTimeout(500);
   }
  }
  await verifyFilters(page,platform);
  const size=page.locator('.el-pagination input[placeholder="请选择"]:visible');
  if(await size.count()!==1)throw Error('roster-page-size-not-unique');
  if(await size.inputValue()!=='200条/页'){
   await size.click();let chosen=[];
   for(let observation=0;observation<30;observation++){
    chosen=[];for(const option of await page.locator('.el-select-dropdown__item:visible').all())if((await option.textContent()).trim()==='200条/页')chosen.push(option);
    if(chosen.length>1)throw Error('roster-page-size-option-not-unique');if(chosen.length===1)break;
    await page.waitForTimeout(100);
   }
   if(chosen.length!==1)throw Error('roster-page-size-200-unavailable');await chosen[0].click();
   await page.waitForTimeout(400);
  }
  if(await size.inputValue()!=='200条/页')throw Error('roster-page-size-not-confirmed');
  const current=page.locator('.el-pager li.active:visible');
  if(await current.count()===1&&(await current.innerText()).trim()!=='1'){
   const first=page.locator('.el-pager li.number:visible').filter({hasText:/^1$/});
   if(await first.count()!==1)throw Error('roster-first-page-unavailable');await first.click();
  }
  const indices=headerIndices(await page.locator('.el-table__header-wrapper:visible th').allTextContents());
  const ready=await waitPaginationStable(paginationPage,{rowSelector});
  const pages=[];
  let previousPageFingerprint='';
  const rows=await collectAllPages(paginationPage,ready,async()=>{
   await verifyFilters(page,platform);await assertAuthenticated(page);
   let raw,last='',fingerprint='',stable=0;
   for(let observation=0;observation<60;observation++){
    raw=await page.locator(rowSelector).evaluateAll((rows,indices)=>rows.map(row=>{const cells=row.querySelectorAll('td');return Object.fromEntries(Object.entries(indices).map(([key,i])=>[key,cells[i]?.innerText??'']));}),indices);
    fingerprint=crypto.createHash('sha256').update(JSON.stringify(raw)).digest('hex');
    stable=fingerprint===last?stable+1:1;last=fingerprint;
    if(fingerprint!==previousPageFingerprint&&stable>=2)break;
    await page.waitForTimeout(100);
   }
   if(fingerprint===previousPageFingerprint||stable<2)throw Error('roster-page-content-not-stable');
   previousPageFingerprint=fingerprint;
   const result=parseRosterRows(platform,raw,{allowMissingCity:true});pages.push({page:pages.length+1,count:result.length,fingerprint});return result;
  },{rowSelector});
  await verifyFilters(page,platform);
  const end=await waitPaginationStable(paginationPage,{pageNumber:ready.totalPages,rowSelector,prior:ready});
  const next=page.locator('.el-pagination .btn-next:visible');
  if(await next.count()!==1||!await next.isDisabled())throw Error('roster-last-page-not-confirmed');
  records.push(...rows);platformProof[platform]={filters:['是会员','营业中','授权中'],paginationComplete:true,total:end.expected,pages};
  console.log(JSON.stringify({stage:'platform-pagination-complete',platform,total:end.expected,pages:pages.length}));
 }
 validateObservedCounts(records,platformProof);
 const unresolved=records.filter(r=>!r.city).map(r=>({...r,reason:'source-city-empty'}));
 const keyed=new Map();for(const r of records){const key=JSON.stringify([r.platform,r.name,r.city]);keyed.set(key,(keyed.get(key)||0)+1);}
 const duplicates=[...keyed].filter(([,n])=>n>1).map(([key,count])=>({identity:JSON.parse(key),count}));
 if(!unresolved.length&&!duplicates.length)validateRoster(records,platformProof);
 return {complete:unresolved.length===0&&duplicates.length===0,countVerified:true,source:'jinsha-store-list',collectedAt:new Date().toISOString(),total:records.length,records,platformProof,unresolved,duplicates};
}

const value=k=>process.argv[process.argv.indexOf(k)+1];
async function main(){
 if(!process.argv.includes('--out')||process.argv.includes('--inspect')===process.argv.includes('--collect'))throw Error('roster-mode-arguments-required');
 const out=path.resolve(value('--out'));
 let lease,browser,page,before,finalData;
 try{
  // The Python original-post wrapper checks this lock too; fail conservatively here.
  try{const o=JSON.parse(await fs.readFile('/tmp/zhensi-jinsha-cua-exam.lock','utf8'));if(!Number.isInteger(o.pid)||o.pid<=0)throw Error('jinsha-owner-invalid');try{process.kill(o.pid,0);throw Error('jinsha-live-owner-busy');}catch(e){if(e.code!=='ESRCH')throw e;}}catch(e){if(e.code!=='ENOENT')throw e;}
  lease=await acquireJinshaLease('monthly-roster-'+crypto.randomUUID());
  const targets=await (await fetch('http://127.0.0.1:9232/json/list')).json();
  const selected=await selectExistingJinshaTarget(targets);
  browser=await connectJinsha();
  const candidates=browser.contexts().flatMap(c=>c.pages()).filter(p=>p.url()===selected.url);
  const owned=[];for(const p of candidates)if(!selected.jinshaOwnerMarker||await p.evaluate(()=>window.name)===selected.jinshaOwnerMarker)owned.push(p);
  if(owned.length!==1)throw Error('jinsha-owned-page-binding-not-unique');
  page=owned[0];before=page.url();await assertAuthenticated(page);
  const menu=page.locator('a[href="#/mtLookStore"]');
  if(await menu.count()!==1||!(await menu.innerText()).includes('店铺列表'))throw Error('jinsha-store-list-menu-not-unique');
  await menu.click();await page.waitForTimeout(1500);await assertAuthenticated(page);
  if(!page.url().endsWith('#/mtLookStore'))throw Error('jinsha-store-list-route-mismatch');
  if(process.argv.includes('--city-probe')){
   if(value('--city-probe')!=='陈氏三鲜豆皮(天门店)')throw Error('city-probe-target-not-registered');
   const radio=page.locator('label.el-radio-button').filter({hasText:/^淘宝闪购$/});
   if(await radio.count()!==1)throw Error('city-probe-platform-not-unique');
   if(!await radio.locator('input').isChecked()){await radio.click();await page.waitForTimeout(500);}
   const input=page.locator('input[placeholder="请输入：店铺名称/城市"]:visible');
   if(await input.count()!==1)throw Error('city-probe-search-not-unique');
   const target=value('--city-probe');
   const search=page.locator('.selectT').filter({has:input}).locator('.points').filter({hasText:/^搜索$/});
   if(await search.count()!==1)throw Error('city-probe-search-button-not-unique');
   await input.fill(target);await search.click();await page.waitForTimeout(800);
   const rows=page.locator(rowSelector);
   if(await rows.count()!==1)throw Error('city-probe-target-row-not-unique');
   const headers=await page.locator('.el-table__header-wrapper:visible th').allTextContents();
   const indices=headerIndices(headers);const ids=headers.flatMap((s,i)=>s.trim()==='店铺id'?[i]:[]);
   if(ids.length!==1)throw Error('city-probe-id-header-not-unique');
   const record=await rows.locator('td').evaluateAll((cells,indices)=>Object.fromEntries(Object.entries(indices).map(([k,i])=>[k,cells[i]?.innerText.trim()])),{...indices,shopId:ids[0]});
   if(record.name!==target||!/^[0-9]+$/.test(record.shopId)||record.authorization!=='授权中')throw Error('city-probe-identity-not-confirmed');
   const entry=rows.getByRole('button',{name:'进入店铺',exact:true});
   if(await entry.count()!==1)throw Error('city-probe-entry-not-unique');
   let popup;
   try{
    const pending=page.waitForEvent('popup',{timeout:4000}).catch(()=>null);await entry.click();popup=await pending;
    const detail=popup||page;await detail.waitForLoadState('domcontentloaded');await detail.waitForTimeout(1000);
    if(new URL(detail.url()).origin!=='https://data.guoshuyufen.com')throw Error('city-probe-detail-outside-jinsha');
    await assertAuthenticated(detail);
    finalData={ok:true,mode:'inspect-city-detail',target,record,observedAt:new Date().toISOString(),detailPath:new URL(detail.url()).hash.split('?')[0],
     detailText:(await detail.locator('body').innerText()).slice(0,7000)};
   }finally{if(popup&&!popup.isClosed())await popup.close();}
  }
  else if(process.argv.includes('--collect'))finalData=await collect(page);
  else {
  const filterOptions=[];
  for(const expected of ['营业状态','授权状态','会员状态']){
   const matches=[];for(const input of await page.locator('input.el-input__inner:visible').all())if(await input.inputValue()===expected)matches.push(input);
   if(matches.length!==1)throw Error('roster-filter-not-unique:'+expected);
   await matches[0].click();await page.waitForTimeout(150);
   filterOptions.push({field:expected,options:await page.locator('.el-select-dropdown:visible .el-select-dropdown__item').allTextContents()});
   await matches[0].press('Escape');
  }
  const observed=await page.evaluate(()=>({
   body:document.body.innerText.split('店铺名字')[0].slice(0,2000),
   inputs:[...document.querySelectorAll('input,select')].map(e=>({tag:e.tagName,type:e.type,value:e.value,placeholder:e.getAttribute('placeholder'),className:e.className,controls:e.getAttribute('aria-controls'),describedby:e.getAttribute('aria-describedby'),selectMarkup:e.closest('.el-select')?.outerHTML.slice(0,1800)})),
   headers:[...document.querySelectorAll('th')].map(e=>e.innerText),
   buttons:[...new Set([...document.querySelectorAll('button')].filter(e=>e.getBoundingClientRect().height>0).map(e=>e.innerText))],
   tables:[...document.querySelectorAll('table')].map(e=>({rows:e.rows.length})),
   radios:[...document.querySelectorAll('label.el-radio-button')].map(e=>({text:e.innerText,checked:e.querySelector('input')?.checked})),
   pagination:[...document.querySelectorAll('.el-pagination')].map(e=>e.innerText)
  }));
  observed.filterOptions=filterOptions;
  finalData={ok:true,mode:'inspect',source:'jinsha-store-list',observedAt:new Date().toISOString(),observed};
  }
 }finally{
  try{if(page&&before&&page.url()!==before){await page.goto(before,{waitUntil:'domcontentloaded',timeout:20000});await assertAuthenticated(page);}}finally{if(browser)await browser.close();if(lease)await releaseJinshaLease(lease);}
 }
 const destination=finalData.complete===false?out+'.incomplete.json':out;
 await fs.mkdir(path.dirname(destination),{recursive:true});const tmp=destination+'.'+process.pid+'.tmp';await fs.writeFile(tmp,JSON.stringify(finalData,null,2),{mode:0o600});await fs.rename(tmp,destination);
 console.log(JSON.stringify({ok:finalData.complete!==false,mode:process.argv.includes('--collect')?'collect':'inspect',out:destination,total:finalData.total,unresolved:finalData.unresolved?.length,duplicates:finalData.duplicates?.length,platformTotals:finalData.platformProof&&Object.fromEntries(Object.entries(finalData.platformProof).map(([k,v])=>[k,v.total]))}));
 if(finalData.complete===false)process.exitCode=2;
}
main().catch(e=>{console.error(JSON.stringify({ok:false,reason:e.message}));process.exitCode=1;});
