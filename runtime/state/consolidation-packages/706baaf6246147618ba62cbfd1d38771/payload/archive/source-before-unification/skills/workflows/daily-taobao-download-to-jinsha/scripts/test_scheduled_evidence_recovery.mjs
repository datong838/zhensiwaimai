import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { inspectPendingEvidence, markerName } from './scheduled_evidence_recovery.mjs';

const sha256 = (value) => crypto.createHash('sha256').update(value).digest('hex');
const businessDate = '2026-09-27';
const policyVersion = 'daily-taobao-jinsha-code-enforced-2026-09-28';
const groupName = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
const temporary = await fs.mkdtemp(path.join(os.tmpdir(), 'taobao-evidence-recovery-test-'));
const root = path.join(temporary, 'evidence');
const ledger = path.join(temporary, 'ledger');
await fs.mkdir(root);
await fs.mkdir(ledger);

// 构造一个完成态 run 目录 + 双图证据，返回 {dir, manifest, payloads, receiptFile}
async function makeRun(runId) {
  const directory = path.join(root, `${businessDate}-${runId}`);
  await fs.mkdir(directory);
  const images = [];
  const payloads = [];
  for (const [index, name] of ['jinsha-store-final.png', 'jinsha-review-final.png'].entries()) {
    const imagePath = path.join(directory, name);
    const bytes = Buffer.from(`fixed-screenshot-${runId}-${index}`);
    await fs.writeFile(imagePath, bytes);
    images.push({ path: imagePath, sha256: sha256(bytes) });
    payloads.push({ path: await fs.realpath(imagePath), name, size: bytes.length, sha256: sha256(bytes) });
  }
  const evidenceManifest = {
    executor: 'background-browser-executor', channel: 'control-background-dedicated-chrome',
    runId, mode: 'execute', groupName, businessDate,
    uploadDecision: { store: 'uploaded-complete', review: 'uploaded-complete' }, images,
  };
  const receipt = {
    ok: true, stage: 'completed', phase: 'completed', cleanupStatus: 'completed',
    businessDate, runId, runReview: [], reviewSummary: { controlPolicyVersion: policyVersion },
    evidenceManifest,
  };
  const receiptFile = path.join(directory, 'receipt.json');
  await fs.writeFile(receiptFile, JSON.stringify(receipt));
  return { directory, manifest: evidenceManifest, payloads, receipt, receiptFile };
}

const writeJson = (file, value) => fs.writeFile(file, JSON.stringify(value));

