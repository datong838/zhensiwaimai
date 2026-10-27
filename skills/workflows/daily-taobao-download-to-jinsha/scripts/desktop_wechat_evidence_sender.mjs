import { userImagePrefix } from './user_image_prefix.mjs';
import crypto from 'node:crypto';
import { readFileSync } from 'node:fs';
import fs from 'node:fs/promises';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

const exec = promisify(execFile);
const PYTHON_CANDIDATES = [
  '/Users/ddt/.workbuddy/binaries/python/envs/default/bin/python',
  '/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python',
  '/usr/bin/python3',
];
const SENDER = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/workflow_bridge_windows.py';
const SENDER_MANIFEST = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/dependencies.json';
const SENDER_MANIFEST_KEY = 'scripts/workflow_bridge_windows.py';
const LEDGER = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/.local/state/taobao-jinsha-wechat-evidence-attempts';
const EVIDENCE_ROOT = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/state/business-evidence/taobao-download/background-browser";
const OUTPUT_ROOT = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/state/business-evidence/taobao-download/desktop-wechat";
const GROUP_NAME = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
const SCHEDULED_POLICY_ID = 'user-approved-unattended-daily-2026-09-12';
const RESOURCE_WAIT_MS = 10 * 60_000;
const RESOURCE_RETRY_DELAY_MS = 5_000;
const SAFE_CONTENTION_STAGES = new Set(['locate_group', 'verify_target_and_input']);
const IMAGE_NAMES = ['jinsha-store-final.png', 'jinsha-review-final.png'];

