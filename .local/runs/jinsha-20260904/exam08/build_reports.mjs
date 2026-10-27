import crypto from "node:crypto";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const DEFAULTS = {
  receipt: "/tmp/zhensi_jinsha_reports/download_receipt.json",
  buildReceipt: "/tmp/zhensi_jinsha_reports/build_receipt.json",
  customer: "/Users/ddt/work/臻肆/报表/客户表最新.xlsx",
  meituanReference: "/Users/ddt/work/臻肆/报表/美团全部_2026-08-25至2026-08-25.xlsx",
  taobaoTemplate: "/Users/ddt/work/臻肆/报表/淘宝闪购_模版2026-08-24至2026-08-24.xlsx",
  outputDir: "/Users/ddt/work/臻肆/报表",
  filenameSuffix: "",
  titleSuffix: "",
};
function normalizeId(value) {
  if (value == null) return "";
  return String(value).trim().replace(/\.0+$/, "");
}

function isNumericId(value) {
  return /^\d+$/.test(normalizeId(value));
}

async function loadWorkbook(file) {
  return SpreadsheetFile.importXlsx(await FileBlob.load(file));
}

async function valuesOf(workbook) {
  const sheet = workbook.worksheets.getItemAt(0);
  const values = await sheet.getUsedRange(true).values;
  return { sheet, values };
}

function indexHeaders(headers) {
  return new Map(headers.map((value, index) => [String(value ?? "").trim(), index]));
}

function buildCustomerMap(rows, idHeader) {
  const headers = indexHeaders(rows[0] ?? []);
  const idIndex = headers.get(idHeader);
  const directorIndex = headers.get("运营总监");
  const levelIndex = headers.get("客户等级");
  if ([idIndex, directorIndex, levelIndex].some((value) => value == null)) throw new Error(`customer-columns-missing:${idHeader}`);
  const map = new Map();
  let ignoredNonNumeric = 0;
  let duplicateSame = 0;
  let duplicateConflict = 0;
  for (const row of rows.slice(1)) {
    const id = normalizeId(row[idIndex]);
    if (!id) continue;
    if (!isNumericId(id)) {
      ignoredNonNumeric += 1;
      continue;
    }
    const next = { director: row[directorIndex] ?? "", level: row[levelIndex] ?? "" };
    if (map.has(id)) {
      const prior = map.get(id);
      if (prior.director !== next.director || prior.level !== next.level) {
        duplicateConflict += 1;
        continue;
      }
      duplicateSame += 1;
      continue;
    }
    map.set(id, next);
  }
  return { map, ignoredNonNumeric, duplicateSame, duplicateConflict };
}

function requireDownloadRows(rows, platform) {
  if (rows.length < 3) throw new Error(`${platform}-download-empty`);
  const headers = indexHeaders(rows[1] ?? []);
  if (!headers.has("店铺ID")) throw new Error(`${platform}-shop-id-missing`);
  return headers;
}

function stableRevenueDescending(rows, revenueIndex) {
  return rows.map((row, index) => ({ row, index })).sort((left, right) => {
    const leftValue = Number(left.row[revenueIndex] ?? 0);
    const rightValue = Number(right.row[revenueIndex] ?? 0);
    if (!Number.isFinite(leftValue) || !Number.isFinite(rightValue)) throw new Error("revenue-not-numeric");
    return rightValue - leftValue || left.index - right.index;
  }).map(({ row }) => row);
}

function verifyRevenueDescending(rows, revenueIndex) {
  for (let index = 1; index < rows.length; index += 1) {
    if (Number(rows[index - 1][revenueIndex]) < Number(rows[index][revenueIndex])) {
      throw new Error(`revenue-sort-failed:${index}`);
    }
  }
}

async function extendStyleRows(sheet, templateLastRow, targetLastRow, lastColumn) {
  if (targetLastRow <= templateLastRow) return;
  const source = sheet.getRange(`A${templateLastRow}:${lastColumn}${templateLastRow}`);
  for (let row = templateLastRow + 1; row <= targetLastRow; row += 1) {
    sheet.getRange(`A${row}:${lastColumn}${row}`).copyFrom(source, "all");
  }
}

