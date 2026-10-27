// Read-only evidence validation. This module does not authorize sending or mutate run state.
const GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
export function validateUiDeliveryEvidence(proof, expected) {
  const reject = reason => ({ok: false, reason});
  if (!/^\d{4}-\d{2}-\d{2}$/.test(expected.businessDate || '')) return reject('business-date-invalid');
  const name = `差评分析数据_${expected.businessDate}_${expected.businessDate}.xlsx`;
  if (proof?.state !== 'visible-delivery-confirmed') return reject('delivery-not-confirmed');
  if (proof.groupName !== GROUP || expected.groupName !== GROUP) return reject('target-mismatch');
  if (proof.fileName !== name || expected.name !== name) return reject('file-name-mismatch');
  if (!/^[a-f0-9]{64}$/.test(expected.sha256 || '') || proof.sourceSha256 !== expected.sha256) return reject('file-digest-mismatch');
  if (!Number.isSafeInteger(expected.size) || expected.size < 1 || proof.sourceBytes !== expected.size) return reject('file-size-mismatch');
  if (proof.sendAttempts !== 1 || proof.originalUnknownMarkerPreserved !== true) return reject('attempt-contract-invalid');
  if (proof.authorization !== '用户本轮明确回复授权补发一次') return reject('explicit-resend-authorization-missing');
  if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+08:00$/.test(proof.sentAt || '') || proof.sentAt.slice(0,10) !== expected.runDay) return reject('delivery-day-mismatch');
  return {ok: true, evidenceLevel: 'visible-ui-observation', originalBridgeUnchanged: true, newSendAttempts: 0};
}

export async function readUiDeliveryEvidence(config, groupName) {
  const fs = await import('node:fs/promises');
  const path = await import('node:path');
  const crypto = await import('node:crypto');
  const root = path.resolve(config.runDir, '../../../..');
  const proofPath = path.join(root, 'runtime/state', `negative-review-user-authorized-resend-${config.runDay.replaceAll('-', '')}.json`);
  let proof; try { proof = JSON.parse(await fs.readFile(proofPath, 'utf8')); } catch (error) { if(error.code === 'ENOENT') return null; throw error; }
  const bytes = await fs.readFile(config.report);
  const identity = {businessDate:config.businessDate,runDay:config.runDay,groupName,name:path.basename(config.report),size:bytes.length,sha256:crypto.createHash('sha256').update(bytes).digest('hex')};
  const result = validateUiDeliveryEvidence(proof, identity);
  if(!result.ok) throw Error(`external-ui-evidence-invalid:${result.reason}`);
  return {...result, proofPath, sourceSha256:identity.sha256, sourceBytes:identity.size, groupName, sentAt:proof.sentAt};
}
