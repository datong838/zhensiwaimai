import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile } from "/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const baseDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const input = process.argv[2];

if (!input) {
  throw new Error("请传入一条 JSON 记录。");
}

const record = JSON.parse(input);
for (const key of ["date", "sentAt", "session", "store", "question", "reply", "status"]) {
  if (!record[key] || typeof record[key] !== "string") {
    throw new Error(`记录字段缺失或无效：${key}`);
  }
}

const workbookPath = `${baseDir}/records/美团客户回复记录-${record.date}.xlsx`;
const source = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(source);
const sheet = workbook.worksheets.getItem("当日记录");
const rows = sheet.getRange("A5:H1000").values;
const exists = rows.some((row) =>
  String(row[1] ?? "") === record.sentAt &&
  String(row[2] ?? "") === record.session &&
  String(row[5] ?? "") === record.reply
);

if (exists) {
  console.log(JSON.stringify({ appended: false, reason: "duplicate", workbookPath }));
  process.exit(0);
}

const table = sheet.tables.getItem("DailyReplyLog");
table.rows.add(null, [[
  new Date(`${record.date}T00:00:00Z`),
  record.sentAt,
  record.session,
  record.store,
  record.question,
  record.reply,
  record.status,
  record.note ?? "仅保留脱敏业务信息"
]]);

workbook.recalculate();
const verification = await workbook.inspect({
  kind: "table",
  range: "当日记录!A4:H1000",
  include: "values,formulas",
  tableMaxRows: 1000,
  tableMaxCols: 8
});
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan"
});
if (formulaErrors.ndjson.split("\n").some((line) => {
  try {
    const item = JSON.parse(line);
    return item.type === "match" || (Array.isArray(item.matches) && item.matches.length > 0);
  } catch {
    return false;
  }
})) {
  throw new Error("工作簿存在公式错误，未保存。");
}

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(workbookPath);
console.log(JSON.stringify({ appended: true, workbookPath, verification: verification.ndjson }));
