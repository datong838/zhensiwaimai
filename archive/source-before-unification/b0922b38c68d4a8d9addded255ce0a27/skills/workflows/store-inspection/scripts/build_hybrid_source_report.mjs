import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const FIRST_ROW = 2;
const LAST_ROW = 45;
const SOURCE_LABELS = {
  jinsha_report: "金鲨数据下载",
  agent_service_backend: "淘宝服务商后台",
  brand_backend: "淘宝品牌商后台",
  meituan_backend: "美团商家后台",
  consumer_page: "手机翻查",
};
const MOBILE_MODULE_LABELS = {
  search: "搜索",
  products: "商品",
  reviews: "评价",
  merchant: "商家信息",
};

function text(value) { return String(value ?? "").trim(); }

function carryProjectNames(values) {
  let current = "";
  return values.map((row) => {
    if (text(row[0])) current = text(row[0]);
    return current;
  });
}

function oldFinding(value) {
  const content = text(value);
  const marker = "巡店发现：";
  const index = content.indexOf(marker);
  return index < 0 ? "" : content.slice(index + marker.length).trim();
}

export function buildSourceRows({ inspection, templateValues, oldResultValues }) {
  if (!Array.isArray(inspection?.templateChecks) || inspection.templateChecks.length !== 44) {
    throw new Error("source-report-template-check-count");
  }
  const ledger = new Map((inspection.sourceLedger ?? []).map((item) => [Number(item.row), item]));
  const projects = carryProjectNames(templateValues.slice(1));
  const rows = [];
  for (let row = FIRST_ROW; row <= LAST_ROW; row += 1) {
    const finding = text(inspection.templateChecks[row - FIRST_ROW]?.finding);
    const source = ledger.get(row);
    if (finding && !source) throw new Error(`source-ledger-missing:row-${row}`);
    if (!finding && source) throw new Error(`source-ledger-without-finding:row-${row}`);
    const old = oldFinding(oldResultValues?.[row - 1]?.[1]);
    let comparison = "";
    if (finding && old) comparison = finding === old ? "内容一致" : "观察结果变化";
    else if (finding) comparison = "本次新增";
    else if (old) comparison = "本次未复核，未沿用旧值";
    rows.push([
      row,
      projects[row - FIRST_ROW],
      text(templateValues[row - 1]?.[1]),
      source ? SOURCE_LABELS[source.sourceType] : "留空",
      source ? text(source.observedDate) : "",
      finding,
      comparison,
    ]);
  }
  return rows;
}

