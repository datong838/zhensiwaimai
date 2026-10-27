import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {execFile as execFileCb} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import {yesterdayInShanghai, isNonIncreasing, isFirstPageTenRows, obstructionCloseId} from './desktop_executor.mjs';
const execFile = promisify(execFileCb);
const dir = path.dirname(fileURLToPath(import.meta.url));
const merchant = 'melody.shop.ele.me/app/chain/95708808/';
const target = merchant+'store-analysis';
export const isMerchantWindow = text => text.split('\n').slice(0,3).some(x=>x.includes(merchant));
export const isStoreWindow = text => text.split('\n').slice(0,3).some(x=>x.includes(target));
export function freshRealtimePage(text) {
  const frames=text.split('\n').filter(x=>/HTML 内容 melody-stats-new, URL: .*\/storeAnalysisDetail\?/.test(x));
  return isStoreWindow(text) && frames.length===1 && /[?&]dateType=realTime(?:&|$)/.test(frames[0])
    && /单选按钮 今日实时, Value: 1/.test(text) && /单选按钮 昨日, Value: 0/.test(text);
}
export function navigationLink(text) {const candidates=text.split('\n').filter(x=>/链接 门店分析$/.test(x));return candidates.length===1 ? Number(candidates[0].match(/^\s*(\d+)/)[1]) : null;}
const id = line => Number(line?.match(/^\s*(\d+)/)?.[1]);
const line = (text, pattern) => text.split('\n').find(x => pattern.test(x));
export function parseRows(text) {
  const blocks = text.split(/\n(?=\s*\d+ row\b)/);
  const head = blocks.find(x => /列标题/.test(x) && /文本 营业额(?:\n|$)/.test(x));
  if (!head) return [];
  const headers = head.split(/\n(?=\s*\d+ 列标题)/).slice(1);
  const revenueIndex = headers.findIndex(x => /营业额/.test(x));
  const revenueCol = revenueIndex + (headers.some(x=>/门店名称|店铺名称/.test(x)) ? 0 : 1);
  if (revenueIndex < 0) return [];
  return blocks.filter(x => /链接 门店详情/.test(x)).map(block => {
    const cells = block.split(/\n(?=\s*\d+ 单元格)/).slice(1);
    const values = cells.map(cell => cell.split('\n').filter(x => /\d+ (?:文本|text) /.test(x)).map(x => x.replace(/^.*?\d+ (?:文本|text) /, '')).join(' '));
    const money = values[revenueCol]?.match(/^([\d,]+\.\d{2})(?:\s|$)/);
    return {store:values[0], revenue:money ? Number(money[1].replaceAll(',','')) : NaN};
  });
}
export async function runDesktopCua({app, outputRoot='/tmp/zhensi_top10', runId=crypto.randomUUID()}) {
  const outputDir=path.join(outputRoot,runId);
  await fs.mkdir(outputDir,{recursive:true,mode:0o700});
  const receiptFile=path.join(outputDir,'desktop_receipt.json');
  const receipt={ok:false,executor:'desktop',runId,stageMs:{},stageResults:{},trace:[],retryCount:0,receiptFile};
  let started=0, deadline=0, state='', requireStore=false;
  const check=()=>{if(deadline && Date.now()>=deadline) throw Error('total-deadline-exceeded');};
  const read=async()=>{check();state=await app.getAXState({emit:false,disableDiffing:true});
    if (!app.ensureFullscreen && /Window: "淘宝闪购商(?:家)?版"/.test(state) && /^0 菜单 Secondary Actions: Cancel/m.test(state) && /经营分析/.test(state)) {
      if(receipt.menuNormalization)throw Error('navigation-menu-reappeared');
      receipt.menuNormalization=1;
      await app.pressKey('Escape');
      state=await app.getAXState({emit:false,disableDiffing:true});
    }
    receipt.trace.push({event:'read',stage:receipt.stage,url:state.split('\n').slice(0,3).join(' ').match(/URL: ([^ ,]+)/)?.[1]??null,yesterday:/单选按钮 昨日/.test(state)});check();return state;};
  const onTarget=()=>{if(!(requireStore?isStoreWindow(state):isMerchantWindow(state)))throw Error('target-window-changed');};
  const foreground=async()=>{if(app.foreground)return app.foreground();const {stdout}=await execFile('/usr/bin/osascript',['-e','tell application "System Events" to get bundle identifier of first application process whose frontmost is true'],{timeout:3000});if(stdout.trim()!=='com.google.Chrome')throw Error('chrome-not-frontmost');};
  const click=async index=>{check();await foreground();if(!Number.isFinite(index))throw Error('element-missing');receipt.trace.push({event:'click',index,label:state.split('\n').find(x=>new RegExp('^\\s*'+index+' ').test(x))?.trim()});await app.click(index);await read();};
  const key=async value=>{receipt.lastAction='key:'+value;check();onTarget();await foreground();await app.pressKey(value);await read();onTarget();};
  const until=async(predicate,ms=5000)=>{const end=Date.now()+ms;do{await read();if(predicate(state))return;}while(Date.now()<end);throw Error('state-postcondition-timeout');};
  const stage=async(name,fn)=>{receipt.stage=name;const t=performance.now();try{await fn();receipt.stageResults[name]='PASS';}catch(e){receipt.stageResults[name]='FAIL';throw e;}finally{receipt.stageMs[name]=Math.round(performance.now()-t);}};
  const ocr=async file=>{check();const {stdout}=await execFile(path.join(dir,'ocr_vision'),[file,'zh-Hans'],{timeout:Math.max(1,Math.min(15000,deadline-Date.now())),maxBuffer:4e6});return stdout.split('\n').flatMap(record=>{const [box,confidence,text]=record.split('\t');if(!text)return [];const [x,y,w,h]=box.split(',').map(Number);return [{x,y,w,h,text,confidence:Number(confidence)}];});};
  const dimensions=async file=>{const {stdout}=await execFile('/usr/bin/sips',['-g','pixelWidth','-g','pixelHeight',file]);return {width:Number(stdout.match(/pixelWidth:\s*(\d+)/)?.[1]),height:Number(stdout.match(/pixelHeight:\s*(\d+)/)?.[1])};};
  try {
    if(app.activate)await app.activate();
    else await execFile('/usr/bin/osascript',['-e','tell application "Google Chrome" to activate'],{timeout:3000});
    const focusEnd=Date.now()+2000;
    while(true){try{await foreground();break;}catch(e){if(Date.now()>=focusEnd)throw e;await new Promise(r=>setTimeout(r,50));}}
    await read(); onTarget();
    started=Date.now();deadline=started+180000;
    Object.assign(receipt,{startedAt:started,deadlineAt:deadline,dataDate:yesterdayInShanghai()});
    await stage('focus_fullscreen',async()=>{
      if(app.ensureFullscreen){await app.ensureFullscreen();await read();onTarget();return;}
      const view=id(line(state,/^\s*\d+ 显示$/));
      if(Number.isFinite(view)) {
        await click(view);
        const enter=id(line(state,/^\s*\d+ 进入全屏幕(?:,|$)/));
        if(Number.isFinite(enter)) {
          await click(enter);
          await until(isMerchantWindow);
        } else {
          if(!/^\s*\d+ 退出全屏幕(?:,|$)/m.test(state))throw Error('fullscreen-menu-unknown');
          const cancel=line(state,/Secondary Actions:.*Cancel/);
          if(!cancel)throw Error('menu-cancel-not-exposed');
          await app.performSecondaryAction(id(cancel),'Cancel');await read();
        }
      }
      onTarget();
    });
    await stage('navigate_store_analysis',async()=>{
      if(!isStoreWindow(state)) {
        if(navigationLink(state)==null){
          const menus=state.split('\n').filter(x=>/^\s*\d+ 菜单项 数据中心$/.test(x));
          if(menus.length!==1)throw Error('unique-data-center-menu-missing');
          if(app.hover){
            await foreground();await app.hover(id(menus[0]));
            await new Promise(r=>setTimeout(r,250));
            if(app.visualClickText){await app.visualClickText('门店分析');await read();}
            else {await read();try{await until(s=>isMerchantWindow(s)&&navigationLink(s)!=null,900);}catch{await click(id(menus[0]));}}
          }else await click(id(menus[0]));
          if(!isStoreWindow(state)&&navigationLink(state)==null)await until(s=>isStoreWindow(s)||navigationLink(s)!=null,2500);
        }
        const link=navigationLink(state);
        if(!isStoreWindow(state)){
          if(link==null)throw Error('unique-store-analysis-link-missing');
          await click(link);
        }
        await until(isStoreWindow,8000);
        if(/[?&]dateType=realTime(?:&|$)/.test(state.split('\n')[0]))await until(freshRealtimePage,5000);
      }
      requireStore=true;onTarget();
    });
    await stage('select_yesterday',async()=>{
      await until(s=>isStoreWindow(s)&&/单选按钮 昨日,/.test(s),5000);
      if(!/单选按钮 昨日, Value: 1/.test(state))await click(id(line(state,/单选按钮 昨日,/)));
      await until(s=>/单选按钮 昨日, Value: 1/.test(s)&&s.includes('已选时间：'+receipt.dataDate.slice(5)));onTarget();
    });
    let rows;
    await stage('verify_sort',async()=>{
      await until(s=>{rows=parseRows(s);return rows.length===10&&rows.every(x=>Number.isFinite(x.revenue)&&x.store);},12000);
      if(!isNonIncreasing(rows.map(x=>x.revenue))) {
        const headerBlock=state.split(/\n(?=\s*\d+ 列标题)/).find(x=>/^\s*\d+ 列标题/.test(x)&&/文本 营业额(?:\n|$)/.test(x));
        await click(id(headerBlock));receipt.retryCount++;
        await until(s=>{rows=parseRows(s);return rows.length===10&&rows.every(x=>Number.isFinite(x.revenue))&&isNonIncreasing(rows.map(x=>x.revenue));},6000);
      }
      if(!isFirstPageTenRows(state))throw Error('page-one-ten-rows-required');
    });
    await stage('layout',async()=>{
      await click(id(line(state,/文本 门店列表$/)));
      await key('super+0');
      for(let i=0;i<4;i++)await key('super+minus');
      const inner=id(line(state,/HTML 内容 melody-stats-new/));
      if(!Number.isFinite(inner))throw Error('table-scroll-container-missing');
      await app.scroll(inner,'down',5);await read();onTarget();
      const fresh=id(line(state,/HTML 内容 melody-stats-new/));
      await app.scroll(fresh,'up',0.08);await read();onTarget();
      const current=parseRows(state);
      if(!/单选按钮 昨日, Value: 1/.test(state)||!isFirstPageTenRows(state)||current.length!==10||JSON.stringify(current)!==JSON.stringify(rows))throw Error('layout-contract-changed');
    });
    await stage('clear_obstruction',async()=>{await read();onTarget();let close=obstructionCloseId(state);if(close===null){const lines=state.split('\n'),im=lines.findIndex(l=>/图片 IM$/.test(l));if(im>=0){const matches=lines.slice(im,im+12).filter(l=>/图像 close$/.test(l));if(matches.length===1)close=id(matches[0]);}}if(close!==null)await click(close);});
    await stage('capture_self_check',async()=>{
      const raw=path.join(outputDir,'raw.png');
      await read();onTarget();
      await foreground();
      if(app.captureOriginal)await app.captureOriginal(raw);
      else await execFile('/usr/sbin/screencapture',['-x',raw],{timeout:10000});
      await fs.chmod(raw,0o600);
      await read();onTarget();
      const size=await dimensions(raw);
      let crop;
      if(app.getCropGeometry)crop=await app.getCropGeometry();
      else {
        const entries=await ocr(raw);
        const header=entries.filter(x=>/^(门店名称|店铺名称)$/.test(x.text.replaceAll(' ','')));
        const pagers=entries.filter(x=>x.text.replaceAll(' ','').includes('跳至'));
        if(header.length!==1||pagers.length!==1)throw Error('crop-anchors-missing');
        const h=header[0],p=pagers[0];
        const x=Math.max(0,Math.floor(h.x-h.w/2-24)), y=Math.max(0,Math.floor(h.y-h.h/2-22));
        crop={x,y,width:size.width-x-24,height:Math.ceil(p.y+p.h/2+25-y)};
      }
      const {x,y,width,height}=crop;
      if(width<1500||height<400||height+y>size.height)throw Error('crop-geometry-invalid');
      const file=path.join(outputDir,`${receipt.dataDate}_top10seller.png`);
      await execFile('/usr/bin/sips',['-c',String(height),String(width),'--cropOffset',String(y),String(x),raw,'--out',file]);
      const out=await ocr(file), texts=out.map(x=>x.text.replaceAll(' ','')).join('\n');
      if(/顾客|手机号|已下\d*单|补充备注|催单|投诉|发票申请/.test(texts))throw Error('privacy-ocr-hit');
      for(const token of ['营业额','有效订单','商圈收入排名','跳至'])if(!texts.includes(token))throw Error('crop-field-missing:'+token);
      if(!out.some(e=>e.y>height-80&&e.text.replaceAll(' ','').includes('10条/页')))throw Error('crop-page-size-missing');
      if(!/门店名称|店铺名称/.test(texts))throw Error('crop-header-missing');
      // Check every store name is represented in the original-pixel crop, not just in AX.
      const normalize=x=>x.replace(/新店|[\s·•（）()，,。.\-]/g,'');
      const joined=normalize(texts);
      for(const row of rows)if(!joined.includes(normalize(row.store).slice(0,5)))throw Error('crop-store-missing:'+row.store.slice(0,5));
      Object.assign(receipt,{file,...await dimensions(file),sha256:crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex'),stores:rows.map(x=>x.store),revenues:rows.map(x=>x.revenue),page:1,pageSize:10,layout:'table-and-pagination',crop:{x,y,width,height}});
      await fs.unlink(raw);
    });
    check();receipt.ok=true;
  } catch(error) {receipt.reason=error.message;}
  receipt.elapsedMs=started?Date.now()-started:0;
  await fs.writeFile(receiptFile,JSON.stringify(receipt,null,2),{mode:0o600});
  return receipt;
}
