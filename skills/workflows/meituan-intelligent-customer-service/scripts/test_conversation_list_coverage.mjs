import test from 'node:test';
import assert from 'node:assert/strict';
import {collectAllCards,processCards} from './reply_unanswered_sessions.mjs';

async function fixture({rows=10,stalled=false,growOnce=false,forever=false,badId=false,height=100,startTop=0,missingIdAt=-1}={}){
  const oldDocument=globalThis.document,oldTimer=globalThis.setTimeout;
  let total=rows,top=startTop,ticks=0,grown=false;
  const sc={clientHeight:height,get scrollHeight(){return total*100},get scrollTop(){return top},
    set scrollTop(value){if(!stalled)top=Math.max(0,Math.min(value,total*100-height))}};
  const cards=()=>{
    const first=Math.floor(top/100),last=Math.min(total-1,Math.ceil((top+height)/100)-1);
    return Array.from({length:Math.max(0,last-first+1)},(_,i)=>({id:badId?'invalid-nonempty-id':first+i===missingIdAt?'':String(1000000000000000000n+BigInt(first+i)),innerText:'相同预览'}));
  };
  globalThis.document={querySelector:s=>s.includes('sessionListContent')?sc:cards()[0],querySelectorAll:cards};
  globalThis.setTimeout=fn=>{ticks++;if(forever)total++;if(growOnce&&!grown&&top+height>=total*100){total+=2;grown=true;}queueMicrotask(fn);return 1};
  try{return {cards:await collectAllCards({evaluate:fn=>fn()}),top,ticks,total};}
  catch(error){error.restoredTop=top;error.ticks=ticks;throw error;}
  finally{globalThis.document=oldDocument;globalThis.setTimeout=oldTimer;}
}

test('small viewport scan covers every exact ID without 200px gaps',async()=>{
  const result=await fixture();assert.equal(result.cards.length,10);assert.equal(new Set(result.cards.map(x=>x.sessionId)).size,10);assert.equal(result.top,0);
});
test('bottom delayed height growth is collected within the same original budget',async()=>{
  const result=await fixture({growOnce:true});assert.equal(result.total,12);assert.equal(result.cards.length,12);assert.equal(result.top,0);
});
test('nonzero starting viewport still scans prefix and restores original position',async()=>{
  const result=await fixture({startTop:400});assert.equal(result.cards.length,10);assert.equal(result.cards[0].sessionId,'1000000000000000000');assert.equal(result.top,400);
  await assert.rejects(fixture({stalled:true,startTop:400}),e=>e.message==='customer-list-start-not-top'&&e.restoredTop===400);
});
test('stalled scroll rejects partial list and restores viewport',async()=>{
  await assert.rejects(fixture({stalled:true}),e=>e.message==='customer-list-scroll-stalled'&&e.restoredTop===0);
});
test('continuous growth ends as incomplete at budget, never partial success',async()=>{
  await assert.rejects(fixture({forever:true}),e=>e.message==='customer-list-scan-incomplete'&&e.ticks===301&&e.restoredTop===0);
});
test('invalid card identity fails before any reply and invalid viewport is not complete',async()=>{
  await assert.rejects(fixture({badId:true}),/session-id-unavailable/);
  await assert.rejects(fixture({height:0}),/viewport-unavailable/);
});


test('missing external identity is isolated without input or submission',async()=>{
 const receipt={scanned:0,decisions:[],sent:[],failed:[],verificationPending:[]};
 await processCards({locator(){assert.fail('missing-ID must not access controls')}},[{sessionId:'',text:'旧会话摘要',identityUnavailable:true}],receipt,{date:'2026-10-28',h:12,m:0},new Set());
 assert.equal(receipt.identityPending.length,1);assert.equal(receipt.identityPending[0].newSubmitCalls,0);assert.equal(receipt.sent.length,0);
});


test('whole discovery retains identifiable cards plus explicit missing-identity entry',async()=>{
 const result=await fixture({missingIdAt:3});assert.equal(result.cards.length,10);
 assert.equal(result.cards.filter(x=>/^\d{19}$/.test(x.sessionId)).length,9);
 assert.equal(result.cards.filter(x=>x.identityUnavailable===true).length,1);
});

for(const [question,pending] of [['我不喜欢给差评，我也不想给差评，看怎么处理吧。',false],['少送米饭 11:00',true]]) test('unique full missing-ID card inspected read-only: '+question,async()=>{
 let clicks=0,forbidden=0;
 const identity='甲**（测试店） 10/27 '+question;
 const card={innerText:async()=>identity,click:async()=>clicks++};
 const list={count:async()=>1,nth:()=>card};
 const page={locator(selector){
   if(selector.includes(':not([id])'))return list;
   if(selector.startsWith('.roo-modal-dialog'))return {filter:()=>({count:async()=>0})};
   forbidden++;throw Error('missing ID must never access input or send');
 },waitForTimeout:async()=>{},evaluate:async()=>[{side:'left',text:question,timeSource:'message-formattime',timeLabel:'10-28 11:00:00'}]};
 const receipt={scanned:0,decisions:[],sent:[],failed:[],verificationPending:[]};
 await processCards(page,[{sessionId:'',text:identity,identityUnavailable:true,textComplete:true}],receipt,{date:'2026-10-28',h:12,m:0},new Set());
 assert.equal(clicks,1);assert.equal(forbidden,0);assert.equal(receipt.sent.length,0);
 assert.equal(!!receipt.identityPending?.length,pending);assert.equal(receipt.decisions[0].readOnlyMissingIdentity,true);
});

test('ambiguous missing-ID preview remains pending and is never opened',async()=>{
 let clicks=0;
 const item={innerText:async()=>'同一预览',click:async()=>clicks++};
 const page={locator:()=>({count:async()=>2,nth:()=>item})};
 const receipt={scanned:0,decisions:[],sent:[],failed:[],verificationPending:[]};
 await processCards(page,[{sessionId:'',text:'同一预览',identityUnavailable:true,textComplete:true}],receipt,{date:'2026-10-28',h:12,m:0},new Set());
 assert.equal(clicks,0);assert.equal(receipt.identityPending.length,1);
});
