import assert from "node:assert/strict";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildHybridExecutionPlan, finalizeHybridExecution } from "./hybrid_inspection_executor.mjs";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const skillDir = path.resolve(scriptDir, "..");
const caseDir = path.join(skillDir, "runtime", "hybrid-final-2026-09-12", "淘宝闪购-9家湘菜（金谊广场店）");
const [factsInput, expectedInspection, routes] = (await Promise.all([
  fs.readFile(path.join(caseDir, "facts-final.json"), "utf8"),
  fs.readFile(path.join(caseDir, "inspection-final.json"), "utf8"),
  fs.readFile(path.join(skillDir, "references", "verified-store-routes.json"), "utf8"),
])).map((content) => JSON.parse(content));

const store = { ...factsInput.store, poi: routes.poi };
const bySource = (sourceType) => factsInput.facts.filter((fact) => fact.sourceType === sourceType);
const plan = buildHybridExecutionPlan({
  store,
  stages: {
    reports: { status: "complete", attempts: 1, finishedAt: "2026-09-12T09:00:00+08:00", facts: bySource("jinsha_report") },
    agent_service: { status: "complete", attempts: 1, finishedAt: "2026-09-12T09:30:00+08:00", facts: bySource("agent_service_backend") },
    brand_backend: { status: "skipped", attempts: 0, finishedAt: "2026-09-12T09:31:00+08:00", facts: [] },
  },
}, routes);

const expectedMobileRows = [2, 3, 4, 21, 23, 25, 26, 38, 39, 40, 41, 45];
const expectedUnresolvedRows = [8, 9, 20, 24, 27, 28, 32, 33, 34, 35, 37];
assert.deepEqual(plan.mobileRows, expectedMobileRows);
assert.deepEqual(plan.unresolvedRows, expectedUnresolvedRows);
assert.deepEqual(plan.mobileChecklist.map((item) => item.module), ["search", "products", "merchant"]);
assert.ok(!plan.mobileChecklist.some((item) => item.module === "reviews"));

const consumerFacts = bySource("consumer_page");
const moduleReceipts = Object.fromEntries(plan.mobileChecklist.map((item, index) => [item.module, {
  status: "complete",
  attempts: 1,
  finishedAt: `2026-09-12T10:${String(index * 10).padStart(2, "0")}:00+08:00`,
  facts: consumerFacts.filter((fact) => item.rows.includes(Number(fact.row))),
}]));
const actual = finalizeHybridExecution(plan, {
  store: { ...store, consumerStoreName: "9家湘菜（金谊广场店）", merchantAddress: "上海市浦东新区上南路4467弄73号405室、406室-1铺、407室-1铺、408室-1铺" },
  moduleReceipts,
});

const counts = actual.sourceLedger.reduce((result, item) => ({ ...result, [item.sourceType]: (result[item.sourceType] ?? 0) + 1 }), {});
assert.deepEqual(counts, { consumer_page: 12, jinsha_report: 7, agent_service_backend: 14 });
assert.equal(actual.sourceLedger.length, 33);
assert.deepEqual(actual.executionReceipt.unresolvedRows, expectedUnresolvedRows);
assert.deepEqual(actual.executionReceipt.mobileModuleReceipts.map((item) => item.module), ["search", "products", "merchant"]);
assert.deepEqual(actual.templateChecks, expectedInspection.templateChecks);
assert.deepEqual(actual.sourceLedger, expectedInspection.sourceLedger);
assert.ok(!JSON.stringify(actual).includes("证据："));
console.log(JSON.stringify({ ok: true, covered: actual.sourceLedger.length, mobileRows: plan.mobileRows.length, mobileModules: plan.mobileChecklist.map((item) => item.module), unresolvedRows: plan.unresolvedRows.length, counts }));
