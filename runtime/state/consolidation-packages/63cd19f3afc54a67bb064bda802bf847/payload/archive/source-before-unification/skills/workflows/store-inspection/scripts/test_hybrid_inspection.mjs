import assert from "node:assert/strict";
import { assembleHybridInspection, JINSHA_ELIGIBLE_ROWS, MEITUAN_PHASE_ONE_ROWS, MEITUAN_PHASE_TWO_ROWS } from "./assemble_hybrid_inspection.mjs";
import { buildHybridQueue } from "./build_hybrid_queue.mjs";
import { buildSourceRows } from "./build_hybrid_source_report.mjs";
import { validateInspectionInput } from "./build_inspection_result.mjs";
import { mergeHybridFacts } from "./merge_hybrid_facts.mjs";
import { buildHybridExecutionPlan, finalizeHybridExecution } from "./hybrid_inspection_executor.mjs";

const records = Array.from({ length: 1000 }, (_, index) => ({ platform: index % 2 ? "淘宝闪购" : "美团外卖", name: `测试门店${String(index).padStart(4, "0")}`, city: "上海市" }));
const queue = buildHybridQueue({ week: "2026-09-第2周", records });
assert.equal(queue.totalStores, 1000);
assert.deepEqual(queue.days.map((day) => day.assigned), [160, 160, 160, 160, 160, 160, 40]);
assert.ok(queue.queue.every((item) => item.batch === 1 || item.batch === 2));
assert.throws(() => buildHybridQueue({ week: "test", records, dailyCapacities: Array(7).fill(100) }), /weekly-capacity-insufficient/);
assert.throws(() => buildHybridQueue({ week: "test", records: records.slice(0, 1), dailyCapacities: [161] }), /invalid-daily-capacity/);

const store = { platform: "淘宝闪购", city: "上海市", rosterStoreName: "测试门店", storeName: "测试门店", inspectionDate: "2026-09-12" };
const inspection = assembleHybridInspection({ store, facts: [
  { ...store, row: 11, sourceType: "jinsha_report", observedDate: "2026-09-11", sourceRef: "sha256:test-report", finding: "日有效订单已从报表读取。", recommendation: "按同一口径复核周趋势。" },
  { ...store, row: 3, sourceType: "brand_backend", observedDate: "2026-09-12", sourceRef: "brand-observation:test", finding: "门店头像配置已读取。", recommendation: "消费者端复核实际展示。" },
  { ...store, row: 43, sourceType: "agent_service_backend", observedDate: "2026-09-12", sourceRef: "agent-service-observation:test", finding: "推广余额与当日消耗已读取。", recommendation: "按日复核余额与消耗。" },
  { ...store, row: 42, sourceType: "consumer_page", observedDate: "2026-09-12", sourceRef: "consumer-observation:test", finding: "分类展示已读取。", recommendation: "保持分类名称清晰。" },
] });
assert.equal(inspection.templateChecks.length, 44);
assert.equal(inspection.templateChecks.find((item) => item.row === 11).finding, "日有效订单已从报表读取。");
assert.equal(inspection.templateChecks.find((item) => item.row === 8).finding, "");
assert.equal(inspection.sourceLedger.length, 4);
assert.throws(() => assembleHybridInspection({ store, facts: [{ ...store, row: 9, sourceType: "brand_backend", observedDate: "2026-09-12", sourceRef: "brand:test", finding: "不应接受", recommendation: "不应接受" }] }), /backend-row-not-eligible/);
assert.throws(() => assembleHybridInspection({ store, facts: [{ ...store, row: 8, sourceType: "agent_service_backend", observedDate: "2026-09-12", sourceRef: "agent:test", finding: "不应接受", recommendation: "不应接受" }] }), /agent-service-row-not-eligible/);
const templateValues = [["项目", "注意事项", "具体方案"], ...Array.from({ length: 44 }, (_, index) => [`项目${index + 2}`, `检查点${index + 2}`, ""])];
const oldResultValues = [["项目", "注意事项", "具体方案"], ...Array.from({ length: 44 }, (_, index) => [`项目${index + 2}`, `检查点：检查点${index + 2}\n巡店发现：${index === 9 ? "旧销量" : ""}`, ""])];
const sourceRows = buildSourceRows({ inspection, templateValues, oldResultValues });
assert.equal(sourceRows.length, 44);
assert.equal(sourceRows.find((row) => row[0] === 11)[3], "金鲨数据下载");
assert.equal(sourceRows.find((row) => row[0] === 43)[3], "淘宝服务商后台");
assert.equal(sourceRows.find((row) => row[0] === 11)[6], "观察结果变化");
assert.equal(sourceRows.find((row) => row[0] === 8)[3], "留空");
const merged = mergeHybridFacts({ store, facts: [{ row: 7, finding: "旧事实" }, { row: 11, finding: "保留事实" }] }, { facts: [{ row: 7, finding: "新事实" }, { row: 43, finding: "新增事实" }] });
assert.deepEqual(merged.facts.map((fact) => [fact.row, fact.finding]), [[7, "新事实"], [11, "保留事实"], [43, "新增事实"]]);
assert.throws(() => mergeHybridFacts({ store, facts: [] }, { facts: [{ row: 7 }, { row: 7 }] }), /hybrid-override-row-invalid/);

