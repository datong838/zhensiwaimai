// 汇总当日客户回复：把 records/待整理客户回复-<date>.md 的 Markdown 表格
// 写入 records/美团客户回复记录-<date>.xlsx（与 build_empty_daily_reply_log.mjs /
// append_daily_reply_log.mjs 共用同一工作簿结构与去重规则）。
// 用法: node compile_daily_reply_xlsx.mjs <YYYY-MM-DD>
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { FileBlob, SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const baseDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
function localDate() {
  const d = new Date();
  const local = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return local.toISOString().slice(0, 10);
}
const date = process.argv[2] || localDate();
if (!/^\d{4}-\d{2}-\d{2}$/.test(date ?? "")) {
  throw new Error("请传入 YYYY-MM-DD 日期。");
}

const mdPath = path.join(baseDir, "records", `待整理客户回复-${date}.md`);
const xlsxPath = path.join(baseDir, "records", `美团客户回复记录-${date}.xlsx`);
const scanPath = path.join(baseDir, "records", `.last-scan-${date}.json`);

// 候选（已核验待回复）计数：优先 --candidate，其次 step2 落盘的 last-scan 文件；缺省 0。
// scanned/views 同样取自 last-scan，供 0 条时如实记录「本轮真实检查覆盖数」（不静默）。
let candidate = 0, scanned = null, views = null;
try {
  const s = JSON.parse(await fs.readFile(scanPath, "utf-8"));
  candidate = Number(s.candidateCount) || 0;
  scanned = s.scanned; views = s.views;
} catch {}
const ci = process.argv.indexOf("--candidate");
if (ci >= 0 && Number.isFinite(Number(process.argv[ci + 1]))) candidate = Number(process.argv[ci + 1]);

// 0 条/矛盾判定：md 缺失或解析 0 行时，按候选计数区分「真 0 条」与「矛盾缺口」。
function decideZeroOrGap() {
  if (candidate > 0) {
    // 候选>0 却无记账 → 当轮 FAIL + CRITICAL（方案 §52② / §53：禁止静默发送空表）
    console.log(JSON.stringify({ compiled: 0, reason: "ledger-gap-contradiction", candidate, ledgerRows: 0, scanned, views }));
    process.exit(1);
  }
  // 真 0 条：按用户规格「有回复才汇总 Excel 发群」——不产表、不汇总、不静默（如实写覆盖数）
  console.log(JSON.stringify({ compiled: 0, reason: "zero-replies-no-aggregate", candidate: 0, scanned, views }));
  process.exit(0);
}

let mdText;
try {
  mdText = await fs.readFile(mdPath, "utf-8");
} catch {
  decideZeroOrGap();
}

// 解析 Markdown 表格（跳过标题/表头/分隔行）
const records = [];
let headerSeen = false;
for (const line of mdText.split("\n")) {
  const t = line.trim();
  if (!t.startsWith("|")) continue;
  if (/^\|[\s\-:|]+\|$/.test(t)) continue; // 分隔行
  const cells = t.split("|").slice(1, -1).map((c) => c.trim());
  if (cells.length < 8) continue;
  if (!headerSeen) { headerSeen = true; continue; }
  records.push({
    date: cells[0],
    sentAt: cells[1],
    session: cells[2],
    store: cells[3],
    question: cells[4],
    reply: cells[5],
    status: cells[6],
    note: cells[7] || "仅保留脱敏业务信息",
  });
}

if (records.length === 0) decideZeroOrGap();

// 确保工作簿存在（缺失则先用既有 build_empty 建空簿，含表头与 DailyReplyLog 表）
try {
  await FileBlob.load(xlsxPath);
} catch {
  execFileSync(process.execPath, [path.join(baseDir, "scripts", "build_empty_daily_reply_log.mjs"), date], { stdio: "inherit" });
}

const source = await FileBlob.load(xlsxPath);
const workbook = await SpreadsheetFile.importXlsx(source);
const sheet = workbook.worksheets.getItem("当日记录");
const table = sheet.tables.getItem("DailyReplyLog");
const rows = sheet.getRange("A5:H1000").values;
const dataRows = rows.filter((r) => (r[1] ?? "") !== "" || (r[2] ?? "") !== "");
const seen = new Set(dataRows.map((r) => `${r[1]}|${r[2]}|${r[5]}`));

let added = 0;
for (const r of records) {
  const key = `${r.sentAt}|${r.session}|${r.reply}`;
  if (seen.has(key)) continue;
  table.rows.add(null, [[
    new Date(`${r.date}T00:00:00Z`),
    r.sentAt,
    r.session,
    r.store,
    r.question,
    r.reply,
    r.status,
    r.note,
  ]]);
  seen.add(key);
  added++;
}

workbook.recalculate();
const formulaErrors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
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
await output.save(xlsxPath);
console.log(JSON.stringify({ compiled: added, scanned: records.length, xlsxPath }));
