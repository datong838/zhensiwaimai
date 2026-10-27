import assert from "node:assert/strict";
import { JINSHA_ELIGIBLE_ROWS } from "./assemble_hybrid_inspection.mjs";
import { JINSHA_ROW_CONTRACTS, mapJinshaFacts } from "./map_jinsha_facts.mjs";

const store = {
  platform: "美团外卖",
  city: "上海市",
  rosterStoreName: "9家湘菜（金谊广场店）",
  storeName: "9家湘菜（金谊广场店）",
  storeId: "1093331",
  inspectionDate: "2026-09-14",
};
const modules = new Map();
for (const groups of Object.values(JINSHA_ROW_CONTRACTS)) {
  for (const [module, ...fields] of groups) {
    if (!modules.has(module)) modules.set(module, {});
    for (const field of fields) modules.get(module)[field] = { rawName: field, value: `${field}实值` };
  }
}
const receipts = [...modules].map(([module, fields]) => ({ ...store, module, status: "available", observedAt: "2026-09-14T12:00:00+08:00", fields }));
const candidates = JINSHA_ELIGIBLE_ROWS.map((row) => ({ row, finding: `第${row}行事实`, recommendation: `第${row}行方案` }));
const mapped = mapJinshaFacts({ store, receipts, candidates });
assert.deepEqual(mapped.facts.map((fact) => fact.row), JINSHA_ELIGIBLE_ROWS);
assert.ok(mapped.facts.every((fact) => fact.sourceType === "jinsha_report" && fact.sourceRef.startsWith("jinsha:1093331:")));
assert.equal(mapped.facts.find((fact) => fact.row === 14).fieldRefs.length, 2);
assert.throws(() => mapJinshaFacts({ store, receipts, candidates: [{ row: 7, finding: "错误", recommendation: "错误" }] }), /jinsha-row-contract-missing/);
const wrongStoreReceipts = structuredClone(receipts);
wrongStoreReceipts[0].storeId = "other";
assert.throws(() => mapJinshaFacts({ store, receipts: wrongStoreReceipts, candidates: [] }), /jinsha-receipt-store-mismatch/);
const missingFieldReceipts = structuredClone(receipts);
delete missingFieldReceipts.find((receipt) => receipt.module === "negative-reviews").fields["差评主题"];
assert.throws(() => mapJinshaFacts({ store, receipts: missingFieldReceipts, candidates: [{ row: 10, finding: "事实", recommendation: "方案" }] }), /jinsha-row-field-missing/);
console.log(JSON.stringify({ ok: true, facts: mapped.facts.length, rows: mapped.facts.map((fact) => fact.row) }));
