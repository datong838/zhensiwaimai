import assert from 'node:assert/strict';
import {resetIM} from './im_env_reset_20261008.mjs';
const target='https://waimaie.meituan.com/imworkbench/home?appId=4&clientType=140006#/im/page/workbench/reception';
let scenarios=0;
async function scenario({text='顾客消息 未回复',blocked=false,url=target,gotoFails=false,finalText=text,finalBlocked=blocked,closeFails=false,expectedInitial=true,expectedFinal=true}={}) {
 let oldClosed=0,foreignClosed=0,created=false,bodyReads=0;
 const old={url:()=>target,close:async()=>{if(closeFails)throw Error('close-failed');oldClosed++}};
 const foreignUrls=['https://example.com/imworkbench/home','https://waimaie.meituan.com.example.com/imworkbench/home','https://waimaie.meituan.com/login','https://www.workbuddy.cn/login'];
 const foreign=foreignUrls.map(u=>({url:()=>u,close:async()=>{foreignClosed++}}));
 const fresh={url:()=>url,goto:async()=>{if(gotoFails)throw Error('navigation-failed')},evaluate:async fn=>{
   if(fn.toString().includes('querySelectorAll'))return bodyReads>1?finalBlocked:blocked;
   bodyReads++;return bodyReads>1?finalText:text;
 }};
 const ctx={newPage:async()=>{created=true;return fresh},pages:()=>[...(oldClosed?[]:[old]),...foreign,...(created?[fresh]:[])]};
 let connected=0,disconnected=0;
 const browser={contexts:()=>[ctx],close:async()=>{disconnected++}};
 const result=await resetIM({chromium:{connectOverCDP:async()=>{connected++;return browser}},wait:async()=>{}});
 assert.equal(connected,1);assert.equal(disconnected,1);assert.equal(foreignClosed,0);
 assert.equal(oldClosed,expectedInitial&&!closeFails?1:0);
 assert.equal(result.ok,expectedInitial&&expectedFinal&&!closeFails);
 if(!expectedInitial){assert.equal(result.oldPagesPreserved,true);assert.equal(result.closed,0);}
 if(expectedInitial&&!expectedFinal&&!closeFails)assert.equal(result.finalHealth.ok,false);
 scenarios++;
}
await scenario();
await scenario({text:'unready',expectedInitial:false});
await scenario({blocked:true,expectedInitial:false});
await scenario({text:'顾客消息 noPermission',expectedInitial:false});
await scenario({text:'顾客消息 no Permission',expectedInitial:false});
await scenario({text:'顾客消息 登录已失效',expectedInitial:false});
await scenario({url:target.replace('/reception',''),expectedInitial:false});
await scenario({url:target.replace('waimaie.meituan.com','example.com'),expectedInitial:false});
await scenario({gotoFails:true,expectedInitial:false});
await scenario({finalText:'顾客消息 noPermission',expectedFinal:false});
await scenario({finalBlocked:true,expectedFinal:false});
await scenario({closeFails:true,expectedFinal:false});
console.log(JSON.stringify({ok:true,scenarios,realBrowserConnections:0}));
