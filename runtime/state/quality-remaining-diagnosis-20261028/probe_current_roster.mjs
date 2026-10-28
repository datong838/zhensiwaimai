// UI navigation and request identity metadata only. No request body, headers or response JSON.
export async function probeCurrentRoster({withPost,post,pw}){
 return await withPost(post,async()=>{
  const browser=await pw.chromium.connectOverCDP('http://127.0.0.1:9231');let page;
  const result={at:new Date().toISOString(),pages:[],events:[],sendAttempts:0,productSubmissions:0};
  const active=new Set(),ids=new WeakMap();let serial=0,phase='initial',lastFinished=Date.now();
  const matches=request=>request.url().includes('pageQueryOpenTaskMerchantList');
  async function stable(expected){
   let previous='';const until=Date.now()+20000;
   while(Date.now()<until){
    const value=await page.evaluate(()=>({page:Number(document.querySelector('.ant-pagination-item-active')?.textContent)||1,
     selected:document.querySelector('input[value="material_quality_entree_proportion_rate"]')?.checked,
     loading:!!document.querySelector('.ant-spin-spinning'),
     next:!!document.querySelector('li.ant-pagination-next:not(.ant-pagination-disabled)'),
     rows:[...document.querySelectorAll('tbody tr.ant-table-row')].map(row=>({key:row.getAttribute('data-row-key'),
      name:row.querySelector('td')?.innerText.trim(),metric:row.querySelectorAll('td')[1]?.innerText.trim()}))}));
    const signature=JSON.stringify(value);
    if(value.page===expected&&value.selected&&!value.loading&&value.rows.length&&value.rows.every(r=>r.metric==='优质商品率低')
      &&active.size===0&&Date.now()-lastFinished>=500&&signature===previous)return value;
    previous=signature;await page.waitForTimeout(250);
   }
   throw Error('roster-network-and-ui-not-stable:'+expected);
  }
  try{
   page=await browser.contexts()[0].newPage();
   page.on('request',request=>{if(matches(request)){ids.set(request,++serial);active.add(request);result.events.push({kind:'request',id:serial,phase,origin:new URL(request.url()).origin,path:new URL(request.url()).pathname,at:Date.now()});}});
   page.on('response',response=>{const id=ids.get(response.request());if(id)result.events.push({kind:'response',id,phase,status:response.status(),at:Date.now()});});
   const finished=request=>{const id=ids.get(request);if(id){active.delete(request);lastFinished=Date.now();result.events.push({kind:'finished',id,phase,at:lastFinished});}};
   page.on('requestfinished',finished);page.on('requestfailed',finished);
   await page.goto('https://open.shop.ele.me/manager/base/abnormal-diagnosis',{waitUntil:'domcontentloaded',timeout:15000});
   const metric=page.locator('label').filter({has:page.locator('input[value="material_quality_entree_proportion_rate"]')});
   await metric.waitFor({state:'visible',timeout:10000});phase='metric-select';await metric.click();
   for(let number=1;number<=40;number++){
    const current=await stable(number);result.pages.push(current);
    if(!current.next)break;
    phase='page-'+(number+1);
    const requestP=page.waitForRequest(matches,{timeout:10000});requestP.catch(()=>{});
    await page.locator('li.ant-pagination-next:not(.ant-pagination-disabled)').click();
    const request=await requestP,response=await request.response();
    if(!response||response.status()!==200)throw Error('new-pagination-request-response-not-ok');
    await response.finished();
   }
   const rows=result.pages.flatMap(p=>p.rows),keys=rows.map(r=>r.key).filter(Boolean);
   result.rowCount=rows.length;result.uniqueRowKeys=new Set(keys).size;result.uniqueNames=new Set(rows.map(r=>r.name)).size;
   result.duplicateRowKeys=[...new Set(keys.filter((key,i)=>keys.indexOf(key)!==i))];
   result.lastPageHasNext=result.pages.at(-1)?.next;return result;
  }finally{try{if(page&&!page.isClosed())await page.close();}finally{await browser.close();}}
 });
}
