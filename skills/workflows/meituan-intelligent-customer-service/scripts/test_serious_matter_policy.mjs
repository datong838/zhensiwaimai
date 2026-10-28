import test from 'node:test';
import assert from 'node:assert/strict';
import {judge,processCards} from './reply_unanswered_sessions.mjs';
const now={date:'2026-10-28',h:12,m:0};
const decide=text=>judge('甲**（测试店） 11:00',[{side:'left',text,timeSource:'message-formattime',timeLabel:'10-28 11:00:00'}],now);

test('explicit serious food, personal, payment and fraud cases never get generic fallback',()=>{
  for(const text of ['米饭里有虫子','餐里有异物','有蟑螂要求退款','这个菜变质了','食物过期了','味道有异味','餐品不卫生','食品安全问题','吃完腹泻了要求退款','食物中毒了','严重过敏要求退款','吃坏肚子','呕吐后去医院','我受伤了','骑手威胁我','支付异常要求退款','重复扣款申请退款','疑似盗刷','退款没到账，怀疑被骗','诈骗要求退款']){
    const d=decide(text+' 11:00');
    assert.equal(d.qualify,false,text);assert.equal(d.reply,'',text);assert.equal(d.escalate,true,text);
    assert.match(d.reason,/manual-review-required/);
  }
});

test('ordinary eligible requests keep original path and timeout gates',()=>{
  for(const text of ['少送一份米饭','餐具漏放','还没收到餐品','配送超时了','我想退款','配送到医院门口还没到']){
    const d=decide(text+' 11:00');assert.equal(d.qualify,true,text);assert.ok(d.reply);assert.notEqual(d.escalate,true);
    assert.equal(judge('甲** 11:55',[{side:'left',text:text+' 11:55',timeSource:'message-formattime',timeLabel:'10-28 11:55:00'}],now).qualify,false);
    assert.equal(judge('甲**',[{side:'left',text}],now).qualify,false);
  }
});

test('existing human response still excludes without a new escalation',()=>{
  const d=judge('甲** 11:00',[{side:'left',text:'米饭里有虫子 11:00'},
    {side:'right',nick:'店长',text:'您好已经在门店核实处理。'}],now);
  assert.equal(d.qualify,false);assert.notEqual(d.escalate,true);assert.match(d.reason,/owner-human-reply-present/);
});

test('real processCards serious branch never locates input or creates intent or ledger',async()=>{
  let cardClicks=0,forbiddenCalls=0;
  const page={locator(selector){
    if(selector.startsWith('[class*='))return {count:async()=>1,click:async()=>cardClicks++};
    if(selector.startsWith('.roo-modal-dialog'))return {filter:()=>({count:async()=>0})};
    forbiddenCalls++;throw Error('must-not-access-reply-controls:'+selector);
  },waitForTimeout:async()=>{},evaluate:async()=>[{side:'left',text:'米饭里有虫子 11:00'}]};
  const receipt={scanned:0,decisions:[],sent:[],failed:[],verificationPending:[]};
  await processCards(page,[{sessionId:'1234567890123456789',text:'甲**（测试店）11:00'}],receipt,now,new Set(),'未回复',
    {submissions:'/must-not-create-submission',appendLedger:async()=>assert.fail('must-not-write-ledger')});
  assert.equal(cardClicks,1);assert.equal(forbiddenCalls,0);assert.equal(receipt.sent.length,0);
  assert.equal(receipt.escalationRequired.length,1);assert.equal(receipt.decisions[0].qualify,false);
});
