import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const file = process.argv[2];
if (!file) throw new Error("usage: validate_weekly_roster.mjs <workbook.xlsx>");
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(file));
const sheet = workbook.worksheets.getItem("巡店台账");
const values = sheet.getUsedRange(true).values;
if (values.length !== 943) throw new Error(`row-count-mismatch:${values.length}`);
if (JSON.stringify(values[1]) !== JSON.stringify(["平台", "店铺名称", "所在城市", "是否已巡店", "巡店日期", "巡店结果文件"])) {
  throw new Error("header-mismatch");
}
const rows = values.slice(2).filter((row) => row?.[0]);
const keys = rows.map((row) => `${row[0]}\u0000${row[1]}\u0000${row[2]}`);
if (new Set(keys).size !== rows.length) throw new Error("duplicate-key");
if (rows.some((row) => row[3] !== "否" || row[4] || row[5])) throw new Error("unexpected-completion-state");
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 20 },
  summary: "final formula error scan",
});
console.log(JSON.stringify({
  ok: true,
  rows: rows.length,
  platforms: Object.fromEntries(["美团外卖", "淘宝闪购"].map((p) => [p, rows.filter((r) => r[0] === p).length])),
  firstRows: rows.slice(0, 3),
  formulaErrorScan: formulaErrors.ndjson,
}, null, 2));
