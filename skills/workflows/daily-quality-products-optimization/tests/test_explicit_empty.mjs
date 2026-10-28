import assert from 'node:assert/strict';
import {optimizationDisposition,EXPLICIT_EMPTY_DESCRIPTION} from '../scripts/quality_core.mjs';
import {readyOptimization} from '../scripts/quality_optimizer.mjs';
const description=EXPLICIT_EMPTY_DESCRIPTION;
const snapshot={total:0,products:[],page:1,hasNext:false,loading:false,headers:[],empty:[description],
 emptyState:{description,descriptionCount:1,visible:true,tabCount:0,rowCount:0,headerCount:0,buttonCount:0}};
const action={count:0,disabled:null};let tests=0;
const expected={action:'skip',reason:'platform-explicit-no-problem-products'};
assert.deepEqual(optimizationDisposition(snapshot,action),expected);tests++;
const frozen=structuredClone(snapshot);optimizationDisposition(snapshot,action);assert.deepEqual(snapshot,frozen);tests++;
for(const change of [{total:NaN},{total:1},{total:false},{products:[{}]},{products:null},{page:2},{page:0},
 {loading:true},{loading:undefined},{hasNext:true},{headers:['商品名称']},{empty:[]},{empty:[description,description]},
 {empty:['暂无数据']},{imageOnly:{}}]){
 assert.throws(()=>optimizationDisposition({...snapshot,...change},action),/quality-product-/);tests++;
}
for(const change of [{description:'暂无数据'},{description:''},{descriptionCount:0},{descriptionCount:2},{visible:false},
 {visible:undefined},{tabCount:1},{rowCount:1},{headerCount:1},{buttonCount:1},{buttonCount:false}]){
 assert.throws(()=>optimizationDisposition({...snapshot,emptyState:{...snapshot.emptyState,...change}},action),/quality-product-/);tests++;
}
for(const wrong of [{count:1,disabled:false},{count:0,disabled:false},{count:false,disabled:null}]){
 assert.throws(()=>optimizationDisposition(snapshot,wrong),/quality-product-/);tests++;
}
// Unrecognized empty text must not become a valid total-zero observation.
assert.throws(()=>optimizationDisposition({...snapshot,total:NaN,emptyState:undefined,empty:['暂无数据']},action),/quality-product-/);tests++;
const frame={evaluate:async()=>structuredClone(snapshot),getByRole:()=>({count:async()=>0,isDisabled:async()=>{throw Error('nonexistent action');}})};
assert.deepEqual((await readyOptimization(frame,Date.now()+2000)).disposition,expected);tests++;
console.log(JSON.stringify({ok:true,tests,browserActions:0,sendAttempts:0}));
