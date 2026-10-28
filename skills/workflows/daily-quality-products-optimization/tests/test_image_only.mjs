import assert from 'node:assert/strict';
import {optimizationDisposition,singlePassSummary,SINGLE_PASS} from '../scripts/quality_core.mjs';
import {readyOptimization,skipBeforeFrame} from '../scripts/quality_optimizer.mjs';
const original={total:2,page:1,hasNext:false,loading:false,
 products:['123','456'].map((taskId,i)=>({taskId,name:'商品'+i,hasSuggestion:false,
  issues:[{kind:'图片亮度不够',current:'',suggestion:'暂无建议'}]})),
 imageOnly:{tabs:[{text:'图片问题(2)',selected:true}],headers:['商品名称','图片问题','建议内容','操作'],
  buttonCount:0,hiddenTabOverflowCount:0,operatorTexts:['手动优化申诉','手动优化申诉'],rowStructureValid:true}};
const action={count:0,disabled:null},reason='image-only-no-automatic-suggestions';
let tests=0;
assert.deepEqual(optimizationDisposition(original,action),{action:'skip',reason});tests++;
assert.deepEqual(optimizationDisposition({...original,imageOnly:{...original.imageOnly,hiddenTabOverflowCount:1}},action),{action:'skip',reason});tests++;
const frozen=structuredClone(original);optimizationDisposition(original,action);assert.deepEqual(original,frozen);tests++;
for(const change of [{total:0},{total:NaN},{total:3},{page:2},{hasNext:true},{loading:true},
 {products:[]},{products:[original.products[0],original.products[0]]},
 ...[{taskId:''},{taskId:123},{name:6},{name:''},{hasSuggestion:true},{hasSuggestion:null},{issues:[]},
 {issues:[null]},{issues:[{kind:'',current:'',suggestion:'暂无建议'}]},
 {issues:[{kind:'图片亮度不够',current:'',suggestion:'可优化图片'}]},
 {issues:[{kind:'图片亮度不够',current:'old',suggestion:'暂无建议'}]}].map(p=>({products:[{...original.products[0],...p},original.products[1]]}))]){
 assert.throws(()=>optimizationDisposition({...original,...change},action),/quality-product-/);tests++;
}
for(const change of [{tabs:[]},{tabs:[null]},{tabs:[{text:'图片问题(2)',selected:false}]},
 {tabs:[{text:'图片问题(3)',selected:true}]},{tabs:[...original.imageOnly.tabs,{text:'类目详情问题(1)',selected:false}]},
 {headers:['商品名称','图片问题','操作']},{buttonCount:1},{buttonCount:false},{rowStructureValid:false},
 {hiddenTabOverflowCount:2},{hiddenTabOverflowCount:-1},{hiddenTabOverflowCount:false},{hiddenTabOverflowCount:undefined},
 {operatorTexts:['手动优化申诉']},{operatorTexts:['手动优化申诉','采纳建议']}]){
 assert.throws(()=>optimizationDisposition({...original,imageOnly:{...original.imageOnly,...change}},action),/quality-product-/);tests++;
}
for(const change of [{count:1,disabled:false},{count:2,disabled:null},{count:false,disabled:null},{count:0,disabled:false}]){
 assert.throws(()=>optimizationDisposition(original,change),/quality-product-/);tests++;
}
const frame={evaluate:async()=>structuredClone(original),getByRole:()=>({count:async()=>0,isDisabled:async()=>{throw Error('must not read nonexistent control');}})};
assert.equal((await readyOptimization(frame,Date.now()+2500)).disposition.reason,reason);tests++;
const summary=singlePassSummary({executionPolicy:SINGLE_PASS,scopeFinished:true,stores:[{state:'checked_no_action',reason}]});
assert.equal(summary.checkedNoAction,1);assert.equal(summary.optimized,0);assert.equal(summary.failed,0);
assert.ok(summary.text.includes('1 家仅有图片问题且平台无自动建议'));assert.ok(!summary.text.includes('全部店铺优化完成'));tests++;
for(const state of ['blocked','unknown','attempted','checked_no_action']){assert.equal(skipBeforeFrame({state},'new-source-version'),true);tests++;}
console.log(JSON.stringify({ok:true,tests,browserActions:0,sendAttempts:0}));
