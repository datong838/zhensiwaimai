import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
import {FIELDS,assertConfig,assertInternal} from './workflow_policy.mjs';

// 2026-10-22 大同定版样式（对齐 feibing_zhensi/差评分析数据_2026-10-21 参考文件）：
//   表头浅粉 #E6B9B8（Office 经典主题 accent2 C0504D tint 0.6）＋微软雅黑 11 加粗居中；
//   首列（店铺名称）浅青 #DBEEF4（accent5 4BACC6 tint 0.8）；数据微软雅黑 10 居中换行；
//   全表 thin 细边框；列宽按参考文件字符宽换算。点踩商品列保留（有真实数据，FIELDS 七字段硬校验）。
const HEADER_FILL='#E6B9B8';
const HEADER_TEXT='#3A2424';
const INDEX_FILL='#DBEEF4';
const BODY_TEXT='#262626';
const BORDER_COLOR='#000000';
const FONT_NAME='Microsoft YaHei';
const WIDTHS=[280,55,105,110,625,240,245];

function safe(value){return typeof value==='string'&&value.startsWith('=')?`'${value}`:(value??'');}
function displayWidth(value){if(value instanceof Date)return 10;return [...String(value??'')].reduce((sum,char)=>sum+(char.charCodeAt(0)>255?1.9:1),0);}
async function atomicJson(file,value){await fs.mkdir(path.dirname(file),{recursive:true,mode:0o700});const temp=file+'.tmp';await fs.writeFile(temp,JSON.stringify(value,null,2),{mode:0o600});await fs.rename(temp,file);}

async function buildReport(config,{enforceConfig=true}={}){
  if(enforceConfig)assertConfig(config);
  const rows=JSON.parse(await fs.readFile(config.finalData,'utf8'));
  if(!Array.isArray(rows))throw Error('final-data-invalid');
  if(rows.length===0)throw Error('empty-source-data');
  if(rows.some(row=>FIELDS.some(field=>!(field in row))))throw Error('final-data-fields-missing');
  await fs.mkdir(config.outputDir,{recursive:true,mode:0o700});
  const workbook=Workbook.create();
  const sheet=workbook.worksheets.add('差评分析数据');
  const endRow=rows.length+1;
  const values=[FIELDS,...rows.map(row=>[safe(row['店铺名称']),Number(row['总分']),new Date(`${String(row['评价日期']).slice(0,10)}T00:00:00Z`),safe(row['店铺类型']),safe(row['差评内容']),safe(row['点踩商品']),safe(row['评论订单详情'])])];
  sheet.showGridLines=false;
  sheet.getRange(`A1:G${endRow}`).values=values;
  // 表头：浅粉底＋雅黑 11 加粗居中（参考文件 row1，高 33）
  sheet.getRange('A1:G1').format={fill:HEADER_FILL,font:{name:FONT_NAME,size:11,bold:true,color:HEADER_TEXT},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true,rowHeight:33};
  if(endRow>=2){
    // 数据区：雅黑 10 居中换行；首列（店铺名称）浅青底
    sheet.getRange(`A2:G${endRow}`).format={font:{name:FONT_NAME,size:10,color:BODY_TEXT},horizontalAlignment:'center',verticalAlignment:'center',wrapText:true};
    sheet.getRange(`A2:A${endRow}`).format.fill=INDEX_FILL;
    sheet.getRange(`C2:C${endRow}`).setNumberFormat('yyyy-mm-dd');
  }
  for(let index=0;index<WIDTHS.length;index++){const column=String.fromCharCode(65+index);sheet.getRange(`${column}1:${column}${endRow}`).format.columnWidthPx=WIDTHS[index];}
  for(let rowIndex=2;rowIndex<=endRow;rowIndex++){
    const data=values[rowIndex-1];
    const lines=data.map((value,index)=>{const available=Math.max(4,(WIDTHS[index]-16)/7);const text=value instanceof Date?value.toISOString().slice(0,10):String(value??'');return text.split('\n').reduce((sum,line)=>sum+Math.max(1,Math.ceil(displayWidth(line)/available)),0);});
    sheet.getRange(`A${rowIndex}:G${rowIndex}`).format.rowHeightPx=Math.min(220,Math.max(30,Math.max(...lines)*20+10));
  }
  // 全表 thin 细边框（参考文件所有单元格 thin）
  sheet.getRange(`A1:G${endRow}`).format.borders={preset:'all',style:'thin',color:BORDER_COLOR};
  sheet.freezePanes.freezeRows(1);
  const inspection=await workbook.inspect({kind:'region',sheetId:sheet.id??sheet.name,range:'A1:G8',maxChars:4000,tableMaxRows:8,tableMaxCols:7});
  const output=await SpreadsheetFile.exportXlsx(workbook);
  await output.save(config.report);
  const bytes=await fs.readFile(config.report);
  const validation={ok:true,businessDate:config.businessDate,sheetName:'差评分析数据',fields:FIELDS,rows:rows.length,path:config.report,name:path.basename(config.report),size:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),inspection:inspection.ndjson,runtimeModelDecisions:0};
  await atomicJson(config.reportValidation,validation);
  return validation;
}

async function main(){assertInternal();const config=JSON.parse(await fs.readFile(process.argv[2],'utf8'));console.log(JSON.stringify(await buildReport(config)));}
export {buildReport};

if(fileURLToPath(import.meta.url)===path.resolve(process.argv[1]||''))main().catch(error=>{console.error(JSON.stringify({ok:false,reason:String(error.message||error),runtimeModelDecisions:0}));process.exitCode=1;});
