import test from 'node:test';
import assert from 'node:assert/strict';
import {parseMessageTime, latestCustomer, recentMetadata} from './message_time.mjs';
import {judge, readConversation} from './reply_unanswered_sessions.mjs';
const now = {date:'2026-10-28',h:12,m:0,clock:'12:00:00'};
const customer = (text, label) => ({side:'left',text,timeSource:'message-formattime',timeLabel:label});

test('body and preview clocks never authorize timeout without independent date label',()=>{
  for(const text of ['少送米饭 08:00','退款，约好11:00送到']) {
    const result=judge('甲** 08:00',[{side:'left',text}],now);
    assert.equal(result.qualify,false);assert.match(result.reason,/no-parseable-message-time/);
  }
});
test('latest request uses exact label regardless of forward or reverse DOM order',()=>{
  const old=customer('少送米饭','10-28 10:00:00'),latest=customer('好的谢谢','10-28 11:00:00');
  for(const messages of [[old,latest],[latest,old]]) {
    assert.equal(latestCustomer(messages,now).message,latest);
    assert.equal(judge('甲** 08:00',messages,now).qualify,false);
  }
});
test('newer eligible request is not replaced by old body clock',()=>{
  const old=customer('好的谢谢 11:59','10-28 10:00:00'),latest=customer('少送米饭，原约08:00送','10-28 11:00:00');
  assert.equal(judge('',[latest,old],now).qualify,true);
  assert.equal(latestCustomer([latest,old],now).message,latest);
});
test('strictly over ten minutes, including seconds',()=>{
  assert.equal(judge('',[customer('少送米饭','10-28 11:50:00')],now).qualify,false);
  assert.equal(judge('',[customer('少送米饭','10-28 11:50:01')],now).qualify,false);
  assert.equal(judge('',[customer('少送米饭','10-28 11:49:59')],now).qualify,true);
});
test('previous day and year boundary preserve actual elapsed time',()=>{
  const midnight={date:'2026-10-28',h:0,m:5,clock:'00:05:00'};
  assert.equal(judge('',[customer('配送还没收到','10-27 23:50:00')],midnight).qualify,true);
  assert.notEqual(parseMessageTime('12-31 23:50:00',{date:'2027-01-01',h:0,m:5}),null);
  assert.notEqual(parseMessageTime('2025-10-28 11:00:00',now),null);
});
test('invalid or future date, bare clock, and unknown source never qualify',()=>{
  for(const label of ['11:00','10-28 25:00:00','10-28 11:61:00','10-28 11:00:60','02-30 10:00:00','10-29 10:00:00','10-28 12:01:00','x10-28 10:00:00'])
    assert.equal(parseMessageTime(label,now),null,label);
  assert.equal(judge('',[{side:'left',text:'退款',timeSource:'preview',timeLabel:'10-28 10:00:00'}],now).qualify,false);
});
test('ambiguous latest customer timestamp or coverage stays conservative',()=>{
  assert.equal(judge('',[customer('退款','10-28 10:00:00'),customer('不要取消','10-28 10:00:00')],now).qualify,false);
  assert.equal(judge('',[customer('退款','10-28 10:00:00'),{side:'left',text:'少送米饭'}],now).qualify,false);
  assert.equal(judge('',[{...customer('退款','10-28 10:00:00'),timeContextUncertain:true}],now).qualify,false);
});
test('latest forty metadata selection is order independent',()=>{
  const values=Array.from({length:60},(_,i)=>({index:i,id:'id'+i,timeLabel:`10-28 10:${String(i).padStart(2,'0')}:00`}));
  for(const input of [values,[...values].reverse()]) {
    const result=recentMetadata(input,now);assert.equal(result.selected.length,40);
    assert.equal(result.selected[0].id,'id20');assert.equal(result.selected.at(-1).id,'id59');
  }
});
test('undated right-side card does not replace or invalidate dated customer request',()=>{
  const metadata=[{index:0,side:'left',timeLabel:'10-28 11:00:00'},
    {index:1,side:'right',timeLabel:''}];
  assert.equal(recentMetadata(metadata,now).uncertain,false);
  metadata[1].side='left';assert.equal(recentMetadata(metadata,now).uncertain,true);
});

function fixture(rows) {
  let textReads=0;
  const items=rows.map((row,index)=>({id:'message-'+index,
    get innerText(){textReads++;return row.text;},
    querySelector(selector){
      if(selector==='.message-wrapper')return {className:'message-wrapper '+(row.side||'left')+'-message',
        querySelectorAll:()=>[{textContent:row.label}],querySelector:()=>({innerText:'顾客昵称'})};
      return null;
    }}));
  return {items,reads:()=>textReads};
}
test('real reader sorts latest forty while preserving original text and bounded reads',async()=>{
  const f=fixture(Array.from({length:60},(_,i)=>({text:'原格式正文 '+i,label:`10-28 10:${String(i).padStart(2,'0')}:00`})).reverse());
  const previous=globalThis.document;globalThis.document={querySelectorAll:()=>f.items};let calls=0;
  try {
    const messages=await readConversation({evaluate:async(fn,arg)=>{if(++calls===2)assert.equal(f.reads(),0);return fn(arg);}},now);
    assert.equal(f.reads(),40);assert.equal(messages.length,40);assert.equal(messages[0].text,'原格式正文 20');assert.equal(messages.at(-1).text,'原格式正文 59');
    assert.equal(latestCustomer(messages,now).message.text,'原格式正文 59');
  }finally{globalThis.document=previous;}
});
test('real reader rejects metadata drift before reading any customer text',async()=>{
  const f=fixture([{text:'退款',label:'10-28 10:00:00'}]),previous=globalThis.document;
  globalThis.document={querySelectorAll:()=>f.items};let calls=0;
  try {
    await assert.rejects(readConversation({evaluate:async(fn,arg)=>{if(++calls===2)f.items[0].id='changed';return fn(arg);}},now),/snapshot-drift/);
    assert.equal(f.reads(),0);
  }finally{globalThis.document=previous;}
});
