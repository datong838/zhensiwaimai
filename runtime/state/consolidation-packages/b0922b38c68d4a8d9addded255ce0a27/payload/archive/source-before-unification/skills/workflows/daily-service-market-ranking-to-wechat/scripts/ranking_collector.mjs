import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';
const HOME='https://open.shop.ele.me/manager/base/home';
const POST=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../../posts/taobao-svc-post');
export const REQUIRED=['经营任务完成率','新店养活率','新店养好率','本月新签商家数','服务中商家数','正增长商户占比','老店日均收入增幅','服务满意度'];
export const compact=value=>String(value??'').replace(/\s+/g,'');
export function validAmount(value){return /^-?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?%?$/.test(value)||/^\d+\/[1-9]\d*$/.test(value);}
export function validateSnapshot(value){
 const match=compact(value.title).match(/^(.+?)排名(\d+)\/(\d+)$/);
 if(!match||Number(match[2])<1||Number(match[2])>Number(match[3]))throw Error('service-ranking-invalid');
 if(!/\d{4}-\d{2}-\d{2}更新/.test(compact(value.update))||!value.heading?.includes('本月考核指标'))throw Error('service-ranking-period-missing');
 if(!Array.isArray(value.metrics)||value.metrics.length<REQUIRED.length||value.metrics.length>40)throw Error('service-metric-count-invalid');
 const names=value.metrics.map(m=>compact(m.name));
 if(new Set(names).size!==names.length||REQUIRED.some(name=>!names.includes(name)))throw Error('service-metric-missing-or-duplicate');
 for(const metric of value.metrics){
  if(!compact(metric.name)||!validAmount(compact(metric.current))||(metric.required&&!validAmount(compact(metric.required)))||(metric.yesterday&&!validAmount(compact(metric.yesterday))))throw Error('service-metric-value-invalid');
  if(REQUIRED.includes(compact(metric.name))&&!metric.required)throw Error('service-metric-requirement-missing');
  const percent=['经营任务完成率','新店养活率','新店养好率','正增长商户占比','老店日均收入增幅'].includes(compact(metric.name));
  if(percent&&(!compact(metric.current).endsWith('%')||!compact(metric.required).endsWith('%')||(metric.yesterday&&!compact(metric.yesterday).endsWith('%'))))throw Error('service-metric-unit-invalid');
  if(['本月新签商家数','服务中商家数'].includes(compact(metric.name))&&[metric.current,metric.required,metric.yesterday].filter(Boolean).some(v=>!/^\d[\d,]*$/.test(compact(v))))throw Error('service-count-unit-invalid');
 }
 return {...value,grade:match[1],rank:Number(match[2]),rankTotal:Number(match[3])};
}
export function panelSnapshot(element){
 const text=(e,selector)=>e.querySelector(selector)?.textContent?.trim()||'';
 return {title:text(element,'[class*="AgencyGrade--title--"]'),update:text(element,'[class*="AgencyGrade--updateTime--"]'),heading:text(element,'[class*="AgencyGrade--listTitle--"]'),metrics:[...element.querySelectorAll('li[class*="AgencyGrade--item--"]')].map(e=>({name:text(e,'[class*="AgencyGrade--itemTitle--"] [class*="AgencyGrade--name--"]'),current:text(e,'[class*="AgencyGrade--itemRate--"]').replace(/\s+/g,''),required:text(e,'[class*="AgencyGrade--itemDesc--"] span'),yesterday:text(e,'[class*="AgencyGrade--compareRate--"] span:last-child').replace(/^昨日$/,''),achieved:!!e.querySelector('[class*="AgencyGrade--success--"]')}))};
}
async function postIntegrity(){const manifest=JSON.parse(await fs.readFile(path.join(POST,'dependencies.json'),'utf8'));for(const [name,hash] of Object.entries(manifest.files)){if(crypto.createHash('sha256').update(await fs.readFile(path.join(POST,name))).digest('hex')!==hash)throw Error('service-post-dependency-drift:'+name);}}
export async function collect(output){
 await postIntegrity();
 const targets=await(await fetch('http://127.0.0.1:9231/json/list')).json();
 const eligible=targets.filter(p=>p.type==='page'&&p.url.startsWith('https://open.shop.ele.me/manager/'));
 if(eligible.length!==1)throw Error('service-existing-page-not-unique');
 const {acquirePostLease,releasePostLease}=await import(path.join(POST,'scripts/lease.mjs'));
 const {assertAuthenticated,assertOrigin}=await import(path.join(POST,'scripts/auth.mjs'));
 const lease=await acquirePostLease('service-ranking-'+crypto.randomUUID());if(!lease)throw Error('service-post-busy');
 let browser,page,originalUrl,viewport,scroll,receipt;
 try{
  ({browser,page}=await(await import(path.join(POST,'scripts/connect.mjs'))).connectToPost());
  const pages=browser.contexts()[0].pages().filter(p=>p.url().startsWith('https://open.shop.ele.me/manager/'));
  if(pages.length!==1||pages[0]!==page||page.url()!==eligible[0].url)throw Error('service-existing-page-binding-changed');
  originalUrl=page.url();viewport=page.viewportSize();scroll=await page.evaluate(()=>({x:scrollX,y:scrollY}));assertOrigin(originalUrl);assertAuthenticated(await page.locator('body').innerText());
  await page.setViewportSize({width:2200,height:1600});
  if(page.url()!==HOME)await page.goto(HOME,{waitUntil:'domcontentloaded',timeout:30000});
  const panel=page.locator('.sycm-common-agency-grade-wrapper');await panel.waitFor({state:'visible',timeout:20000});if(await panel.count()!==1)throw Error('service-ranking-panel-not-unique');
  assertOrigin(page.url());assertAuthenticated(await page.locator('body').innerText());
  if(page.url()!==HOME||!(await page.locator('body').innerText()).includes('外卖店代运营首页'))throw Error('service-home-identity-invalid');
  let snapshot,previous='',stable=false;
  for(let i=0;i<12;i++){
   snapshot=validateSnapshot(await panel.evaluate(panelSnapshot));const signature=JSON.stringify(snapshot);
   if(signature===previous){stable=true;break;}previous=signature;await page.waitForTimeout(350);
  }
  if(!stable)throw Error('service-metrics-not-stable');
  await fs.mkdir(output,{recursive:true,mode:0o700});const file=path.join(output,'服务市场排名与考核指标.png');
  await panel.screenshot({path:file,timeout:15000,animations:'disabled'});
  if(JSON.stringify(validateSnapshot(await panel.evaluate(panelSnapshot)))!==JSON.stringify(snapshot))throw Error('service-metrics-changed-during-capture');
  const data=await fs.readFile(file);if(data.toString('hex',0,8)!=='89504e470d0a1a0a')throw Error('service-capture-invalid');
  const account=await page.locator('.ant-select-selection-item').allTextContents();
  receipt={ok:true,sourceUrl:HOME,browserPort:9231,collectedAt:new Date().toISOString(),...snapshot,accountLabels:account,file,sha256:crypto.createHash('sha256').update(data).digest('hex'),width:data.readUInt32BE(16),height:data.readUInt32BE(20),runtimeModelDecisions:0,sendAttempts:0};
  if(receipt.width<250||receipt.height<400)throw Error('service-capture-incomplete');
 }finally{
  try{if(page&&originalUrl){if(page.url()!==originalUrl)await page.goto(originalUrl,{waitUntil:'domcontentloaded',timeout:30000});if(viewport)await page.setViewportSize(viewport);if(scroll)await page.evaluate(v=>window.scrollTo(v.x,v.y),scroll);}}finally{if(browser)await browser.close();await releasePostLease(lease);}
 }
 await fs.writeFile(path.join(output,'collection.json'),JSON.stringify(receipt,null,2),{mode:0o600});return receipt;
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{if(process.argv.length!==4||process.argv[2]!=='--output')throw Error('usage: --output DIRECTORY');console.log(JSON.stringify(await collect(path.resolve(process.argv[3]))));}catch(error){console.log(JSON.stringify({ok:false,reason:String(error.message||error),sendAttempts:0}));process.exitCode=1;}
}
