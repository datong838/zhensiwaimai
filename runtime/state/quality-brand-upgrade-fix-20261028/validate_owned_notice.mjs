// Maintenance only: exact owned target + original live lease; no optimization click.
import fs from 'node:fs/promises';
import {connectToPost} from '../../../skills/posts/taobao-svc-post/scripts/connect.mjs';
import {dismissKnownBrandUpgrade} from '../../../skills/workflows/daily-quality-products-optimization/scripts/quality_optimizer.mjs';
const [targetId,shopId,ownerPid]=process.argv.slice(2);
if(!targetId||!/^\d+$/.test(shopId||'')||!/^\d+$/.test(ownerPid||''))throw Error('exact-owned-target-required');
const lease=JSON.parse(await fs.readFile('/tmp/zhensi-post-9231.lock','utf8'));
if(lease.pid!==Number(ownerPid)||!String(lease.runId).startsWith('night-precheck-'))throw Error('original-maintenance-lease-required');
process.kill(lease.pid,0);
const {browser,context}=await connectToPost();
try{
 const matches=[];
 for(const page of context.pages()){
  let url;try{url=new URL(page.url());}catch{continue;}
  if(url.origin!=='https://melody.shop.ele.me'||url.pathname!=='/app/shop/'+shopId+'/food-rectify')continue;
  const session=await context.newCDPSession(page);
  try{if((await session.send('Target.getTargetInfo')).targetInfo.targetId===targetId)matches.push(page);}finally{await session.detach();}
 }
 if(matches.length!==1)throw Error('exact-maintenance-page-not-unique');
 const page=matches[0],before=await page.locator('[class^="updateModalWrapper__"]:visible').count();
 const notice=await dismissKnownBrandUpgrade(page,Date.now()+10000,shopId);
 const frames=page.frames().filter(f=>{try{const u=new URL(f.url());return u.origin==='https://r.ele.me'&&u.pathname==='/napos-goods-quality-pc/rectify/home';}catch{return false;}});
 if(frames.length!==1)throw Error('exact-product-frame-required');
 let trial,reason;
 try{await frames[0].getByRole('button',{name:'一键优化类目详情',exact:true}).click({trial:true,timeout:4000});trial='passed-no-click';}
 catch(error){trial='blocked-no-click';reason=String(error.message).slice(0,4000);}
 console.log(JSON.stringify({ok:notice.dismissed===true&&trial==='passed-no-click',shopId,before,notice,
  after:await page.locator('[class^="updateModalWrapper__"]:visible').count(),trial,reason,productSubmissions:0,sendAttempts:0}));
}finally{await browser.close();}
