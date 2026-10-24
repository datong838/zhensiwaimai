import assert from 'node:assert/strict';
import {datePairMatches,isCurrentMonthDateCell,messageFor,parseLogicalRows,selectionAudit,stableIncremental,uniqueAgentMenu,hardObservationError,waitForUniqueDateCandidate} from './background_merchant_collector.mjs';

const rows=[
  {merchantId:'2',recommendTime:'2026-09-10 10:00:00',merchantName:'乙'},
  {merchantId:'1',recommendTime:'2026-09-10 10:00:00',merchantName:'甲'},
  {merchantId:'3',recommendTime:'2026-09-10 11:00:00',merchantName:'丙'},
];
const selected=stableIncremental(rows,{merchantId:'1',recommendTime:'2026-09-10 10:00:00'},'2026-09-10');
assert.deepEqual(selected.map(row=>row.merchantId),['3']);
assert.equal(messageFor({city:'上海市',contact:'姚，13800000000',merchantName:'店',address:'地址',merchantId:'1338580316'}),'城市：上海市  ；  联系人：姚，13800000000  ；  店铺：店  ；  地址：地址  ；  商家ID：1338580316');
assert.equal(messageFor({city:'多\n行城市',contact:'姚，13800000000',merchantName:'店',address:'地址',merchantId:'1338580316'}),'城市：多 行城市  ；  联系人：姚，13800000000  ；  店铺：店  ；  地址：地址  ；  商家ID：1338580316');
assert.doesNotMatch(messageFor({city:'多\n行城市',contact:'',merchantName:'',address:'',merchantId:''}),/\n/);
assert.match(messageFor({city:'',contact:'',merchantName:'',address:'',merchantId:''}),/城市字段缺失/);
// 2026-10-22：游标行被运营处理移出「待处理」队列（matches=0）⇒ 降级为时间水位，不阻塞当天增量、不重发
assert.deepEqual(stableIncremental(rows,{merchantId:'9',recommendTime:'2026-09-10 10:00:00'},'2026-09-10').map(row=>row.merchantId),['3']);
assert.deepEqual(stableIncremental(rows,{merchantId:'9',recommendTime:'2026-09-10 10:30:00'},'2026-09-10').map(row=>row.merchantId),['3']);
assert.deepEqual(stableIncremental(rows,{merchantId:'9',recommendTime:'2026-09-10 11:00:00'},'2026-09-10').map(row=>row.merchantId),[]);
// 行身份仍不唯一（同一 merchantId+recommendTime 多行）⇒ 继续抛错，防重复外发
assert.throws(()=>stableIncremental([...rows,{merchantId:'1',recommendTime:'2026-09-10 10:00:00',merchantName:'甲重复'}],{merchantId:'1',recommendTime:'2026-09-10 10:00:00'},'2026-09-10'),/same-day-cursor-not-unique/);
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
const guardHeaders=['商家ID','商家名称','推荐时间','状态'];
const guardValid=['12345678','甲','2026-09-15 10:00:00','待处理'];
assert.throws(()=>parseLogicalRows(guardHeaders,[guardValid,['bad']]),/column-mismatch:1/);
assert.throws(()=>parseLogicalRows(guardHeaders,[guardValid,['invalid','乙','2026-09-16 10:00:00','待处理']]),/id-invalid:1/);
assert.throws(()=>parseLogicalRows(['商家ID','商家ID'],[['12345678','87654321']]),/headers-duplicate/);
const auditRows=[{merchantId:'1',recommendTime:'2026-09-15 10:00:00',status:'待处理'},
  {merchantId:'2',recommendTime:'2026-09-16 10:00:00',status:'完成'},
  {merchantId:'3',recommendTime:'2026-09-16 10:00:00',status:'待处理'}];
