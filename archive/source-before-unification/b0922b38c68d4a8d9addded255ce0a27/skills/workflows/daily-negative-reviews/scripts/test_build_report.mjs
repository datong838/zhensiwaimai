import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {buildReport} from './build_report.mjs';

const root=await fs.mkdtemp(path.join(os.tmpdir(),'negative-report-test-'));
try{
  const config={businessDate:'2026-09-17',outputDir:root,finalData:path.join(root,'data.json'),report:path.join(root,'差评分析数据_2026-09-17_2026-09-17.xlsx'),reportValidation:path.join(root,'validation.json')};
  await fs.writeFile(config.finalData,JSON.stringify([{'店铺名称':'门店A','总分':2,'评价日期':'2026-09-17','店铺类型':'淘宝闪购','差评内容':'测试差评','点踩商品':'商品A','评论订单详情':'订单A'}]));
  const result=await buildReport(config,{enforceConfig:false});
  assert.equal(result.ok,true);assert.equal(result.sheetName,'差评分析数据');assert.equal(result.rows,1);assert.deepEqual(result.fields,['店铺名称','总分','评价日期','店铺类型','差评内容','点踩商品','评论订单详情']);assert.ok(result.size>0);assert.equal((await fs.stat(config.report)).size,result.size);assert.match(result.inspection,/店铺名称/);
  await fs.writeFile(config.finalData,'[]');config.report=path.join(root,'空报表.xlsx');config.reportValidation=path.join(root,'empty-validation.json');await assert.rejects(()=>buildReport(config,{enforceConfig:false}),/empty-source-data/);
  console.log(JSON.stringify({ok:true,tests:7}));
}finally{await fs.rm(root,{recursive:true,force:true});}
