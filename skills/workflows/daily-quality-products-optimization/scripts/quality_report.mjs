import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {createRequire} from 'node:module';
import {fileURLToPath,pathToFileURL} from 'node:url';
const MODULES=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../../../../vendor/node_modules');
export async function buildReport(proofFile,output){
 const raw=await fs.readFile(proofFile),proof=JSON.parse(raw);const records=proof.records;
 if(!/^\d{4}-\d{2}-\d{2}$/.test(proof.day)||!Array.isArray(records)||records.some(r=>!r.name||!r.execution))throw Error('quality-report-source-invalid');
 const workspace=await fs.mkdtemp(path.join(os.tmpdir(),'zhensi-quality-report-'));
 try{
  await fs.symlink(MODULES,path.join(workspace,'node_modules'),'dir');const require=createRequire(path.join(workspace,'builder.mjs'));
  const {Workbook,SpreadsheetFile}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
  const wb=Workbook.create(),sheet=wb.worksheets.add('执行台账');sheet.showGridLines=false;
  const values=[['门店名称','执行记录'],...records.map(r=>[String(r.name),String(r.execution)])];
  const range=sheet.getRange(`A1:B${values.length}`);range.values=values;range.format.font={name:'Arial',size:10};range.format.verticalAlignment='center';range.format.wrapText=true;
  sheet.getRange('A1:B1').format={fill:'#1F4E78',font:{name:'Arial',size:10,bold:true,color:'#FFFFFF'},horizontalAlignment:'center',verticalAlignment:'center',rowHeight:25};
  sheet.getRange(`A1:A${values.length}`).format.columnWidth=48;sheet.getRange(`B1:B${values.length}`).format.columnWidth=58;
  if(values.length>1){sheet.getRange(`A2:B${values.length}`).format.rowHeight=38;sheet.getRange(`A2:B${values.length}`).format.autofitRows();}
  sheet.freezePanes.freezeRows(1);wb.recalculate();
  if(JSON.stringify(sheet.getRange(`A1:B${values.length}`).values)!==JSON.stringify(values))throw Error('quality-report-values-mismatch');
  await fs.mkdir(output,{recursive:true,mode:0o700});
  const preview=await wb.render({sheetName:'执行台账',range:`A1:B${Math.min(values.length,10)}`,scale:1,format:'png'});await fs.writeFile(path.join(output,'execution-ledger-preview.png'),new Uint8Array(await preview.arrayBuffer()),{mode:0o600});
  const file=path.join(output,proof.day+'淘宝闪购商品整改执行台账.xlsx');await(await SpreadsheetFile.exportXlsx(wb)).save(file);
  const bytes=await fs.readFile(file);const result={ok:true,file,name:path.basename(file),size:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex'),rows:records.length,sourceSha256:crypto.createHash('sha256').update(raw).digest('hex')};
  await fs.writeFile(path.join(output,'report.json'),JSON.stringify(result,null,2),{mode:0o600});return result;
 }finally{await fs.rm(workspace,{recursive:true,force:true});}
}
if(process.argv[1]&&path.resolve(process.argv[1])===fileURLToPath(import.meta.url)){
 try{if(process.argv.length!==6||process.argv[2]!=='--proof'||process.argv[4]!=='--output')throw Error('usage: --proof FILE --output FOLDER');console.log(JSON.stringify(await buildReport(path.resolve(process.argv[3]),path.resolve(process.argv[5]))));}catch(e){console.log(JSON.stringify({ok:false,reason:String(e.message||e)}));process.exitCode=1;}
}
