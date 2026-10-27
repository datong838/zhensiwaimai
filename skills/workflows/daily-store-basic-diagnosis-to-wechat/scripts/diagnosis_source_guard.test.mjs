import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {collectMetricPages as currentCollect, validateMetricResults} from './diagnosis_source_guard.mjs';
const metrics=[['a','指标A'],['b','指标B']];
const row=(id=1)=>({shop_id:id,shop_name:'测试店'+id,task_status:'未完成'});
const page=(rows,total=rows.length)=>({ok:true,status:200,json:async()=>({code:0,totalCount:total,data:rows})});
const request={rec:{url:'https://example.invalid/original-list',reqBody:'{}',headers:{}},metrics:[metrics[0]],pageSize:2,maxPages:2};
let collect=currentCollect;
if(process.env.DIAG_SOURCE_TEST_ORIGINAL==='1'){
 const source=fs.readFileSync(new URL('../../../../runtime/state/basic-diagnosis-completeness-20261028/originals/basic_diag_collector.mjs',import.meta.url),'utf8');
 const match=source.match(/const out = await page\.evaluate\((async [\s\S]*?\n  }), \{ rec: base/);
 assert.ok(match);
 collect=vm.runInNewContext('('+match[1]+')',{fetch:(...args)=>globalThis.fetch(...args)});
}
async function withPages(responses, operation){
 const old=globalThis.fetch;let calls=0;
 globalThis.fetch=async()=>{assert.ok(calls<responses.length,'unexpected network request');return responses[calls++];};
 try{return await operation(()=>calls);}finally{globalThis.fetch=old;}
}
function complete(){return {'指标A':{totalCount:1,rows:[row(1)]},'指标B':{totalCount:0,rows:[]}};}

test('complete multipage original list succeeds',async()=>{
 await withPages([page([row(1),row(2)],3),page([row(3)],3)],async calls=>{
  const out=await collect(request);assert.equal(out['指标A'].rows.length,3);assert.equal(calls(),2);
  validateMetricResults(out,[metrics[0]]);
 });
});
test('complete zero list succeeds without extra request',async()=>{
 await withPages([page([],0)],async calls=>{
  const out=await collect(request);assert.equal(out['指标A'].rows.length,0);assert.equal(calls(),1);
  validateMetricResults(out,[metrics[0]]);
 });
});
for(const [name,responses,error] of [
 ['HTTP failure',[{ok:false,status:401}],/diag-http-error/],
 ['API nonzero',[{ok:true,json:async()=>({code:401002,message:'fixture'})}],/diag-response-error/],
 ['total drift',[page([row(1)],3),page([row(2)],2)],/diag-total-drift/],
 ['early empty page',[page([row(1)],3),page([],3)],/diag-empty-page-before-total/],
 ['page budget exhausted',[page([row(1)],3),page([row(2)],3)],/diag-pagination-incomplete/],
 ['count overflow',[page([row(1),row(2)],1)],/diag-count-exceeds-total/],
 ['nonarray rows',[{ok:true,json:async()=>({code:0,totalCount:0,data:{}})}],/diag-page-invalid/],
 ['page exceeds requested size',[page([row(1),row(2),row(3)],3)],/diag-page-invalid/],
])test(name+' blocks partial diagnosis',async()=>withPages(responses,()=>assert.rejects(collect(request),error)));
for(const total of [null,undefined,'2',-1,1.5,NaN,true])test('invalid total '+String(total)+' rejected',async()=>{
 await withPages([{ok:true,json:async()=>({code:0,totalCount:total,data:[]})}],()=>assert.rejects(collect(request),/diag-total-invalid/));
});
test('full metric set including zero metrics accepted',()=>assert.equal(validateMetricResults(complete(),metrics)['指标B'].totalCount,0));
for(const [name,change] of [
 ['missing metric',v=>delete v['指标B']],
 ['unexpected extra metric',v=>v.extra={totalCount:0,rows:[]}],
 ['upstream error',v=>v['指标A'].error='api-failed'],
 ['truncated',v=>v['指标A'].truncated=true],
 ['missing rows',v=>delete v['指标A'].rows],
 ['actual count mismatch',v=>v['指标A'].totalCount=2],
 ['wrong status',v=>v['指标A'].rows[0].task_status='已完成'],
 ['missing identity',v=>delete v['指标A'].rows[0].shop_id],
 ['blank shop name',v=>v['指标A'].rows[0].shop_name=' '],
 ['duplicate shop',v=>{v['指标A'].rows.push(row(1));v['指标A'].totalCount=2;}],
])test(name+' fails full-set gate',()=>{const value=complete();change(value);assert.throws(()=>validateMetricResults(value,metrics),/diag-/);});
test('serialized browser function has no module closures',async()=>{
 const isolated=vm.runInNewContext('('+currentCollect.toString()+')',{fetch:async()=>page([row(1)])});
 const out=await isolated(request);assert.equal(out['指标A'].rows.length,1);
});
test('original request scope and metric page settings preserved',async()=>{
 const old=globalThis.fetch;
 globalThis.fetch=async(url,options)=>{
  const body=JSON.parse(options.body);
  assert.equal(url,request.rec.url);assert.equal(body.taskStatus,'未完成');
  assert.equal(body.agentCode,'a');assert.equal(body.current,1);assert.equal(body.pageSize,2);
  assert.equal(options.credentials,'include');return page([],0);
 };
 try{await currentCollect({...request,rec:{...request.rec,reqBody:JSON.stringify({taskStatus:'未完成'})}});}
 finally{globalThis.fetch=old;}
});
