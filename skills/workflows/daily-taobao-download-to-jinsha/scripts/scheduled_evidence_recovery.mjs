import { userImagePrefix } from './user_image_prefix.mjs';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';

const RUN_ID = '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}';
const GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
const IMAGE_NAMES = ['jinsha-store-final.png', 'jinsha-review-final.png'];
const sha256 = (bytes) => crypto.createHash('sha256').update(bytes).digest('hex');

export function markerName(manifest) {
  return `${sha256(`${manifest.groupName}\n${manifest.businessDate}\n${manifest.images.map((image) => image.sha256).join('\n')}`)}.json`;
}

async function payloadBoundToRun(payload, manifest, directory) {
  // 2026-10-03 受控维护（大同授权「方案 B：开搞」）：逐张绑定校验（名称/字节/路径归属）。
  if (!IMAGE_NAMES.includes(payload?.name)) return false;
  const image = manifest.images.find((item) => path.basename(item.path) === payload.name);
  if (!image || !/^[a-f0-9]{64}$/.test(image.sha256 || '') || payload.sha256 !== image.sha256) return false;
  const actualPath = await fs.realpath(image.path);
  if (path.dirname(actualPath) !== await fs.realpath(directory) || await fs.realpath(payload.path) !== actualPath) return false;
  const bytes = await fs.readFile(actualPath);
  return payload.size === bytes.length && sha256(bytes) === image.sha256;
}

function completedReceipt(receipt, businessDate, policyVersion, directory, sourceGroup = GROUP) {
  const manifest = receipt?.evidenceManifest;
  return receipt?.ok === true && receipt.stage === 'completed' && receipt.phase === 'completed'
    && receipt.cleanupStatus === 'completed' && Array.isArray(receipt.runReview)
    && receipt.reviewSummary?.controlPolicyVersion === policyVersion
    && receipt.businessDate === businessDate && manifest?.businessDate === businessDate
    && receipt.runId === manifest.runId && manifest.groupName === sourceGroup
    && manifest.executor === 'background-browser-executor'
    && manifest.channel === 'control-background-dedicated-chrome'
    && ['execute', 'verify-idempotency-only'].includes(manifest.mode)
    && ['store', 'review'].every((kind) =>
      ['uploaded-complete', 'skipped-existing-complete'].includes(manifest.uploadDecision?.[kind]))
    && Array.isArray(manifest.images) && manifest.images.length === 2
    && path.basename(directory) === `${businessDate}-${receipt.runId}`;
}

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key=>[key,canonical(value[key])]));
  return value;
}

async function blockedBeforeSend(marker, markerFile) {
  if (!(marker.state === 'blocked' && marker.verified === false
    && marker.sendAttempts === 0 && marker.newSendAttempts === 0
    && marker.commonReceipt?.status === 'blocked'
    && marker.commonReceipt.reason === marker.reason
    && Array.isArray(marker.commonReceipt.items) && marker.commonReceipt.items.length === 0
    && marker.sendReview?.at(-1)?.stage === 'preflight'
    && marker.sendReview.at(-1).status === 'failed')) return false;
  if (marker.reason === 'wechat-window-capture-failed') return true;
  if (!['wecom-preflight-failed:locate-fail:wecom-not-frontmost', 'ui-post-preflight-not-verified'].includes(marker.reason)) return false;
  const key=marker.commonReceipt.eventKey;
  if (!/^[a-f0-9]{64}$/.test(key||'')) return false;
  const event=path.join(path.dirname(markerFile),'.wechat-messaging','events',key);
  const expected=sha256(JSON.stringify(canonical({groupName:marker.groupName,accountAlias:'main-wechat',
    items:marker.payloads.map((payload,index)=>({itemId:String(index),type:'image',name:payload.name,size:payload.size,sha256:payload.sha256}))})));
  try {
    const binding=JSON.parse(await fs.readFile(path.join(event,'binding.json'),'utf8'));
    if (binding.digest !== expected) return false;
    for (const child of await fs.readdir(event,{withFileTypes:true})) {
      if (marker.reason === 'ui-post-preflight-not-verified') {
        if (child.isFile() && ['binding.json', '.lock'].includes(child.name)) continue;
        const index = marker.payloads.findIndex((_, i) => sha256(JSON.stringify([key, String(i)])) === child.name);
        if (!child.isDirectory() || index < 0) return false;
        const work = path.join(event, child.name), payload = marker.payloads[index];
        const children = await fs.readdir(work, {withFileTypes:true});
        if (children.length !== 1 || children[0].name !== 'payload' || !children[0].isDirectory()) return false;
        const files = await fs.readdir(path.join(work, 'payload'), {withFileTypes:true});
        if (files.length !== 1 || files[0].name !== payload.name || !files[0].isFile()) return false;
        const bytes = await fs.readFile(path.join(work, 'payload', payload.name));
        if (bytes.length !== payload.size || sha256(bytes) !== payload.sha256) return false;
        continue;
      }
      if (!child.isDirectory()) continue;
      try { await fs.stat(path.join(event,child.name,'delivery.json'));return false; }
      catch(error) { if(error.code!=='ENOENT') return false; }
    }
    return true;
  } catch { return false; }
}