async function normalizeBodyRows(sheet, targetLastRow, lastColumn) {
  const source = sheet.getRange(`A3:${lastColumn}3`);
  for (let row = 4; row <= targetLastRow; row += 1) {
    sheet.getRange(`A${row}:${lastColumn}${row}`).copyFrom(source, "all");
  }
  // Imported template styles do not reliably extend beyond its original rows.
  // Apply the actual current data range explicitly, without changing values.
  const body = sheet.getRange(`A3:${lastColumn}${targetLastRow}`);
  body.format.borders = { preset: "all", style: "thin", color: "#000000" };
  body.format.horizontalAlignment = "center";
  body.format.verticalAlignment = "center";
  body.format.rowHeight = 20;
  const percentages = lastColumn === "AK"
    ? ["N", "O", "R", "S", "U", "V", "W", "X", "AC", "AG", "AJ"]
    : ["L", "M", "N", "R", "S", "T", "U", "V", "AA", "AB", "AC", "AD"];
  for (const column of percentages) {
    sheet.getRange(`${column}3:${column}${targetLastRow}`).setNumberFormat("0.00%");
  }
}

async function clearTrailing(sheet, firstRow, lastRow, lastColumn) {
  if (firstRow <= lastRow) sheet.getRange(`A${firstRow}:${lastColumn}${lastRow}`).clear({ applyTo: "contents" });
}

function clearTemplateValueHighlights(sheet, { lastRow, levelColumn, shopColumn, idColumn, ratingColumn, revenueColumn }) {
  if (lastRow < 3) return;
  sheet.getRange(`${levelColumn}3:${levelColumn}${lastRow}`).format = { fill: "#FFFFFF", font: { color: "#000000" } };
  for (const column of [shopColumn, idColumn, ratingColumn]) {
    sheet.getRange(`${column}3:${column}${lastRow}`).format = { fill: "#FFFFFF", font: { color: "#000000" } };
  }
  sheet.getRange(`${revenueColumn}3:${revenueColumn}${lastRow}`).format = { fill: "#FFFFFF" };
}

function applyBusinessFormats(sheet, { lastRow, ratingColumn, revenueColumn, levelColumn, dataBarColumns, lastColumn, preserveTemplateDataBars = false }) {
  if (lastRow < 3) return;
  if (!preserveTemplateDataBars) {
    sheet.getRange(`A3:${lastColumn}${lastRow}`).conditionalFormats.deleteAll();
    for (const column of dataBarColumns) {
      sheet.getRange(`${column}3:${column}${lastRow}`).conditionalFormats.add("dataBar", {
        color: "#F5A623", thresholds: ["min", "max"], gradient: true,
      });
    }
  }
  sheet.getRange(`${ratingColumn}3:${ratingColumn}${lastRow}`).conditionalFormats.add("cellIs", {
    operator: "lessThan", formula: 4.3, format: { font: { color: "#FF0000" } },
  });
  sheet.getRange(`${revenueColumn}3:${revenueColumn}${lastRow}`).conditionalFormats.add("cellIs", {
    operator: "between", formula: [0, 300], format: { fill: "#FFF200" },
  });
  sheet.getRange(`${levelColumn}3:${levelColumn}${lastRow}`).conditionalFormats.addCustom(
    `=OR($${levelColumn}3="A",$${levelColumn}3="S")`, { font: { color: "#FF0000" } },
  );
}

function mapMeituan(rows, customerMap) {
  const headers = requireDownloadRows(rows, "meituan");
  const idIndex = headers.get("店铺ID");
  const output = [];
  const unmatched = [];
  for (const row of rows.slice(2)) {
    if (row.every((value) => value == null || value === "")) continue;
    const id = normalizeId(row[idIndex]);
    const customer = customerMap.get(id);
    if (!customer) unmatched.push(id || "(blank)");
    output.push([
      row[1], row[2], customer?.director || "（未匹配）", customer?.level || "（未匹配）",
      row[0], ...row.slice(3),
    ]);
  }
  const sorted = stableRevenueDescending(output, 8);
  verifyRevenueDescending(sorted, 8);
  return { output: sorted, unmatched, revenueIndex: 8 };
}

function mapTaobao(rows, customerMap) {
  const headers = requireDownloadRows(rows, "taobao");
  const idIndex = headers.get("店铺ID");
  const output = [];
  const unmatched = [];
  for (const row of rows.slice(2)) {
    if (row.every((value) => value == null || value === "")) continue;
    const id = normalizeId(row[idIndex]);
    const customer = customerMap.get(id);
    if (!customer) unmatched.push(id || "(blank)");
    output.push([
      row[1], customer?.director || "（未匹配）", customer?.level || "（未匹配）",
      row[2], normalizeId(row[3]), ...row.slice(4),
    ]);
  }
  const sorted = stableRevenueDescending(output, 7);
  verifyRevenueDescending(sorted, 7);
  return { output: sorted, unmatched, revenueIndex: 7 };
}

