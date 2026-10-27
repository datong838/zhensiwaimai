import assert from 'node:assert/strict';
import { inspectionReportScope, inspectionRecordKey } from '../monthly_report_scope.mjs';
const a = { platform: '淘宝闪购', name: '测试店A', city: '上海市' };
const b = { platform: '美团外卖', name: '测试店A', city: '上海市' };
const c = { platform: '美团外卖', name: '测试店B变体', city: '上海市' };
const scope = { month: '2026-10', confirmedAt: '2026-10-27T19:19:26+08:00', sourceSha256: 'a'.repeat(64),
  requestedShops: 2, matchedShops: 1, matchedPlatformRecords: 2, completeRoster: false, reportOnly: true, executionEnabled: false,
  mappings: [{ selected: { shopId: '123', name: '测试店A' }, matched: [a, b], candidates: [], state: '已对应' },
    { selected: { shopId: '456', name: '测试店B' }, matched: [], candidates: [c], state: '候选待核' }] };
const input = { month: '2026-10', sourceSha256: 'a'.repeat(64), records: [a, b, c, { platform: '淘宝闪购', name: '缺城市店', city: '' }], completeRoster: false };
let tests = 0;
const original = JSON.stringify({ scope, input });
const result = inspectionReportScope(scope, input);
assert.equal(result.plannedRecords, 2); tests++;
assert.equal(result.requestedShops, 2); tests++;
assert.equal(result.candidateKeys.size, 1); tests++;
assert.equal(result.matchedKeys.has(inspectionRecordKey(c)), false); tests++;
assert.equal(result.scopeRows.length, 2); tests++;
assert.ok(result.scopeRows[1][4].includes('待核')); tests++;
assert.equal([...result.calendarCounts.values()].reduce((a, b) => a + b, 0), 2); tests++;
assert.equal(result.calendarCounts.has('2026-10-26'), false); tests++;
assert.equal(JSON.stringify({ scope, input }), original); tests++;
for (const patch of [{ month: '2026-11' }, { sourceSha256: 'b'.repeat(64) }, { executionEnabled: true },
  { reportOnly: false }, { requestedShops: 3 }, { matchedShops: 2 }, { matchedPlatformRecords: 3 },
  { completeRoster: true }, { confirmedAt: 'not-a-date' }, { confirmedAt: '2026-11-01T00:00:00+08:00' }]) {
  assert.throws(() => inspectionReportScope({ ...scope, ...patch }, input)); tests++;
}
const copy = () => JSON.parse(JSON.stringify(scope));
let bad = copy(); bad.mappings[1].selected.shopId = '123';
assert.throws(() => inspectionReportScope(bad, input)); tests++;
bad = copy(); bad.mappings[0].matched[0].city = '其他城市';
assert.throws(() => inspectionReportScope(bad, input)); tests++;
bad = copy(); bad.mappings[1].matched = [a];
assert.throws(() => inspectionReportScope(bad, input)); tests++;
bad = copy(); bad.mappings[1].candidates = [a];
assert.throws(() => inspectionReportScope(bad, input)); tests++;
bad = copy(); delete bad.mappings[1].state;
assert.throws(() => inspectionReportScope(bad, input)); tests++;
assert.throws(() => inspectionReportScope(scope, { ...input, records: [a, b, c, a] })); tests++;
console.log(JSON.stringify({ ok: true, tests, sourceWrites: 0, executionEnabled: false }));
