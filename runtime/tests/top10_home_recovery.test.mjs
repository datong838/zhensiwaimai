import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
const root=path.resolve(import.meta.dirname,'../..');
for(const [role,relative,url] of [
 ['taobao','skills/workflows/daily-top10-to-wechat-group/scripts/desktop_background_executor.mjs','https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard'],
 ['meituan','skills/workflows/daily-meituan-income-top10-to-wechat/scripts/income_collector.mjs','https://waimaie.meituan.com/?time=1793145624571&ignoreSetRouterProxy=true']
]){
 const live=path.join(root,relative);let module;
 if(process.env.TOP10_HOME_CANDIDATES==='1'){
  let source=await fs.readFile(path.join(root,'runtime/state/top10-home-recovery-20261028/candidates',role+'.mjs'),'utf8');
  source=source.replaceAll('import.meta.url',JSON.stringify(pathToFileURL(live).href));
  source=source.replace("from './desktop_executor.mjs'","from "+JSON.stringify(pathToFileURL(path.join(path.dirname(live),'desktop_executor.mjs')).href));
  module=await import('data:text/javascript;base64,'+Buffer.from(source).toString('base64'));
 }else module=await import(pathToFileURL(live).href);
 const go=module.gotoHomeWithRecovery;
 function fixture(sequence){let now=0,closed=false,calls=[];const page={isClosed:()=>closed,async goto(actual,options){assert.equal(this,page);calls.push({url:actual,...options});const step=sequence[calls.length-1];assert.ok(step,'unexpected extra navigation');now+=step.ms||0;if(step.close)closed=true;if(step.error)throw step.error;}};return {page,calls,clock:()=>now,setNow:x=>now=x};}
 const failure=(address=url)=>new Error('page.goto: net::ERR_CONNECTION_CLOSED at '+address+'\nCall log:\n fixture');
 test(role+' normal path stays one navigation',async()=>{const f=fixture([{}]);const r=await go(f.page,url,{clock:f.clock});assert.equal(f.calls.length,1);assert.equal(r.attempts,1);assert.equal(r.recovered,false);assert.equal(f.calls[0].timeout,30000);});
 test(role+' one exact connection close recovers same page and URL',async()=>{const f=fixture([{error:failure(),ms:10000},{ms:1000}]);const r=await go(f.page,url,{clock:f.clock});assert.equal(r.recovered,true);assert.equal(r.attempts,2);assert.deepEqual(f.calls.map(c=>c.url),[url,url]);assert.equal(f.calls[1].timeout,20000);assert.equal(r.elapsedMs,11000);});
 test(role+' second failure is final and original exception retained',async()=>{const second=failure();const f=fixture([{error:failure()},{error:second}]);await assert.rejects(go(f.page,url,{clock:f.clock}),e=>e===second&&e.homeNavigationRecovery.attempts===2&&!e.homeNavigationRecovery.recovered);assert.equal(f.calls.length,2);});
 for(const message of ['page.goto: Timeout 30000ms exceeded','page.goto: net::ERR_NAME_NOT_RESOLVED','page.goto: net::ERR_CONNECTION_REFUSED','login-required','captcha-required','page.goto: Target page has been closed'])test(role+' other failure never retried: '+message,async()=>{const error=new Error(message),f=fixture([{error}]);await assert.rejects(go(f.page,url,{clock:f.clock}),e=>e===error);assert.equal(f.calls.length,1);});
 test(role+' connection close at another URL not eligible',async()=>{const f=fixture([{error:failure('https://unrelated.invalid/')}]);await assert.rejects(go(f.page,url,{clock:f.clock}));assert.equal(f.calls.length,1);});
 test(role+' closed page not retried',async()=>{const f=fixture([{error:failure(),close:true}]);await assert.rejects(go(f.page,url,{clock:f.clock}));assert.equal(f.calls.length,1);});
 test(role+' exhausted original budget never gains another 30 seconds',async()=>{const f=fixture([{error:failure(),ms:30000}]);await assert.rejects(go(f.page,url,{clock:f.clock}));assert.equal(f.calls.length,1);});
 test(role+' remaining one millisecond is finite',async()=>{const f=fixture([{error:failure(),ms:29999},{}]);await go(f.page,url,{clock:f.clock});assert.equal(f.calls[1].timeout,1);});
 test(role+' invalid timeout rejected before touching browser',async()=>{for(const timeoutMs of [0,-1,30001,Infinity,NaN,true,1.5]){const f=fixture([]);await assert.rejects(go(f.page,url,{clock:f.clock,timeoutMs}));assert.equal(f.calls.length,0);}});
 test(role+' insecure or credentialed URL rejected before browser',async()=>{for(const address of ['http://example.invalid/','https://user:password@example.invalid/']){const f=fixture([]);await assert.rejects(go(f.page,address,{clock:f.clock}));assert.equal(f.calls.length,0);}});
 test(role+' post-navigation business error does not trigger navigation retry',async()=>{const f=fixture([{}]);await assert.rejects((async()=>{await go(f.page,url,{clock:f.clock});throw Error('income-header-not-unique');})(),/income-header-not-unique/);assert.equal(f.calls.length,1);});
}
