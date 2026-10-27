// Read generated disposable workbooks and compare with the already-correct originals.
import fs from 'node:fs/promises';
import path from 'node:path';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import assert from 'node:assert/strict';
const root=path.resolve(import.meta.dirname,'../..');
const require=createRequire(new URL('../../vendor/package.json',import.meta.url));
const {SpreadsheetFile,FileBlob}=await import(pathToFileURL(require.resolve('@oai/artifact-tool')).href);
const output=process.argv[2];if(!output)throw Error('disposable-output-directory-required');
const original=path.join(root,'outputs/01a17923-bee5-7660-9206-86c007d01918/2026-10');
const result=[];
for(const [title,count,plan] of [['商家经营指标互动',753,23],['发优惠券',753,23],['巡店',1096,24]]){
 const name=`${title}-2026-10全量商家与月工作登记.xlsx`;
 const actual=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(output,name)));
 const baseline=await SpreadsheetFile.importXlsx(await FileBlob.load(path.join(original,name)));
 const sheet=actual.worksheets.getItem('商家与月登记');
 const rows=sheet.getRange(`A7:H${count+6}`).values;
 assert.deepEqual(rows,baseline.worksheets.getItem('商家与月登记').getRange(`A7:H${count+6}`).values);
 assert.equal(rows.filter(r=>r[5]==='纳入本月').length,plan);
 assert.equal(Number(sheet.getRange('H3').values[0][0]),0);
 const calendar=actual.worksheets.getItem('每日挂历').getRange('B7:F37').values;
 assert.deepEqual(calendar,baseline.worksheets.getItem('每日挂历').getRange('B7:F37').values);
 if(title==='巡店'){
  assert.equal(rows.filter(r=>r[5]==='本月候选待核').length,15);
  assert.equal(rows.filter(r=>!r[4]).length,1);
  assert.deepEqual(actual.worksheets.getItem('本月23家范围').getRange('A6:F28').values,
                   baseline.worksheets.getItem('本月23家范围').getRange('A6:F28').values);
  for(const [sheetName,range] of [['本月23家范围','A1:F11'],['每日挂历','A29:G37']]){
   const blob=await actual.render({sheetName,range,scale:1.2,format:'png'});
   await fs.writeFile(path.join(output,`巡店-${sheetName}-verified.png`),new Uint8Array(await blob.arrayBuffer()));
  }
 }
 const errors=await actual.inspect({kind:'match',searchTerm:'#REF!|#DIV/0!|#VALUE!|#NAME[?]|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',options:{useRegex:true,maxResults:20},maxChars:1000});
 assert.ok(errors.ndjson.includes('matched 0 entries'));
 result.push({title,rosterCount:rows.length,plannedRecords:plan,completed:0,originalRosterValuesPreserved:true,originalCalendarCountsPreserved:true,formulaErrors:0});
}
await fs.writeFile(path.join(output,'scope-verification.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify({ok:true,workbooks:result,sourceWrites:0,executionEnabled:false}));
