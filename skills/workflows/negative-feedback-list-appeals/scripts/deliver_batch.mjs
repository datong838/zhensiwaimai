// 负反馈列表申诉汇总 · 固定投递器（双平台非空文件）
//
// 固定三要素：workflow-id / 完整群名 / 单一 marker。复用统一微信收发 Skill 的
// workflow_bridge_windows.py 与桌面文件发送器，不新增手工选择器或备用路线。
// 2026-10-24 用户恢复双平台汇总；平台非空明细与今日新增申诉数量分开。
// 原桥与原事件不变；两平台实际Excel明细均须与当天manifest一致。
import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import fs from 'node:fs/promises';
import path from 'node:path';
import { FLOW_ID, GROUP, RECORDS, ROOT, businessDate, shanghaiDay, recentRange, PLATFORMS } from './jinsha.mjs';

const run = promisify(execFile);
const python = '/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python';
const bridge = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts/workflow_bridge_windows.py';

const runDate = shanghaiDay();
const business = businessDate();
const reportDir = path.join(ROOT, 'outputs', `${FLOW_ID}-${runDate.replaceAll('-', '')}`);
const ledger = `/Users/ddt/work/projects/ai_agent/state/${FLOW_ID}/wechat-attempts`;
// workflow-id/授权串必须与桥 REGISTRY 注册值逐字一致（2026-10-06 受控再封印登记）：
// 桥 key = negative-feedback-appeals；台账路径独立（state/negative-feedback-list-appeals）。
const BRIDGE_WORKFLOW_ID = 'negative-feedback-appeals';
const authorization = `user-20261006-negative-feedback-list-appeals`;

/** 读取 buildReports 写出的 manifest，得到待发送文件清单。 */
export async function pendingItems() {
  const manifest = JSON.parse(await fs.readFile(path.join(reportDir, 'reports-manifest.json'), 'utf8'));
  validateManifest(manifest);
  const { SpreadsheetFile } = await import('@oai/artifact-tool');
  for (const report of manifest.reports) {
    const workbook = await SpreadsheetFile.importXlsx(await fs.readFile(report.outputPath));
    const sheet = workbook.worksheets.getItem(`${report.label}负反馈申诉`);
    validateReportRows(sheet.getUsedRange(true).values, report);
  }
  return manifest.reports.map(r => r.outputPath);
}

export function validateReportRows(rows, report) {
  const header = rows.findIndex(row => row[0] === '平台' && row[1] === '门店');
  const details = rows.slice(header + 1).filter(row => row[0]);
  const win = recentRange(business);
  const scope = rows.some(row => row.some(cell => typeof cell === 'string'
    && cell.includes(`业务日期：${business}`) && cell.includes(win[0]) && cell.includes(win[1])));
  if (!scope || header < 0 || details.length !== report.recordCount
      || details.some(row => row[0] !== report.label || !row[1])) throw Error('report-file-row-mismatch');
  return true;
}

export function validateManifest(manifest) {
  if (manifest.ok !== true || manifest.businessDate !== business
      || JSON.stringify(manifest.window) !== JSON.stringify(recentRange(business))
      || manifest.reports?.length !== PLATFORMS.length) throw Error('report-manifest-scope-mismatch');
  for (const spec of PLATFORMS) {
    const matches = manifest.reports.filter(r => r.platformKey === spec.key);
    const expected = path.join(reportDir, `负反馈申诉汇总_${spec.label}_${business}.xlsx`);
    if (matches.length !== 1 || matches[0].label !== spec.label || matches[0].outputPath !== expected
        || !Number.isInteger(matches[0].recordCount) || matches[0].recordCount <= 0) {
      throw Error('report-manifest-nonempty-platform-required');
    }
  }
  return true;
}

export function buildArgs({ items = [], markerSuffix = '', auth = authorization } = {}) {
  return [
    bridge, '--workflow-id', BRIDGE_WORKFLOW_ID, '--group', GROUP, '--payload-type', 'file',
    '--authorization', auth,
    '--ledger', ledger,
    '--marker-name', `${FLOW_ID}-${business}${markerSuffix}.json`,
    '--output-dir', path.join(reportDir, 'wechat-delivery', ...(markerSuffix ? [markerSuffix] : [])),
    ...items.flatMap(item => ['--item', item]),
    '--deadline-unix', String(Math.floor(Date.now() / 1000) + 900),
    ...(items.length ? ['--execute'] : []),
  ];
}

export async function hasAnyRecords(date = business) {
  try {
    const files = await fs.readdir(path.join(RECORDS, date));
    return files.some(f => f.endsWith('.md'));
  } catch { return false; }
}

export async function main(argv = process.argv.slice(2)) {
  const mode = argv[0];
  if (mode === '--self-test') {
    const items = await pendingItems();
    let allOk = items.length > 0;
    for (const p of items) {
      try {
        const s = await fs.stat(p);
        allOk = allOk && s.isFile() && s.size > 0 && p.endsWith('.xlsx')
          && path.basename(p).startsWith('负反馈申诉汇总_');
      } catch { allOk = false; }
    }
    console.log(JSON.stringify({ ok: allOk, workflowId: FLOW_ID, group: GROUP, businessDate: business, itemCount: items.length, runtimeModelDecisions: 0 }));
    if (!allOk) process.exitCode = 1;
    return;
  }
  if (mode !== '--execute') throw Error('usage: deliver_batch.mjs --execute|--self-test');

  // 用户2026-10-24要求双平台汇总：无新增申诉也须核验平台非空明细。
  const items = await pendingItems();
  if (!items.length) {
    console.log(JSON.stringify({
      ok: false, reason: 'no-report-files-to-deliver', workflowId: FLOW_ID, businessDate: business, runtimeModelDecisions: 0,
    }));
    process.exitCode = 1;
    return;
  }
  const { stdout } = await run(python, buildArgs({ items }), { timeout: 960_000, maxBuffer: 16 * 1024 * 1024 });
  console.log(stdout.trim());
}

if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(error => {
    console.error(JSON.stringify({ ok: false, reason: String(error.message || error), stdout: error.stdout || '', stderr: error.stderr || '' }));
    process.exitCode = 1;
  });
}
