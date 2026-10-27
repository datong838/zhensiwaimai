import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFile as cb} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import {yesterdayInShanghai} from './desktop_executor.mjs';
const exec=promisify(cb), dir=path.dirname(fileURLToPath(import.meta.url));
const compact=t=>t.replaceAll(' ','');
export async function runVisualDesktop({app}) {
 const runId=crypto.randomUUID(), folder=path.join('/tmp/zhensi_top10',runId);
 await fs.mkdir(folder,{recursive:true,mode:0o700});
 const receipt={ok:false,executor:'desktop',runId,stageMs:{},stageResults:{},receiptFile:path.join(folder,'desktop_receipt.json'),dataDate:yesterdayInShanghai()};
 const started=Date.now(), deadline=started+180000;Object.assign(receipt,{startedAt:started,deadlineAt:deadline});
 let current,entries=[], ax='', count=0;
 const check=()=>{if(Date.now()>=deadline)throw Error('deadline-exceeded');};
 const timed=async(name,fn)=>{receipt.stage=name;const t=performance.now();try{await fn();receipt.stageResults[name]='PASS';}catch(e){receipt.stageResults[name]='FAIL';throw e;}finally{receipt.stageMs[name]=Math.round(performance.now()-t);}};
 const ocr=async file=>{const {stdout}=await exec(path.join(dir,'ocr_vision'),[file,'zh-Hans'],{timeout:15000});return stdout.split('\n').flatMap(r=>{const [box,confidence,text]=r.split('\t');if(!text)return [];const [x,y,w,h]=box.split(',').map(Number);return [{x,y,w,h,text,confidence:Number(confidence)}];});};
 const snap=async()=>{check();ax=await app.getAXState({emit:false,disableDiffing:true}); current=path.join(folder,'frame-'+(++count)+'.png');await exec('/usr/sbin/screencapture',['-x',current],{timeout:5000});entries=await ocr(current);check();return entries;};
 const site=()=>{if(!entries.some(e=>e.y<250&&compact(e.text).includes('melody.shop.ele.me/app/chain/95708808/')))throw Error('visual-target-url-missing');};
 const choose=(text,predicate=()=>true)=>{const matches=entries.filter(e=>compact(e.text)===text&&predicate(e));if(matches.length!==1)throw Error('visual-target-not-unique:'+text+':'+matches.length);return matches[0];};
 const click=async e=>{check();await app.click([Math.round(e.x/2),Math.round(e.y/2)]);await snap();site();};
 const key=async k=>{check();await app.pressKey(k);ax=await app.getAXState({emit:false,disableDiffing:true});};
 try{
 await timed('visual_preflight',async()=>{await snap();site();const {stdout}=await exec('/usr/bin/sips',['-g','pixelWidth','-g','pixelHeight',current]);if(!/pixelWidth: 2336/.test(stdout)||!/pixelHeight: 1510/.test(stdout))throw Error('uncalibrated-display-geometry');
const {stdout:full}=await exec('/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python',['-c',"from PIL import Image; import sys; im=Image.open(sys.argv[1]).convert('RGB'); print(max(v[1] for v in im.crop((0,0,im.width,46)).getextrema()))",current]);if(full.trim()!=='0')throw Error('fullscreen-menubar-not-hidden');receipt.fullscreenEvidence='native-resolution-and-hidden-menubar';});
 await timed('select_yesterday',async()=>{
   if(!entries.some(e=>e.y<250&&e.text.includes('store-analysis')))throw Error('store-analysis-required');
   const expected=receipt.dataDate.slice(5);
   if(!entries.some(e=>compact(e.text).includes('已选时间：'+expected))){await click(choose('昨日',e=>e.x>400));}
   if(!entries.some(e=>compact(e.text).includes('已选时间：'+expected))) {await snap();site();}
   if(!entries.some(e=>compact(e.text).includes('已选时间：'+expected)))throw Error('yesterday-date-not-verified');
 });
 await timed('layout',async()=>{
   await key('super+0');for(let i=0;i<4;i++)await key('super+minus');
   await key('End');await key('Up');await snap();site();
 });
 await timed('clear_obstruction',async()=>{
   const messages=entries.filter(e=>/已下\d+单|顾客|补充备注|开票申请/.test(e.text));
   if(messages.length){const anchor=messages.find(e=>/已下\d+单/.test(e.text));if(!anchor)throw Error('unrecognized-private-overlay');
     const crosses=entries.filter(e=>/^[×xX]$/.test(e.text)&&e.x>anchor.x&&Math.abs(e.y-anchor.y)<50);
     if(crosses.length!==1)throw Error('overlay-close-not-unique');await click(crosses[0]);
   }
 });
 await timed('verify_table_and_crop',async()=>{
   const header=choose('门店名称',e=>e.x>350), revenue=choose('营业额',e=>e.y>header.y-10&&e.y<header.y+100);
   const pager=entries.filter(e=>compact(e.text).includes('跳至')&&e.y>header.y);if(pager.length!==1)throw Error('pager-missing');
   const bottom=pager[0].y;
   const amounts=entries.filter(e=>Math.abs(e.x-revenue.x)<90&&e.y>revenue.y+25&&e.y<bottom-40&&/^[\d,]+\.\d{2}$/.test(e.text));
   amounts.sort((a,b)=>a.y-b.y);if(amounts.length!==10)throw Error('visual-revenue-count:'+amounts.length);
   const values=amounts.map(e=>Number(e.text.replaceAll(',','')));if(values.some((v,i)=>i&&v>values[i-1]))throw Error('visual-sort-not-descending');
   const names=amounts.map((a,i)=>entries.filter(e=>e.x>header.x-100&&e.x<revenue.x-180&&e.y>a.y-25&&e.y<(amounts[i+1]?.y??bottom)-35&&!/^第|^[\d,./]+$|名\s*\//.test(e.text)).map(e=>e.text).join(' '));
   if(names.some(n=>!n))throw Error('visual-store-name-missing');
   if(!entries.some(e=>/有效订单/.test(e.text)&&e.y<revenue.y+50&&e.y>header.y-10))throw Error('orders-header-missing');
   const x=Math.floor(header.x-header.w/2-22),y=Math.floor(header.y-header.h/2-25),w=2336-x-170,h=Math.ceil(bottom+30-y);
   if(w<1500||h<600||y<0||y+h>1510)throw Error('crop-geometry');
   const file=path.join(folder,receipt.dataDate+'_top10seller.png');await exec('/usr/bin/sips',['-c',String(h),String(w),'--cropOffset',String(y),String(x),current,'--out',file]);
   const text=(await ocr(file)).map(e=>e.text).join('\n');if(/顾客|手机号|已下\d*单|补充备注|催单|投诉|开票申请|\*\*\s*[（(]\d{4}/.test(text))throw Error('private-content-in-crop');
   for(const t of ['门店名称','营业额','有效订单','跳至'])if(!compact(text).includes(t))throw Error('crop-required-missing:'+t);
   Object.assign(receipt,{file,width:w,height:h,sha256:crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex'),stores:names,revenues:values,page:1,pageSize:10,layout:'visual-table-and-pagination'});
 });
 check();receipt.ok=true;
 }catch(e){receipt.reason=e.message;receipt.lastFrame=current;}
 receipt.elapsedMs=Date.now()-started;await fs.writeFile(receipt.receiptFile,JSON.stringify(receipt,null,2),{mode:0o600});return receipt;
}
