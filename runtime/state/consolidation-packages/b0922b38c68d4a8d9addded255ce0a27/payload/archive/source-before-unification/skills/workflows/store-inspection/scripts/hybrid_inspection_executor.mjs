import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { assembleHybridInspection } from "./assemble_hybrid_inspection.mjs";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const DEFAULT_ROUTES_PATH = path.resolve(SCRIPT_DIR, "../references/verified-store-routes.json");
const POLICY_VERSION = 2;
const FIRST_ROW = 2;
const LAST_ROW = 45;
const BACKEND_STAGE_DEFINITIONS = Object.freeze({
  reports: { name: "reports", sourceType: "jinsha_report" },
  agent_service: { name: "agent_service", sourceType: "agent_service_backend" },
  brand_backend: { name: "brand_backend", sourceType: "brand_backend" },
  meituan_backend: { name: "meituan_backend", sourceType: "meituan_backend" },
});
const PLATFORM_BACKEND_STAGE_NAMES = Object.freeze({
  "淘宝闪购": Object.freeze(["reports", "agent_service", "brand_backend"]),
  "美团外卖": Object.freeze(["reports", "meituan_backend"]),
});
const MOBILE_MODULE_ORDER = ["search", "products", "reviews", "merchant"];
const CONSUMER_REQUIRED_ROWS = new Set([2, 3, 4, 21, 23, 25, 26, 38, 39, 40, 41, 45]);
const JINSHA_PRIORITY_ROWS = new Set([5, 6, 10, 11, 12, 13, 14, 15, 16, 17, 22, 31, 36, 44]);
const MOBILE_COST_POLICIES = new Set(["standard", "backend-first"]);
const AGENT_SERVICE_PRIORITY_ROWS = new Set([7, 13, 14, 15, 16, 17, 18, 19, 29, 30, 31, 36, 42, 43]);
const MOBILE_ROW_MODULE = new Map([
  [2, "search"], [21, "search"], [23, "search"], [25, "search"], [26, "search"], [29, "search"], [30, "search"],
  [3, "products"], [4, "products"], [13, "products"], [14, "products"], [15, "products"], [16, "products"], [17, "products"], [31, "products"], [36, "products"], [38, "products"], [40, "products"],
  [5, "reviews"], [6, "reviews"], [7, "reviews"], [10, "reviews"],
  [18, "merchant"], [19, "merchant"], [39, "merchant"], [41, "merchant"], [45, "merchant"],
]);
const MEITUAN_MOBILE_ROW_MODULE = new Map([
  ...MOBILE_ROW_MODULE,
  [11, "search"], [12, "search"],
  [32, "products"], [37, "products"],
  [20, "merchant"], [33, "merchant"],
]);

function text(value) { return String(value ?? "").trim(); }
function normalizeText(value) { return text(value).replace(/[（）]/g, (char) => char === "（" ? "(" : ")").replace(/[·•.\s]/g, "").toLowerCase(); }
function sameStore(left, right) { return ["platform", "city", "rosterStoreName"].every((key) => text(left?.[key]) === text(right?.[key])); }
function isoTime(value, label) {
  const timestamp = Date.parse(text(value));
  if (!Number.isFinite(timestamp)) throw new Error(`${label}-finished-at-invalid`);
  return timestamp;
}

function validateAttempts(receipt, label) {
  const attempts = Number(receipt?.attempts);
  if (!Number.isInteger(attempts) || attempts < 0 || attempts > 2) throw new Error(`${label}-attempts-invalid:${receipt?.attempts}`);
  if (receipt.status === "complete" && attempts < 1) throw new Error(`${label}-complete-without-attempt`);
  if (receipt.status === "failed" && attempts < 1) throw new Error(`${label}-failed-without-attempt`);
}

function validateStatusReceipt(receipt, label) {
  if (!receipt || !["complete", "skipped", "failed"].includes(receipt.status)) throw new Error(`${label}-status-invalid:${receipt?.status}`);
  validateAttempts(receipt, label);
  return isoTime(receipt.finishedAt, label);
}

