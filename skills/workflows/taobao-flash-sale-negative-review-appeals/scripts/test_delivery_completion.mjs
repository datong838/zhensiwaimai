import assert from 'node:assert/strict';
for (const flow of ['taobao-flash-sale-negative-review-appeals','meituan-waimai-negative-review-appeals']) {
  const {completeDelivery,summaryDisposition}=await import(`../../${flow}/scripts/deliver_batch.mjs`);
  const ok={ok:true,verified:true};
  assert.equal(completeDelivery(ok,ok).ok,true);
  assert.equal(completeDelivery(ok,{ok:false,state:'unknown'}).ok,false);
  assert.equal(completeDelivery(ok,null).verified,false);
  assert.equal(completeDelivery(ok,null,true).ok,true);
  assert.equal(completeDelivery({ok:false},ok).ok,false);
  assert.equal(completeDelivery(ok,{ok:true}).ok,false);
  assert.equal(summaryDisposition({state:'unknown',sendAttempts:1}),'reconcile');
  assert.equal(summaryDisposition({state:'attempted',sendAttempts:null}),'reconcile');
  assert.equal(summaryDisposition({state:'blocked',sendAttempts:0}),'pending');
  assert.equal(summaryDisposition({state:'verified',sendAttempts:1,...ok}),'verified');
  assert.equal(summaryDisposition({state:'blocked'}),'reconcile');
  assert.equal(summaryDisposition(null),'pending');
}
console.log(JSON.stringify({ok:true,tests:24,sendAttempts:0}));
