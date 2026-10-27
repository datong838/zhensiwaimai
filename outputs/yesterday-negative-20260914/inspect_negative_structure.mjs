import {withTaskPage} from '../../aos-platform/plugins/browser/control-background-dedicated-chrome/scripts/run_task.mjs';
const options={profile:'jinsha-business',port:'9232',instance:'04304cc1-7979-4f53-b14c-6008605c4c87','task-id':'negative-daily-20260914'};
console.log(JSON.stringify(await withTaskPage(options,async({page})=>{
 await page.goto('https://data.guoshuyufen.com/#/negativeAnalyse',{waitUntil:'domcontentloaded',timeout:30000});await page.waitForTimeout(4000);
 const selectors=['.shopName','.in_shop','.pointLi','.cryptonymText','.txt','.el-pagination__total','.download_btn'];
 const counts={};for(const s of selectors)counts[s]=await page.locator(s).count();
 let first=null;const shop=page.locator('.shopName').first();if(await shop.count())first=await shop.evaluate(el=>{const ancestors=[];let p=el;for(let i=0;i<7&&p;i++,p=p.parentElement)ancestors.push({tag:p.tagName,className:String(p.className||'')});const root=el.closest('.in_shop')||el.parentElement?.parentElement;return {ancestors,descendants:[...root.querySelectorAll('*')].map(x=>String(x.className||'')).filter(Boolean).slice(0,80)};});
 return {url:page.url(),counts,first};
})));
