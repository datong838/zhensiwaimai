import { businessPath } from '../../../../runtime/business_storage.mjs';
import { pathToFileURL } from "node:url";
import { execFile } from "node:child_process";
import { promisify } from "node:util";
import fs from "node:fs/promises";
import path from "node:path";
import {preserveZeroSendSummary} from '../../../../runtime/summary_zero_payload.mjs';

const run = promisify(execFile);
const python = "/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python";
const bridge = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/workflow_bridge_windows.py";
// 2026-10-22 大同指定：员工群=FEIBING NEO AI数字员工，运营群=上海臻肆外卖运营-盯个盯-饭敢当。
// 申诉 Excel 结果表一律发运营群（原发员工群）。
const group = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰";
const SUMMARY_WORKFLOW = "taobao-flash-appeals-summary";
const SUMMARY_AUTH = "user-20261022-appeals-summary-card";
const summaryLedger = path.join(businessPath('taobao-appeals'), 'summary-attempts');
const cardScript = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/appeals_summary_card.py";
const shanghaiDay = (date = new Date()) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
const runDate = shanghaiDay();
const businessDateValue = new Date(`${runDate}T00:00:00+08:00`);
businessDateValue.setUTCDate(businessDateValue.getUTCDate() - 1);
const businessDate = shanghaiDay(businessDateValue);
const authorization = "automation-3-taobao-flash-appeals-daily-authorized";
const ledger = path.join(businessPath('taobao-appeals'), 'wechat-attempts');
const reportDir = path.join("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/outputs", `taobao-flash-sale-negative-review-appeals-${runDate.replaceAll("-", "")}`);
const outputDir = path.join(reportDir, "wechat-delivery");
const report = path.join(reportDir, `淘宝闪购差评申诉汇总-${businessDate}.xlsx`);
const summaryCard = path.join(reportDir, `淘宝闪购差评申诉台账-${businessDate}.png`);

function args(mode, correction = false) {
  return [
    bridge,
    "--workflow-id", "taobao-flash-appeals",
    "--group", group,
    "--payload-type", "file",
    "--authorization", correction ? `user-${runDate.replaceAll("-", "")}-taobao-flash-appeals-correction-v1` : authorization,
    "--ledger", ledger,
    "--marker-name", `taobao-flash-appeals-${businessDate}${correction ? "-correction-v1" : ""}.json`,
    "--output-dir", correction ? path.join(outputDir, "correction-v1") : outputDir,
    "--item", report,
    // 2026-10-03：发 xlsx 需「上传 + 服务端 GUI 发送 + 回读验证」，原 180s 外层闸门
    // 会在服务端仍处理时提前判定 deadline-expired，造成「已送达但回执 unknown」。
    // 放宽到 900s（仍小于 manifest 的 timeout_seconds=1800）。
    "--deadline-unix", String(Math.floor(Date.now() / 1000) + 900),
    ...(correction ? ["--correction-v1"] : []),
    mode
  ];
}