function selectRoute(store, routes) {
  if (normalizeText(store.city) !== normalizeText(routes.city)) throw new Error(`route-city-mismatch:${store.city}`);
  if (normalizeText(store.poi) !== normalizeText(routes.poi)) throw new Error(`route-poi-mismatch:${store.poi}`);
  const candidates = routes.routes.filter((route) => route.platform === store.platform && normalizeText(route.rosterStoreName) === normalizeText(store.rosterStoreName));
  if (candidates.length !== 1) throw new Error(`route-match-count:${candidates.length}:${store.platform}:${store.rosterStoreName}`);
  return candidates[0];
}

function validateObservedRoute(plan, mobileRun) {
  if (!sameStore(plan.store, mobileRun.store)) throw new Error("mobile-run-store-mismatch");
  if (normalizeText(mobileRun.store.poi) !== normalizeText(plan.store.poi)) throw new Error(`route-poi-mismatch:${mobileRun.store.poi}`);
  const names = [plan.route.consumerStoreName, ...(plan.route.aliases ?? [])];
  if (!names.some((name) => normalizeText(name) === normalizeText(mobileRun.store.consumerStoreName))) throw new Error(`route-store-mismatch:${mobileRun.store.consumerStoreName}`);
  if (!normalizeText(mobileRun.store.merchantAddress).includes(normalizeText(plan.route.merchantAddressAnchor))) throw new Error(`route-address-mismatch:${mobileRun.store.merchantAddress}`);
}

function backendStagesFor(platform) {
  const names = PLATFORM_BACKEND_STAGE_NAMES[text(platform)];
  if (!names) throw new Error(`platform-not-supported:${platform}`);
  return names.map((name) => BACKEND_STAGE_DEFINITIONS[name]);
}

function mobileRowModuleFor(platform) { return platform === "美团外卖" ? MEITUAN_MOBILE_ROW_MODULE : MOBILE_ROW_MODULE; }

function sourcePriority(row, platform) {
  if (platform === "美团外卖") {
    if (JINSHA_PRIORITY_ROWS.has(row)) return ["jinsha_report", "meituan_backend"];
    return ["meituan_backend", "jinsha_report"];
  }
  if (JINSHA_PRIORITY_ROWS.has(row)) return ["jinsha_report", "agent_service_backend", "brand_backend"];
  if (AGENT_SERVICE_PRIORITY_ROWS.has(row)) return ["agent_service_backend", "brand_backend", "jinsha_report"];
  return ["brand_backend", "agent_service_backend", "jinsha_report"];
}

function validateFact(store, fact) {
  assembleHybridInspection({ store, facts: [fact] });
  return fact;
}

