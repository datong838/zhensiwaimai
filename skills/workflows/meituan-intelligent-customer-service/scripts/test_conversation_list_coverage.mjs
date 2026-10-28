import test from 'node:test';
import assert from 'node:assert/strict';
import {collectAllCards} from './reply_unanswered_sessions.mjs';

async function fixture({rows=10,stalled=false,growOnce=false,forever=false,badId=false,height=100,startTop=0}={}){
  const oldDocument=globalThis.document,oldTimer=globalThis.setTimeout;
  let total=rows,top=startTop,ticks=0,grown=false;
  const sc={clientHeight:height,get scrollHeight(){return total*100},get scrollTop(){return top},
    set scrollTop(value){if(!stalled)top=Math.max(0,Math.min(value,total*100-height))}};
  const cards=()=>{
    const first=Math.floor(top/100),last=Math.min(total-1,Math.ceil((top+height)/100)-1);
    return Array.from({length:Math.max(0,last-first+1)},(_,i)=>({id:badId?'':String(1000000000000000000n+BigInt(first+i)),innerText:'相同预览'}));
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