try {
  assert.equal((await inspectPendingEvidence({ root, ledger, businessDate, policyVersion })).kind, 'none');

  // 场景 1：整对 marker —— blocked 零尝试 → resume
  const run1 = await makeRun('b75cb7e5-6904-415b-ba81-c1a8e4925a32');
  const pairMarkerFile = path.join(ledger, markerName(run1.manifest));
  const pairMarker = {
    bridgeVersion: 1, state: 'blocked', verified: false, groupName, payloadType: 'image',
    sendAttempts: 0, newSendAttempts: 0, reason: 'wechat-window-capture-failed',
    commonReceipt: { status: 'blocked', reason: 'wechat-window-capture-failed', items: [] },
    payloads: run1.payloads, attemptMarker: pairMarkerFile,
    sendReview: [{ stage: 'preflight', status: 'failed' }],
  };
  await writeJson(pairMarkerFile, pairMarker);
  let result = await inspectPendingEvidence({ root, ledger, businessDate, policyVersion });
  assert.equal(result.kind, 'resume');
  assert.equal(result.receipt.runId, run1.receipt.runId);
  assert.equal(result.markerFile, pairMarkerFile);
  // WeCom preflight is resumable only with a bound event and no item journal.
  const eventKey='a'.repeat(64),event=path.join(ledger,'.wechat-messaging','events',eventKey);
  await fs.mkdir(event,{recursive:true});
  const binding={accountAlias:'main-wechat',groupName,items:run1.payloads.map((v,i)=>({itemId:String(i),name:v.name,sha256:v.sha256,size:v.size,type:'image'}))};
  await writeJson(path.join(event,'binding.json'),{digest:sha256(JSON.stringify(binding))});
  const wecomMarker={...pairMarker,reason:'wecom-preflight-failed:locate-fail:wecom-not-frontmost',
    commonReceipt:{...pairMarker.commonReceipt,reason:'wecom-preflight-failed:locate-fail:wecom-not-frontmost',eventKey}};
  await writeJson(pairMarkerFile,wecomMarker);
  assert.equal((await inspectPendingEvidence({root,ledger,businessDate,policyVersion})).kind,'resume');
  await fs.mkdir(path.join(event,'item0'));
  await writeJson(path.join(event,'item0','delivery.json'),{status:'unknown'});
  assert.equal((await inspectPendingEvidence({root,ledger,businessDate,policyVersion})).kind,'blocked');
  await fs.rm(path.join(event,'item0'),{recursive:true});
  await writeJson(path.join(event,'binding.json'),{digest:'b'.repeat(64)});
  assert.equal((await inspectPendingEvidence({root,ledger,businessDate,policyVersion})).kind,'blocked');
  await writeJson(pairMarkerFile,{...wecomMarker,sendAttempts:null});
  assert.equal((await inspectPendingEvidence({root,ledger,businessDate,policyVersion})).kind,'blocked');
  await writeJson(pairMarkerFile,pairMarker);


  // 场景 2：整对 marker 非零尝试未 verified → blocked（需 reconcile）
  await writeJson(pairMarkerFile, { ...pairMarker, state: 'attempted', sendAttempts: 1 });
  result = await inspectPendingEvidence({ root, ledger, businessDate, policyVersion });
  assert.equal(result.kind, 'blocked');
  assert.equal(result.reason, 'scheduled-evidence-external-effect-reconcile-required');

  // 场景 3：整对 marker verified → completed
  await writeJson(pairMarkerFile, { ...pairMarker, state: 'verified', verified: true, sendAttempts: 2,
    commonReceipt: { ok: true, items: [{ status: 'verified' }, { status: 'verified' }] } });
  result = await inspectPendingEvidence({ root, ledger, businessDate, policyVersion });
  assert.equal(result.kind, 'completed');

  // 场景 4：无主/不绑定 marker（半成品，attemptMarker 缺失或 sha 不符）→ 不阻塞（'none'）
  await fs.rm(pairMarkerFile);
  await writeJson(path.join(ledger, 'orphan.json'), { bridgeVersion: 1, state: 'attempted', groupName,
    payloadType: 'image', payloads: [{ ...run1.payloads[0], sha256: '0'.repeat(64) }], verified: false });
  result = await inspectPendingEvidence({ root, ledger, businessDate, policyVersion });
  assert.equal(result.kind, 'none');

  // 场景 5：单图（保序子集）verified marker —— 只补语义
  const run2 = await makeRun('0e5a5b1c-0000-4000-8000-000000000002');
  // 5a：只 review 交付 → 无阻塞、未全交付 → 'none'（下轮由发送端补 store）
  const reviewOnlyFile = path.join(ledger, 'review-only.json');
  await writeJson(reviewOnlyFile, { bridgeVersion: 1, state: 'verified', verified: true, groupName,
    payloadType: 'image', sendAttempts: 1, newSendAttempts: 1,
    payloads: [run2.payloads[1]], attemptMarker: reviewOnlyFile,
    commonReceipt: { ok: true, items: [{ status: 'verified' }] } });
  result = await inspectPendingEvidence({ root, ledger, businessDate, policyVersion });
  assert.equal(result.kind, 'none');
  // 5b：store 由另一 marker 交付 → 两图齐 → 'completed'（跨 marker union）
  const storeOnlyFile = path.join(ledger, 'store-only.json');
  await writeJson(storeOnlyFile, { bridgeVersion: 1, state: 'verified', verified: true, groupName,
    payloadType: 'image', sendAttempts: 1, newSendAttempts: 1,
    payloads: [run2.payloads[0]], attemptMarker: storeOnlyFile,
    commonReceipt: { ok: true, items: [{ status: 'verified' }] } });
  result = await inspectPendingEvidence({ root, ledger, businessDate, policyVersion });
  assert.equal(result.kind, 'completed');
  // 5c：review marker sha 与 manifest 不符（不绑定）→ 回落为仅 store → 'none'
  await writeJson(reviewOnlyFile, { bridgeVersion: 1, state: 'verified', verified: true, groupName,
    payloadType: 'image', sendAttempts: 1,
    payloads: [{ ...run2.payloads[1], sha256: '1'.repeat(64) }], attemptMarker: reviewOnlyFile,
    commonReceipt: { ok: true, items: [{ status: 'verified' }] } });
  result = await inspectPendingEvidence({ root, ledger, businessDate, policyVersion });
  assert.equal(result.kind, 'none');

  // 场景 6：部分交付后遗留未交付图的非零尝试 marker → blocked
  const run3 = await makeRun('0e5a5b1c-0000-4000-8000-000000000003');
  const openFile = path.join(ledger, 'open-pair.json');
  await writeJson(openFile, { bridgeVersion: 1, state: 'attempted', verified: false, groupName,
    payloadType: 'image', sendAttempts: 1, newSendAttempts: 1,
    payloads: run3.payloads, attemptMarker: openFile,
    commonReceipt: { ok: false, status: 'unknown', items: [{ status: 'verified' }, { status: 'unknown' }] } });
  result = await inspectPendingEvidence({ root, ledger, businessDate, policyVersion });
  assert.equal(result.kind, 'blocked');
  assert.equal(result.reason, 'scheduled-evidence-external-effect-reconcile-required');

  console.log(JSON.stringify({ ok: true, checks: 18 }));
} finally {
  await fs.rm(temporary, { recursive: true, force: true });
}