export function buildHybridExecutionPlan(input, routeRegistry) {
  const store = input?.store ?? {};
  for (const key of ["platform", "city", "rosterStoreName", "storeName", "inspectionDate", "poi"]) if (!text(store[key])) throw new Error(`store-field-required:${key}`);
  const route = selectRoute(store, routeRegistry);
  const mobileCostPolicy = text(input.mobileCostPolicy) || "standard";
  if (!MOBILE_COST_POLICIES.has(mobileCostPolicy)) throw new Error(`mobile-cost-policy-invalid:${mobileCostPolicy}`);
  const backendStages = backendStagesFor(store.platform);
  const allowedStageNames = new Set(backendStages.map((stage) => stage.name));
  const unexpectedStage = Object.keys(input?.stages ?? {}).find((name) => !allowedStageNames.has(name));
  if (unexpectedStage) throw new Error(`stage-not-allowed-for-platform:${store.platform}:${unexpectedStage}`);
  const candidates = new Map();
  const stageReceipts = [];
  let previousFinishedAt = -Infinity;

  for (const stage of backendStages) {
    const receipt = input?.stages?.[stage.name];
    const finishedAt = validateStatusReceipt(receipt, `stage-${stage.name}`);
    if (finishedAt < previousFinishedAt) throw new Error(`stage-order-invalid:${stage.name}`);
    previousFinishedAt = finishedAt;
    const facts = Array.isArray(receipt.facts) ? receipt.facts : [];
    if (receipt.status !== "complete" && facts.length) throw new Error(`stage-${stage.name}-facts-not-allowed:${receipt.status}`);
    const rows = new Set();
    for (const fact of facts) {
      if (fact.sourceType !== stage.sourceType) throw new Error(`stage-${stage.name}-source-mismatch:${fact.sourceType}`);
      validateFact(store, fact);
      const row = Number(fact.row);
      if (rows.has(row)) throw new Error(`stage-${stage.name}-duplicate-row:${row}`);
      rows.add(row);
      if (!candidates.has(row)) candidates.set(row, []);
      candidates.get(row).push(fact);
    }
    stageReceipts.push({ stage: stage.name, status: receipt.status, attempts: receipt.attempts, finishedAt: receipt.finishedAt, factRows: [...rows].sort((a, b) => a - b) });
  }

  const selectedFacts = [];
  const ignoredBackendFacts = [];
  for (let row = FIRST_ROW; row <= LAST_ROW; row += 1) {
    const rowCandidates = candidates.get(row) ?? [];
    if (CONSUMER_REQUIRED_ROWS.has(row)) {
      ignoredBackendFacts.push(...rowCandidates.map((fact) => ({ row, sourceType: fact.sourceType, reason: "consumer-display-required" })));
      continue;
    }
    const priorities = sourcePriority(row, store.platform);
    const selected = priorities.map((sourceType) => rowCandidates.find((fact) => fact.sourceType === sourceType)).find(Boolean);
    if (selected) selectedFacts.push(selected);
    ignoredBackendFacts.push(...rowCandidates.filter((fact) => fact !== selected).map((fact) => ({ row, sourceType: fact.sourceType, reason: "lower-priority-source" })));
  }

  const selectedRows = new Set(selectedFacts.map((fact) => Number(fact.row)));
  const mobileRowModule = mobileRowModuleFor(store.platform);
  const mobileRows = [];
  const unresolvedRows = [];
  const costPolicySuppressedMobileRows = [];
  const canSuppressMeituanReplyOnlyReview = store.platform === "美团外卖"
    && mobileCostPolicy === "backend-first"
    && [5, 6, 10].every((row) => selectedRows.has(row));
  for (let row = FIRST_ROW; row <= LAST_ROW; row += 1) {
    if (selectedRows.has(row)) continue;
    if (row === 7 && canSuppressMeituanReplyOnlyReview) {
      unresolvedRows.push(row);
      costPolicySuppressedMobileRows.push(row);
      continue;
    }
    if (mobileRowModule.has(row)) mobileRows.push(row);
    else unresolvedRows.push(row);
  }
  const mobileChecklist = MOBILE_MODULE_ORDER.map((module) => ({ module, rows: mobileRows.filter((row) => mobileRowModule.get(row) === module) })).filter((item) => item.rows.length);
  return {
    policyVersion: POLICY_VERSION,
    safetyMode: "READ_ONLY",
    mobileCostPolicy,
    stageSequence: [...backendStages.map((stage) => stage.name), "mobile", "assemble", "validate"],
    currentStage: "mobile",
    store,
    route: { ...route, city: routeRegistry.city, poi: routeRegistry.poi, merchantAddressAnchor: routeRegistry.merchantAddressAnchor },
    stageReceipts,
    selectedFacts,
    ignoredBackendFacts,
    mobileChecklist,
    mobileRows,
    unresolvedRows,
    costPolicySuppressedMobileRows,
  };
}

