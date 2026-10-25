import assert from 'node:assert/strict';
import { validateManifest, validateReportRows, buildArgs } from './deliver_batch.mjs';
import { ROOT, FLOW_ID, PLATFORMS, businessDate, shanghaiDay, recentRange } from './jinsha.mjs';
import { previewLastRow } from './report_builder.mjs';
const business = businessDate();
const valid = {ok:true,businessDate:business,window:recentRange(business),reports:PLATFORMS.map(spec=>({platformKey:spec.key,label:spec.label,recordCount:2,outputPath:`${ROOT}/outputs/${FLOW_ID}-${shanghaiDay().replaceAll('-','')}/负反馈申诉汇总_${spec.label}_${business}.xlsx`}))};
assert.equal(validateManifest(valid),true);
for (const mutate of [m=>m.businessDate='2000-01-01',m=>m.window=['2000-01-01','2000-01-07'],m=>m.reports.pop(),m=>m.reports[1]=m.reports[0],m=>m.reports[0].recordCount=0,m=>m.reports[0].recordCount=-1,m=>m.reports[0].recordCount=1.5,m=>m.reports[0].outputPath='/tmp/other.xlsx',m=>m.reports[0].label='其他',m=>m.ok=false]) {
 const bad=structuredClone(valid);mutate(bad);assert.throws(()=>validateManifest(bad));
}
const report=valid.reports[0];
const rows=[[`业务日期：${business}；范围：${recentRange(business).join(' 至 ')}`],['平台','门店'],[report.label,'A'],[report.label,'B']];
assert.equal(validateReportRows(rows,report),true);
assert.throws(()=>validateReportRows(rows.slice(0,-1),report));
assert.throws(()=>validateReportRows([['旧日期'],...rows.slice(1)],report));
assert.throws(()=>validateReportRows([...rows.slice(0,-1),['其他','B']],report));
assert.throws(()=>validateReportRows([...rows.slice(0,-1),[report.label,'']],report));
assert.equal(previewLastRow(8,8),8);
assert.equal(previewLastRow(8,12),12);
assert.equal(previewLastRow(8,28),28);
assert.equal(previewLastRow(8,600),28);
const before=Math.floor(Date.now()/1000),args=buildArgs({items:['a.xlsx','b.xlsx']}),deadline=Number(args[args.indexOf('--deadline-unix')+1]);
assert.ok(deadline-before>=900 && deadline-before<=901);
console.log(JSON.stringify({ok:true,tests:21,sendAttempts:0}));
