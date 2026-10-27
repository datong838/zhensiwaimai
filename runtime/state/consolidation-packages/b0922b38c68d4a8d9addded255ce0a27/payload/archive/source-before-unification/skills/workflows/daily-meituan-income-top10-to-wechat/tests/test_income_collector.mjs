import assert from 'node:assert/strict';
import {expandHeaders,incomeIndex,sortLeafIndex,validateRows,amount,yesterday} from '../scripts/income_collector.mjs';
const cell=(text,rowSpan=1,colSpan=1)=>({text,rowSpan,colSpan});
const headers=[[cell('排名',2),cell('门店名称',2),cell('订单收入',1,2),cell('订单实付',1,2)],[cell('数值'),cell('涨跌'),cell('数值'),cell('涨跌')]];
const matrix=Array.from({length:10},(_,i)=>[String(i+1),'门店'+i,String(100-i),'999',String(i*10),'10']);
let tests=0;const snapshot={headers,matrix,sortOrders:['descending',null,null,null]};
assert.deepEqual(expandHeaders(headers),['排名','门店名称','订单收入/数值','订单收入/涨跌','订单实付/数值','订单实付/涨跌']);tests++;
assert.equal(incomeIndex(expandHeaders(headers)),2);tests++;
assert.equal(sortLeafIndex(expandHeaders(headers)),0);tests++;
assert.equal(validateRows(snapshot).rows[0].income,100);tests++;
assert.equal(yesterday(new Date('2026-10-25T17:00:00Z')),'2026-10-25');tests++;
assert.equal(amount('6,632.33'),6632.33);tests++;
for(const v of ['第1名','--','1,23.00','123涨跌','20%']){assert.throws(()=>amount(v));tests++;}
for(const bad of [{...snapshot,sortOrders:['ascending']},{...snapshot,matrix:matrix.slice(1)},{...snapshot,matrix:matrix.map((r,i)=>i===2?[...r.slice(0,2),'200',...r.slice(3)]:r)},{...snapshot,matrix:matrix.map(r=>['1',...r.slice(1)])}]){assert.throws(()=>validateRows(bad));tests++;}
assert.throws(()=>incomeIndex(['订单收入/涨跌','订单实付/数值']));tests++;
const swapped=[[cell('排名',2),cell('门店名称',2),cell('订单实付',1,2),cell('订单收入',1,2)],headers[1]];
assert.equal(sortLeafIndex(expandHeaders(swapped)),2);tests++;
console.log(JSON.stringify({ok:true,tests,browserActions:0,sendAttempts:0}));