const auditCursor=auditRows[0];
assert.throws(()=>stableIncremental(auditRows,auditCursor,'2026-09-16'),/cursor-outside-filter-range/);
// 2026-10-22：游标行消失 ⇒ 时间水位继续（见 stableIncremental 修复注释），不再抛 cursor-not-unique
assert.deepEqual(stableIncremental(auditRows,{...auditCursor,merchantId:'missing'},'2026-09-15').map(row=>row.merchantId),['2','3']);
assert.throws(()=>stableIncremental([auditCursor,...auditRows],auditCursor,'2026-09-15'),/cursor-not-unique/);
const audit=selectionAudit(auditRows,auditCursor,'2026-09-15');
assert.deepEqual([audit.totalRows,audit.pendingRows,audit.excludedAtOrBeforeCursor,audit.excludedAfterCursorNotPending,audit.targetCount],[3,2,1,1,1]);
assert.equal(audit.totalRows,audit.excludedAtOrBeforeCursor+audit.excludedAfterCursorNotPending+audit.targetCount);
assert.deepEqual(stableIncremental(auditRows,auditRows[1],'2026-09-15').map(row=>row.merchantId),['3']);
assert.equal(selectionAudit(auditRows,auditRows[2],'2026-09-15').targetCount,0);
assert.equal(parseLogicalRows(guardHeaders,[guardValid]).length,1);
// 2026-10-08 F11-2：饿了么出现 6 位商家 ID（真实案值 712641，QQ鸡架锡纸花甲粉），
// 校验由 ^\d{7,}$ 放宽至 ^\d{6,}$；5 位仍拒。
assert.equal(parseLogicalRows(guardHeaders,[guardValid,['712641','QQ鸡架锡纸花甲粉','2026-10-07 21:35:09','待处理']])[1].merchantId,'712641');
assert.throws(()=>parseLogicalRows(guardHeaders,[guardValid,['12345','乙','2026-10-07 21:35:09','待处理']]),/id-invalid:1/);
const dateCellA={id:'first'},dateCellB={id:'second'};
assert.equal(isCurrentMonthDateCell(['ant-picker-cell','ant-picker-cell-in-view']),true);
assert.equal(isCurrentMonthDateCell(['ant-picker-cell','ant-picker-cell-in-view','ant-picker-cell-disabled']),false);
assert.equal(isCurrentMonthDateCell(['ant-picker-cell','ant-picker-cell-in-view ant-picker-cell-disabled']),false);
const monthScopedCandidates=[{id:'in-view',classes:['ant-picker-cell-in-view']},{id:'overflow',classes:['ant-picker-cell']},{id:'disabled',classes:['ant-picker-cell-in-view','ant-picker-cell-disabled']}].filter(item=>isCurrentMonthDateCell(item.classes));
assert.deepEqual(monthScopedCandidates.map(item=>item.id),['in-view']);
let candidateReads=0;
assert.equal(await waitForUniqueDateCandidate(async()=>++candidateReads===1?[dateCellA,dateCellB]:[dateCellB],'2026-09-28',{maxAttempts:3,delay:async()=>{}}),dateCellB);
candidateReads=0;
assert.equal(await waitForUniqueDateCandidate(async()=>++candidateReads===1?[]:[dateCellA],'2026-09-28',{maxAttempts:3,delay:async()=>{}}),dateCellA);
await assert.rejects(waitForUniqueDateCandidate(async()=>[dateCellA,dateCellB],'2026-09-28',{maxAttempts:3,delay:async()=>{}}),/calendar-day-count:2026-09-28:2/);
await assert.rejects(waitForUniqueDateCandidate(async()=>[],'2026-09-28',{maxAttempts:3,delay:async()=>{}}),/calendar-day-count:2026-09-28:0/);
candidateReads=0;
assert.equal(await waitForUniqueDateCandidate(async()=>++candidateReads===1?{candidates:[dateCellA,dateCellB],pickerCount:1}:{candidates:[dateCellB],pickerCount:1},'2026-09-28',{maxAttempts:3,delay:async()=>{}}),dateCellB);
await assert.rejects(waitForUniqueDateCandidate(async()=>({candidates:[dateCellA],pickerCount:2}),'2026-09-28',{maxAttempts:3,delay:async()=>{}}),/calendar-picker-count:2026-09-28:2/);
await assert.rejects(waitForUniqueDateCandidate(async()=>({candidates:[],pickerCount:0}),'2026-09-28',{maxAttempts:3,delay:async()=>{}}),/calendar-picker-count:2026-09-28:0/);
console.log(JSON.stringify({ok:true,tests:39,runtimeModelDecisions:0}));
