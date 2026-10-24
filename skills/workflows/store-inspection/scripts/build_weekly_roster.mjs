import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const HEADERS = ["平台", "店铺名称", "所在城市", "是否已巡店", "巡店日期", "巡店结果文件"];

export function storeKey(row) {
  return [row.platform, row.name, row.city].map((v) => String(v ?? "").trim()).join("\u0000");
}

export function normalizeRecords(records) {
  const map = new Map();
  for (const row of records ?? []) {
    const normalized = {
      platform: String(row.platform ?? "").trim(),
      name: String(row.name ?? "").trim(),
      city: String(row.city ?? "").trim(),
    };
    if (!normalized.platform || !normalized.name || !normalized.city) {
      throw new Error(`invalid-roster-row:${JSON.stringify(row)}`);
    }
    map.set(storeKey(normalized), normalized);
  }
  return [...map.values()].sort((a, b) =>
    a.platform.localeCompare(b.platform, "zh-CN") ||
    a.city.localeCompare(b.city, "zh-CN") ||
    a.name.localeCompare(b.name, "zh-CN"));
}

async function readExistingStatus(outputPath) {
  try {
    await fs.access(outputPath);
  } catch {
    return new Map();
  }
  const book = await SpreadsheetFile.importXlsx(await FileBlob.load(outputPath));
  const sheet = book.worksheets.getItem("巡店台账");
  const used = sheet.getUsedRange(true);
  const values = used?.values ?? [];
  const status = new Map();
  for (const row of values.slice(3)) {
    if (!row?.[0] || !row?.[1] || !row?.[2]) continue;
    status.set([row[0], row[1], row[2]].map(String).join("\u0000"), {
      inspected: row[3] === "是" ? "是" : "否",
      date: row[4] ?? "",
      result: row[5] ?? "",
    });
  }
  return status;
}

export async function buildWeeklyRoster({ inputPath, outputPath }) {
  const source = JSON.parse(await fs.readFile(inputPath, "utf8"));
  const records = normalizeRecords(source.records);
  const existing = await readExistingStatus(outputPath);
  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add("巡店台账");
  sheet.showGridLines = false;

  sheet.getRange("A2:F2").values = [[`${source.week} 巡店台账`, "", "", "", "", ""]];
  sheet.mergeCells("A2:F2");
  sheet.getRange("A3:F3").values = [HEADERS];
  const rows = records.map((row) => {
    const old = existing.get(storeKey(row)) ?? { inspected: "否", date: "", result: "" };
    return [row.platform, row.name, row.city, old.inspected, old.date, old.result];
  });
  if (rows.length) sheet.getRange(`A4:F${rows.length + 3}`).values = rows;

  const used = sheet.getRange(`A2:F${rows.length + 3}`);
  used.format.font = { name: "Arial", size: 10, color: "#1F2937" };
  used.format.verticalAlignment = "center";
  sheet.getRange("A2:F2").format = {
    fill: "#1F4E78",
    font: { name: "Arial", size: 14, bold: true, color: "#FFFFFF" },
    rowHeight: 28,
    verticalAlignment: "center",
  };
  sheet.getRange("A3:F3").format = {
    fill: "#4472C4",
    font: { name: "Arial", size: 10, bold: true, color: "#FFFFFF" },
    rowHeight: 24,
    horizontalAlignment: "center",
    verticalAlignment: "center",
    borders: { preset: "all", style: "thin", color: "#D9E2F3" },
  };
  if (rows.length) {
    sheet.getRange(`A4:F${rows.length + 3}`).format.borders = {
      preset: "all", style: "thin", color: "#E5E7EB",
    };
    sheet.getRange(`D4:D${rows.length + 3}`).dataValidation = {
      rule: { type: "list", values: ["否", "是"] },
    };
    sheet.getRange(`D4:D${rows.length + 3}`).conditionalFormats.add("containsText", {
      text: "是", format: { fill: "#DCFCE7", font: { color: "#166534", bold: true } },
    });
  }
  sheet.getRange("A:A").format.columnWidth = 14;
  sheet.getRange("B:B").format.columnWidth = 38;
  sheet.getRange("C:C").format.columnWidth = 22;
  sheet.getRange("D:D").format.columnWidth = 14;
  sheet.getRange("E:E").format.columnWidth = 14;
  sheet.getRange("F:F").format.columnWidth = 64;
  sheet.getRange(`B4:B${Math.max(4, rows.length + 3)}`).format.wrapText = true;
  sheet.getRange(`F4:F${Math.max(4, rows.length + 3)}`).format.wrapText = false;
  sheet.freezePanes.freezeRows(3);
  sheet.freezePanes.freezeColumns(3);
  sheet.tables.add(`A3:F${rows.length + 3}`, true, "WeeklyInspectionRoster");
  workbook.recalculate();

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const preview = await workbook.render({ sheetName: "巡店台账", range: "A2:F18", scale: 1.5, format: "png" });
  await fs.writeFile(outputPath.replace(/\.xlsx$/i, ".preview.png"), new Uint8Array(await preview.arrayBuffer()));
  const exported = await SpreadsheetFile.exportXlsx(workbook);
  await exported.save(outputPath);
  return { outputPath, count: rows.length, sourceCounts: source.sourceCounts };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) throw new Error("usage: build_weekly_roster.mjs <roster.json> <output.xlsx>");
  console.log(JSON.stringify(await buildWeeklyRoster({ inputPath, outputPath }), null, 2));
}
