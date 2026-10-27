import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { Workbook, SpreadsheetFile } from "@oai/artifact-tool";

const baseDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const date = process.argv[2];

if (!/^\d{4}-\d{2}-\d{2}$/.test(date ?? "")) {
  throw new Error("请传入 YYYY-MM-DD 日期。");
}

const outputPath = path.join(baseDir, "records", `美团客户回复记录-${date}.xlsx`);
await fs.mkdir(path.dirname(outputPath), { recursive: true, mode: 0o700 });
try {
  await fs.access(outputPath);
  throw new Error("当日台账已存在，不覆盖。");
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("当日记录");
sheet.showGridLines = false;
sheet.getRange("A1:H1").merge();
sheet.getRange("A1").values = [[`美团客户回复记录 ${date}`]];
sheet.getRange("A2:H2").merge();
sheet.getRange("A2").values = [["已核验回复：0 条"]];
const headers = [["日期", "发送时间", "脱敏会话标识", "门店", "客户问题摘要", "实际回复", "平台核验状态", "备注"]];
sheet.getRange("A4:H4").values = headers;
sheet.getRange("A1:H1").format = {
  fill: "#1F4E78",
  font: { name: "Arial", size: 14, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  rowHeight: 28,
};
sheet.getRange("A2:H2").format = {
  fill: "#EAF2F8",
  font: { name: "Arial", size: 11, color: "#1F1F1F" },
  horizontalAlignment: "left",
  verticalAlignment: "center",
  rowHeight: 22,
};
sheet.getRange("A4:H4").format = {
  fill: "#5B9BD5",
  font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
  horizontalAlignment: "center",
  verticalAlignment: "center",
  wrapText: true,
  rowHeight: 28,
};
const widths = [105, 125, 150, 230, 250, 390, 140, 220];
for (let index = 0; index < widths.length; index += 1) {
  const column = String.fromCharCode(65 + index);
  sheet.getRange(`${column}:${column}`).format.columnWidthPx = widths[index];
}
sheet.tables.add("A4:H4", true, "DailyReplyLog").style = "TableStyleMedium2";
sheet.freezePanes.freezeRows(4);

const inspection = await workbook.inspect({
  kind: "region",
  sheetId: sheet.id ?? sheet.name,
  range: "A1:H6",
  include: "values,formulas",
});
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(outputPath);
const bytes = await fs.readFile(outputPath);
console.log(JSON.stringify({
  ok: true,
  outputPath,
  sha256: crypto.createHash("sha256").update(bytes).digest("hex"),
  size: bytes.length,
  inspection: inspection.ndjson,
}));
