import assert from 'node:assert/strict';
import {resetIM} from './im_env_reset_20261008.mjs';
const target='https://waimaie.meituan.com/imworkbench/home?appId=4&clientType=140006#/im/page/workbench/reception';
async function scenario(healthy,blocked=false){
 let oldClosed=0,foreignClosed=0;
 const old={url:()=>target,close:async()=>{oldClosed++}};
 const foreign={url:()=> 'https://example.com/imworkbench/home',close:async()=>{foreignClosed++}};
 const fresh={url:()=>target,goto:async()=>{},evaluate:async fn=>fn.toString().includes('querySelectorAll')?blocked:(healthy?'顾客消息 未回复':'unready')};
 const ctx={newPage:async()=>fresh,pages:()=>[...(oldClosed?[]:[old]),foreign,fresh]};
 const browser={contexts:()=>[ctx],close:async()=>{}};
 const result=await resetIM({chromium:{connectOverCDP:async()=>browser},wait:async()=>{}});
 assert.equal(foreignClosed,0);
 assert.equal(oldClosed,healthy&&!blocked?1:0);
 assert.equal(result.ok,healthy&&!blocked);
}
await scenario(true);
await scenario(false);
await scenario(true,true);
console.log(JSON.stringify({ok:true,scenarios:3,realBrowserConnections:0}));