function previouslyVerified(marker) {
  // 2026-10-03 受控维护：verified 收据按实际发送张数判定（1..2 张，items 与 payloads 对齐）。
  return marker.state === 'verified' && marker.verified === true
    && Number.isInteger(marker.sendAttempts) && marker.sendAttempts > 0
    && marker.commonReceipt?.ok === true
    && Array.isArray(marker.commonReceipt?.items)
    && marker.commonReceipt.items.length >= 1
    && marker.commonReceipt.items.length <= 2
    && marker.commonReceipt.items.length === (Array.isArray(marker.payloads) ? marker.payloads.length : -1)
    && marker.commonReceipt.items.every((item) => item.status === 'verified');
}

export async function inspectPendingEvidence({ root, ledger, businessDate, policyVersion }) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(businessDate || '') || !root || !ledger || !policyVersion) {
    throw new Error('scheduled-evidence-recovery-input-invalid');
  }
  const prefix=await userImagePrefix(businessDate);
  if(prefix){const receipt=JSON.parse(await fs.readFile(prefix.receiptFile,'utf8'));return {kind:'resume',receipt,receiptFile:prefix.receiptFile,userAcceptedNames:[prefix.name]};}
  const runDirectoryPattern = new RegExp(`^${businessDate}-${RUN_ID}$`);
  let entries;
  try {
    entries = await fs.readdir(root, { withFileTypes: true });
  } catch (error) {
    if (error?.code === 'ENOENT') return { kind: 'none' };
    throw error;
  }
  // 2026-10-03 受控维护（大同授权「方案 B：开搞」）：逐图 union 语义。
  // - 「已交付」= 某张 marker 绑定到某 run 目录且其 commonReceipt 对应项 status==='verified'；
  // - 两图全部已交付 → 'completed'（不再重发）；
  // - 存在绑定本 run 且含未交付图的非零尝试 marker → 'blocked'（需 reconcile，原语义保留）；
  // - 仅剩零尝试、发送前被拦的 marker → 'resume'（安全重发其缺失图）；
  // - 无法绑定到任何 run 的孤儿 marker 不再阻塞预检（16:43 半成品 marker 类事故改由
  //   发送端逐图去重兜底，避免整条流卡死）。
  const delivered = new Map();
  const blockedOpen = [];
  let resumeCandidate = null;
  for (const entry of entries) {
    if (!entry.isDirectory() || !runDirectoryPattern.test(entry.name)) continue;
    const directory = path.join(root, entry.name);
    const receiptFile = path.join(directory, 'receipt.json');
    let receipt;
    try {
      receipt = JSON.parse(await fs.readFile(receiptFile, 'utf8'));
    } catch (error) {
      if (error?.code === 'ENOENT') continue;
      throw new Error(`scheduled-evidence-receipt-invalid:${entry.name}`);
    }
    if (!completedReceipt(receipt, businessDate, policyVersion, directory)) continue;
    let ledgerEntries;
    try {
      ledgerEntries = await fs.readdir(ledger, { withFileTypes: true });
    } catch (error) {
      if (error?.code === 'ENOENT') continue;
      throw error;
    }
    for (const ledgerEntry of ledgerEntries) {
      if (!ledgerEntry.isFile() || !ledgerEntry.name.endsWith('.json') || ledgerEntry.name.endsWith('.bridge.lock')) continue;
      const markerFile = path.join(ledger, ledgerEntry.name);
      let marker;
      try {
        marker = JSON.parse(await fs.readFile(markerFile, 'utf8'));
      } catch {
        continue;
      }
      if (marker?.bridgeVersion !== 1 || marker.groupName !== GROUP || marker.payloadType !== 'image'
          || !Array.isArray(marker.payloads) || marker.payloads.length < 1 || marker.payloads.length > 2
          || marker.attemptMarker !== markerFile) continue;
      let bound = true;
      for (const payload of marker.payloads) {
        bound = await payloadBoundToRun(payload, receipt.evidenceManifest, directory);
        if (!bound) break;
      }
      if (!bound) continue;
      const items = Array.isArray(marker.commonReceipt?.items) ? marker.commonReceipt.items : [];
      const verifiedNames = marker.payloads
        .filter((payload, index) => items[index]?.status === 'verified')
        .map((payload) => payload.name);
      if (previouslyVerified(marker)) {
        for (const name of marker.payloads.map((payload) => payload.name)) {
          if (!delivered.has(name)) delivered.set(name, { receipt, receiptFile, marker, markerFile });
        }
        continue;
      }
      const unverifiedNames = marker.payloads.map((payload) => payload.name).filter((name) => !delivered.has(name) && !verifiedNames.includes(name));
      if (unverifiedNames.length === 0) continue;
      if (await blockedBeforeSend(marker, markerFile) && marker.sendAttempts === 0) {
        if (!resumeCandidate) resumeCandidate = { receipt, receiptFile, marker, markerFile };
        continue;
      }
      blockedOpen.push({ name: unverifiedNames[0], receipt, receiptFile, marker, markerFile });
    }
  }
  if (blockedOpen.length > 0) {
    const match = blockedOpen[0];
    return { kind: 'blocked', reason: 'scheduled-evidence-external-effect-reconcile-required',
      receipt: match.receipt, receiptFile: match.receiptFile, marker: match.marker, markerFile: match.markerFile };
  }
  if (IMAGE_NAMES.every((name) => delivered.has(name))) {
    const full = [...delivered.values()].find((match) => match.marker.payloads.length === 2)
      || [...delivered.values()].at(-1);
    return { kind: 'completed', receipt: full.receipt, receiptFile: full.receiptFile, marker: full.marker, markerFile: full.markerFile };
  }
  if (resumeCandidate) {
    return { kind: 'resume', receipt: resumeCandidate.receipt, receiptFile: resumeCandidate.receiptFile,
      marker: resumeCandidate.marker, markerFile: resumeCandidate.markerFile };
  }
  return { kind: 'none' };
}


