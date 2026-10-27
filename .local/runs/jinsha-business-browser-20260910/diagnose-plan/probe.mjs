import fs from 'node:fs/promises';
import {createRequire} from 'node:module';

const require=createRequire(import.meta.url);
const {chromium}=require('/Users/ddt/work/projects/ai_agent/aos-platform/plugins/browser/headless-playwright/node_modules/playwright-core');
const browser=await chromium.connectOverCDP('http://127.0.0.1:9232');
let page;
try {
  const context=browser.contexts()[0];
  page=await context.newPage();
  await page.addInitScript(()=>{window.name='aos-background-task:jinsha-plan-diagnose-01';});
  await page.goto('https://data.guoshuyufen.com/#/reportDownload',{waitUntil:'domcontentloaded',timeout:30000});
  await page.waitForTimeout(3000);
  const overlay=page.locator('.upload:visible').filter({hasText:'新功能上线'});
  if(await overlay.count()===1){const close=overlay.getByText('关闭',{exact:true});if(await close.count()===1)await close.click();}
  const taobao=page.getByText('淘宝闪购',{exact:true}).filter({visible:true});
  for(let i=0;i<await taobao.count();i++)if(await taobao.nth(i).isVisible()){await taobao.nth(i).click();break;}
  await page.waitForTimeout(500);
  const input=page.locator('input[placeholder="请选择下载方案"]:visible');
  if(await input.count()!==1)throw Error(`plan-input-count:${await input.count()}`);
  await input.click();await page.waitForTimeout(500);
  const candidates=await page.locator('.el-select-dropdown__item:visible, [role="option"]:visible').allInnerTexts();
  const lines=(await page.locator('body').innerText()).split('\n').map(value=>value.trim()).filter(value=>/(日报|最新|方案)/.test(value));
  const exactNodes=await page.locator('body *').evaluateAll(nodes=>nodes.filter(node=>node.children.length===0&&node.textContent.trim()==='饿了么...最新最新'&&getComputedStyle(node).visibility!=='hidden').map(node=>({tag:node.tagName,className:node.className,parentTag:node.parentElement?.tagName,parentClass:node.parentElement?.className})).slice(0,10));
  const plan=page.locator('.plan_li_one.plan_li_val').filter({hasText:'饿了么...最新最新'});
  if(await plan.count()===1)await plan.click();
  await page.waitForTimeout(500);
  const metricNodes={};
  for(const label of ['单均实付','单均到手'])metricNodes[label]=await page.locator('body *').evaluateAll((nodes,label)=>nodes.filter(node=>node.children.length===0&&node.textContent.trim()===label&&getComputedStyle(node).visibility!=='hidden').map(node=>({tag:node.tagName,className:node.className,parentTag:node.parentElement?.tagName,parentClass:node.parentElement?.className,grandTag:node.parentElement?.parentElement?.tagName,grandClass:node.parentElement?.parentElement?.className,parentHtml:node.parentElement?.outerHTML?.slice(0,500)})).slice(0,10),label);
  const stateTransitions={};
  for(const label of ['单均实付','单均到手']){
    const text=page.getByText(label,{exact:true});
    const visible=[];
    for(let i=0;i<await text.count();i++)if(await text.nth(i).isVisible())visible.push(text.nth(i));
    if(visible.length!==1)throw Error(`metric-text-count:${label}:${visible.length}`);
    const container=visible[0].locator('xpath=parent::div[contains(concat(" ",normalize-space(@class)," ")," check_one ")]');
    const icon=container.locator(':scope > span.checkSpan');
    const before={containerClass:await container.getAttribute('class'),iconClass:await icon.getAttribute('class'),selected:(await page.locator('body').innerText()).match(/已选择\s*[（(](\d+)[)）]/)?.[1]};
    await container.click();await page.waitForTimeout(250);
    const after={containerClass:await container.getAttribute('class'),iconClass:await icon.getAttribute('class'),selected:(await page.locator('body').innerText()).match(/已选择\s*[（(](\d+)[)）]/)?.[1]};
    stateTransitions[label]={before,after};
  }
  await page.screenshot({path:'/Users/ddt/work/projects/ai_agent/zhensi_waimai/.local/runs/jinsha-business-browser-20260910/diagnose-plan/page.png',fullPage:false});
  const receipt={ok:true,url:page.url(),currentValue:await input.inputValue(),candidates:[...new Set(candidates.map(value=>value.trim()).filter(Boolean))],relatedText:[...new Set(lines)],exactNodes,metricNodes,stateTransitions};
  await fs.writeFile('/Users/ddt/work/projects/ai_agent/zhensi_waimai/.local/runs/jinsha-business-browser-20260910/diagnose-plan/receipt.json',JSON.stringify(receipt,null,2),{mode:0o600});
  console.log(JSON.stringify(receipt));
} finally {if(page)await page.close().catch(()=>{});await browser.close();}
