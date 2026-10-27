import assert from 'node:assert/strict';
import {validateSnapshot,validAmount,REQUIRED,compact} from '../scripts/ranking_collector.mjs';
const fixture={title:'钻石商\n排名\n2/243',update:'2026-10-03更新，本月已更新等级',heading:'本月考核指标\n全部',metrics:REQUIRED.map(name=>({name,...(['本月新签商家数','服务中商家数'].includes(name)?{current:'82',required:'100',yesterday:'0'}:{current:'90.93%',required:'90.00%',yesterday:'90.51%'})}))};
let tests=0;
assert.equal(validateSnapshot(fixture).rank,2);tests++;
assert.equal(compact('90.\n93%'),'90.93%');tests++;
for(const value of ['90.93%','82','177.0','123/201','-1.25%','1,234.50']){assert.equal(validAmount(value),true);tests++;}
for(const value of ['--','NaN','20名','123/0','1,23','90.1%junk']){assert.equal(validAmount(value),false);tests++;}
for(const change of [{title:'钻石商 排名 0/243'},{title:'钻石商排名244/243'},{heading:'别的指标'},{update:''},{metrics:fixture.metrics.slice(1)},{metrics:[...fixture.metrics,fixture.metrics[0]]},{metrics:fixture.metrics.map((x,i)=>i?x:{...x,current:'--'})},{metrics:fixture.metrics.map((x,i)=>i?x:{...x,required:''})}]){assert.throws(()=>validateSnapshot({...fixture,...change}));tests++;}
for(const [name,value] of [['经营任务完成率','90'],['服务中商家数','90%']]){assert.throws(()=>validateSnapshot({...fixture,metrics:fixture.metrics.map(m=>m.name===name?{...m,current:value}:m)}));tests++;}
const more=validateSnapshot({...fixture,metrics:[...fixture.metrics,{name:'平均服务天数',current:'177.0',required:'35.0',yesterday:''},{name:'官代增长目标达成',current:'123/201',required:'',yesterday:''}]});assert.equal(more.metrics.length,10);tests++;
console.log(JSON.stringify({ok:true,tests,browserActions:0,sendAttempts:0}));
