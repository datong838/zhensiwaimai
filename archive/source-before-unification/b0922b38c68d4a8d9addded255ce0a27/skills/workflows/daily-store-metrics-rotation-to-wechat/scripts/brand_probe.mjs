import {session} from './lib/cdp.mjs';
import {isRestoredChain} from './capture_receipt.mjs';
import {assertAuthenticated} from '../../../posts/taobao-brand-post/scripts/auth.mjs';
let s;
try{
 s=await session({port:9230,width:0,height:0});
 const url=await s.mainEval('location.href');assertAuthenticated(url);
 if(process.argv.includes('--expect-chain')&&!isRestoredChain(url))throw Error('brand-restore-unverified');
 const safe=await s.mainEval(`(()=>{const t=document.body?.innerText||'';return {login:['扫码登录','账号密码登录','请重新登录'].some(x=>t.includes(x)),risk:['滑动验证','拖动滑块','账号存在风险'].some(x=>t.includes(x)),shell:['商家首页','商品管理','顾客管理','门店管理','数据中心'].filter(x=>t.includes(x)).length};})()`);
 if(!safe||safe.login||safe.risk||safe.shell<2)throw Error(safe?.risk?'brand-security-required':'brand-login-required');
 console.log(JSON.stringify({ok:true,port:9230,shell:true}));
}catch(e){console.log(JSON.stringify({ok:false,reason:/^[a-z-]+$/.test(e.message)?e.message:'brand-probe-failed'}));process.exitCode=3;}
finally{s?.cdp.close();}
// The shared CDP transport has timeout handles; this is a one-shot job, never a daemon.
setImmediate(()=>process.exit(process.exitCode||0));
