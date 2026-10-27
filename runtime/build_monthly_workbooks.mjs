// Reporting only. No dispatch, browser connection, plan import, or completion writes.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import crypto from 'node:crypto';
import {inspectionReportScope,inspectionRecordKey} from './monthly_report_scope.mjs';
const require=createRequire(new URL('../vendor/package.json',import.meta.url));
const {Workbook,SpreadsheetFile,FileBlob}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const ROOT=path.resolve(import.meta.dirname,'..');
const arg=(key,fallback)=>{const i=process.argv.indexOf(key);return i<0?fallback:process.argv[i+1];};
const MONTH=arg('--month',new Date().toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'}).slice(0,7));
if(!/^[0-9]{4}-[0-9]{2}$/.test(MONTH))throw Error('month-invalid');
const output=path.resolve(arg('--output-dir',path.join(ROOT,'outputs/01a17923-bee5-7660-9206-86c007d01918',MONTH)));
const json=async p=>JSON.parse(await fs.readFile(p,'utf8'));
const FLOWS=[['daily-store-metrics-rotation-to-wechat','商家经营指标互动'],['coupon-issue-task-flow','发优惠券'],['store-inspection','巡店']];
const verified=t=>['verified','already_verified'].includes(t.status);
const uncertain=t=>['unknown','attempted'].includes(t.status);
function style(sheet,last,headers,widths){
 sheet.showGridLines=false;
 sheet.getRange(`A2:${last}${headers}`).format.font={name:'Arial',size:10,color:'#1F2937'};
 sheet.getRange(`A2:${last}${headers}`).format.verticalAlignment='center';
 sheet.getRange(`A2:${last}${headers}`).format.rowHeight=23;
 sheet.getRange('A2').format.font={name:'Arial',size:14,bold:true,color:'#17365D'};
 sheet.getRange(`A6:${last}6`).format={fill:'#24466B',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:28,horizontalAlignment:'center',verticalAlignment:'center'};
 widths.forEach((w,i)=>{const c=String.fromCharCode(65+i);sheet.getRange(`${c}2:${c}${headers}`).format.columnWidth=w;});
 sheet.freezePanes.freezeRows(6);
}
async function load(flow){
 const base=path.join(ROOT,'skills/workflows',flow,'.runtime/monthly',MONTH);
 let registry,daily,source,records;
 try{
  const pointer=await json(path.join(base,'latest.json'));
  if(!/^[a-f0-9]{32}$/.test(pointer.generation))throw Error('registry-pointer-invalid');
  const dir=path.join(base,pointer.generation);const raw=await fs.readFile(path.join(dir,'registry.json'));
  if(crypto.createHash('sha256').update(raw).digest('hex')!==pointer.registrySha256)throw Error('registry-hash-mismatch');
  registry=JSON.parse(raw);daily=await json(path.join(dir,'daily-plan.json'));source=await json(path.join(dir,'source.json'));records=await json(path.join(dir,'current-roster.json'));
 }catch(e){
  if(e.code!=='ENOENT'||flow!=='store-inspection')throw e;
  source=await json(path.join(base,'jinsha-roster.json.incomplete.json'));
  if(source.countVerified!==true||source.duplicates.length||source.total!==source.records.length)throw Error('inspection-source-count-unproved');
  records=source.records;registry={plan:null,tasks:{},merchants:{},executionEnabled:false};daily={status:'waiting-sa',days:[]};
 }
 if(registry.flow&&registry.flow!==flow||registry.month&&registry.month!==MONTH)throw Error('registry-scope-mismatch');
 if(registry.executionEnabled!==false)throw Error('report-execution-scope-unexpected');
 if(flow!=='store-inspection'&&records.some(r=>r.status.trim()!=='营业中'))throw Error('non-open-merchant-in-current-roster');
 let reportScope=null;
 if(flow==='store-inspection'&&registry.plan===null){
  let scope;
  try{scope=await json(path.join(base,'monthly-scope.json'));}catch(e){if(e.code!=='ENOENT')throw e;}
  if(scope){
   const raw=await fs.readFile(path.join(base,'jinsha-roster.json.incomplete.json'));
   reportScope=inspectionReportScope(scope,{month:MONTH,sourceSha256:crypto.createHash('sha256').update(raw).digest('hex'),records,completeRoster:source.complete});
  }
 }
 return {registry,daily,source,records,reportScope};
}
// Validate every source before exporting any report.
const loaded=new Map(await Promise.all(FLOWS.map(async([flow])=>[flow,await load(flow)])));
await fs.mkdir(output,{recursive:true});const summaries=[];
for(const [flow,title] of FLOWS){
 const {registry,daily,source,records,reportScope}=loaded.get(flow);
 const book=Workbook.create();const roster=book.worksheets.add('商家与月登记');const calendar=book.worksheets.add('每日挂历');
 const tasks=Object.values(registry.tasks);const planKeys=new Set(registry.plan?.merchantKeys||[]);
 const keysByRecord=new Map(Object.entries(registry.merchants).map(([key,m])=>[JSON.stringify(m.record),key]));
 const rows=records.map((r,i)=>{
  const key=keysByRecord.get(JSON.stringify(r));const own=tasks.filter(t=>t.merchantKey===key);
  const missing=flow==='store-inspection'&&!r.city;
  return [i+1,r.platform||'淘宝闪购',String(r.shopId||''),r.name||r.shopName,r.city||r.orgPath||'',
   reportScope?(reportScope.matchedKeys.has(inspectionRecordKey(r))?'纳入本月':reportScope.candidateKeys.has(inspectionRecordKey(r))?'本月候选待核':'未纳入本月'):registry.plan===null?'待导入SA名单':planKeys.has(key)?'纳入本月':'未纳入本月',own.filter(verified).length,
   missing?'城市待补核（原始字段为空）':own.some(uncertain)?'有结果未确认，禁止重发':registry.executionEnabled?'':'未启用执行'];
 });
 const end=rows.length+6;
 roster.getRange('A2').values=[[`${MONTH} ${title}商家与月登记`]];
 roster.getRange('A3:H3').values=[['商家数',null,null,reportScope?'本月平台记录':'本月计划',reportScope?reportScope.plannedRecords:registry.plan===null?'待导入SA名单':planKeys.size,null,'完成任务数',null]];
 if(reportScope)roster.getRange('A5').values=[[`本月范围${reportScope.requestedShops}家；已对应${reportScope.matchedShops}家、${reportScope.plannedRecords}条平台记录；${reportScope.candidateKeys.size}条候选待核。暂停执行。`]];
 roster.getRange('B3').formulas=[[`=COUNTA(D7:D${end})`]];roster.getRange('H3').formulas=[[`=SUM(G7:G${end})`]];
 const sourceName=flow==='store-inspection'?'金鲨店铺列表（会员、营业中、授权中）':'淘宝品牌商主账号组织树（仅营业中）';
 roster.getRange('A4').values=[[`来源：${sourceName}；采集时间：${source.collectedAt}`]];
 roster.getRange('A6:H6').values=[['序号','平台','店铺ID','完整店名',flow==='store-inspection'?'所在城市':'运营组织','本月计划','完成任务数','备注']];
 roster.getRange(`A7:H${end}`).values=rows;
 roster.tables.add(`A6:H${end}`,true,'MerchantMonthlyRegister');
 style(roster,'H',end,[8,14,17,48,22,22,14,36]);
 roster.getRange(`C7:C${end}`).setNumberFormat('@');roster.getRange(`G7:G${end}`).setNumberFormat('#,##0');
 roster.getRange(`D7:F${end}`).format.wrapText=true;roster.getRange(`H7:H${end}`).format.wrapText=true;
 roster.getRange(`A7:H${end}`).format.autofitRows();
 roster.getRange(`H7:H${end}`).conditionalFormats.add('containsText',{text:'待补核',format:{fill:'#FFF2CC',font:{bold:true,color:'#9C5700'}}});
 const [year,month]=MONTH.split('-').map(Number);const count=new Date(Date.UTC(year,month,0)).getUTCDate();
 const byDate=new Map((daily.days||[]).map(d=>[d.date,d.taskKeys]));
 const calendarRows=Array.from({length:count},(_,i)=>{
  const day=`${MONTH}-${String(i+1).padStart(2,'0')}`;const keys=byDate.get(day)||[];const selected=keys.map(k=>registry.tasks[k]).filter(Boolean);
  const planned=registry.plan!==null||reportScope!==null;
  const completed=tasks.filter(t=>verified(t)&&String(t.completedAt||'').slice(0,10)===day).length;
  const unknown=tasks.filter(t=>uncertain(t)&&String(t.attemptedAt||'').slice(0,10)===day).length;
  const draft=reportScope?.calendarCounts.get(day)||0;
  return [new Date(Date.UTC(year,month-1,i+1)),reportScope?draft:planned?new Set(selected.map(t=>t.merchantKey)).size:null,reportScope?draft:planned?selected.length:null,completed,unknown,reportScope?draft:planned?selected.filter(t=>t.status==='pending').length:null,reportScope?(draft?'本地草案，暂停执行':'未排班'):planned?'本地计划，尚未启用':'待SA名单，未排班'];
 });
 calendar.getRange('A2').values=[[`${MONTH} ${title}每日挂历`]];
 calendar.getRange('A3').values=[[reportScope?'按平台分别计量；已对应记录仅为草案，候选未排入；启用时重排。':registry.plan===null?'待导入SA名单；当前未排班。':'读取本流独立计划；未知结果不重发。']];
 calendar.getRange('A6:G6').values=[['日期','计划商家数','计划任务数','已完成任务','结果未确认','待执行任务','状态']];
 calendar.getRange(`A7:G${count+6}`).values=calendarRows;style(calendar,'G',count+6,[15,17,17,17,17,17,34]);
 calendar.getRange(`A7:A${count+6}`).setNumberFormat('yyyy-mm-dd');calendar.getRange(`B7:F${count+6}`).setNumberFormat('#,##0');
 if(reportScope){
  const sheet=book.worksheets.add(`本月${reportScope.requestedShops}家范围`),last=reportScope.scopeRows.length+5;sheet.showGridLines=false;
  sheet.getRange('A2').values=[[`${MONTH} 巡店首批${reportScope.requestedShops}家`]];
  sheet.getRange('A3').values=[['平台分别登记；未对应与候选保留待核，当前暂停执行。']];
  sheet.getRange('A5:F5').values=[['序号','品牌店铺ID','首批完整店名','淘宝闪购对应','美团外卖对应','状态']];
  sheet.getRange(`A6:F${last}`).values=reportScope.scopeRows;
  sheet.getRange(`A2:F${last}`).format.font={name:'Arial',size:10,color:'#1F2937'};
  sheet.getRange('A2').format.font={name:'Arial',size:14,bold:true,color:'#17365D'};
  sheet.getRange('A5:F5').format={fill:'#24466B',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},rowHeight:28};
  [8,18,49,56,60,24].forEach((w,i)=>sheet.getRange(`${String.fromCharCode(65+i)}2:${String.fromCharCode(65+i)}${last}`).format.columnWidth=w);
  sheet.getRange(`B6:B${last}`).setNumberFormat('@');sheet.getRange(`A6:F${last}`).format.wrapText=true;sheet.getRange(`A6:F${last}`).format.autofitRows();sheet.freezePanes.freezeRows(5);
 }
 book.recalculate();
 const inspect=await book.inspect({kind:'table',range:'商家与月登记!A3:H9',include:'values,formulas',tableMaxRows:7,tableMaxCols:8,maxChars:2200});
 const errors=await book.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME[?]|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1200});
 if(!errors.ndjson.includes('matched 0 entries'))throw Error('monthly-report-formula-errors:'+errors.ndjson);
 const filename=`${title}-${MONTH}全量商家与月工作登记.xlsx`;const file=path.join(output,filename);
 await (await SpreadsheetFile.exportXlsx(book)).save(file);
 const reimported=await SpreadsheetFile.importXlsx(await FileBlob.load(file));
 const exported=reimported.worksheets.getItem('商家与月登记').getRange(`A7:H${end}`).values;
 if(exported.length!==rows.length||exported.some((r,i)=>r[3]!==rows[i][3]||(r[2]??'')!==rows[i][2]))throw Error('exported-roster-identity-mismatch');
 if(Number(reimported.worksheets.getItem('商家与月登记').getRange('B3').values[0][0])!==rows.length)throw Error('exported-count-mismatch');
 const views=[['商家与月登记','A1:H16'],['每日挂历','A1:G18']];
 if(reportScope)views.push([`本月${reportScope.requestedShops}家范围`,'A1:F11']);
 for(const [sheetName,range] of views){
  const blob=await book.render({sheetName,range,scale:1.5,format:'png'});
  await fs.writeFile(path.join(output,`${title}-${sheetName}.png`),new Uint8Array(await blob.arrayBuffer()));
 }
 summaries.push({flow,file,merchantCount:rows.length,completeRoster:source.complete,sourceTime:source.collectedAt,inspection:inspect.ndjson,formulaErrors:errors.ndjson});
 console.log(JSON.stringify({ok:true,flow,file,merchantCount:rows.length,completeRoster:source.complete}));
}
await fs.writeFile(path.join(output,'validation.json'),JSON.stringify(summaries,null,2));
