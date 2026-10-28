import test from 'node:test';
import assert from 'node:assert/strict';
import {revealSessionCard} from './session_card_locator.mjs';
import {processCards} from './reply_unanswered_sessions.mjs';
const id = i => String(1234567890123456789n + BigInt(i));

async function virtual(options, action) {
  const previous = globalThis.document, timer = globalThis.setTimeout;
  let top = options.start || 0, height = 1200;
  const sc = {clientHeight:100,
    get scrollTop(){return top;},set scrollTop(value){if(!options.stalled)top=Math.max(0,Math.min(value,height-100));},
    get scrollHeight(){if(options.grow)height+=100;return height;}};
  const cards = () => options.duplicate ? [{id:id(0)},{id:id(0)}]
    : Array.from({length:20},(_,i)=>({id:id(i),index:i,closest:()=>sc,parentElement:sc}))
      .filter(x=>x.index*60>=top && x.index*60<top+100);
  globalThis.document={querySelectorAll:()=>cards(),querySelector:s=>s.includes('sessionListContent')?sc:cards()[0]};
  globalThis.setTimeout=callback=>{callback();return 0;};
  try {await action({page:{evaluate:(fn,arg)=>fn(arg)},top:()=>top,sc});}
  finally{globalThis.document=previous;globalThis.setTimeout=timer;}
}
test('offscreen exact ID is revealed without click and original viewport restored',async()=>{
  await virtual({},async f=>{
    const result=await revealSessionCard(f.page,id(15));assert.equal(result.found,true);assert.ok(f.top()>0);
    await result.restore();assert.equal(f.top(),0);
  });
});
test('search wraps once from middle to earlier exact card and restores middle',async()=>{
  await virtual({start:500},async f=>{
    const result=await revealSessionCard(f.page,id(0));assert.equal(result.found,true);assert.equal(f.top(),0);
    await result.restore();assert.equal(f.top(),500);
  });
});
test('genuinely absent session remains not found and restores original viewport',async()=>{
  await virtual({start:500},async f=>{
    const result=await revealSessionCard(f.page,id(99));assert.equal(result.found,false);assert.equal(f.top(),500);
  });
});
test('duplicate exact ID and invalid identity rejected without guessing',async()=>{
  await virtual({duplicate:true},async f=>{await assert.rejects(revealSessionCard(f.page,id(0)),/not-unique/);assert.equal(f.top(),0);});
  await assert.rejects(revealSessionCard({evaluate:()=>assert.fail('no UI')},'invalid'),/id-unavailable/);
});
test('stalled scrolling and perpetual growth fail, never return partial absence',async()=>{
  await virtual({start:500,stalled:true},async f=>{await assert.rejects(revealSessionCard(f.page,id(19)),/scroll-stalled/);assert.equal(f.top(),500);});
  await virtual({grow:true,start:200},async f=>{await assert.rejects(revealSessionCard(f.page,id(99)),/location-incomplete/);assert.equal(f.top(),200);});
});
test('current exact card requires no scrolling or restore',async()=>{
  await virtual({},async f=>{const result=await revealSessionCard(f.page,id(0));assert.equal(result.found,true);assert.equal(result.restore,null);assert.equal(f.top(),0);});
});

function originalProcessFixture() {
  const state={count:0,clicks:0,restore:0};
  const page={locator(selector){
    if(selector.startsWith('[class*='))return {count:async()=>state.count,click:async()=>state.clicks++};
    if(selector.startsWith('.roo-modal-dialog'))return {filter:()=>({count:async()=>0})};
    assert.fail('must never access input or send controls:'+selector);
  },waitForTimeout:async()=>{},evaluate:async()=>[]};
  const receipt={scanned:0,decisions:[],sent:[],failed:[],verificationPending:[]};
  const entries=[{sessionId:id(1),text:'甲**（测试店）'}];
  return {state,page,receipt,entries};
}
test('original process does not count absent virtual card checked or done; next view can finish it',async()=>{
  const f=originalProcessFixture(),done=new Set(),options={
    revealCard:async()=>({found:false,restore:async()=>f.state.restore++}),
    appendLedger:async()=>assert.fail('no ledger')};
  const now={date:'2026-10-28',h:12,m:0};
  assert.equal(await processCards(f.page,f.entries,f.receipt,now,done,'未回复',options),0);
  assert.equal(done.size,0);assert.equal(f.receipt.locatePending.length,1);assert.equal(f.state.clicks,0);
  assert.ok(!JSON.stringify(f.receipt).includes(id(1)));assert.equal(f.state.restore,1);
  f.state.count=1;
  assert.equal(await processCards(f.page,f.entries,f.receipt,now,done,'正在接待',options),1);
  assert.equal(f.receipt.locatePending.length,0);assert.equal(done.size,1);assert.equal(f.state.clicks,1);
  assert.equal(f.receipt.sent.length,0);
});
test('original process rechecks unique identity after reveal before opening',async()=>{
  const f=originalProcessFixture(),done=new Set();
  await assert.rejects(processCards(f.page,f.entries,f.receipt,{date:'2026-10-28',h:12,m:0},done,'未回复',{
    revealCard:async()=>{f.state.count=2;return {found:true,restore:async()=>f.state.restore++};}
  }),/not-unique/);
  assert.equal(f.state.restore,1);assert.equal(f.state.clicks,0);assert.equal(done.size,0);
});
test('revealed viewport is restored when conversation read fails',async()=>{
  const f=originalProcessFixture();f.page.evaluate=async()=>{throw Error('read-failed');};
  await assert.rejects(processCards(f.page,f.entries,f.receipt,{date:'2026-10-28',h:12,m:0},new Set(),'未回复',{
    revealCard:async()=>{f.state.count=1;return {found:true,restore:async()=>f.state.restore++};}
  }),/read-failed/);
  assert.equal(f.state.restore,1);assert.equal(f.state.clicks,1);assert.equal(f.receipt.sent.length,0);
});