// 历史UI交付独立证据：只读核对，不改旧marker，不冒充附件像素回读。
export async function inspectHistoricalUIDelivery({ root, ledger, businessDate, policyVersion, evidenceFile }) {
  if (!evidenceFile) return { kind: 'none' };
  if (!/^\d{4}-\d{2}-\d{2}$/.test(businessDate || '') || !root || !ledger || !policyVersion) throw Error('historical-ui-input-invalid');
  let evidence;
  try { evidence = JSON.parse(await fs.readFile(evidenceFile, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return { kind: 'none' }; throw Error('historical-ui-evidence-invalid'); }
  const deny = (reason) => ({ kind: 'blocked', reason: `historical-ui-${reason}` });
  if (evidence.groupName !== GROUP || evidence.channel !== 'cua-visible-ui'
      || evidence.originalMarkerPreserved !== true || evidence.status !== 'both-visible-delivery-confirmed'
      || typeof evidence.authorization !== 'string' || !evidence.authorization.trim()
      || evidence.items?.length !== 2) return deny('scope-invalid');
  for (const item of evidence.items) {
    const sent = new Date(item.at);
    const dayAfter = new Date(`${businessDate}T12:00:00+08:00`); dayAfter.setUTCDate(dayAfter.getUTCDate()+1);
    if (Number.isNaN(sent.getTime()) || sent.toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'})
        !== dayAfter.toLocaleDateString('en-CA',{timeZone:'Asia/Shanghai'})
        || item.state !== 'visible-delivery-confirmed' || item.sendAttempts !== 1
        || !/^[a-f0-9]{64}$/.test(item.sha256 || '') || !item.verification) return deny('item-invalid');
    try { if (sha256(await fs.readFile(item.source)) !== item.sha256) return deny('copy-drift'); }
    catch { return deny('copy-unavailable'); }
  }
  const matches = [];
  for (const entry of await fs.readdir(root, { withFileTypes:true })) {
    if (!entry.isDirectory() || !new RegExp(`^${businessDate}-${RUN_ID}$`).test(entry.name)) continue;
    const directory=path.join(root,entry.name), receiptFile=path.join(directory,'receipt.json');
    let receipt; try { receipt=JSON.parse(await fs.readFile(receiptFile,'utf8')); } catch { continue; }
    const sourceGroup=receipt?.evidenceManifest?.groupName;
    // 用户已明确将原FEIBING结果迁运营群；保留原收据群名，绝不改写历史。
    if (![GROUP,'FEIBING NEO AI数字员工'].includes(sourceGroup)
        || !completedReceipt(receipt,businessDate,policyVersion,directory,sourceGroup)) continue;
    const images=receipt.evidenceManifest.images;
    if (!images.every((image,index)=>path.basename(image.path)===IMAGE_NAMES[index]
        && image.sha256===evidence.items[index].sha256)) continue;
    for (const image of images) {
      try { if (path.dirname(await fs.realpath(image.path))!==await fs.realpath(directory)
          || sha256(await fs.readFile(image.path))!==image.sha256) return deny('original-drift'); }
      catch { return deny('original-unavailable'); }
    }
    matches.push({receipt,receiptFile});
  }
  if (matches.length !== 1) return deny('production-match-not-unique');
  // 历史UI证据不得掩盖其他原事件的未知发送。
  for (const entry of await fs.readdir(ledger,{withFileTypes:true})) {
    if (!entry.isFile() || !entry.name.endsWith('.json')) continue;
    let marker;try {marker=JSON.parse(await fs.readFile(path.join(ledger,entry.name),'utf8'));}catch{return deny('ledger-invalid');}
    if (!marker.payloads?.some(payload=>path.basename(path.dirname(payload.path||'')).startsWith(`${businessDate}-`))) continue;
    if (![GROUP,'FEIBING NEO AI数字员工'].includes(marker.groupName) || marker.bridgeVersion !== 1 || marker.payloadType !== 'image') return deny('ledger-scope-invalid');
    if (previouslyVerified(marker)) continue;
    if (marker.state !== 'blocked' || marker.sendAttempts !== 0 || marker.newSendAttempts !== 0
        || marker.commonReceipt?.status !== 'blocked' || marker.commonReceipt?.items?.length !== 0)
      return deny('unsettled-original-event');
  }
  return {kind:'historical-ui-completed',...matches[0],
    historicalUIDelivery:{status:'reconciled-historical-ui',verification:'historical-visible-ui-observation',
      evidenceFile,evidenceSha256:sha256(await fs.readFile(evidenceFile)),
      sourceHashes:evidence.items.map(item=>item.sha256),newSendAttempts:0,
      limitation:'Historical visible delivery observation; not attachment pixel or byte readback.'}};
}
