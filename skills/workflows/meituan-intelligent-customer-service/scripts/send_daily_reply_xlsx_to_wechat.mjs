// 美团客户回复记录每日落群发送器（17:00 汇总步骤的第三步）。
// 复用统一微信桥 workflow_bridge_windows.py（与 meituan-waimai-appeals 同一运输层），
// 仅登记 meituan-customer-reply-daily 这一业务身份，严格走 REGISTRY 合同校验。
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
// 2026-10-04 铁律硬闸：发群前读取 xlsx 实际数据行数，0 条汇总结果绝不外发 Excel。
// 复用 step3 同款 artifact_tool 解析工作簿（路径与 compile_daily_reply_xlsx.mjs 一致）。
import { FileBlob, SpreadsheetFile } from "/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/@oai/artifact-tool/dist/artifact_tool.mjs";

const run = promisify(execFile);
const python = "/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python";
const bridge = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/workflow_bridge_windows.py";
const group = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰";
const authorization = "user-20261001-meituan-customer-reply-daily";
const workflowId = "meituan-customer-reply-daily";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const skillRoot = path.dirname(__dirname);                       // .../skills/workflows/meituan-intelligent-customer-service
// 2026-10-05 修复：包迁入 skills/workflows/（多一层目录）后 repoRoot 少退一级，
// ledger 被算成 skills/state/... 与桥 REGISTRY 登记的 <项目根>/state/... 不一致 → workflow-ledger-mismatch 拒发。
const repoRoot = path.dirname(path.dirname(path.dirname(skillRoot)));  // .../zhensi_waimai_back

const shanghaiDay = (date = new Date()) =>
  new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
const shanghaiClock = (date = new Date()) =>
  new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Shanghai", hour12: false, hour: "2-digit", minute: "2-digit", second: "2-digit" }).format(date).replace(/:/g, "");
const runDate = shanghaiDay();
// 2026-10-03 大同指令：Excel 外发「当天当次数据、不限次数、没有重复门禁」。
// marker/输出目录从按天唯一改为每轮唯一（带时分秒轮次戳）——每轮都是全新事件，
// 桥的防重门禁天然不再拦截同日多次外发；每轮发送前由 step2 重新编译当日 Excel。
const roundStamp = `${runDate}-${shanghaiClock()}`;
const report = path.join(skillRoot, "records", `美团客户回复记录-${runDate}.xlsx`);
// 2026-10-05 20:39 桥侧受控维护（授权记录见 dependency_maintenance.py 同日条目）已把
// meituan-customer-reply-daily 的 expected_report 校正为本新布局路径，直接以 report 过桥。
const ledger = path.join(repoRoot, "state", "meituan-customer-reply-daily", "wechat-attempts");
const marker = `meituan-customer-reply-daily-${roundStamp}.json`;
const outputDir = path.join(skillRoot, "records", "wechat-delivery", `meituan-customer-reply-daily-${roundStamp}`);

function args() {
  return [bridge, "--workflow-id", workflowId, "--group", group, "--payload-type", "file",
    "--authorization", authorization, "--ledger", ledger, "--marker-name", marker,
    "--output-dir", outputDir, "--item", report,
    "--deadline-unix", String(Math.floor(Date.now() / 1000) + 840), "--execute"];
}

// 读取「当日记录」表实际数据行数（A5 起，有效行 = B/C 列任一非空）。
// 返回 -1 表示读取失败（保守交由 ledgerRows 回退判定，避免在读取异常时误发空表）。
async function countDataRows(xlsxPath) {
  try {
    const source = await FileBlob.load(xlsxPath);
    const workbook = await SpreadsheetFile.importXlsx(source);
    const sheet = workbook.worksheets.getItem("当日记录");
    const rows = sheet.getRange("A5:H1000").values;
    return rows.filter((r) => (r[1] ?? "") !== "" || (r[2] ?? "") !== "").length;
  } catch {
    return -1;
  }
}

async function main() {
  const supplied = process.argv.slice(2);
  const mode = supplied.find((v) => ["--execute", "--self-test"].includes(v)) || "--execute";
  const scanPath = path.join(skillRoot, "records", `.last-scan-${runDate}.json`);
  let scanned = null, views = null, candidate = 0, ledgerRows = 0;
  try {
    const s = JSON.parse(await fs.readFile(scanPath, "utf-8"));
    scanned = s.scanned; views = s.views; candidate = s.candidateCount || 0; ledgerRows = s.ledgerRows || 0;
  } catch {}

  if (mode === "--self-test") {
    let ok = false, rows = 0;
    try {
      const stat = await fs.stat(report);
      ok = stat.isFile() && report.endsWith(`-${runDate}.xlsx`);
      if (ok) rows = await countDataRows(report);
    } catch { /* report not present yet */ }
    // 0 条汇总结果（空簿）视为不可发；self-test 不实发，仅如实标注。
    if (ok && rows === 0) ok = false;
    console.log(JSON.stringify({ ok, workflowId, group, runDate, itemCount: 1, dataRows: rows, runtimeModelDecisions: 0 }));
    if (!ok) process.exitCode = 1;
    return;
  }

  // 报表未生成（0 条合格回复时 compile 不产出 xlsx）→ 按用户铁律「有回复才汇总发群」绝不外发。
  try {
    await fs.stat(report);
  } catch {
    console.log(JSON.stringify({ ok: false, reason: "zero-replies-no-send", skipped: false, scanned, views, candidate, ledgerRows, workflowId, runDate }));
    return;
  }

  // 硬闸（用户 2026-10-04 铁律）：汇总结果（xlsx 实际数据行）为 0 条时，绝不外发 Excel。
  // xlsx 读取失败（dataRows=-1）时回退到 last-scan.ledgerRows 判定，二者皆 0 则视为 0 条不发，
  // 绝不调用微信桥（bridge）发送，避免把空表发到群里。
  const dataRows = await countDataRows(report);
  if (dataRows === 0 || (dataRows === -1 && ledgerRows === 0)) {
    console.log(JSON.stringify({ ok: false, reason: "zero-replies-no-send:empty-workbook", skipped: false, scanned, views, candidate, ledgerRows: dataRows === -1 ? ledgerRows : dataRows, workflowId, runDate }));
    return;
  }

  const { stdout } = await run(python, args(), { timeout: 900_000, maxBuffer: 16 * 1024 * 1024 });
  console.log(stdout.trim());
}

main().catch((error) => {
  console.error(JSON.stringify({ ok: false, reason: String(error.message || error), stdout: error.stdout || "", stderr: error.stderr || "" }));
  process.exitCode = 1;
});