async function sha256File(file) {
  return crypto.createHash("sha256").update(await fs.readFile(file)).digest("hex");
}

async function saveReceipt(file, receipt) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${Date.now()}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, file);
}

export async function verifySavedWorkbook(file, expectedValues, lastColumn, dataBarCount) {
  const saved = await loadWorkbook(file);
  const actual = saved.worksheets.getItemAt(0).getRange(`A2:${lastColumn}${expectedValues.length + 1}`).values;
  if (JSON.stringify(actual) !== JSON.stringify(expectedValues)) throw new Error("saved-values-mismatch");
  // 只读检查实际磁盘中的标准条件格式，不把内存预览当作保存证明。
  const xml = execFileSync("/usr/bin/unzip", ["-p", file, "xl/worksheets/sheet1.xml"], { encoding: "utf8", maxBuffer: 12 * 1024 * 1024 });
  const rules = [...xml.matchAll(/<(?:x:)?cfRule\b[^>]*>/g)].map((m) => m[0]);
  const bars = rules.filter((r) => /type="dataBar"/.test(r)).length;
  if (bars !== dataBarCount || !rules.some((r) => /operator="lessThan"/.test(r)) ||
      !rules.some((r) => /operator="between"/.test(r)) || !rules.some((r) => /type="expression"/.test(r))) {
    throw new Error("saved-conditional-format-missing");
  }
  const styles = execFileSync("/usr/bin/unzip", ["-p", file, "xl/styles.xml"], { encoding: "utf8", maxBuffer: 12 * 1024 * 1024 });
  verifyBodyStyles(xml, styles, lastColumn, expectedValues.length + 1);
  return { savedValuesVerified: true, savedDataBars: bars, savedBusinessRules: 3, savedBodyStylesVerified: true };
}

export function verifyBodyStyles(sheetXml, stylesXml, lastColumn, lastRow) {
  const xfsBlock = stylesXml.match(/<(?:\w+:)?cellXfs\b[^>]*>([\s\S]*?)<\/(?:\w+:)?cellXfs>/)?.[1] || "";
  const xfs = [...xfsBlock.matchAll(/<(?:\w+:)?xf\b[^>]*>/g)].map(m => m[0]);
  const percentageColumn = lastColumn === "AK" ? "N" : "L";
  for (const row of [3, lastRow]) {
    for (const column of ["A", percentageColumn, lastColumn]) {
      const tag = [...sheetXml.matchAll(/<(?:\w+:)?c\b[^>]*>/g)].map(m => m[0])
        .find(t => new RegExp(`\\br="${column}${row}"`).test(t));
      const styleId = Number(tag?.match(/\bs="(\d+)"/)?.[1] || 0);
      const style = xfs[styleId] || "";
      if (!tag || !/\bborderId="[1-9]\d*"/.test(style)) throw new Error("saved-body-border-missing");
      const formatId = style.match(/\bnumFmtId="(\d+)"/)?.[1];
      const customFormat = [...stylesXml.matchAll(/<(?:\w+:)?numFmt\b[^>]*>/g)].map(m => m[0])
        .find(t => new RegExp(`\\bnumFmtId="${formatId}"`).test(t));
      if (column === percentageColumn && formatId !== "10" &&
          !/\bformatCode="0\.00%"/.test(customFormat || "")) throw new Error("saved-body-percentage-missing");
    }
  }
}

