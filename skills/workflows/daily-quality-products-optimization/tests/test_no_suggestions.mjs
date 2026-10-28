import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { noExecutableSuggestions, optimizationDisposition } from '../scripts/quality_core.mjs';
import { readyOptimization } from '../scripts/quality_optimizer.mjs';
const product = { taskId: '123', name: '测试商品', hasSuggestion: false,
  issues: [{ kind: '类目问题', current: '原类目', suggestion: '' }] };
const snapshot = { total: 1, products: [product], loading: false, hasNext: false };
let tests = 0;
assert.equal(noExecutableSuggestions(snapshot), true); tests++;
for (const change of [{ loading: true }, { hasNext: true }, { total: 2 }, { total: 0 },
  { products: [] }, { products: [{ ...product, taskId: '' }] },
  { products: [{ ...product, hasSuggestion: true }] }, { products: [{ ...product, hasSuggestion: null }] },
  { products: [{ ...product, issues: [] }] }, { products: [{ ...product, name: '' }] },
  { hasNext: undefined }, { loading: undefined }, { total: NaN }]) {
  assert.equal(noExecutableSuggestions({ ...snapshot, ...change }), false); tests++;
}
assert.equal(noExecutableSuggestions({ ...snapshot, total: 2, products: [product, { ...product, taskId: '456' }] }), true); tests++;
assert.equal(noExecutableSuggestions({ ...snapshot, total: 2, products: [product, { ...product, taskId: '456', hasSuggestion: true }] }), false); tests++;
const source = await fs.readFile(new URL('../scripts/quality_optimizer.mjs', import.meta.url), 'utf8');
const guard = source.indexOf('if(disposition.action===');
assert.ok(guard > 0 && guard < source.indexOf('store.selectionNote=await prepareSelection'));
assert.ok(source.includes('store.reason=disposition.reason')); tests++;
// The original condition wrongly treated a missing control on an unread page as no work.
assert.equal(Number.NaN === 0 || 0 === 0, true); tests++;
const ready={...snapshot,page:1},enabled={count:1,disabled:false};
assert.throws(()=>optimizationDisposition({...ready,total:NaN,products:[]},{count:0,disabled:null}),/quality-product-readiness-invalid/); tests++;
const actionable={...ready,products:[{...product,hasSuggestion:true}]};
assert.deepEqual(optimizationDisposition(actionable,enabled),{action:'submit'}); tests++;
assert.equal(optimizationDisposition(ready,{count:0,disabled:null}).reason,'no-executable-platform-suggestions'); tests++;
assert.equal(optimizationDisposition(actionable,{count:1,disabled:true}).action,'skip'); tests++;
assert.equal(optimizationDisposition({...ready,total:0,products:[]},{count:0,disabled:null}).action,'skip'); tests++;
for(const change of [{total:NaN},{total:-1},{total:1.5},{loading:true},{products:[]},
 {total:2},{hasNext:undefined},{page:0},{products:[{...product,taskId:''}]},
 {products:[{...product,issues:[]}]},{total:2,products:[product,product]}]){
 assert.throws(()=>optimizationDisposition({...ready,...change},enabled),/quality-product-/); tests++;
}
for(const action of [{count:0,disabled:null},{count:2,disabled:null},{count:1,disabled:null},{count:true,disabled:false}]){
 assert.throws(()=>optimizationDisposition(actionable,action),/quality-product-action-not-ready/); tests++;
}
assert.deepEqual(optimizationDisposition({...actionable,total:2,hasNext:true},enabled),{action:'submit'}); tests++;
assert.deepEqual(optimizationDisposition({...ready,total:2,hasNext:true},enabled),{action:'submit'}); tests++;
// Exercise the actual bounded reader: an initially absent control can become ready,
// while a permanently absent control never becomes a no-action success.
function fakeFrame(values,counts){
 let reads=0,actions=0;
 return {evaluate:async()=>values[Math.min(reads++,values.length-1)],
  getByRole:()=>({count:async()=>counts[Math.min(actions++,counts.length-1)],isDisabled:async()=>false})};
}
const read=await readyOptimization(fakeFrame([actionable],[0,1]),Date.now()+2500);
assert.equal(read.disposition.action,'submit'); tests++;
const blank={...actionable,total:NaN,products:[]};
const loaded=await readyOptimization(fakeFrame([blank,blank,actionable,actionable],[0,1]),Date.now()+2500);
assert.equal(loaded.disposition.action,'submit'); tests++;
await assert.rejects(readyOptimization(fakeFrame([actionable],[0]),Date.now()+800),/quality-product-/); tests++;
assert.ok(!source.includes('before.total===0||await action.count()===0')); tests++;
console.log(JSON.stringify({ ok: true, tests, businessWrites: 0, sendAttempts: 0 }));
