import { pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs/promises";
import path from "node:path";

const run = promisify(execFile);
const python = "/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python";
const bridge = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/workflow_bridge_windows.py";
// 2026-10-22 大同指定：员工群=FEIBING NEO AI数字员工，运营群=上海臻肆外卖运营-盯个盯-饭敢当。
// 美团外卖差评申诉 Excel 结果表一律发运营群（原发员工群）。
const group = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰";
const SUMMARY_WORKFLOW = "meituan-waimai-appeals-summary";
const SUMMARY_AUTH = "user-20261022-appeals-summary-card";
const summaryLedger = "/Users/ddt/work/projects/ai_agent/state/meituan-waimai-negative-review-appeals/summary-attempts";
const cardScript = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/appeals_summary_card.py";
const authorization = "user-20260923-meituan-waimai-appeals-fixed-delivery";
const shanghaiDay = (date = new Date()) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
const runDate = shanghaiDay();
const businessDateValue = new Date(`${runDate}T00:00:00+08:00`);
businessDateValue.setUTCDate(businessDateValue.getUTCDate() - 1);
const businessDate = shanghaiDay(businessDateValue);
// 2026-10-06 跨树整改（大同授权）：旧树 zhensi_waimai → 线上树 zhensi_waimai_back。
// ledger 仍保留 ai_agent/state/<flow>/wechat-attempts（与 taobao-flash 同构的共享账本区，刻意不动）。
const root = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back";
const reportDir = path.join(root, "outputs", `meituan-waimai-negative-review-appeals-${runDate.replaceAll("-", "")}`);
const report = path.join(reportDir, `美团外卖差评申诉汇总-${businessDate}.xlsx`);
const summaryCard = path.join(reportDir, `美团外卖差评申诉台账-${businessDate}.png`);
const ledger = "/Users/ddt/work/projects/ai_agent/state/meituan-waimai-negative-review-appeals/wechat-attempts";

function args(correction = false) {
  return [bridge, "--workflow-id", "meituan-waimai-appeals", "--group", group, "--payload-type", "file",
    "--authorization", correction ? `user-${runDate.replaceAll("-", "")}-meituan-waimai-appeals-correction-v1` : authorization,
    "--ledger", ledger, "--marker-name", `meituan-waimai-appeals-${businessDate}${correction ? "-correction-v1" : ""}.json`,
    "--output-dir", path.join(reportDir, "wechat-delivery", ...(correction ? ["correction-v1"] : [])), "--item", report,
    "--deadline-unix", String(Math.floor(Date.now() / 1000) + 180),
    ...(correction ? ["--correction-v1"] : []), "--execute"];
}

export function summaryDisposition(marker) {
  if (!marker) return 'pending';
  if (marker.ok === true && marker.verified === true && marker.state === 'verified') return 'verified';
  if (['unknown', 'attempted'].includes(marker.state) || marker.sendAttempts !== 0) return 'reconcile';
  return marker.state === 'blocked' ? 'pending' : 'reconcile';
}
export function completeDelivery(receipt, card, correction = false) {
  const complete = receipt?.ok === true && receipt?.verified === true
    && (correction || (card?.ok === true && card?.verified === true));
  return { ...receipt, ok: complete, verified: complete, excelReceipt: receipt,
    summaryCard: card, ...(!complete ? {reason: 'delivery-incomplete-reconcile-required'} : {}) };
}
async function finishDelivery(receipt, correction) {
  let card = null;
  if (!correction && receipt?.ok === true && receipt?.verified === true) {
    try { card = await sendSummaryCard(); }
    catch (error) { card = {ok:false, reason:String(error.message || error)}; }
  }
  const result = completeDelivery(receipt, card, correction);
  console.log(JSON.stringify(result));
  if (!result.ok) process.exitCode = 1;
}

async function sendSummaryCard() {
  // 2026-10-22 大同要求：Excel 结果表发完后，补发「汇总台账」截图到同一运营群。
  try {
    const marker = JSON.parse(await fs.readFile(
      path.join(summaryLedger, `meituan-waimai-appeals-summary-${businessDate}.json`), "utf8"));
    if (summaryDisposition(marker) === "reconcile") return {ok:false, verified:false, state:marker.state, reason:"summary-prior-attempt-readonly-reconciliation-required"};
    if (marker && marker.ok === true && marker.verified === true && marker.state === "verified") {
      return { ok: true, verified: true, status: "already_verified", skipped: true, path: summaryCard };
    }
  } catch (error) { if (error.code !== "ENOENT") throw error; }
  await run(python, [cardScript, "--flow", "meituan", "--business-date", businessDate,
    "--run-key", runDate.replaceAll("-", ""), "--output", summaryCard],
    { timeout: 120_000, maxBuffer: 8 * 1024 * 1024 });
  const { stdout } = await run(python, [
    bridge, "--workflow-id", SUMMARY_WORKFLOW, "--group", group, "--payload-type", "image",
    "--authorization", SUMMARY_AUTH, "--ledger", summaryLedger,
    "--marker-name", `meituan-waimai-appeals-summary-${businessDate}.json`,
    "--output-dir", path.join(reportDir, "wechat-delivery", "summary-card"),
    "--item", summaryCard,
    "--deadline-unix", String(Math.floor(Date.now() / 1000) + 900),
    "--execute"
  ], { timeout: 240_000, maxBuffer: 16 * 1024 * 1024 });
  return JSON.parse(stdout.trim());
}

async function main() {
  const supplied = process.argv.slice(2);
  const correction = supplied.includes("--correction-v1");
  const mode = supplied.find((value) => value !== "--correction-v1");
  if (supplied.some((value) => !["--execute", "--self-test", "--correction-v1"].includes(value))
      || new Set(supplied).size !== supplied.length
      || (correction && mode !== "--execute")) throw new Error("invalid correction or mode flags");
  if (mode === "--self-test") {
    const stat = await fs.stat(report);
    const ok = stat.isFile() && report.endsWith(`-${businessDate}.xlsx`);
    console.log(JSON.stringify({ ok, workflowId: "meituan-waimai-appeals", group, businessDate, itemCount: 1, runtimeModelDecisions: 0 }));
    if (!ok) process.exitCode = 1;
    return;
  }
  if (mode !== "--execute") throw new Error("usage: deliver_batch.mjs --execute|--self-test");
  // 2026-10-22 大同指令：「这 2 个任务流的汇总明细和台账截图都发运营群」——每天一份汇总表。
  // 原判据（大同 2026-10-05「无新待申诉内容则跳过」）看的是 records/<业务日期>/*.md，
  // 业务日期当天没有新发起申诉时该目录为空 ⇒ 整批跳过（10-22 实测：汇总表 61 条却被
  // no-candidate-records 挡下，运营群当天没收到表）。改用与淘宝闪购流同构的判据：
  // 读回 xlsx 实际数据行数，>0 才发、0 行绝不外发（守住大同「0 条/空表绝不外发」铁律）。
  // 美团汇总表固定布局：第 7 行表头（记录键/门店/…），第 8 行起明细。
  async function hasDataRows(file) {
    try {
      const stat = await fs.stat(file);
      if (!stat.isFile()) return false;
    } catch { return false; }
    const code = [
      "import sys, openpyxl",
      "wb = openpyxl.load_workbook(sys.argv[1], read_only=True)",
      "ws = wb[wb.sheetnames[0]]",
      "n = 0",
      "for row in ws.iter_rows(min_row=8, max_col=1, values_only=True):",
      "    if row and row[0] is not None and str(row[0]).strip():",
      "        n += 1",
      "print(n)",
    ].join("\n");
    const { stdout } = await run(python, ["-c", code, file], { timeout: 120_000 });
    return Number.parseInt(stdout.trim(), 10) > 0;
  }
  if (!await hasDataRows(report)) {
    console.log(JSON.stringify({ ok: true, skipped: true, reason: `report-has-no-data-rows-${businessDate}`, workflowId: "meituan-waimai-appeals", group, businessDate, itemCount: 0, runtimeModelDecisions: 0 }));
    return;
  }
  // 2026-10-22 对齐淘宝闪购流：业务日期 marker 已 verified 时直接回终态，不重复外发。
  // 淘宝流的同一守卫注释（skills/workflows/taobao-flash-sale-negative-review-appeals/
  // scripts/deliver_batch.mjs 第 2026-09-30 条）说明了原因：内容若已变化，桥会以
  // legacy-marker-binding-mismatch 拒发。修正通道 --correction-v1 有独立 marker，不受限。
  if (!correction) {
    try {
      const marker = JSON.parse(await fs.readFile(path.join(ledger, `meituan-waimai-appeals-${businessDate}.json`), "utf8"));
      if (marker && marker.ok === true && marker.verified === true && marker.state === "verified") {
        await finishDelivery({ ok: true, verified: true, status: "already_verified", skipped: true,
          businessDate, reason: "business-date-marker-already-verified", runtimeModelDecisions: 0 }, false);
        return;
      }
    } catch {}
  }
  const { stdout } = await run(python, args(correction), { timeout: 240_000, maxBuffer: 16 * 1024 * 1024 });
  const receipt = JSON.parse(stdout.trim());
  await finishDelivery(receipt, correction);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch((error) => {
  console.error(JSON.stringify({ ok: false, reason: String(error.message || error), stdout: error.stdout || "", stderr: error.stderr || "" }));
  process.exitCode = 1;
});
