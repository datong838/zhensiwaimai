// F11-3 离线 A/B 回归验证（零副作用：只读两份源码文本，不 import、不改文件、不联网）
// 用法: node scripts/test_f11_3_recovery_budget.mjs   （scripts 目录下亦可）
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';

const HERE = path.dirname(new URL(import.meta.url).pathname);
const CUR = path.join(HERE, 'background_browser_executor.mjs');
const OLD = HERE + '/background_browser_executor.mjs.bak-20261008-2055';

function extractLiteral(src, label) {
  const key = '\n    recoveryAttempts: {';
  const at = src.indexOf(key);
  if (at < 0) throw new Error(label + ': 未定位 recoveryAttempts 字面量');
  let i = src.indexOf('{', at), depth = 0, j = i;
  for (; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (depth === 0) break; }
  }
  return src.slice(i, j + 1);
}

// 上一轮 fixture：jinshaLogReload 已用满 budget(=1)（10-08 死锁现场），且已跨轮 resume 过 3 次
const FIXTURE = {
  recoveryAttempts: {
    'taobao-brandNavigation': 0, 'jinsha-businessNavigation': 0,
    taobaoAuthAnchorRecovery: 0, taobaoHomeReload: 0,
    jinshaLogReload: 1,
    jinshaBorrowedLogReload: 0, jinshaBorrowedLogReadRetry: 0,
    jinshaBorrowedStoreLogReadRetry: 0, jinshaBorrowedReviewLogReadRetry: 0,
    jinshaUploadOverlay: 0, productionResume: 3,
  },
};

const BUDGET = { jinshaLogReload: 1 };
function claim(receipt, key) {
  const used = receipt.recoveryAttempts[key] || 0;
  if (used >= BUDGET[key]) throw new Error('recovery-budget-exhausted:' + key);
  receipt.recoveryAttempts[key] = used + 1;
}

const targets = [['OLD(修复前 10-08 20:55 备份)', OLD], ['NEW(修复后 当前)', CUR]];
const results = {};
for (const [label, file] of targets) {
  const src = fs.readFileSync(file, 'utf8');
  const fn = new Function('resumeReceipt', 'return ' + extractLiteral(src, label) + ';');
  const inherited = fn(FIXTURE);
  let detail;
  try {
    claim({ recoveryAttempts: { ...inherited } }, 'jinshaLogReload'); // waitForCompletedLog 首次 reload
    detail = 'claim-ok(本轮可合法 reload 1 次)';
  } catch (e) { detail = e.message; }
  results[label] = {
    inherited_jinshaLogReload: inherited.jinshaLogReload,
    inherited_productionResume: inherited.productionResume,
    first_claim: detail,
  };
}

console.log('=== F11-3 恢复预算继承 · 离线 A/B 回归 ===');
console.log('fixture: 上一轮 recoveryAttempts.jinshaLogReload=1（budget=1，已耗尽）；productionResume=3');
console.log('');
for (const [k, v] of Object.entries(results)) {
  console.log(k);
  console.log('   继承后 jinshaLogReload =', v.inherited_jinshaLogReload);
  console.log('   继承后 productionResume =', v.inherited_productionResume);
  console.log('   本轮首次 claim =', v.first_claim);
  console.log('');
}

const oldOK = results['OLD(修复前 10-08 20:55 备份)'].inherited_jinshaLogReload === 1;
const newOK = results['NEW(修复后 当前)'].inherited_jinshaLogReload === 0;
const keepOK = results['NEW(修复后 当前)'].inherited_productionResume === 3;
console.log('断言:');
console.log('  [1] 旧版继承已耗尽预算(1) —— 复现当日死锁 :', oldOK ? 'PASS' : 'FAIL');
console.log('  [2] 新版回归单轮语义(0)  —— 死锁已解除    :', newOK ? 'PASS' : 'FAIL');
console.log('  [3] 新版仍保留跨轮代数 productionResume   :', keepOK ? 'PASS' : 'FAIL');
process.exit(oldOK && newOK && keepOK ? 0 : 1);
