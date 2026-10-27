import test from 'node:test';
import assert from 'node:assert/strict';
import {headerIndices,parseRosterRows,validateRoster,matchesFilterLabel,validateObservedCounts} from './monthly_roster_contract.mjs';
test('count-bearing filter labels are exact semantic matches',()=>{
 assert.equal(matchesFilterLabel('是会员547家','是会员'),true);
 assert.equal(matchesFilterLabel(' 营业中 1724 家 ','营业中'),true);
 assert.equal(matchesFilterLabel('授权中','授权中'),true);
 assert.equal(matchesFilterLabel('非会员1507家','是会员'),false);
 assert.equal(matchesFilterLabel('非营业中1724家','营业中'),false);
});
test('semantic headers can move, missing or duplicate headers reject',()=>{
 const h=['是否会员','所在城市','授权状态','店铺名字','店铺状态'];assert.deepEqual(headerIndices(h),{name:3,city:1,status:4,member:0,authorization:2});
 assert.throws(()=>headerIndices(h.slice(1)));assert.throws(()=>headerIndices([...h,'店铺名字']));
});
test('only all three exact filters qualify; city/name must exist',()=>{
 const r={name:'甲店',city:'上海市',status:'营业中',member:'是',authorization:'授权中'};
 assert.deepEqual(parseRosterRows('淘宝闪购',[r]),[{platform:'淘宝闪购',name:'甲店',city:'上海市'}]);
 for(const change of [{status:'非营业中'},{status:'已打烊'},{member:'否'},{authorization:'授权失效'},{city:''},{name:''}])assert.throws(()=>parseRosterRows('淘宝闪购',[{...r,...change}]));
});
test('both platforms, complete pagination, exact totals and no silent duplicates',()=>{
 const records=['美团外卖','淘宝闪购'].map(platform=>({platform,name:'同名店',city:'上海市'}));
 const proof=Object.fromEntries(records.map(r=>[r.platform,{filters:['是会员','营业中','授权中'],paginationComplete:true,total:1}]));
 assert.equal(validateRoster(records,proof),true);
 assert.throws(()=>validateRoster([...records,records[0]],proof));
 assert.throws(()=>validateRoster(records,{...proof,'美团外卖':{...proof['美团外卖'],total:2}}));
 assert.throws(()=>validateRoster(records,{...proof,'美团外卖':{...proof['美团外卖'],paginationComplete:false}}));
});
test('missing city is preserved for count diagnostics but never a complete roster',()=>{
 const a=parseRosterRows('淘宝闪购',[{name:'城市缺失店',city:'',status:'营业中',member:'是',authorization:'授权中'}],{allowMissingCity:true});
 const proof={'美团外卖':{filters:['是会员','营业中','授权中'],paginationComplete:true,total:0},'淘宝闪购':{filters:['是会员','营业中','授权中'],paginationComplete:true,total:1}};
 assert.equal(a[0].city,'');assert.equal(validateObservedCounts(a,proof),true);assert.throws(()=>validateRoster(a,proof));
});
