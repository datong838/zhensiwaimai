import assert from 'node:assert/strict';
import {merchantListRequest,changePage,merchantDom} from '../scripts/quality_optimizer.mjs';
const url='https://lsycm.alibaba.com/api/oShopOpTask/open/general/pageQueryOpenTaskMerchantList',frame={};
const request=(value=url,owner=frame)=>({url:()=>value,frame:()=>owner});let tests=0;
const telemetry=request('https://fourier.taobao.com/ts?source='+encodeURIComponent(url));
assert.equal(telemetry.url().includes('pageQueryOpenTaskMerchantList'),true);tests++;
assert.equal(merchantListRequest(telemetry,frame),false);tests++;
assert.equal(merchantListRequest(request(),frame),true);tests++;
for(const wrong of [request(url,{}),request('https://open.shop.ele.me'+new URL(url).pathname),
 request(url+'Count'),request(url+'/extra'),request('https://lsycm.alibaba.com/ts?source='+encodeURIComponent(url)),
 {url:()=>url,frame:()=>{throw Error('no-frame');}},{url:()=> 'bad-url',frame:()=>frame}]){
 assert.equal(merchantListRequest(wrong,frame),false);tests++;
}
assert.equal(merchantListRequest(request(),null),false);tests++;
let accept,resolveRequest,finished=false,reads=0,calledAfterClick=false;
const owner={mainFrame:()=>frame,
 waitForResponse:()=>{throw Error('must not accept an older in-flight response');},
 waitForRequest:predicate=>{accept=predicate;return new Promise(resolve=>resolveRequest=resolve);},
 evaluate:async()=>{reads++;return {page:2,loading:false,rows:[{name:finished?'new':'old'}]};}};
const oldResponse={status:()=>200,finished:async()=>{throw Error('old response must never be awaited');}};
const next=request();next.response=async()=>({status:()=>200,finished:async()=>{finished=true;}});
const answer=await changePage(owner,{click:async()=>{
 assert.equal(accept(telemetry),false);assert.equal(finished,false);
 assert.equal(typeof oldResponse.finished,'function');
 calledAfterClick=true;if(accept(next))resolveRequest(next);
}},merchantDom,Date.now()+2500,{page:1,rows:[{name:'old'}]});
assert.equal(calledAfterClick,true);assert.equal(finished,true);assert.equal(answer.rows[0].name,'new');assert.ok(reads>=2);tests++;
for(const response of [null,{status:()=>503,finished:async()=>{throw Error('non200 must not continue');}}]){
 const bad={...owner,waitForRequest:async()=>({response:async()=>response})};
 await assert.rejects(changePage(bad,{click:async()=>{}},merchantDom,Date.now()+2000,{page:1,rows:[]}),/quality-pagination-response-/);tests++;
}
console.log(JSON.stringify({ok:true,tests,browserActions:0,sendAttempts:0}));
