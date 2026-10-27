import assert from 'node:assert/strict';
import {datePairMatches,messageFor,parseLogicalRows,stableIncremental,uniqueAgentMenu,hardObservationError} from './background_merchant_collector.mjs';

const rows=[
  {merchantId:'2',recommendTime:'2026-09-10 10:00:00',merchantName:'乙'},
  {merchantId:'1',recommendTime:'2026-09-10 10:00:00',merchantName:'甲'},
  {merchantId:'3',recommendTime:'2026-09-10 11:00:00',merchantName:'丙'},
];
const selected=stableIncremental(rows,{merchantId:'1',recommendTime:'2026-09-10 10:00:00'},'2026-09-10');
assert.deepEqual(selected.map(row=>row.merchantId),['3']);
assert.equal(messageFor({city:'上海市',contact:'姚，18014000718',merchantName:'店',address:'地址'}),'上海市\n姚，18014000718\n店\n地址');
assert.match(messageFor({city:'',contact:'',merchantName:'',address:''}),/城市字段缺失/);
assert.throws(()=>stableIncremental(rows,{merchantId:'9',recommendTime:'2026-09-10 10:00:00'},'2026-09-10'),/same-day-cursor-not-unique/);
const headers=['商家名称','商家ID','详细地址','门店类型','推荐人','市场经理','城市','商户来源类型','状态','剩余处理时间','推荐时间','签约时间','操作'];
const logical=parseLogicalRows(headers,[['店A','1338580316','地址','','商家邀约','经理','阳泉市','服务市场商家邀约','待处理','13天','2026-09-10 16:46:12','','详情']]);
assert.equal(logical[0].merchantId,'1338580316');
assert.throws(()=>parseLogicalRows(headers,[['不完整']]),/merchant-row-column-mismatch/);
assert.equal(datePairMatches(['2026-09-11','2026-09-11'],'2026-09-11','2026-09-11'),true);
assert.equal(datePairMatches(['2026-09-11',''],'2026-09-11','2026-09-11'),false);
const sidebar={item:'sidebar',box:{x:30,y:100,width:50,height:20}};
assert.equal(uniqueAgentMenu([sidebar,{item:'card',box:{x:300,y:100,width:50,height:20}}]),'sidebar');
assert.equal(uniqueAgentMenu([sidebar,sidebar]),'sidebar');
assert.throws(()=>uniqueAgentMenu([]),/agent-menu-count:0/);
assert.throws(()=>uniqueAgentMenu([sidebar,{item:'other',box:{x:30,y:200,width:50,height:20}}]),/agent-menu-count:2/);
assert.equal(hardObservationError(Error('agent-menu-count:4')),true);
assert.equal(hardObservationError(Error('agent-menu-count:0')),false);
assert.equal(hardObservationError(Error('service-login-required')),true);
console.log(JSON.stringify({ok:true,tests:15,runtimeModelDecisions:0}));