function yesterdayShanghai(now = new Date()) {
  const date = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }));
  date.setDate(date.getDate() - 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function buildAuthorizationChallenge(manifest) {
  assertManifestShape(manifest);
  return challengeFor(manifest.images, manifest.groupName, manifest.businessDate);
}

// 2026-10-03 受控维护（大同授权「方案 B：开搞」）：授权挑战按实际发送集合生成；
// 两张时与旧格式逐字节一致（确认发送两张截图到…），一张时为「确认发送一张截图到…」。
export function challengeFor(items, groupName, businessDate) {
  const countWord = { 1: '一张', 2: '两张' }[items.length];
  if (!countWord) throw Error('evidence-challenge-count-invalid');
  return [
    `确认发送${countWord}截图到 ${groupName}`,
    `业务日期 ${businessDate}`,
    ...items.map((item) => `${path.basename(item.path)} ${item.sha256}`),
  ].join('\n');
}

// 逐图已交付核验：扫描台账（含 .voided-* 历史归档）中 bridgeVersion=1 的图片 marker，
// 凡 commonReceipt.items[i].status==='verified'（物理回读核验通过）且 payload 路径
// 归属同一业务日期 run 目录，即认定该图当日已交付。只读，不修改任何台账文件。
async function deliveredEvidenceNames(businessDate) {
  const delivered = new Set();
  const accepted=await userImagePrefix(businessDate);
  if(accepted)delivered.add(accepted.name);
  const scan = async (dir) => {
    let entries;
    try { entries = await fs.readdir(dir, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) { if (entry.name.startsWith('.voided-')) await scan(full); continue; }
      if (!entry.isFile() || !entry.name.endsWith('.json') || entry.name.endsWith('.bridge.lock')) continue;
      let marker;
      try { marker = JSON.parse(await fs.readFile(full, 'utf8')); } catch { continue; }
      if (marker?.bridgeVersion !== 1 || marker.groupName !== GROUP_NAME || marker.payloadType !== 'image') continue;
      if (!Array.isArray(marker.payloads) || !Array.isArray(marker.commonReceipt?.items)) continue;
      marker.payloads.forEach((payload, index) => {
        if (marker.commonReceipt.items[index]?.status !== 'verified') return;
        const parent = path.basename(path.dirname(String(payload?.path || '')));
        if (parent.startsWith(`${businessDate}-`) && IMAGE_NAMES.includes(payload?.name)) delivered.add(payload.name);
      });
    }
  };
  await scan(LEDGER);
  return delivered;
}

function assertManifestShape(manifest) {
  if (manifest?.executor !== 'background-browser-executor' || manifest?.channel !== 'control-background-dedicated-chrome') throw Error('evidence-manifest-origin-invalid');
  if (!['execute', 'verify-idempotency-only', 'download-and-verify-no-upload'].includes(manifest.mode)) throw Error('evidence-manifest-mode-invalid');
  if (manifest.groupName !== GROUP_NAME || manifest.businessDate !== yesterdayShanghai() || !/^[0-9a-f-]{36}$/i.test(manifest.runId || '')) throw Error('evidence-manifest-scope-invalid');
  for (const type of ['store', 'review']) {
    if (!['skipped-existing-complete', 'uploaded-complete'].includes(manifest?.uploadDecision?.[type])) throw Error(`evidence-upload-decision-invalid:${type}`);
  }
  if (!Array.isArray(manifest.images) || manifest.images.length !== 2) throw Error('evidence-image-count-invalid');
  const expectedNames = ['jinsha-store-final.png', 'jinsha-review-final.png'];
  manifest.images.forEach((item, index) => {
    const resolved = path.resolve(item?.path || '');
    const ownedPrefix = [EVIDENCE_ROOT, "/tmp/zhensi_daily_download/background-browser"].map(root => `${root}/${manifest.businessDate}-${manifest.runId}/`);
    if (!ownedPrefix.some(prefix => resolved.startsWith(prefix)) || path.basename(resolved) !== expectedNames[index] || !/^[a-f0-9]{64}$/.test(item?.sha256 || '')) {
      throw Error(`evidence-image-scope-invalid:${index}`);
    }
  });
}

export function isSafePreSendContention(receipt) {
  const reason = String(receipt?.reason || '');
  return receipt?.sendAttempts === 0 && SAFE_CONTENTION_STAGES.has(receipt?.stage) && (
    reason.startsWith('desktop-group-title-not-unique:') ||
    reason === 'desktop-chat-input-focus-failed'
  );
}

function parseReceipt(stdout) {
  const line = String(stdout || '').trim().split('\n').filter(Boolean).at(-1);
  if (!line) throw Error('desktop-wechat-receipt-missing');
  return JSON.parse(line);
}

function centralSenderHash(manifest, senderBytes) {
  const expected = manifest?.schemaVersion === 1 ? manifest?.files?.[SENDER_MANIFEST_KEY] : null;
  if (!/^[a-f0-9]{64}$/.test(expected || '')) throw Error('public-sender-central-manifest-invalid');
  const actual = crypto.createHash('sha256').update(senderBytes).digest('hex');
  if (actual !== expected) throw Error('desktop-wechat-public-sender-code-drift');
  return actual;
}

export function verifyCentralSenderIntegrity(senderPath = SENDER, manifestPath = SENDER_MANIFEST) {
  return centralSenderHash(JSON.parse(readFileSync(manifestPath, 'utf8')), readFileSync(senderPath));
}

async function invokeSender(python, args) {
  try {
    // 2026-10-03：发多张证据图要「上传 + 服务端 GUI 发送 + 回读验证」，原 190s 会在
    // 服务端仍处理时提前杀掉子进程，导致消息可能已送达但回执失败（与 #10 同款超时）。
    // 2026-10-25：等待真实UI任务结束，不按执行倒计时杀进程。
    const { stdout } = await exec(python, args, { maxBuffer: 4 * 1024 * 1024 });
    return parseReceipt(stdout);
  } catch (error) {
    if (error?.stdout) return parseReceipt(error.stdout);
    throw error;
  }
}

async function sendVerifiedManifest(manifest, authorization, authorizationMode, pendingOverride) {
  assertManifestShape(manifest);
  const evidenceStorageHelper = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/evidence_storage.mjs";
  if (crypto.createHash('sha256').update(await fs.readFile(evidenceStorageHelper)).digest('hex') !== 'ba84c386010a0a887f0103da38d170bc145c50a5846caf6d8fe58d26efd758d2') throw Error('evidence-storage-helper-drift');
  await (await import(`file://${evidenceStorageHelper}`)).ensureEvidenceAliases();
  const senderSha256 = verifyCentralSenderIntegrity();
  // 2026-10-03 受控维护（大同授权「方案 B：开搞」）：定时通道先做逐图已交付核验，
  // 只发送当日尚未核验交付的缺失图；全缺=原双图行为（授权话术/marker 键逐字节不变），
  // 全部已交付=不发并引用既有 verified marker 作为证据；手动通道保持整对授权不变。
  const pending = pendingOverride ?? manifest.images;
  if (pending.length === 0) {
    return {
      ok: true, groupName: manifest.groupName, imageSha256: [],
      alreadyDelivered: true, deliveredNames: manifest.images.map((item) => path.basename(item.path)),
      channel: 'desktop', authorizationMode,
      authorizationPolicyId: authorizationMode === 'scheduled-standing' ? SCHEDULED_POLICY_ID : null,
      publicSenderSha256: senderSha256, resourceWaitAttempts: 0, resourceWaitMs: 0,
      receipt: { ok: true, verified: true, reason: 'evidence-already-verified-in-ledger',
        sendAttempts: 0, items: [], runtimeModelDecisions: 0 },
    };
  }
  const hashes = [];
  for (const image of pending) {
    const bytes = await fs.readFile(image.path);
    const actual = crypto.createHash('sha256').update(bytes).digest('hex');
    if (actual !== image.sha256) throw Error('desktop-wechat-image-hash-mismatch');
    hashes.push(actual);
  }
  const marker = crypto.createHash('sha256').update(`${manifest.groupName}\n${manifest.businessDate}\n${hashes.join('\n')}`).digest('hex') + '.json';
  const args = [SENDER, '--workflow-id', 'taobao-evidence', '--group', manifest.groupName, '--payload-type', 'image', '--authorization', authorization,
    '--ledger', LEDGER, '--marker-name', marker, '--output-dir', OUTPUT_ROOT, '--execute'];
  for (const image of pending) args.push('--item', path.resolve(image.path));
  let python = null;
  for (const candidate of PYTHON_CANDIDATES) {
    try {
      await exec(candidate, ['-c', 'import AppKit, PIL'], { timeout: 3000 });
      python = candidate;
      break;
    } catch {}
  }
  if (!python) throw Error('desktop-wechat-python-runtime-missing');
  const waitStarted = performance.now();
  let resourceWaitAttempts = 0;
  let receipt;
  do {
    receipt = await invokeSender(python, args);
    if (receipt.verified === true || !isSafePreSendContention(receipt)) break;
    if (performance.now() - waitStarted + RESOURCE_RETRY_DELAY_MS > RESOURCE_WAIT_MS) break;
    resourceWaitAttempts += 1;
    await new Promise((resolve) => setTimeout(resolve, RESOURCE_RETRY_DELAY_MS));
  } while (true);
  return {
    ok: receipt.verified === true,
    groupName: manifest.groupName,
    imageSha256: hashes,
    ...(pending.length !== manifest.images.length
      ? { partialResend: true, skippedDeliveredNames: manifest.images.map((item) => path.basename(item.path)).filter((name) => !pending.some((image) => path.basename(image.path) === name)) }
      : {}),
    channel: 'desktop',
    authorizationMode,
    authorizationPolicyId: authorizationMode === 'scheduled-standing' ? SCHEDULED_POLICY_ID : null,
    publicSenderSha256: senderSha256,
    resourceWaitAttempts,
    resourceWaitMs: Math.round(performance.now() - waitStarted),
    receipt,
  };
}

export async function sendDesktopWechatEvidence(manifest, authorization) {
  assertManifestShape(manifest);
  const expectedAuthorization = buildAuthorizationChallenge(manifest);
  const actualAuthorization = String(authorization || '');
  if (actualAuthorization.length !== expectedAuthorization.length || !crypto.timingSafeEqual(Buffer.from(actualAuthorization), Buffer.from(expectedAuthorization))) {
    throw Error('wechat-evidence-authorization-mismatch');
  }
  return sendVerifiedManifest(manifest, actualAuthorization, 'manual-exact');
}

export async function sendScheduledDesktopWechatEvidence(manifest) {
  assertManifestShape(manifest);
  const delivered = await deliveredEvidenceNames(manifest.businessDate);
  const pending = manifest.images.filter((image) => !delivered.has(path.basename(image.path)));
  const fixedAuthorization = challengeFor(pending, manifest.groupName, manifest.businessDate);
  return sendVerifiedManifest(manifest, fixedAuthorization, 'scheduled-standing', pending);
}

export function selfTest() {
  if (!isSafePreSendContention({ stage: 'verify_target_and_input', sendAttempts: 0, reason: 'desktop-group-title-not-unique:0' })) throw Error('safe-contention-positive');
  if (isSafePreSendContention({ stage: 'locate_group', sendAttempts: 0, reason: 'desktop-open-group:desktop-wechat-preflight-failed' })) throw Error('generic-preflight-retry-forbidden');
  if (isSafePreSendContention({ stage: 'locate_group', sendAttempts: 0, reason: 'desktop-open-group:wechat-main-window-too-small' })) throw Error('login-window-retry-forbidden');
  if (isSafePreSendContention({ stage: 'prepare_payload', sendAttempts: 0, reason: 'desktop-group-title-not-unique:0' })) throw Error('prepared-payload-retry-forbidden');
  if (isSafePreSendContention({ stage: 'post_send_verify', sendAttempts: 1, reason: 'desktop-open-group:busy' })) throw Error('post-send-retry-forbidden');
  const businessDate = yesterdayShanghai();
  const runId = '50459ecd-01cb-452a-9e9f-f78588871317';
  const sample = {
    executor: 'background-browser-executor', channel: 'control-background-dedicated-chrome', runId,
    mode: 'verify-idempotency-only', groupName: GROUP_NAME, businessDate,
    uploadDecision: { store: 'skipped-existing-complete', review: 'skipped-existing-complete' },
    images: [
      { path: `${EVIDENCE_ROOT}/${businessDate}-${runId}/jinsha-store-final.png`, sha256: 'a'.repeat(64) },
      { path: `${EVIDENCE_ROOT}/${businessDate}-${runId}/jinsha-review-final.png`, sha256: 'b'.repeat(64) },
    ],
  };
  if (!buildAuthorizationChallenge(sample).includes('jinsha-review-final.png')) throw Error('authorization-challenge-self-test');
  if (!challengeFor(sample.images, GROUP_NAME, businessDate).startsWith('确认发送两张截图到')) throw Error('challenge-two-count-self-test');
  const singleChallenge = challengeFor([sample.images[0]], GROUP_NAME, businessDate);
  if (!singleChallenge.startsWith('确认发送一张截图到') || !singleChallenge.includes('jinsha-store-final.png')
      || singleChallenge.includes('jinsha-review-final.png')) throw Error('challenge-one-count-self-test');
  let countRejected = false;
  try { challengeFor([], GROUP_NAME, businessDate); } catch (error) { countRejected = error.message === 'evidence-challenge-count-invalid'; }
  if (!countRejected) throw Error('challenge-count-guard-self-test');
  let wrongOrderRejected = false;
  try { buildAuthorizationChallenge({ ...sample, images: [...sample.images].reverse() }); } catch (error) { wrongOrderRejected = error.message === 'evidence-image-scope-invalid:0'; }
  if (!wrongOrderRejected) throw Error('evidence-order-self-test');
  if (SCHEDULED_POLICY_ID !== 'user-approved-unattended-daily-2026-09-12') throw Error('scheduled-policy-self-test');
  const actualSenderSha256 = verifyCentralSenderIntegrity();
  let malformedRejected = false;
  try { centralSenderHash({ schemaVersion: 1, files: {} }, Buffer.from('x')); } catch (error) { malformedRejected = error.message === 'public-sender-central-manifest-invalid'; }
  if (!malformedRejected) throw Error('public-sender-central-manifest-negative-self-test');
  let driftRejected = false;
  try { centralSenderHash({ schemaVersion: 1, files: { [SENDER_MANIFEST_KEY]: 'a'.repeat(64) } }, Buffer.from('x')); } catch (error) { driftRejected = error.message === 'desktop-wechat-public-sender-code-drift'; }
  if (!driftRejected) throw Error('public-sender-drift-negative-self-test');
  return { ok: true, tests: 15, scheduledPolicyId: SCHEDULED_POLICY_ID, publicSenderSha256: actualSenderSha256,
    dependencyAuthority: SENDER_MANIFEST };
}
