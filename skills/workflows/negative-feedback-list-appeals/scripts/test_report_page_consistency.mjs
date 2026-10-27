import test from 'node:test';
import assert from 'node:assert/strict';
import { collectCurrentPages } from './all_feedback_collector.mjs';
import { FEEDBACK, JINSHA_TITLE } from './jinsha.mjs';

const window = ['2026-10-21','2026-10-27'];
const gate = {platformKey:'meituan',status:'全部',window};
const card = id => ({store:'店'+id,date:'2026-10-27',orderNo:String(id),category:'服务'});
function page(n, total, ids, change={}) {
  return {url:FEEDBACK,title:JINSHA_TITLE,risk:false,platform:'美团',timeTab:'近7日',dates:window,
    appealFilter:'全部',status:'全部',statusCounts:{全部:total,未申诉:total,申诉中:0,申诉成功:0,申诉失败:0},
    category:'全部',categoryCounts:{全部:total,食品安全负反馈率:0,服务负反馈率:total},
    totalNumber:total,pageActive:n,cards:ids.map(card),...change};
}
async function collect(first, later=[], final=first, options={}) {
  let readCount=0, nextCount=0, active=first;
  return collectCurrentPages({eval:async()=>options.hasNext ?? (active.cards.length>0 && active.pageActive<(later.length+1))},options.gate||gate,{
    read:async()=>++readCount===1?first:final,
    advance:async()=>{active=later[nextCount++];if(!active)throw Error('fixture-missing-next');return {state:active};},
  });
}
test('stable single page preserves actual source count',async()=>{
  const s=page(1,2,[1,2]);const result=await collect(s);
  assert.equal(result.rows.length,2);assert.equal(result.total,2);
  assert.deepEqual(result.counts,s.statusCounts);
});
test('stable multipage collects physical rows in original order',async()=>{
  const first=page(1,3,[1,2]),last=page(2,3,[3]);const result=await collect(first,[last],last);
  assert.deepEqual(result.rows.map(x=>x.orderNo),['1','2','3']);
});
test('actual duplicate physical rows are retained',async()=>{
  const s=page(1,2,[1,1]);assert.equal((await collect(s)).rows.length,2);
});
test('stable empty view remains a valid zero snapshot',async()=>{
  const s=page(0,0,[]);assert.deepEqual((await collect(s)).rows,[]);
});
test('total drift on later page cannot be accepted as original total',async()=>{
  const first=page(1,3,[1,2]),last=page(2,4,[3]);
  await assert.rejects(collect(first,[last],last),/total-drift/);
});
test('final readback total drift is not ignored',async()=>{
  await assert.rejects(collect(page(1,1,[1]),[],page(1,2,[1])),/total-drift/);
});
test('final page content change is not ignored',async()=>{
  await assert.rejects(collect(page(1,1,[1]),[],page(1,1,[2])),/final-page-changed/);
});
test('source all count must agree with page total',async()=>{
  const s=page(1,1,[1],{statusCounts:{全部:2,未申诉:1,申诉中:0,申诉成功:0,申诉失败:0}});
  await assert.rejects(collect(s),/dimension-total/);
});
test('missing dimension count cannot become a fabricated zero',async()=>{
  const s=page(1,1,[1]);delete s.statusCounts.申诉失败;
  await assert.rejects(collect(s),/dimension-count/);
});
test('final dimension count drift is rejected',async()=>{
  const s=page(1,1,[1]),last=page(1,1,[1]);last.statusCounts.未申诉=0;last.statusCounts.申诉中=1;
  await assert.rejects(collect(s,[],last),/dimension-drift/);
});
test('wrong platform, window or category cannot contribute rows',async()=>{
  for(const change of [{platform:'淘宝'},{dates:['2026-10-20','2026-10-26']},{risk:true}]) {
    await assert.rejects(collect(page(1,1,[1],change)),/feedback-/);
  }
});
test('starting at a later page is not full collection',async()=>{
  await assert.rejects(collect(page(2,1,[1])),/page-sequence/);
});
test('noncontinuous next page is rejected',async()=>{
  await assert.rejects(collect(page(1,3,[1,2]),[page(3,3,[3])],page(3,3,[3])),/page-sequence/);
});
test('rows equal initial total but next page still enabled is incomplete',async()=>{
  await assert.rejects(collect(page(1,1,[1]),[],undefined,{hasNext:true}),/unexpected-next/);
});
test('too few rows and no next page remains a hard failure',async()=>{
  await assert.rejects(collect(page(1,2,[1]),[],undefined,{hasNext:false}),/total-mismatch/);
});
test('category mode reads actual category counters',async()=>{
  const s=page(1,1,[1],{platform:'淘宝',status:'',statusCounts:{}});
  const r=await collect(s,[],s,{gate:{platformKey:'taobao',window}});assert.equal(r.rows.length,1);
  assert.deepEqual(r.counts,s.categoryCounts);
  await assert.rejects(collect({...s,category:'食品安全负反馈率'},[],s,{gate:{platformKey:'taobao',window}}),/category-mismatch/);
});
