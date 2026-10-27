import assert from 'node:assert/strict';
import {validateUiDeliveryEvidence as check} from './ui_delivery_evidence.mjs';
const expected={businessDate:'2026-10-23',runDay:'2026-10-24',groupName:'上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰',name:'差评分析数据_2026-10-23_2026-10-23.xlsx',sha256:'a'.repeat(64),size:18940};
const proof={state:'visible-delivery-confirmed',groupName:expected.groupName,fileName:expected.name,sourceSha256:expected.sha256,sourceBytes:expected.size,sendAttempts:1,originalUnknownMarkerPreserved:true,authorization:'用户本轮明确回复授权补发一次',sentAt:'2026-10-24T13:12:00+08:00'};
assert.equal(check(proof,expected).ok,true);
for(const change of [{state:'send-intent'},{groupName:'其他群'},{fileName:'other.xlsx'},{sourceSha256:'b'.repeat(64)},{sourceBytes:1},{sendAttempts:2},{originalUnknownMarkerPreserved:false},{authorization:''},{sentAt:'2026-10-23T13:12:00+08:00'}]) assert.equal(check({...proof,...change},expected).ok,false,JSON.stringify(change));
assert.equal(check(proof,{...expected,businessDate:'bad'}).ok,false);
assert.equal(check(proof,{...expected,sha256:'bad'}).ok,false);
console.log('PASS: 12 evidence cases; zero IO, browser, ledger or send effects');
