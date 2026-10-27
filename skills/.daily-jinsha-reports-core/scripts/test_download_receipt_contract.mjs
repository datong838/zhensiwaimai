import assert from 'node:assert/strict';
import { assertJinshaReleased, isCurrentDownloadUi } from './download_receipt_contract.mjs';

const waitStartedAt = 1_788_584_000_000;
const config = {runId:'jinsha-exam12'};
const valid = {
  runId:config.runId,
  startedAt:waitStartedAt,
  receiptIssuedAt:waitStartedAt + 1500,
  jinshaResourceReleased:true,
  jinshaReleasedAt:waitStartedAt + 1000,
};

assert.equal(isCurrentDownloadUi(config, valid, waitStartedAt), true);
assert.equal(isCurrentDownloadUi(config, {...valid, runId:'old-run'}, waitStartedAt), false);
assert.equal(isCurrentDownloadUi(config, {...valid, startedAt:waitStartedAt - 3000}, waitStartedAt), true);
assert.equal(isCurrentDownloadUi(config, {...valid, receiptIssuedAt:waitStartedAt - 3000}, waitStartedAt), false);
assert.doesNotThrow(() => assertJinshaReleased(valid));
assert.throws(() => assertJinshaReleased({...valid, jinshaResourceReleased:false}), /jinsha-not-released/);

console.log(JSON.stringify({ok:true,tests:6,externalActions:0,cases:['current-run','wrong-run','resume-start-can-be-old','stale-receipt','released','not-released']}));