const routedStore = { platform: "淘宝闪购", city: "上海市", poi: "中房金谊广场", rosterStoreName: "9家湘菜（金谊广场店）", storeName: "9家湘菜（金谊广场店）", inspectionDate: "2026-09-12" };
const routedFact = (row, sourceType, suffix = row) => ({ ...routedStore, row, sourceType, observedDate: "2026-09-12", sourceRef: `${sourceType}:${suffix}`, finding: `第${row}行事实`, recommendation: `第${row}行方案` });
const routeRegistry = { version: 1, city: "上海市", poi: "中房金谊广场", merchantAddressAnchor: "上南路4467", routes: [{ platform: "淘宝闪购", rosterStoreName: "9家湘菜（金谊广场店）", consumerStoreName: "9家湘菜（金谊广场店）", aliases: [] }] };
const stagedInput = {
  store: routedStore,
  stages: {
    reports: { status: "complete", attempts: 1, finishedAt: "2026-09-12T09:00:00+08:00", facts: [routedFact(5, "jinsha_report")] },
    agent_service: { status: "complete", attempts: 1, finishedAt: "2026-09-12T09:10:00+08:00", facts: [routedFact(2, "agent_service_backend"), routedFact(13, "agent_service_backend"), routedFact(43, "agent_service_backend")] },
    brand_backend: { status: "skipped", attempts: 0, finishedAt: "2026-09-12T09:20:00+08:00", facts: [] },
  },
};
const plan = buildHybridExecutionPlan(stagedInput, routeRegistry);
assert.equal(plan.currentStage, "mobile");
assert.ok(plan.mobileRows.includes(2));
assert.ok(!plan.mobileRows.includes(13));
assert.ok(plan.ignoredBackendFacts.some((item) => item.row === 2 && item.reason === "consumer-display-required"));
assert.deepEqual(plan.selectedFacts.map((fact) => fact.row), [5, 13, 43]);
assert.throws(() => buildHybridExecutionPlan({ ...stagedInput, stages: { ...stagedInput.stages, reports: { ...stagedInput.stages.reports, attempts: 3 } } }, routeRegistry), /stage-reports-attempts-invalid/);
assert.throws(() => buildHybridExecutionPlan({ ...stagedInput, stages: { ...stagedInput.stages, agent_service: { ...stagedInput.stages.agent_service, finishedAt: "2026-09-12T08:00:00+08:00" } } }, routeRegistry), /stage-order-invalid/);

