import {withTaskPage} from '../../aos-platform/plugins/browser/control-background-dedicated-chrome/scripts/run_task.mjs';

const options={profile:'jinsha-business',port:'9232',instance:'04304cc1-7979-4f53-b14c-6008605c4c87','task-id':'negative-daily-20260914'};
const result=await withTaskPage(options,async({page})=>{
 await page.goto('https://data.guoshuyufen.com/#/negativeAnalyse',{waitUntil:'domcontentloaded',timeout:30000});
 await page.waitForTimeout(5000);
 if(page.url().includes('#/login'))throw Error('jinsha-login-required');
 const inputs=await page.locator('input').evaluateAll(nodes=>nodes.filter(el=>el.offsetWidth||el.offsetHeight).map(el=>({placeholder:el.getAttribute('placeholder'),type:el.getAttribute('type'),value:el.value,className:String(el.className||'')})));
 const buttons=await page.locator('button').evaluateAll(nodes=>nodes.filter(el=>el.offsetWidth||el.offsetHeight).map(el=>({text:(el.innerText||'').trim(),className:String(el.className||''),disabled:el.disabled})));
 const radios=await page.locator('[role="radio"],input[type="radio"]').evaluateAll(nodes=>nodes.filter(el=>el.offsetWidth||el.offsetHeight).map(el=>({tag:el.tagName,text:(el.innerText||el.parentElement?.innerText||'').trim().slice(0,80),className:String(el.className||''),checked:el.checked??null,ariaChecked:el.getAttribute('aria-checked')})));
 const text=await page.locator('body').textContent();
 const totals=[...String(text||'').matchAll(/共\s*(\d+)\s*条/g)].map(x=>Number(x[1]));
 const labels=['美团外卖','淘宝闪购','京东到家','差评列表','开始日期','结束日期','下载','查询'].filter(x=>String(text||'').includes(x));
 await page.screenshot({path:'/Users/ddt/work/projects/ai_agent/outputs/yesterday-negative-20260914/negative-page.png',fullPage:false});
 return {url:page.url(),title:await page.title(),inputs,buttons,radios,totals,labels,textLength:String(text||'').length};
});
console.log(JSON.stringify(result));
