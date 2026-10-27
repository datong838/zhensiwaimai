import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const [, , inputPath, outputDir] = process.argv;
if (!inputPath || !outputDir) {
  throw new Error("usage: inspect_inspection_template.mjs <template.xlsx> <preview-dir>");
}

const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(inputPath));
const summary = await workbook.inspect({
  kind: "workbook,sheet,table,region",
  maxChars: 24000,
  tableMaxRows: 80,
  tableMaxCols: 20,
  tableMaxCellChars: 200,
});

await fs.mkdir(outputDir, { recursive: true });
const sheets = [];
for (const sheet of workbook.worksheets.items) {
  const used = sheet.getUsedRange(false);
  const values = used?.values ?? [];
  sheets.push({ name: sheet.name, rows: values.length, columns: Math.max(0, ...values.map((row) => row.length)), values });
  const preview = await workbook.render({ sheetName: sheet.name, autoCrop: "all", scale: 1.5, format: "png" });
  await fs.writeFile(path.join(outputDir, `${sheet.name}.png`), new Uint8Array(await preview.arrayBuffer()));
}

console.log(JSON.stringify({ summary: summary.ndjson, sheets }, null, 2));
