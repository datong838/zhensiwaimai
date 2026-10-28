// A read-only maintenance export. The caller supplies the original lease and persistent CDP client.
export async function probeOriginalShop(deps,exactName,{allowOriginalRouteRestore=false}={}){
 const {withPost,post,pw,fs,child,repo}=deps;
 const day=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai'}).format(new Date());
 const state=JSON.parse(await fs.readFile(repo+'/skills/workflows/daily-quality-products-optimization/.runtime/days/'+day+'/state.json','utf8'));
 const prior=state.stores.find(s=>s.clickedRowName===exactName&&s.state==='blocked'&&!s.submission);
 const rowError=state.rowErrors?.find(s=>s.name===exactName);
 if(state.day!==day||(!prior&&!rowError))throw Error('current-day-original-unsubmitted-failure-required');
 if(state.stores.some(s=>s.clickedRowName===exactName&&s.submission))throw Error('prior-submission-readonly-diagnostic-not-authorized');
 const started=Date.now();
 return await withPost(post,async()=>{
  const browser=await pw.chromium.connectOverCDP('http://127.0.0.1:9231');
  let page,detail;
  const result={day,exactName,originalReason:prior?.reason||rowError.reason,originalShopId:prior?.shopId||null,
   productSubmissions:0,sendAttempts:0,scanTrace:[]};
  async function stablePage(expected,previousRows){
   let last='';const until=Date.now()+15000;
   while(Date.now()<until){
    const value=await page.evaluate(()=>({
     loading:!!document.querySelector('.ant-spin-spinning'),
     selected:document.querySelector('input[value="material_quality_entree_proportion_rate"]')?.checked,
     page:Number(document.querySelector('.ant-pagination-item-active')?.textContent)||1,
     next:!!document.querySelector('li.ant-pagination-next:not(.ant-pagination-disabled)'),
     filter:document.querySelector('input[placeholder="按组织/城市查找"]')?.value,
     status:[...document.querySelectorAll('.ant-select-selection-item')].map(e=>e.textContent.trim()).filter(t=>['未完成','已完成','全部'].includes(t)),
     rows:[...document.querySelectorAll('tbody tr.ant-table-row')].map(e=>[...e.querySelectorAll('td')].map(c=>c.innerText.trim()))
    }));
    const signature=JSON.stringify(value);
    if(value.selected&&!value.loading&&value.page===expected&&value.filter===''
      &&value.status.length===1&&value.status[0]==='未完成'&&value.rows.length
      &&value.rows.every(r=>r[1]==='优质商品率低')&&signature===last
      &&JSON.stringify(value.rows)!==previousRows)return value;
    last=signature;await page.waitForTimeout(250);
   }
   throw Error('diagnostic-merchant-page-not-stable:'+expected);
  }
  try{
   page=await browser.contexts()[0].newPage();
   await page.goto('https://open.shop.ele.me/manager/base/abnormal-diagnosis',{waitUntil:'domcontentloaded',timeout:15000});
   const label=page.locator('label').filter({has:page.locator('input[value="material_quality_entree_proportion_rate"]')});
   await label.waitFor({state:'visible',timeout:10000});await label.click();
   let previousRows=null;
   for(let number=1;number<=40;number++){
    const current=await stablePage(number,previousRows);
    result.scanTrace.push({page:number,rowCount:current.rows.length,hasNext:current.next});
    const indexes=current.rows.flatMap((r,i)=>r[0]===exactName?[i]:[]);
    if(indexes.length>1)throw Error('diagnostic-original-row-ambiguous');
    if(indexes.length===1){
     const row=page.locator('tbody tr.ant-table-row').nth(indexes[0]);
     if((await row.locator('td').first().innerText()).trim()!==exactName)throw Error('diagnostic-row-changed');
     const popup=page.waitForEvent('popup',{timeout:10000});
     await row.getByRole('button',{name:'去完成',exact:true}).click();detail=await popup;
     const until=Date.now()+10000;let observedId=null;
     while(Date.now()<until){
      const url=new URL(detail.url());
      observedId=url.origin==='https://melody.shop.ele.me'?url.pathname.match(/^\/app\/shop\/(\d+)\/food-rectify$/)?.[1]:null;
      if(observedId)break;
      await detail.waitForTimeout(250);
     }
     const url=new URL(detail.url());result.observedOrigin=url.origin;result.observedPath=url.pathname;
     result.observedShopId=observedId;
     if(!observedId){result.outcome='original-sso-did-not-reach-product-route';return result;}
     if(prior?.shopId&&observedId!==prior.shopId)throw Error('diagnostic-original-shop-id-mismatch');
     await detail.waitForTimeout(7000);
     if(detail.isClosed()){result.outcome='original-owned-popup-closed';return result;}
     const settled=new URL(detail.url());result.settledOrigin=settled.origin;result.settledPath=settled.pathname;
     result.settledTitle=await detail.title();
     const mainText=await detail.locator('body').innerText({timeout:3000});
     result.settledSignals=['扫码登录','账号登录','验证码','没有权限','无效店铺','当前账号无法访问','商品整改','加载失败','加载中','网络异常'].filter(word=>mainText.includes(word));
     if(settled.origin!=='https://melody.shop.ele.me'||settled.pathname!=='/app/shop/'+observedId+'/food-rectify'){
      const controls=detail.getByText('商品整改',{exact:true});result.rectifyControlCount=await controls.count();
      if(result.rectifyControlCount<=4)result.rectifyControls=await controls.evaluateAll(es=>es.map(e=>({tag:e.tagName,role:e.getAttribute('role'),href:e.getAttribute('href'),className:e.className,parentTag:e.parentElement?.tagName,parentRole:e.parentElement?.getAttribute('role'),parentHref:e.parentElement?.getAttribute('href'),visible:!!(e.getBoundingClientRect().width&&e.getBoundingClientRect().height)&&getComputedStyle(e).visibility!=='hidden'})));
      const safePath=['evaluate-group-buy','customer-receipt','customerStats'].some(module=>settled.pathname==='/app/shop/'+observedId+'/'+module);
      const titleMatches=result.settledTitle.replace(/\s+/g,'')===exactName.replace(/\s+/g,'');
      const blocked=result.settledSignals.some(word=>word!=='商品整改');
      const overlays=await detail.locator('.riskControlModal:visible,.ant-modal:visible,[role="dialog"]:visible,[class^="updateModalWrapper__"]:visible').count();
      if(!allowOriginalRouteRestore||!rowError||settled.origin!=='https://melody.shop.ele.me'||!safePath||!titleMatches||blocked||overlays){
       result.outcome='original-sso-left-product-route';return result;
      }
      result.originalRouteRestore={attempts:1,from:result.settledPath,shopId:observedId,matchedOriginalSso:true};
      await detail.goto('https://melody.shop.ele.me/app/shop/'+observedId+'/food-rectify',{waitUntil:'domcontentloaded',timeout:12000});
      await detail.waitForTimeout(7000);
      const restored=new URL(detail.url());result.originalRouteRestore.finalOrigin=restored.origin;result.originalRouteRestore.finalPath=restored.pathname;
      if(restored.origin!=='https://melody.shop.ele.me'||restored.pathname!=='/app/shop/'+observedId+'/food-rectify'){
       result.outcome='same-sso-original-route-restore-did-not-stay';return result;
      }
     }
     const session=await detail.context().newCDPSession(detail);
     let target;try{target=(await session.send('Target.getTargetInfo')).targetInfo.targetId;}finally{await session.detach();}
     const lease=JSON.parse(await fs.readFile('/tmp/zhensi-post-9231.lock','utf8'));
     const output=child.execFileSync('/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',
      [repo+'/runtime/state/quality-page-readiness-diagnosis-20261028/inspect_owned_product.mjs',target,observedId,String(lease.pid)],
      {encoding:'utf8',timeout:25000});
     return {...result,...JSON.parse(output.trim().split('\n').at(-1)),elapsedMs:Date.now()-started};
    }
    if(!current.next){result.outcome='not-present-in-current-uncompleted-roster';return result;}
    previousRows=JSON.stringify(current.rows);
    const responseP=page.waitForResponse(r=>r.url().includes('pageQueryOpenTaskMerchantList'),{timeout:10000});
    await page.locator('li.ant-pagination-next:not(.ant-pagination-disabled)').click();
    const response=await responseP;if(response.status()!==200)throw Error('diagnostic-pagination-response-not-ok');
    await response.finished();
   }
   throw Error('diagnostic-pagination-bound');
  }catch(error){
   result.outcome='diagnostic-stopped';result.error=String(error.message||error).replace(/wss?:\/\/\S+/g,'[endpoint]').slice(0,2500);
   return result;
  }finally{
   result.elapsedMs=Date.now()-started;
   try{if(detail&&!detail.isClosed())await detail.close();}
   finally{try{if(page&&!page.isClosed())await page.close();}finally{await browser.close();}}
  }
 });
}