export async function buildHybridSourceReport({ inspectionPath, templatePath, oldResultPath, outputPath, previewPath }) {
  const inspection = JSON.parse(await fs.readFile(inspectionPath, "utf8"));
  const templateBook = await SpreadsheetFile.importXlsx(await FileBlob.load(templatePath));
  const templateValues = templateBook.worksheets.getItem("Sheet1").getRange("A1:C45").values;
  const oldBook = await SpreadsheetFile.importXlsx(await FileBlob.load(oldResultPath));
  const oldResultValues = oldBook.worksheets.getItem("Sheet1").getRange("A1:C45").values;
  const rows = buildSourceRows({ inspection, templateValues, oldResultValues });
  const counts = rows.reduce((acc, row) => {
    acc[row[3]] = (acc[row[3]] ?? 0) + 1;
    return acc;
  }, {});
  const covered = rows.length - (counts["留空"] ?? 0);

  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("来源汇报");
  sheet.showGridLines = false;
  sheet.getRange("A1:G1").values = [[`${inspection.platform}｜${inspection.city}｜${inspection.storeName}｜最终覆盖表`, "", "", "", "", "", ""]];
  sheet.mergeCells("A1:G1");
  sheet.getRange("A2:G2").values = [[
    `覆盖 ${covered}/44（${(covered / 44 * 100).toFixed(1)}%）`,
    `金鲨数据下载 ${counts["金鲨数据下载"] ?? 0} 条`,
    `淘宝服务商 ${counts["淘宝服务商后台"] ?? 0} 条`,
    `淘宝品牌商 ${counts["淘宝品牌商后台"] ?? 0} 条`,
    `美团商家后台 ${counts["美团商家后台"] ?? 0} 条`,
    `手机翻查 ${counts["手机翻查"] ?? 0} 条`,
    `留空 ${counts["留空"] ?? 0} 条`,
  ]];
  const moduleReceipts = inspection.executionReceipt?.mobileModuleReceipts ?? [];
  const mobileModules = inspection.executionReceipt?.completedStages?.includes("mobile")
    ? (moduleReceipts.length
      ? moduleReceipts.map((item) => `${MOBILE_MODULE_LABELS[item.module] ?? item.module}${item.status === "complete" ? `（${item.factRows?.length ?? 0}条）` : `（${item.status}）`}`).join("、")
      : (inspection.executionReceipt?.plannedMobileRows?.length ? "按执行计划完成所需模块" : "无需手机模块"))
    : "未提供执行收据";
  sheet.getRange("A3:G3").values = [[`巡店日 ${inspection.inspectionDate}；手机范围：${mobileModules}。后台只计入实际读取且通过门店身份门禁的字段；未取得字段保持留空。`, "", "", "", "", "", ""]];
  sheet.mergeCells("A3:G3");
  sheet.getRange("A5:G5").values = [["模板行", "项目", "检查点", "本次来源", "数据/观察日期", "本次结果", "与原结果对比"]];
  sheet.getRange("A6:G49").values = rows;

  sheet.getRange("A1:G49").format.font = { name: "Arial", size: 10, color: "#1F2937" };
  sheet.getRange("A1:G49").format.verticalAlignment = "top";
  sheet.getRange("A1:G49").format.wrapText = true;
  sheet.getRange("A1:G1").format = { fill: "#1F4E78", font: { name: "Arial", size: 14, bold: true, color: "#FFFFFF" }, rowHeight: 30, verticalAlignment: "center" };
  sheet.getRange("A2:G2").format = { fill: "#D9EAF7", font: { name: "Arial", size: 10, bold: true, color: "#1F2937" }, rowHeight: 40, verticalAlignment: "center", wrapText: true };
  sheet.getRange("A3:G3").format = { fill: "#FFF2CC", font: { name: "Arial", size: 10, color: "#7F6000" }, rowHeight: 34, verticalAlignment: "center", wrapText: true };
  sheet.getRange("A5:G5").format = { fill: "#4472C4", font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" }, rowHeight: 26, horizontalAlignment: "center", verticalAlignment: "center", borders: { preset: "all", style: "thin", color: "#D9E2F3" } };
  sheet.getRange("A6:G49").format.borders = { preset: "all", style: "thin", color: "#E5E7EB" };
  sheet.getRange("A:A").format.columnWidth = 16;
  sheet.getRange("B:B").format.columnWidth = 20;
  sheet.getRange("C:C").format.columnWidth = 48;
  sheet.getRange("D:D").format.columnWidth = 16;
  sheet.getRange("E:E").format.columnWidth = 15;
  sheet.getRange("F:F").format.columnWidth = 54;
  sheet.getRange("G:G").format.columnWidth = 24;
  sheet.getRange("D6:D49").conditionalFormats.add("containsText", { text: "金鲨数据下载", format: { fill: "#E0F2FE", font: { color: "#075985", bold: true } } });
  sheet.getRange("D6:D49").conditionalFormats.add("containsText", { text: "后台", format: { fill: "#EDE9FE", font: { color: "#5B21B6", bold: true } } });
  sheet.getRange("D6:D49").conditionalFormats.add("containsText", { text: "手机翻查", format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } } });
  sheet.getRange("D6:D49").conditionalFormats.add("containsText", { text: "留空", format: { fill: "#F3F4F6", font: { color: "#6B7280" } } });
  sheet.freezePanes.freezeRows(5);
  sheet.tables.add("A5:G49", true, "HybridSourceReport");
  workbook.recalculate();

  const errors = await workbook.inspect({ kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!", options: { useRegex: true, maxResults: 100 }, summary: "source report formula scan" });
  const matches = text(errors.ndjson).split("\n").filter(Boolean).map((line) => JSON.parse(line)).filter((entry) => entry.kind === "match");
  if (matches.length) throw new Error(`source-report-formula-errors:${JSON.stringify(matches)}`);

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.mkdir(path.dirname(previewPath), { recursive: true });
  const preview = await workbook.render({ sheetName: "来源汇报", range: "A1:G49", scale: 1.15, format: "png" });
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  await (await SpreadsheetFile.exportXlsx(workbook)).save(outputPath);
  return { outputPath, previewPath, covered, counts };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , inspectionPath, templatePath, oldResultPath, outputPath, previewPath] = process.argv;
  if (![inspectionPath, templatePath, oldResultPath, outputPath, previewPath].every(Boolean)) {
    throw new Error("usage: build_hybrid_source_report.mjs <inspection.json> <template.xlsx> <old-result.xlsx> <output.xlsx> <preview.png>");
  }
  console.log(JSON.stringify(await buildHybridSourceReport({ inspectionPath, templatePath, oldResultPath, outputPath, previewPath }), null, 2));
}
