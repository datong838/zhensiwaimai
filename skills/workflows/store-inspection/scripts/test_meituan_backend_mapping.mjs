import assert from "node:assert/strict";
import { MEITUAN_ROW_CONTRACTS, mapMeituanBackendFacts } from "./map_meituan_backend_facts.mjs";

const store = { platform: "美团外卖", city: "上海市", rosterStoreName: "9家湘菜（金谊广场店）", storeName: "9家湘菜（金谊广场店）", storeId: "1093331", address: "上海市浦东新区上南路4467弄73号", inspectionDate: "2026-09-14" };
const modules = new Map();
for (const groups of Object.values(MEITUAN_ROW_CONTRACTS)) for (const [module, ...fields] of groups) {
  if (!modules.has(module)) modules.set(module, {});
  for (const name of fields) modules.get(module)[name] = { rawName: name, value: `${name}原值` };
}
const receipts = [...modules].map(([module, fields]) => ({ ...store, module, status: "available", observedAt: "2026-09-13T17:00:00.000Z", fields }));
const candidates = Object.keys(MEITUAN_ROW_CONTRACTS).map(Number).map((row) => ({ row, finding: `第${row}行后台事实`, recommendation: `第${row}行方案` }));
const result = mapMeituanBackendFacts({ store, receipts, candidates });
assert.equal(result.facts.length, 25);
assert.deepEqual(result.facts.map((fact) => fact.row).sort((a, b) => a - b), candidates.map((item) => item.row).sort((a, b) => a - b));
assert.ok(result.facts.every((fact) => fact.observedDate === "2026-09-14" && fact.sourceType === "meituan_backend" && fact.fieldRefs.length));

const profileOnly = receipts.filter((receipt) => receipt.module === "store-profile");
assert.deepEqual(mapMeituanBackendFacts({ store, receipts: profileOnly, candidates: [{ row: 19, finding: "营业时间10:00-21:00。", recommendation: "保持营业时长。" }] }).facts.map((fact) => fact.row), [19]);
assert.throws(() => mapMeituanBackendFacts({ store, receipts: profileOnly, candidates: [{ row: 43, finding: "不应通过", recommendation: "不应通过" }] }), /meituan-row-receipt-not-available/);
const missingHours = structuredClone(profileOnly);missingHours[0].fields["营业时间"].value = null;
assert.throws(() => mapMeituanBackendFacts({ store, receipts: missingHours, candidates: [{ row: 19, finding: "不应通过", recommendation: "不应通过" }] }), /meituan-row-field-missing/);
assert.throws(() => mapMeituanBackendFacts({ store, receipts: profileOnly, candidates: [{ row: 2, finding: "不应通过", recommendation: "不应通过" }] }), /meituan-row-contract-missing/);
console.log(JSON.stringify({ ok: true, contractRows: Object.keys(MEITUAN_ROW_CONTRACTS).length, mappedRows: result.facts.length }));
