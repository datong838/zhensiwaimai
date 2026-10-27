import test from 'node:test';
import assert from 'node:assert/strict';
import {safeTaskId,inspectPage} from './run_task.mjs';

test('task ids are explicit and bounded',()=>{
  assert.equal(safeTaskId('daily-report-20260909'),true);
  assert.equal(safeTaskId(''),false);
  assert.equal(safeTaskId('../daily'),false);
  assert.equal(safeTaskId('Daily Report'),false);
});

function pageFixture(body,url='https://waimaie.meituan.com/'){
 const frame={url:()=>url,locator:()=>({first:()=>({innerText:async()=>body})})};
 return {url:()=>url,title:async()=>'美团外卖商家版',frames:()=>[frame],mainFrame:()=>frame,waitForTimeout:async()=>{}};
}
test('headless Meituan inspection reuses verified image-brand and security rules',async()=>{
 const o={profile:'meituan-merchant','task-id':'test-headless'};
 const body='全部门店 今日有效订单 今日预计收入 巡店助手 巡检门店';
 assert.equal((await inspectPage(pageFixture(body),o,'inspect')).authenticated,true);
 assert.equal((await inspectPage(pageFixture(body+' 安全验证'),o,'inspect')).authenticated,false);
 await assert.rejects(inspectPage(pageFixture(body,'https://example.com/'),o,'inspect'),/UNEXPECTED_TASK_URL/);
});