export function finalizeHybridExecution(plan, mobileRun) {
  if (plan?.policyVersion !== POLICY_VERSION || plan?.currentStage !== "mobile") throw new Error("hybrid-plan-state-invalid");
  validateObservedRoute(plan, mobileRun);
  const expectedModules = plan.mobileChecklist.map((item) => item.module);
  const suppliedModules = Object.keys(mobileRun.moduleReceipts ?? {});
  if (suppliedModules.some((module) => !expectedModules.includes(module))) throw new Error(`mobile-module-not-planned:${suppliedModules.find((module) => !expectedModules.includes(module))}`);
  const consumerFacts = [];
  const usedRows = new Set();
  let previousFinishedAt = -Infinity;
  for (const item of plan.mobileChecklist) {
    const receipt = mobileRun.moduleReceipts?.[item.module];
    const finishedAt = validateStatusReceipt(receipt, `mobile-${item.module}`);
    if (finishedAt < previousFinishedAt) throw new Error(`mobile-module-order-invalid:${item.module}`);
    previousFinishedAt = finishedAt;
    const facts = Array.isArray(receipt.facts) ? receipt.facts : [];
    if (receipt.status !== "complete" && facts.length) throw new Error(`mobile-${item.module}-facts-not-allowed:${receipt.status}`);
    for (const fact of facts) {
      if (fact.sourceType !== "consumer_page") throw new Error(`mobile-source-mismatch:${fact.sourceType}`);
      validateFact(plan.store, fact);
      const row = Number(fact.row);
      if (!item.rows.includes(row)) throw new Error(`mobile-row-not-planned:${item.module}:${row}`);
      if (usedRows.has(row)) throw new Error(`mobile-duplicate-row:${row}`);
      usedRows.add(row);
      consumerFacts.push(fact);
    }
  }
  const facts = [...plan.selectedFacts, ...consumerFacts].sort((a, b) => Number(a.row) - Number(b.row));
  const inspection = assembleHybridInspection({ store: plan.store, facts });
  return {
    ...inspection,
    workflowMode: "hybrid",
    executionReceipt: {
      policyVersion: POLICY_VERSION,
      safetyMode: "READ_ONLY",
      mobileCostPolicy: plan.mobileCostPolicy ?? "standard",
      costPolicySuppressedMobileRows: plan.costPolicySuppressedMobileRows ?? [],
      completedStages: [...plan.stageReceipts.map((receipt) => receipt.stage), "mobile", "assemble"],
      nextStage: "validate",
      plannedMobileRows: plan.mobileRows,
      mobileModuleReceipts: plan.mobileChecklist.map((item) => {
        const receipt = mobileRun.moduleReceipts[item.module];
        return {
          module: item.module,
          status: receipt.status,
          attempts: receipt.attempts,
          factRows: (receipt.facts ?? []).map((fact) => Number(fact.row)).sort((a, b) => a - b),
        };
      }),
      completedMobileRows: [...usedRows].sort((a, b) => a - b),
      unresolvedRows: inspection.templateChecks.filter((item) => !item.finding).map((item) => item.row),
    },
  };
}

export async function buildHybridExecutionPlanFile({ inputPath, outputPath, routesPath = DEFAULT_ROUTES_PATH }) {
  const [input, routes] = await Promise.all([fs.readFile(inputPath, "utf8"), fs.readFile(routesPath, "utf8")]);
  const result = buildHybridExecutionPlan(JSON.parse(input), JSON.parse(routes));
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  return { outputPath, mobileRows: result.mobileRows.length, mobileModules: result.mobileChecklist.map((item) => item.module), unresolvedRows: result.unresolvedRows.length };
}

export async function finalizeHybridExecutionFile({ planPath, mobileRunPath, outputPath }) {
  const [plan, mobileRun] = await Promise.all([fs.readFile(planPath, "utf8"), fs.readFile(mobileRunPath, "utf8")]);
  const result = finalizeHybridExecution(JSON.parse(plan), JSON.parse(mobileRun));
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  return { outputPath, checks: result.templateChecks.length, facts: result.sourceLedger.length, unresolvedRows: result.executionReceipt.unresolvedRows.length };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , command, firstPath, secondPath, thirdPath] = process.argv;
  if (command === "plan" && firstPath && secondPath) console.log(JSON.stringify(await buildHybridExecutionPlanFile({ inputPath: firstPath, outputPath: secondPath }), null, 2));
  else if (command === "finalize" && firstPath && secondPath && thirdPath) console.log(JSON.stringify(await finalizeHybridExecutionFile({ planPath: firstPath, mobileRunPath: secondPath, outputPath: thirdPath }), null, 2));
  else throw new Error("usage: hybrid_inspection_executor.mjs plan <input.json> <plan.json> | finalize <plan.json> <mobile-run.json> <inspection.json>");
}
