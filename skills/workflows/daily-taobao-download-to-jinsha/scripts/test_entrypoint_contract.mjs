import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

const source = path.join(path.dirname(fileURLToPath(import.meta.url)), 'entrypoint.mjs');
const installed = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/installed-taobao-skill/scripts/entrypoint.mjs';

function scheduledFunctionBody(code) {
  const start = code.indexOf('export async function runScheduled(...args) {');
  const end = code.indexOf('\nexport async function verifyTodayCompleted', start);
  assert.notEqual(start, -1, 'runScheduled-export-missing');
  assert.notEqual(end, -1, 'runScheduled-end-missing');
  return code.slice(start, end);
}

async function verify(file) {
  const code = await fs.readFile(file, 'utf8');
  assert.doesNotMatch(code, /export\s+async\s+function\s+sendScheduledEvidence\b/, 'scheduled-send-must-not-be-exported');
  assert.match(code, /async function sendScheduledEvidence\(receiptFile\)/, 'scheduled-send-private-step-missing');
  const body = scheduledFunctionBody(code);
  assert.equal((body.match(/sendScheduledEvidence\(workflowReceipt\.receiptFile\)/g) || []).length, 1, 'scheduled-send-call-not-unique');
  assert.match(code, /const MAX_SCHEDULED_WORKFLOW_ATTEMPTS = 3;/, 'scheduled-attempt-budget-missing');
  assert.match(body, /for \(let attempt = 1; !workflowReceipt && attempt <= MAX_SCHEDULED_WORKFLOW_ATTEMPTS;/, 'scheduled-attempt-loop-missing');
  assert.match(body, /inspectPendingEvidence\(/, 'original-evidence-recovery-inspection-missing');
  assert.match(body, /pending\.kind === 'resume'/, 'original-evidence-resume-branch-missing');
  assert.match(code, /scheduled-evidence-recovery-code-drift/, 'original-evidence-recovery-digest-gate-missing');
  assert.match(body, /continuationDecision\(workflowReceipt\)/, 'code-continuation-decision-missing');
  assert.match(body, /scheduled-workflow-attempt-budget-exhausted/, 'scheduled-attempt-budget-stop-missing');
  assert.match(body, /workflowAttempts: Object\.freeze\(workflowAttempts\)/, 'workflow-attempt-review-missing');
  assert.match(body, /sendExceptionResult\(workflowReceipt, error,/, 'structured-send-exception-missing');
  assert.match(body, /controlDecision: decision/, 'code-control-decision-missing');
  assert.match(body, /completionDisposition/, 'completion-disposition-missing');
  assert.doesNotMatch(body, /while\s*\(true\)/, 'unbounded-scheduled-loop-forbidden');
  assert.match(code, /failedReview\('entrypoint_preflight', '固定入口完整性预检'/, 'entrypoint-preflight-review-missing');
  assert.match(code, /failedReview\('sender_integrity_preflight', '微信发送器完整性预检'/, 'sender-preflight-review-missing');
  assert.match(code, /installed-entrypoint-drift/, 'installed-entrypoint-sync-gate-missing');
  assert.match(code, /selfTestHistoricalExperience\(\)/, 'historical-experience-self-test-missing');
  const entrypoint = await import(pathToFileURL(file).href);
  assert.equal('sendScheduledEvidence' in entrypoint, false, 'scheduled-send-public-export-forbidden');
  assert.equal(entrypoint.classifyIncompleteDisposition('taobao-login-expired').kind, 'await-user-authentication');
  assert.equal(entrypoint.classifyIncompleteDisposition('executor-code-drift').kind, 'repair-and-resume');
  assert.equal(entrypoint.classifyIncompleteDisposition('upload-result-unknown').kind, 'reconcile-external-effect');
  assert.equal(entrypoint.classifyIncompleteDisposition('sender-failed', true).kind, 'reconcile-external-effect');
  assert.equal(entrypoint.classifyIncompleteDisposition('executor-code-drift').mayEndTurn, false);
  assert.equal(entrypoint.classifyIncompleteDisposition('executor-code-drift').retryExternalEffect, false);
  const staleTarget = entrypoint.lookupHistoricalExperience({ pitfalls: [{
    code: 'controller-target-rebound', reason: 'stale-target-id-completed-business-workflow-marker',
  }] });
  assert.equal(staleTarget.caseId, 'jinsha-stale-target-matching-marker');
  assert.equal(staleTarget.mayRetryExternalEffect, false);
  const drift = entrypoint.lookupHistoricalExperience({ stage: 'dependency_integrity_preflight',
    reason: 'dependency-drift:scripts/heartbeat_recovery.py', sendAttempts: 0, items: [] });
  assert.equal(drift.caseId, 'wechat-dependency-drift-before-dispatch');
  assert.equal(drift.effectBoundary, 'proven-zero');
  const unprovenDrift = entrypoint.lookupHistoricalExperience({ stage: 'dependency_integrity_preflight',
    reason: 'dependency-drift:scripts/heartbeat_recovery.py', sendAttempts: null, items: [] });
  assert.equal(unprovenDrift.effectBoundary, 'unknown');
  assert.equal(unprovenDrift.mayRetryExternalEffect, false);
  assert.equal(entrypoint.lookupHistoricalExperience({ stage: 'preflight',
    reason: 'wechat-main-window-count-not-one', sendAttempts: 0, items: [] }).caseId,
  'wechat-main-window-preflight-ambiguity');
  assert.equal(entrypoint.lookupHistoricalExperience({ stage: 'preflight',
    reason: 'wechat-window-capture-failed', sendAttempts: 0, items: [] }).caseId,
  'wechat-window-id-capture-failed-before-send');
  const genericTimeout = entrypoint.lookupHistoricalExperience({ stage: 'preflight',
    reason: 'deadline-expired', sendAttempts: null, items: [] });
  assert.equal(genericTimeout.caseId, 'wechat-preflight-timeout-unproven');
  assert.equal(genericTimeout.effectBoundary, 'unknown');
  assert.equal(genericTimeout.mayRetryExternalEffect, false);
  const stoppedTaobao = entrypoint.lookupHistoricalExperience({ stage: 'profile_preflight',
    clickAttempts: { download: { store: 0 } },
    pitfalls: [{ code: 'fixed-profile-started', reason: 'stale-state-pid-restarted-same-dedicated-profile' }] });
  assert.equal(stoppedTaobao.caseId, 'taobao-fixed-profile-stopped');
  assert.equal(stoppedTaobao.mayRetryExternalEffect, false);
  const taobaoActivityShell = entrypoint.lookupHistoricalExperience({ stage: 'taobao_task_open',
    clickAttempts: { download: { store: 0 } },
    pitfalls: [{ code: 'auth-anchor-recovery', reason: 'unique-taobao-activity-shell-shopid-matched-live-frames' }] });
  assert.equal(taobaoActivityShell.caseId, 'taobao-activity-shell-auth-anchor');
  assert.equal(taobaoActivityShell.effectBoundary, 'send-not-applicable-production-receipt');
  assert.equal(taobaoActivityShell.mayRetryExternalEffect, false);
  assert.equal(entrypoint.lookupHistoricalExperience({ stage: 'preflight',
    reason: 'new-unseen-failure', sendAttempts: 0, items: [] }).status, 'unmatched');
  assert.equal(entrypoint.lookupHistoricalExperience({ stage: 'preflight',
    reason: 'new-unseen-failure', sendAttempts: 0, items: [] }).mayRetryExternalEffect, false);
  return { file, ok: true };
}

const [projectResult, installedResult] = await Promise.all([verify(source), verify(installed)]);
assert.deepEqual(await fs.readFile(source), await fs.readFile(installed), 'project-installed-entrypoint-drift');
console.log(JSON.stringify({ ok: true, projectResult, installedResult, checks: 50 }));