async function hasDataRows(file) {
  // 零条硬闸判据：明细区 A8 起至少一行、A 列首个数据格非空（表头在 A7，数据从 A8）。
  // 用 artifact-tool 读回已保存的 xlsx（与生成器同一套 API，不引入新依赖）。
  const { Workbook, SpreadsheetFile } = await import("@oai/artifact-tool");
  const { readFileSync } = await import("node:fs");
  const workbook = await SpreadsheetFile.importXlsx(readFileSync(file));
  const sheet = workbook.worksheets.getItem("申诉汇总");
  const used = sheet.getUsedRange(true);
  const rowCount = used ? used.rowCount : 0;
  if (rowCount <= 7) return false; // 7 行内只有标题/说明/统计/表头，无数据行
  const firstData = sheet.getCell(7, 0).values?.[0]?.[0];
  return firstData !== null && firstData !== undefined && String(firstData).trim() !== "";
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
  let reusedFrozen=false;
  // 2026-10-22 大同要求：Excel 结果表发完后，补发「汇总台账」截图到同一运营群。
  // 独立 marker（summary-attempts）+ 独立 workflow 通道 ⇒ 与 xlsx 投递解耦，可单独补发/幂等跳过。
  try {
    const marker = JSON.parse(await fs.readFile(
      path.join(summaryLedger, `taobao-flash-appeals-summary-${businessDate}.json`), "utf8"));
    if (summaryDisposition(marker) === "reconcile") return {ok:false, verified:false, state:marker.state, reason:"summary-prior-attempt-readonly-reconciliation-required"};
    if (marker && marker.ok === true && marker.verified === true && marker.state === "verified") {
      return { ok: true, verified: true, status: "already_verified", skipped: true, path: summaryCard };
    }
    if(marker.state==='blocked'&&marker.sendAttempts===0){
      try{await preserveZeroSendSummary({marker,markerPath:path.join(summaryLedger,`taobao-flash-appeals-summary-${businessDate}.json`),
        summaryCard,ledger:summaryLedger,workflow:SUMMARY_WORKFLOW,group,
        queueRoot:path.join(root,'skills/wechat-messaging/.runtime/ui-post-queue')});}
      catch(error){throw Error('summary-zero-recovery-proof-failed:'+error.message);}
      reusedFrozen=true;
    }
  } catch (error) { if (error.code !== "ENOENT") throw error; }
  if(!reusedFrozen)await run(python, [cardScript, "--flow", "taobao", "--business-date", businessDate,
    "--run-key", runDate.replaceAll("-", ""), "--output", summaryCard],
    { timeout: 120_000, maxBuffer: 8 * 1024 * 1024 });
  const { stdout } = await run(python, [
    bridge, "--workflow-id", SUMMARY_WORKFLOW, "--group", group, "--payload-type", "image",
    "--authorization", SUMMARY_AUTH, "--ledger", summaryLedger,
    "--marker-name", `taobao-flash-appeals-summary-${businessDate}.json`,
    "--output-dir", path.join(outputDir, "summary-card"),
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
    const reportStat = await fs.stat(report);
    const valid = reportStat.isFile() && report.endsWith(`-${businessDate}.xlsx`);
    console.log(JSON.stringify({ ok: valid, workflowId: "taobao-flash-appeals", group, businessDate, itemCount: 1, runtimeModelDecisions: 0 }));
    if (!valid) process.exitCode = 1;
    return;
  }
  if (mode !== "--execute") throw new Error("usage: deliver_batch.mjs --execute|--self-test");
  // 2026-09-30 大同授权「verified 后幂等跳过」：业务日期 marker 已 verified 时
  // 直接回 already_verified 终态（SKILL.md 认可的已发送凭据），不再调桥重发——
  // 内容若已变化，桥会以 legacy-marker-binding-mismatch 拒发并每 2 小时告警。
  // 修正通道 --correction-v1 有独立 marker，不受此守卫限制。
  if (!correction) {
    try {
      const marker = JSON.parse(await fs.readFile(path.join(ledger, `taobao-flash-appeals-${businessDate}.json`), "utf8"));
      if (marker && marker.ok === true && marker.verified === true && marker.state === "verified") {
        await finishDelivery({ ok: true, verified: true, status: "already_verified", skipped: true,
          businessDate, reason: "business-date-marker-already-verified", runtimeModelDecisions: 0 }, false);
        return;
      }
    } catch {}
  }
  // 2026-10-12 零条硬闸（大同 10-04 永久铁律「0 条/空表绝不外发」）：读回 xlsx 实际
  // 数据行数，0 行一律 exit 1 拒发——排程修复（earliest 0→9）挡住「数据未聚合」的
  // 主因，本闸兜住任何残余路径（数据晚到/异常采集/未来排程回退）。事故：00:11 凌晨档
  // 把「明细 0 条」空表发进群。修正通道 --correction-v1 同样受闸（修正对象本就是
  // 已 verified 的非空载荷）。放在 marker 守卫之后：已 verified 的幂等跳过不需要
  // 读文件，避免多余 IO 让干净跳过路径报错。
  if (!await hasDataRows(report)) {
    console.error(JSON.stringify({ ok: false, reason: "zero-replies-no-send:report-has-no-data-rows",
      businessDate, report, runtimeModelDecisions: 0 }));
    process.exit(1);
  }
  const { stdout } = await run(python, args("--execute", correction), { timeout: 240_000, maxBuffer: 16 * 1024 * 1024 });
  const receipt = JSON.parse(stdout.trim());
  await finishDelivery(receipt, correction);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) main().catch((error) => {
  console.error(JSON.stringify({ ok: false, reason: String(error.message || error), stdout: error.stdout || "", stderr: error.stderr || "" }));
  process.exitCode = 1;
});
