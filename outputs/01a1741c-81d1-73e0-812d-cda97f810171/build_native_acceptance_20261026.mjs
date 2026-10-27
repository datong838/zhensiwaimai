import fs from "node:fs/promises";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/outputs/01a1741c-81d1-73e0-812d-cda97f810171";
const xlsxPath = `${outputDir}/NATIVE-20261026-T01.xlsx`;
const pngPath = `${outputDir}/NATIVE-20261026-T01.png`;

await fs.mkdir(outputDir, { recursive: true });

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("合成测试数据");
sheet.showGridLines = false;

sheet.getRange("A2:D2").values = [["原生UI连续交付测试", null, null, null]];
sheet.mergeCells("A2:D2");
sheet.getRange("A2:D2").format = {
  font: { name: "Arial", size: 14, bold: true, color: "#17365D" },
  verticalAlignment: "center",
};
sheet.getRange("A3:D3").values = [["2026-10-26 合成数据，无客户信息与商家标识", null, null, null]];
sheet.mergeCells("A3:D3");
sheet.getRange("A3:D3").format = {
  font: { name: "Arial", size: 10, italic: true, color: "#666666" },
};

sheet.getRange("A5:D10").values = [
  ["序号", "测试项目", "数量", "状态"],
  [1, "合成记录甲", 12, "仅测试"],
  [2, "合成记录乙", 18, "仅测试"],
  [3, "合成记录丙", 15, "仅测试"],
  [4, "合成记录丁", 21, "仅测试"],
  ["合计", null, null, "核验三类载荷"],
];
sheet.getRange("C10").formulas = [["=SUM(C6:C9)"]];
sheet.getRange("A5:D5").format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "outside", style: "thin", color: "#1F4E78" },
};
sheet.getRange("A6:D10").format.font = { name: "Arial", size: 10, color: "#222222" };
sheet.getRange("A6:A10").format.horizontalAlignment = "center";
sheet.getRange("C6:D10").format.horizontalAlignment = "center";
sheet.getRange("C6:C10").format.numberFormat = "#,##0";
sheet.getRange("A10:D10").format = {
  fill: "#D9EAF7",
  font: { name: "Arial", size: 10, bold: true, color: "#17365D" },
  borders: { preset: "doubleBottom", style: "thin", color: "#1F4E78" },
};
sheet.getRange("A5:D10").format.borders = {
  insideHorizontal: { style: "thin", color: "#D9E2F3" },
  insideVertical: { style: "thin", color: "#EEF3F8" },
  bottom: { style: "thin", color: "#9EADBA" },
};
sheet.getRange("A2:D10").format.verticalAlignment = "center";
sheet.getRange("A2:A10").format.columnWidthPx = 72;
sheet.getRange("B2:B10").format.columnWidthPx = 190;
sheet.getRange("C2:C10").format.columnWidthPx = 86;
sheet.getRange("D2:D10").format.columnWidthPx = 150;
sheet.getRange("A2:D10").format.rowHeightPx = 24;
sheet.getRange("A2:D2").format.rowHeightPx = 34;

workbook.recalculate();

const table = await workbook.inspect({
  kind: "table",
  range: "合成测试数据!A2:D10",
  include: "values,formulas",
  tableMaxRows: 12,
  tableMaxCols: 6,
});
const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 50 },
  summary: "final formula error scan",
});
const preview = await workbook.render({
  sheetName: "合成测试数据",
  range: "A2:D10",
  scale: 1.5,
  format: "png",
});
await fs.writeFile(pngPath, new Uint8Array(await preview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(xlsxPath);

console.log(JSON.stringify({ xlsxPath, pngPath, table: table.ndjson, errors: errors.ndjson }));
