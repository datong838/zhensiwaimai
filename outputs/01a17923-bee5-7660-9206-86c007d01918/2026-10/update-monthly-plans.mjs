import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {SpreadsheetFile,FileBlob} from '@oai/artifact-tool';
const ROOT='/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
const OUT=import.meta.dirname;
const read=async p=>JSON.parse(await fs.readFile(p,'utf8'));
const scope=await read(`${ROOT}/skills/workflows/store-inspection/.runtime/monthly/2026-10/monthly-scope.json`);
if(!scope.reportOnly||scope.executionEnabled!==false)throw Error('inspection-scope-not-report-only');
if(crypto.createHash('sha256').update(await fs.readFile(scope.source)).digest('hex')!==scope.sourceSha256)throw Error('inspection-source-drift');
const key=r=>[r.platform,r.name,r.city].join('\x1f');
const matched=new Set(scope.mappings.flatMap(m=>m.matched).map(key));
const candidates=new Set(scope.mappings.flatMap(m=>m.candidates).map(key));
const flows=[['daily-store-metrics-rotation-to-wechat','商家经营指标互动',753],['coupon-issue-task-flow','发优惠券',753],['store-inspection','巡店',1096]];
const logs=[];
for(const [flow,title,count] of flows){
 const file=path.join(OUT,`${title}-2026-10全量商家与月工作登记.xlsx`);
 const book=await SpreadsheetFile.importXlsx(await FileBlob.load(file));
 const roster=book.worksheets.getItem('商家与月登记'),calendar=book.worksheets.getItem('每日挂历');
 const baseline=roster.getRange(`A7:H${count+6}`).values;
 const formulas=roster.getRange('A3:H3').formulas;
 const inspection=flow==='store-inspection';let registry,daily,planned;
 if(!inspection){
  const base=`${ROOT}/skills/workflows/${flow}/.runtime/monthly/2026-10`;
  const pointer=await read(`${base}/latest.json`);const raw=await fs.readFile(`${base}/${pointer.generation}/registry.json`);
  if(crypto.createHash('sha256').update(raw).digest('hex')!==pointer.registrySha256)throw Error('registry-hash-mismatch');
  registry=JSON.parse(raw);daily=await read(`${base}/${pointer.generation}/daily-plan.json`);
  if(registry.executionEnabled!==false||registry.plan.merchantKeys.length!==23)throw Error('plan-scope-mismatch');
  planned=new Set(registry.plan.merchantKeys.map(k=>String(registry.merchants[k].record.shopId)));
 }
 const values=baseline.map(r=>{
  if(!inspection)return [planned.has(String(r[2]))?'纳入本月':'未纳入本月'];
  const k=key({platform:r[1],name:r[3],city:r[4]});
  return [matched.has(k)?'纳入本月':candidates.has(k)?'本月候选待核':'未纳入本月'];
 });
 const planCount=values.filter(r=>r[0]==='纳入本月').length;
 if(planCount!==(inspection?24:23))throw Error('planned-row-count-mismatch');
 roster.getRange(`F7:F${count+6}`).values=values;
 roster.getRange('E3').values=[[planCount]];
 if(inspection)roster.getRange('D3').values=[['本月平台记录']];
 roster.getRange('A5').values=[[inspection?'本月范围23家。已对应22家、24条平台记录；15条名称变体候选待核，玉翠店未找到。暂停执行。':'本月首批23家已登记，其他全量商家保留。暂停执行。']];
 calendar.getRange('A3').values=[[inspection?'按平台分别计量；当前24条已对应记录为本地草案，候选未排入。':'首批23家本地计划草案；启用时按剩余日期重排，当前暂停执行。']];
 const days=new Map((daily?.days||[]).map(d=>[d.date,d.taskKeys]));
 const cal=Array.from({length:31},(_,i)=>{
  const day=`2026-10-${String(i+1).padStart(2,'0')}`;
  let tasks=days.get(day)||[];let shops;
  if(inspection){const n=i<26?0:Math.max(0,Math.min(5,24-(i-26)*5));shops=n;tasks=Array(n).fill(null);}
  else shops=new Set(tasks.map(k=>registry.tasks[k].merchantKey)).size;
  return [shops,tasks.length,0,0,tasks.length,i<26?'未排班':'本地草案，暂停执行'];
 });
 calendar.getRange('B7:G37').values=cal;
 if(inspection){
  const sheet=book.worksheets.add('本月23家范围');sheet.showGridLines=false;
  sheet.getRange('A2').values=[['2026年10月巡店首批23家']];
  sheet.getRange('A3').values=[['23家范围，平台分别登记。未对应和候选保持待核，实际完成0。']];
  sheet.getRange('A5:F5').values=[['序号','品牌店铺ID','首批完整店名','淘宝闪购对应','美团外卖对应','状态']];
  const data=scope.mappings.map((m,i)=>[i+1,m.selected.shopId,m.selected.name,
   m.matched.filter(r=>r.platform==='淘宝闪购').map(r=>`${r.name} / ${r.city}`).join('；')||'未找到',
   [...m.matched.filter(r=>r.platform==='美团外卖').map(r=>`${r.name} / ${r.city}`),...m.candidates.map(r=>`待核：${r.name} / ${r.city}`)].join('；')||'暂无对应记录',m.state]);
  sheet.getRange('A6:F28').values=data;
  sheet.getRange('A2:F28').format.font={name:'Arial',size:10,color:'#1F2937'};
  sheet.getRange('A2').format.font={name:'Arial',size:14,bold:true,color:'#17365D'};
  sheet.getRange('A5:F5').format={fill:'#24466B',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:28};
  [8,18,49,56,60,24].forEach((w,i)=>sheet.getRange(`${String.fromCharCode(65+i)}2:${String.fromCharCode(65+i)}28`).format.columnWidth=w);
  sheet.getRange('A6:F28').format.wrapText=true;sheet.getRange('A6:F28').format.autofitRows();sheet.freezePanes.freezeRows(5);
 }
 book.recalculate();
 const errors=await book.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME[?]|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1000});
 if(!errors.ndjson.includes('matched 0 entries'))throw Error('formula-errors:'+errors.ndjson);
 const after=roster.getRange(`A7:H${count+6}`).values;
 if(after.some((r,i)=>r.some((v,j)=>j!==5&&JSON.stringify(v)!==JSON.stringify(baseline[i][j]))))throw Error('unrelated-roster-value-changed');
 if(roster.getRange('B3').formulas[0][0]!==formulas[0][1]||roster.getRange('H3').formulas[0][0]!==formulas[0][7])throw Error('summary-formula-changed');
 const temp=file+'.tmp.xlsx';await(await SpreadsheetFile.exportXlsx(book)).save(temp);
 const verify=await SpreadsheetFile.importXlsx(await FileBlob.load(temp));
 const actual=verify.worksheets.getItem('商家与月登记').getRange(`A7:H${count+6}`).values;
 if(actual.filter(r=>r[5]==='纳入本月').length!==planCount||actual.some((r,i)=>r[3]!==baseline[i][3]||(r[2]??'')!==(baseline[i][2]??'')))throw Error('export-plan-or-identity-mismatch');
 if(Number(verify.worksheets.getItem('商家与月登记').getRange('H3').values[0][0])!==0)throw Error('unexpected-completion');
 if(inspection&&verify.worksheets.getItem('本月23家范围').getRange('C6:C28').values.length!==23)throw Error('scope-list-truncated');
 await fs.rename(temp,file);
 for(const [sheetName,range] of [['商家与月登记','A1:H10'],['每日挂历','A29:G37'],...(inspection?[['本月23家范围','A1:F11']]:[])]){
  const blob=await book.render({sheetName,range,scale:1.2,format:'png'});await fs.writeFile(path.join(OUT,`${title}-${sheetName}-计划更新.png`),new Uint8Array(await blob.arrayBuffer()));
 }
 logs.push({flow,file,rosterCount:count,plannedRecords:planCount,completed:0,executionEnabled:false,formulaErrors:errors.ndjson});
 console.log(JSON.stringify(logs.at(-1)));
}
await fs.writeFile(path.join(OUT,'plan-update-validation.json'),JSON.stringify(logs,null,2));