const meituanStore = { platform: "美团外卖", city: "上海市", poi: "中房金谊广场", rosterStoreName: "9家湘菜（金谊广场店）", storeName: "9家湘菜（金谊广场店）", inspectionDate: "2026-09-14" };
const meituanRouteRegistry = { ...routeRegistry, routes: [{ platform: "美团外卖", rosterStoreName: meituanStore.rosterStoreName, consumerStoreName: meituanStore.storeName, aliases: [] }] };
const meituanFact = (row) => ({ ...meituanStore, row, sourceType: "meituan_backend", observedDate: "2026-09-14", sourceRef: `meituan:receipt:${row}`, finding: `第${row}行美团后台事实`, recommendation: `第${row}行对应方案` });
const jinshaFact = (row) => ({ ...meituanStore, row, sourceType: "jinsha_report", observedDate: "2026-09-14", sourceRef: `jinsha:1093331:${row}`, finding: `第${row}行金鲨事实`, recommendation: `第${row}行对应方案` });
assert.deepEqual(JINSHA_ELIGIBLE_ROWS, [5, 6, 10, 11, 12, 13, 14, 15, 16, 17, 22, 31, 36, 44]);
const meituanEligibleRows = [...MEITUAN_PHASE_ONE_ROWS, ...MEITUAN_PHASE_TWO_ROWS].sort((a, b) => a - b);
assert.equal(new Set(meituanEligibleRows).size, 25);
const meituanPlan = buildHybridExecutionPlan({
  store: meituanStore,
  stages: {
    reports: { status: "skipped", attempts: 0, finishedAt: "2026-09-14T09:00:00+08:00", facts: [] },
    meituan_backend: { status: "complete", attempts: 1, finishedAt: "2026-09-14T09:10:00+08:00", facts: meituanEligibleRows.map(meituanFact) },
  },
}, meituanRouteRegistry);
assert.deepEqual(meituanPlan.stageSequence, ["reports", "meituan_backend", "mobile", "assemble", "validate"]);
assert.deepEqual(meituanPlan.selectedFacts.map((fact) => fact.row), meituanEligibleRows);
assert.ok(!meituanPlan.mobileRows.some((row) => meituanEligibleRows.includes(row)));
const meituanProfileOnlyPlan = buildHybridExecutionPlan({
  store: meituanStore,
  stages: {
    reports: { status: "skipped", attempts: 0, finishedAt: "2026-09-14T09:00:00+08:00", facts: [] },
    meituan_backend: { status: "complete", attempts: 1, finishedAt: "2026-09-14T09:10:00+08:00", facts: [meituanFact(19)] },
  },
}, meituanRouteRegistry);
for (const row of [11, 12, 20, 32, 33, 37]) assert.ok(meituanProfileOnlyPlan.mobileRows.includes(row), `meituan-mobile-row-${row}`);
const meituanBackendFirstPlan = buildHybridExecutionPlan({
  store: meituanStore,
  mobileCostPolicy: "backend-first",
  stages: {
    reports: { status: "complete", attempts: 1, finishedAt: "2026-09-14T09:00:00+08:00", facts: JINSHA_ELIGIBLE_ROWS.map(jinshaFact) },
    meituan_backend: { status: "complete", attempts: 1, finishedAt: "2026-09-14T09:10:00+08:00", facts: [meituanFact(19)] },
  },
}, meituanRouteRegistry);
assert.deepEqual(meituanBackendFirstPlan.selectedFacts.map((fact) => fact.row), [...JINSHA_ELIGIBLE_ROWS, 19].sort((a, b) => a - b));
assert.deepEqual(meituanBackendFirstPlan.costPolicySuppressedMobileRows, [7]);
assert.ok(!meituanBackendFirstPlan.mobileChecklist.some((item) => item.module === "reviews"));
assert.equal(meituanBackendFirstPlan.mobileRows.length, 19);
for (const row of [20, 32, 33, 37]) assert.ok(meituanBackendFirstPlan.mobileRows.includes(row), `backend-first-optional-mobile-row-${row}`);
assert.ok(meituanBackendFirstPlan.unresolvedRows.includes(7));
const meituanIncompleteJinshaPlan = buildHybridExecutionPlan({
  store: meituanStore,
  mobileCostPolicy: "backend-first",
  stages: {
    reports: { status: "complete", attempts: 1, finishedAt: "2026-09-14T09:00:00+08:00", facts: [jinshaFact(5), jinshaFact(6)] },
    meituan_backend: { status: "skipped", attempts: 0, finishedAt: "2026-09-14T09:10:00+08:00", facts: [] },
  },
}, meituanRouteRegistry);
assert.ok(meituanIncompleteJinshaPlan.mobileChecklist.some((item) => item.module === "reviews"));
assert.deepEqual(meituanIncompleteJinshaPlan.costPolicySuppressedMobileRows, []);
assert.throws(() => buildHybridExecutionPlan({ ...stagedInput, mobileCostPolicy: "guess" }, routeRegistry), /mobile-cost-policy-invalid/);
assert.throws(() => assembleHybridInspection({ store: meituanStore, facts: [meituanFact(2)] }), /meituan-backend-row-not-eligible/);
assert.throws(() => assembleHybridInspection({ store: meituanStore, facts: [jinshaFact(7)] }), /jinsha-row-not-eligible/);
assert.throws(() => buildHybridExecutionPlan({ store: meituanStore, stages: { reports: { status: "skipped", attempts: 0, finishedAt: "2026-09-14T09:00:00+08:00", facts: [] }, agent_service: { status: "skipped", attempts: 0, finishedAt: "2026-09-14T09:01:00+08:00", facts: [] }, meituan_backend: { status: "skipped", attempts: 0, finishedAt: "2026-09-14T09:02:00+08:00", facts: [] } } }, meituanRouteRegistry), /stage-not-allowed-for-platform/);