async function exportVerified({ workbook, sheetName, output, topRange, bottomRange, previewPrefix, lastColumn, lastRow, dataBarCount }) {
  const expectedValues = workbook.worksheets.getItemAt(0).getRange(`A2:${lastColumn}${lastRow}`).values;
  const errors = await workbook.inspect({
    kind: "match", searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
    options: { useRegex: true, maxResults: 100 }, summary: "formula error scan", maxChars: 5000,
  });
  const bad = errors.ndjson.split("\n").filter((line) => /#REF!|#DIV\/0!|#VALUE!|#NAME\?|#N\/A/.test(line));
  if (bad.length) throw new Error(`${previewPrefix}-formula-errors:${bad.length}`);
  const top = await workbook.render({ sheetName, range: topRange, scale: 1, format: "png" });
  const bottom = await workbook.render({ sheetName, range: bottomRange, scale: 1, format: "png" });
  await fs.writeFile(`/tmp/zhensi_jinsha_reports/${previewPrefix}-top.png`, new Uint8Array(await top.arrayBuffer()));
  await fs.writeFile(`/tmp/zhensi_jinsha_reports/${previewPrefix}-bottom.png`, new Uint8Array(await bottom.arrayBuffer()));
  const blob = await SpreadsheetFile.exportXlsx(workbook);
  await blob.save(output);
  return verifySavedWorkbook(output, expectedValues, lastColumn, dataBarCount);
}

export async function runBuildReports(options = {}) {
  const config = { ...DEFAULTS, ...options };
  const receipt = JSON.parse(await fs.readFile(config.receipt, "utf8"));
  if (receipt.ok !== true || receipt.executor !== "jinsha-download") throw new Error("download-receipt-invalid");
  const businessDate = receipt.businessDate;
  const sources = {
    customer: await loadWorkbook(config.customer),
    meituan: await loadWorkbook(receipt.meituan.file),
    taobao: await loadWorkbook(receipt.taobao.file),
  };
  const customerRows = (await valuesOf(sources.customer)).values;
  const meituanRows = (await valuesOf(sources.meituan)).values;
  const taobaoRows = (await valuesOf(sources.taobao)).values;
  const meituanCustomer = buildCustomerMap(customerRows, "美团ID（完善）");
  const taobaoCustomer = buildCustomerMap(customerRows, "饿了么ID（完善）");
  const meituan = mapMeituan(meituanRows, meituanCustomer.map);
  const taobao = mapTaobao(taobaoRows, taobaoCustomer.map);

  await fs.mkdir(config.outputDir, { recursive: true });
  await fs.mkdir("/tmp/zhensi_jinsha_reports", { recursive: true });
  const outputs = {
    meituan: path.join(config.outputDir, `美团全部_${businessDate}至${businessDate}${config.filenameSuffix}.xlsx`),
    taobao: path.join(config.outputDir, `淘宝闪购_${businessDate}至${businessDate}${config.filenameSuffix}.xlsx`),
  };
  for (const file of Object.values(outputs)) {
    try { await fs.access(file); throw new Error(`output-already-exists:${file}`); } catch (error) {
      if (!String(error).includes("ENOENT")) throw error;
    }
  }

  const mtWorkbook = await loadWorkbook(config.meituanReference);
  const mtSheet = mtWorkbook.worksheets.getItemAt(0);
  const mtTemplateRows = (await mtSheet.getUsedRange(true).values).length;
  const mtLast = meituan.output.length + 2;
  await extendStyleRows(mtSheet, mtTemplateRows, mtLast, "AK");
  await normalizeBodyRows(mtSheet, mtLast, "AK");
  mtSheet.getRange("A2:AK2").values = [["日期", "分组", "运营总监", "客户等级", "店铺名称", "店铺评分", "店铺ID", "月售销量", "营收", "单均实付", "单均到手", "商圈前10营收", "曝光人数", "进店率", "下单率", "有效订单", "【商圈前10】曝光人数", "【商圈前10】进店率", "【商圈前10】下单率", "【商圈前10】有效订单", "30天复购率【新客】", "30天复购率【老客】", "【商圈前十】30天新客复购率", "【商圈前十】30天老客复购率", "点金推广费用", "点金推广【进店次数】", "点金推广【单次进店成本】", "总推广费用", "总推广费用占营收比", "曝光量系数", "评价数量", "好评数量", "好评率", "中评数量", "差评数量", "差评率", "门店排行/商圈同行数量"]];
  mtSheet.getRange("E1").values = [[`${businessDate}至${businessDate} 美团全部数据汇总${config.titleSuffix}`]];
  mtSheet.getRange(`A3:AK${mtLast}`).values = meituan.output;
  await clearTrailing(mtSheet, mtLast + 1, Math.max(mtTemplateRows, mtLast), "AK");
  clearTemplateValueHighlights(mtSheet, { lastRow: mtLast, levelColumn: "D", shopColumn: "E", idColumn: "G", ratingColumn: "F", revenueColumn: "I" });
  applyBusinessFormats(mtSheet, { lastRow: mtLast, ratingColumn: "F", revenueColumn: "I", levelColumn: "D", dataBarColumns: ["H", "I", "M", "N", "O", "P", "V"], lastColumn: "AK" });

  const tbWorkbook = await loadWorkbook(config.taobaoTemplate);
  const tbSheet = tbWorkbook.worksheets.getItemAt(0);
  const tbTemplateRows = (await tbSheet.getUsedRange(true).values).length;
  const tbLast = taobao.output.length + 2;
  await extendStyleRows(tbSheet, tbTemplateRows, tbLast, "AD");
  await normalizeBodyRows(tbSheet, tbLast, "AD");
  tbSheet.getRange("A2:AD2").values = [["日期", "运营总监", "客户等级", "店铺名称", "店铺ID", "店铺评分", "有效订单", "营收", "单均实付", "单均到手", "曝光人数", "进店率", "下单率", "综合转化率", "新客曝光人数", "老客曝光人数", "老客下单人数", "新客进店转化率", "老客进店转化率", "新客下单转化率", "老客下单转化率", "近30天复购率", "评价数量", "好评数量", "中评数量", "差评数量", "评价率", "好评率", "中评率", "差评率"]];
  tbSheet.getRange("D1").values = [[`${businessDate}至${businessDate} 淘宝闪购数据汇总${config.titleSuffix}`]];
  tbSheet.getRange(`A3:AD${tbLast}`).values = taobao.output;
  await clearTrailing(tbSheet, tbLast + 1, Math.max(tbTemplateRows, tbLast), "AD");
  clearTemplateValueHighlights(tbSheet, { lastRow: tbLast, levelColumn: "C", shopColumn: "D", idColumn: "E", ratingColumn: "F", revenueColumn: "H" });
  applyBusinessFormats(tbSheet, { lastRow: tbLast, ratingColumn: "F", revenueColumn: "H", levelColumn: "C", dataBarColumns: ["G", "H", "K", "L", "M", "V"], lastColumn: "AD", preserveTemplateDataBars: true });

  const savedVerification = {};
  savedVerification.meituan = await exportVerified({ workbook: mtWorkbook, sheetName: mtSheet.name, output: outputs.meituan, topRange: "A1:AK22", bottomRange: `A${Math.max(3, mtLast - 12)}:AK${mtLast}`, previewPrefix: "meituan", lastColumn: "AK", lastRow: mtLast, dataBarCount: 7 });
  savedVerification.taobao = await exportVerified({ workbook: tbWorkbook, sheetName: tbSheet.name, output: outputs.taobao, topRange: "A1:AD22", bottomRange: `A${Math.max(3, tbLast - 12)}:AD${tbLast}`, previewPrefix: "taobao", lastColumn: "AD", lastRow: tbLast, dataBarCount: 6 });

  const result = {
    ok: true, executor: "build-reports", businessDate,
    customerAudit: {
      meituanIgnoredNonNumeric: meituanCustomer.ignoredNonNumeric,
      taobaoIgnoredNonNumeric: taobaoCustomer.ignoredNonNumeric,
      meituanDuplicateSame: meituanCustomer.duplicateSame,
      taobaoDuplicateSame: taobaoCustomer.duplicateSame,
      meituanDuplicateConflict: meituanCustomer.duplicateConflict,
      taobaoDuplicateConflict: taobaoCustomer.duplicateConflict,
    },
    files: {},
  };
  for (const platform of ["meituan", "taobao"]) {
    const file = outputs[platform];
    const stat = await fs.stat(file);
    const mapped = platform === "meituan" ? meituan : taobao;
    result.files[platform] = {
      file, name: path.basename(file), size: stat.size, sha256: await sha256File(file),
      savedVerification: savedVerification[platform],
      rows: mapped.output.length, matched: mapped.output.length - mapped.unmatched.length,
      sort: { column: "营收", order: "desc", first: Number(mapped.output[0]?.[mapped.revenueIndex] ?? 0), last: Number(mapped.output.at(-1)?.[mapped.revenueIndex] ?? 0), verified: true },
      unmatched: mapped.unmatched,
    };
  }
  await saveReceipt(config.buildReceipt, result);
  return result;
}

if (process.argv[1]?.endsWith("build_reports.mjs")) {
  runBuildReports().then((result) => console.log(JSON.stringify(result))).catch((error) => {
    console.error(error.stack || String(error)); process.exitCode = 1;
  });
}
