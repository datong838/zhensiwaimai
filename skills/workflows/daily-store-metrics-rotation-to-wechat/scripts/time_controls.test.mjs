import test from 'node:test';import assert from 'node:assert/strict';import {uniqueGoodsGroup} from './lib/time_controls.mjs';
test('goods time selector ignores geometry but rejects absent or ambiguous groups',()=>{
 const g={index:2,visible:true,labels:['今日实时','昨日','近7日','近30日','自定义']};
 assert.equal(uniqueGoodsGroup([{...g,visible:false},g]),2);
 assert.throws(()=>uniqueGoodsGroup([]));assert.throws(()=>uniqueGoodsGroup([g,g]));assert.throws(()=>uniqueGoodsGroup([{...g,labels:['近30日']}]));
});
