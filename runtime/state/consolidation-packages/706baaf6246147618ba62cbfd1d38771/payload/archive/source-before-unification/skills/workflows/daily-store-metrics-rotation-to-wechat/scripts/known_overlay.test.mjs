import test from 'node:test';import assert from 'node:assert/strict';import {bindReminderAction,guardScreenshot} from './lib/known_overlay.mjs';
test('only known optional binding reminder can be skipped',()=>{const good={title:'绑定手机号提醒',text:'为保障您的账号与资产安全，建议绑定手机号。',buttons:['跳 过','去绑定']};assert.equal(bindReminderAction(good),'skip');assert.equal(bindReminderAction(null),'none');for(const patch of [{title:'安全验证'},{text:good.text+'验证码'},{buttons:['去绑定']},{buttons:['跳过','跳 过']}])assert.throws(()=>bindReminderAction({...good,...patch}));});
test('screenshot checks modal before dispatch and fails closed',async()=>{
 const calls=[];let result={action:'none'};
 const send=guardScreenshot(async m=>{calls.push(m);return 'png';},{mainEval:async()=>{calls.push('check');return result;},waitFor:async()=>true});
 assert.equal(await send('Page.captureScreenshot'),'png');assert.deepEqual(calls,['check','Page.captureScreenshot']);
 calls.length=0;result={error:'unknown-modal-blocked'};await assert.rejects(send('Page.captureScreenshot'),/unknown-modal/);assert.deepEqual(calls,['check']);
 calls.length=0;await send('Page.getFrameTree');assert.deepEqual(calls,['Page.getFrameTree']);
});
test('known reminder must disappear before screenshot',async()=>{
 let sent=0;const send=guardScreenshot(async()=>sent++,{mainEval:async()=>({action:'skipped-bind-reminder'}),waitFor:async()=>null});
 await assert.rejects(send('Page.captureScreenshot'),/still-visible/);assert.equal(sent,0);
});
