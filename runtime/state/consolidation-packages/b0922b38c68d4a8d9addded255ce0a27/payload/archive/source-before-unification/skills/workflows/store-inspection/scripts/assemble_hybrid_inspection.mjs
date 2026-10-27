import fs from "node:fs/promises";
import path from "node:path";

const FIRST_ROW = 2;
const LAST_ROW = 45;
const BACKEND_ELIGIBLE_ROWS = new Set([2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 15, 16, 18, 19, 20, 21, 22, 23, 25, 27, 28, 30, 32, 33, 36, 38, 39, 41, 43, 44]);
export const JINSHA_ELIGIBLE_ROWS = Object.freeze([5, 6, 10, 11, 12, 13, 14, 15, 16, 17, 22, 31, 36, 44]);
const JINSHA_ELIGIBLE_ROW_SET = new Set(JINSHA_ELIGIBLE_ROWS);
const AGENT_SERVICE_ELIGIBLE_ROWS = new Set([2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 22, 29, 30, 31, 36, 42, 43, 44]);
export const MEITUAN_PHASE_ONE_ROWS = Object.freeze([7, 13, 14, 15, 16, 17, 18, 19, 29, 30, 31, 36, 42, 43]);
export const MEITUAN_PHASE_TWO_ROWS = Object.freeze([9, 20, 24, 27, 28, 32, 33, 34, 35, 37, 8]);
const MEITUAN_BACKEND_ELIGIBLE_ROWS = new Set([...MEITUAN_PHASE_ONE_ROWS, ...MEITUAN_PHASE_TWO_ROWS]);
const SOURCE_TYPES = new Set(["jinsha_report", "agent_service_backend", "brand_backend", "meituan_backend", "consumer_page"]);

function text(value) { return String(value ?? "").trim(); }
function sameStore(meta, fact) { return ["platform", "city", "rosterStoreName"].every((key) => text(meta[key]) === text(fact[key])); }

function validateFact(meta, fact) {
  const row = Number(fact.row);
  const sourceType = text(fact.sourceType);
  if (!Number.isInteger(row) || row < FIRST_ROW || row > LAST_ROW) throw new Error(`fact-row-invalid:${fact.row}`);
  if (!SOURCE_TYPES.has(sourceType)) throw new Error(`fact-source-type-invalid:${sourceType}`);
  if (!sameStore(meta, fact)) throw new Error(`fact-store-mismatch:row-${row}`);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text(fact.observedDate))) throw new Error(`fact-observed-date-invalid:row-${row}`);
  if (!text(fact.sourceRef)) throw new Error(`fact-source-ref-required:row-${row}`);
  const finding = text(fact.finding);
  const recommendation = text(fact.recommendation);
  if (!finding || !recommendation) throw new Error(`fact-content-required:row-${row}`);
  if (sourceType === "agent_service_backend" && !AGENT_SERVICE_ELIGIBLE_ROWS.has(row)) throw new Error(`agent-service-row-not-eligible:${row}`);
  if (sourceType === "meituan_backend" && !MEITUAN_BACKEND_ELIGIBLE_ROWS.has(row)) throw new Error(`meituan-backend-row-not-eligible:${row}`);
  if (sourceType === "jinsha_report" && !JINSHA_ELIGIBLE_ROW_SET.has(row)) throw new Error(`jinsha-row-not-eligible:${row}`);
  if (sourceType === "brand_backend" && !BACKEND_ELIGIBLE_ROWS.has(row)) throw new Error(`backend-row-not-eligible:${row}`);
  return { row, sourceType, observedDate: text(fact.observedDate), sourceRef: text(fact.sourceRef), finding, recommendation };
}

export function assembleHybridInspection(input) {
  const meta = input?.store ?? {};
  for (const key of ["platform", "city", "rosterStoreName", "storeName", "inspectionDate"]) if (!text(meta[key])) throw new Error(`store-field-required:${key}`);
  const facts = (input.facts ?? []).map((fact) => validateFact(meta, fact));
  const byRow = new Map();
  for (const fact of facts) {
    if (byRow.has(fact.row)) throw new Error(`duplicate-fact-row:${fact.row}`);
    byRow.set(fact.row, fact);
  }
  const templateChecks = Array.from({ length: LAST_ROW - FIRST_ROW + 1 }, (_, index) => {
    const row = index + FIRST_ROW;
    const fact = byRow.get(row);
    return { row, finding: fact?.finding ?? "", recommendation: fact?.recommendation ?? "" };
  });
  return {
    platform: text(meta.platform), city: text(meta.city), rosterStoreName: text(meta.rosterStoreName), storeName: text(meta.storeName), inspectionDate: text(meta.inspectionDate), templateChecks,
    sourceLedger: facts.map(({ row, sourceType, observedDate, sourceRef }) => ({ row, sourceType, observedDate, sourceRef })),
  };
}

export async function assembleHybridInspectionFile({ inputPath, outputPath }) {
  const result = assembleHybridInspection(JSON.parse(await fs.readFile(inputPath, "utf8")));
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  return { outputPath, checks: result.templateChecks.length, facts: result.sourceLedger.length };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) throw new Error("usage: assemble_hybrid_inspection.mjs <facts.json> <inspection.json>");
  console.log(JSON.stringify(await assembleHybridInspectionFile({ inputPath, outputPath }), null, 2));
}
