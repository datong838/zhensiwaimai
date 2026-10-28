import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { noExecutableSuggestions } from '../scripts/quality_core.mjs';
const product = { taskId: '123', name: '测试商品', hasSuggestion: false,
  issues: [{ kind: '类目问题', current: '原类目', suggestion: '' }] };
const snapshot = { total: 1, products: [product], loading: false, hasNext: false };
let tests = 0;
assert.equal(noExecutableSuggestions(snapshot), true); tests++;
for (const change of [{ loading: true }, { hasNext: true }, { total: 2 }, { total: 0 },
  { products: [] }, { products: [{ ...product, taskId: '' }] },
  { products: [{ ...product, hasSuggestion: true }] }, { products: [{ ...product, hasSuggestion: null }] },
  { products: [{ ...product, issues: [] }] }, { products: [{ ...product, name: '' }] },
  { hasNext: undefined }, { loading: undefined }, { total: NaN }]) {
  assert.equal(noExecutableSuggestions({ ...snapshot, ...change }), false); tests++;
}
assert.equal(noExecutableSuggestions({ ...snapshot, total: 2, products: [product, { ...product, taskId: '456' }] }), true); tests++;
assert.equal(noExecutableSuggestions({ ...snapshot, total: 2, products: [product, { ...product, taskId: '456', hasSuggestion: true }] }), false); tests++;
const source = await fs.readFile(new URL('../scripts/quality_optimizer.mjs', import.meta.url), 'utf8');
const guard = source.indexOf('if(noExecutableSuggestions(before))');
assert.ok(guard > 0 && guard < source.indexOf('store.selectionNote=await prepareSelection'));
assert.ok(source.includes("store.reason='no-executable-platform-suggestions'")); tests++;
console.log(JSON.stringify({ ok: true, tests, businessWrites: 0, sendAttempts: 0 }));
