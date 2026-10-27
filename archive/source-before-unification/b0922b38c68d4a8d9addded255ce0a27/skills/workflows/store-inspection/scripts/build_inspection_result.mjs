import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const TEMPLATE_PATH = path.resolve(SCRIPT_DIR, "../runtime/门店自检表(框架+模板).xlsx");
const TEMPLATE_SHA256 = "768f7d095656d569ed517492b9cbd740815428d934fbf8c40cca908d59daa271";
const TEMPLATE_SHEET = "Sheet1";
const FIRST_DETAIL_ROW = 2;
const LAST_DETAIL_ROW = 45;
const DETAIL_COUNT = LAST_DETAIL_ROW - FIRST_DETAIL_ROW + 1;

function safeName(value) {
  return String(value).replace(/[\\/:*?"<>|]/g, "-").replace(/\s+/g, "").trim();
}

async function sha256(filePath) {
  return crypto.createHash("sha256").update(await fs.readFile(filePath)).digest("hex");
}

async function importVerifiedTemplate(templatePath = TEMPLATE_PATH) {
  const digest = await sha256(templatePath);
  if (digest !== TEMPLATE_SHA256) throw new Error(`template-sha256-mismatch:${digest}`);
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(templatePath));
  const names = workbook.worksheets.items.map((sheet) => sheet.name);
  if (names.length !== 1 || names[0] !== TEMPLATE_SHEET) throw new Error(`template-sheet-mismatch:${names.join(",")}`);
  const sheet = workbook.worksheets.getItem(TEMPLATE_SHEET);
  const values = sheet.getRange("A1:C45").values;
  if (JSON.stringify(values[0]) !== JSON.stringify(["项目", "注意事项", "具体方案"])) {
    throw new Error(`template-header-mismatch:${JSON.stringify(values[0])}`);
  }
  if (values.slice(1).length !== DETAIL_COUNT || values.slice(1).some((row) => !String(row[1] ?? "").trim())) {
    throw new Error("template-detail-contract-mismatch");
  }
  return { workbook, sheet, values };
}

export function validateInspectionInput(data, inputPath = "inspection.json") {
  for (const key of ["platform", "city", "rosterStoreName", "storeName", "inspectionDate", "templateChecks"]) {
    if (data[key] === undefined) throw new Error(`missing-inspection-field:${key}:${inputPath}`);
  }
  if (!Array.isArray(data.templateChecks) || data.templateChecks.length !== DETAIL_COUNT) {
    throw new Error(`template-check-count:${data.templateChecks?.length ?? "missing"}`);
  }
  const rows = data.templateChecks.map((item) => Number(item.row));
  const expected = Array.from({ length: DETAIL_COUNT }, (_, index) => index + FIRST_DETAIL_ROW);
  if (JSON.stringify(rows) !== JSON.stringify(expected)) throw new Error(`template-check-rows:${rows.join(",")}`);
  for (const item of data.templateChecks) {
    const values = ["finding", "recommendation"].map((key) => String(item[key] ?? "").trim());
    if (values.some(Boolean) && values.some((value) => !value)) throw new Error(`incomplete-template-check:${item.row}`);
  }
  if (data.workflowMode === "hybrid") {
    const receipt = data.executionReceipt;
    if (!receipt || ![1, 2].includes(receipt.policyVersion) || receipt.safetyMode !== "READ_ONLY" || receipt.nextStage !== "validate") throw new Error("hybrid-execution-receipt-invalid");
    const expectedStages = receipt.policyVersion === 1 || data.platform === "淘宝闪购"
      ? ["reports", "agent_service", "brand_backend", "mobile", "assemble"]
      : data.platform === "美团外卖"
        ? ["reports", "meituan_backend", "mobile", "assemble"]
        : [];
    if (JSON.stringify(receipt.completedStages) !== JSON.stringify(expectedStages)) throw new Error("hybrid-completed-stages-invalid");
    const plannedRows = new Set(receipt.plannedMobileRows ?? []);
    if ((receipt.completedMobileRows ?? []).some((row) => !plannedRows.has(row))) throw new Error("hybrid-completed-mobile-row-not-planned");
    const actualUnresolved = data.templateChecks.filter((item) => !String(item.finding ?? "").trim()).map((item) => item.row);
    if (JSON.stringify(receipt.unresolvedRows) !== JSON.stringify(actualUnresolved)) throw new Error("hybrid-unresolved-rows-mismatch");
  }
}

export async function buildInspectionResult({ inputPath, outputPath, previewDir, templatePath = TEMPLATE_PATH }) {
  const data = JSON.parse(await fs.readFile(inputPath, "utf8"));
  validateInspectionInput(data, inputPath);
  const { workbook, sheet, values } = await importVerifiedTemplate(templatePath);

  for (let index = 0; index < DETAIL_COUNT; index += 1) {
    const rowNumber = index + FIRST_DETAIL_ROW;
    const originalAttention = String(values[index + 1][1]).trim();
    const check = data.templateChecks[index];
    sheet.getRange(`B${rowNumber}`).values = [[
      `检查点：${originalAttention}\n巡店发现：${String(check.finding).trim()}`,
    ]];
    sheet.getRange(`C${rowNumber}`).values = [[String(check.recommendation).trim()]];
  }

  sheet.getRange("A1:C45").format.font = { name: "Arial", size: 10, color: "#1F2937" };
  sheet.getRange("A1:C1").format.font = { name: "Arial", size: 11, bold: true, color: "#FFFFFF" };
  sheet.getRange("A1:C45").format.verticalAlignment = "top";
  sheet.getRange("A1:C45").format.wrapText = true;
  sheet.getRange("A:A").format.columnWidth = 24;
  sheet.getRange("B:B").format.columnWidth = 70;
  sheet.getRange("C:C").format.columnWidth = 62;
  sheet.freezePanes.freezeRows(1);

  workbook.recalculate();
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.mkdir(previewDir, { recursive: true });
  const preview = await workbook.render({ sheetName: TEMPLATE_SHEET, range: "A1:C45", scale: 1.2, format: "png" });
  await fs.writeFile(
    path.join(previewDir, `${safeName(data.platform)}-${safeName(data.storeName)}-门店自检表.png`),
    new Uint8Array(await preview.arrayBuffer()),
  );
  const exported = await SpreadsheetFile.exportXlsx(workbook);
  await exported.save(outputPath);
  return { inputPath, outputPath, sheet: TEMPLATE_SHEET, checks: DETAIL_COUNT };
}

export async function validateInspectionResult(outputPath, templatePath = TEMPLATE_PATH) {
  const { values: templateValues } = await importVerifiedTemplate(templatePath);
  const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
  const names = workbook.worksheets.items.map((sheet) => sheet.name);
  if (names.length !== 1 || names[0] !== TEMPLATE_SHEET) throw new Error(`output-sheet-mismatch:${names.join(",")}`);
  const values = workbook.worksheets.getItem(TEMPLATE_SHEET).getRange("A1:C45").values;
  if (JSON.stringify(values[0]) !== JSON.stringify(["项目", "注意事项", "具体方案"])) {
    throw new Error(`output-header-mismatch:${JSON.stringify(values[0])}`);
  }
  for (let index = 1; index < values.length; index += 1) {
    if (String(values[index][0] ?? "") !== String(templateValues[index][0] ?? "")) throw new Error(`project-drift:row-${index + 1}`);
    const originalAttention = String(templateValues[index][1] ?? "").trim();
    const attention = String(values[index][1] ?? "");
    if (!attention.includes(`检查点：${originalAttention}`) || !attention.includes("巡店发现：") || attention.includes("证据：")) {
      throw new Error(`attention-contract:row-${index + 1}`);
    }
  }
  const errors = await workbook.inspect({
    kind: "match",
    searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
    options: { useRegex: true, maxResults: 100 },
    summary: "final formula error scan",
  });
  const formulaMatches = String(errors.ndjson ?? "")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line))
    .filter((entry) => entry.kind === "match");
  if (formulaMatches.length) throw new Error(`formula-errors:${JSON.stringify(formulaMatches)}`);
  return { outputPath, sheet: TEMPLATE_SHEET, checks: DETAIL_COUNT };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , inputPath, outputPath, previewDir] = process.argv;
  if (!inputPath || !outputPath || !previewDir) throw new Error("usage: build_inspection_result.mjs <inspection.json> <output.xlsx> <preview-dir>");
  const result = await buildInspectionResult({ inputPath, outputPath, previewDir });
  console.log(JSON.stringify({ ...result, validation: await validateInspectionResult(outputPath) }, null, 2));
}