const moduleReceipts = Object.fromEntries(plan.mobileChecklist.map((item, index) => [item.module, { status: "complete", attempts: 1, finishedAt: `2026-09-12T10:${String(index).padStart(2, "0")}:00+08:00`, facts: item.module === "search" ? [routedFact(2, "consumer_page")] : [] }]));
const finalized = finalizeHybridExecution(plan, { store: { ...routedStore, consumerStoreName: "9家湘菜（金谊广场店）", merchantAddress: "上海市浦东新区上南路4467弄73号" }, moduleReceipts });
assert.equal(finalized.templateChecks.length, 44);
assert.equal(finalized.sourceLedger.length, 4);
assert.deepEqual(finalized.executionReceipt.completedMobileRows, [2]);
assert.deepEqual(finalized.executionReceipt.mobileModuleReceipts.map(({ module, status, factRows }) => ({ module, status, factRows })), [
  { module: "search", status: "complete", factRows: [2] },
  { module: "products", status: "complete", factRows: [] },
  { module: "reviews", status: "complete", factRows: [] },
  { module: "merchant", status: "complete", factRows: [] },
]);
validateInspectionInput(finalized);
assert.throws(() => validateInspectionInput({ ...finalized, executionReceipt: undefined }), /hybrid-execution-receipt-invalid/);
const badMobileRun = structuredClone({ store: { ...routedStore, consumerStoreName: "9家湘菜（金谊广场店）", merchantAddress: "上海市浦东新区上南路4467弄73号" }, moduleReceipts });
badMobileRun.moduleReceipts.search.facts.push(routedFact(43, "consumer_page", "outside-plan"));
assert.throws(() => finalizeHybridExecution(plan, badMobileRun), /mobile-row-not-planned/);
console.log(JSON.stringify({ ok: true, queueStores: queue.totalStores, checks: inspection.templateChecks.length, sourceRows: sourceRows.length, hybridPlanMobileRows: plan.mobileRows.length }));
