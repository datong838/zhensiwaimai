// 负反馈列表申诉汇总 Excel 构建（双平台各自独立文件）
//
// 事实源：页面「全部」视图分页回读（行数必须 ==「全部」计数）。
// 本地 md 只补充页面没有的字段（申诉类型/核验结论），不虚构申诉内容。
//   • 美团（mode:status）：头部五维状态计数（全部/未申诉/申诉中/申诉成功/申诉失败）。
//   • 淘宝（mode:category）：头部分类维度计数（全部/食品安全负反馈率/服务负反馈率）。
// 两个平台各生成一个独立 .xlsx，文件名带平台标签，降低因结构差异带来的耦合。
import fs from 'node:fs/promises';
import path from 'node:path';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';
import {
  PLATFORMS, RECORDS, STATUS_ORDER, TAOBAO_CATEGORY_ORDER, businessDate, clean, recentRange,
} from './jinsha.mjs';
import { collectAll } from './all_feedback_collector.mjs';

const field = (text, label) => (text.match(new RegExp(`^- ${label}：([^\\n\\r]*)`, 'm')) || [])[1]?.trim() || '';

/** 读取当日已核验的本地 md 事实。 */
export async function localFacts(business) {
  const dir = path.join(RECORDS, business);
  const facts = new Map();
  let names = [];
  try { names = (await fs.readdir(dir)).filter(n => n.endsWith('.md')); }
  catch (error) { if (error.code === 'ENOENT') return facts; throw error; }
  for (const name of names) {
    const text = await fs.readFile(path.join(dir, name), 'utf8');
    const status = field(text, '记录状态');
    if (!['verified_submitted', 'blocked', 'unknown', 'submitted_once'].includes(status)) continue;
    facts.set(field(text, '记录键'), {
      status,
      dialogText: field(text, '弹窗申诉内容'),
      verification: field(text, '页面核验结果'),
      passRate: field(text, '预估通过率'),
    });
  }
  return facts;
}

const DETAIL_HEADERS = ['平台', '门店', '评价日期', '星级', '订单编号', '反馈渠道', '问题分类', '平台预申诉语句', '实际提交申诉内容', '预估通过率', '页面核验', '处理状态'];
const COL_WIDTHS = [14, 26, 12, 7, 22, 12, 18, 52, 52, 11, 30, 14];

export const previewLastRow = (headerRow, lastRow) => Math.min(lastRow, headerRow + 20);

async function buildOnePlatform(spec, snap, facts, { business, win, outputDir, expectedNames }) {
  const mode = spec.mode;
  const counts = snap.counts || {};
  const rows = [];
  for (const item of snap.rows) {
    const fact = facts.get(item.key) || {};
    rows.push([
      spec.label, item.store, new Date(`${item.date}T00:00:00+08:00`), item.score || '',
      item.orderNo, item.channel || '未读取', item.category || '未读取',
      item.preAppeal || '页面未提供',
      fact.status === 'verified_submitted' ? (fact.dialogText || '未读取') : '未核验提交',
      fact.passRate || (item.passRate ? `${item.passRate}%` : '未读取'),
      fact.verification || '页面未提供',
      fact.status || '页面未提供',
    ]);
  }

  // 「全部」列必须等于明细行数
  if (Number(counts.全部) !== rows.length) throw Error(`report-count-vs-rows-mismatch:${spec.key}:${counts.全部}:${rows.length}`);

  const dimLabels = mode === 'status' ? STATUS_ORDER : TAOBAO_CATEGORY_ORDER;
  const dimTitle = mode === 'status' ? '申诉状态维度' : '分类维度';
  const dimCols = dimLabels.length + 1;
  const dimEndCol = String.fromCharCode(64 + dimCols); // 标题列 + N 维标签

  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add(`${spec.label}负反馈申诉`);
  sheet.showGridLines = false;

  sheet.getRange('A2:L2').merge();
  sheet.getRange('A2').values = [[`${spec.label}负反馈列表申诉汇总`]];
  sheet.getRange('A2').format = { font: { name: 'Arial', size: 14, bold: true, color: '#1F2937' }, verticalAlignment: 'center' };

  const scope = mode === 'status'
    ? `业务日期：${business}；范围：近7日（${win[0]} 至 ${win[1]}）；申诉类型「全部」+ 状态「未申诉」为申诉源；明细取「全部」状态页全量 ${rows.length} 条`
    : `业务日期：${business}；范围：近7日（${win[0]} 至 ${win[1]}）；分类「全部」为申诉源；明细取「全部」分类视图全量 ${rows.length} 条`;
  sheet.getRange('A3:L3').merge();
  sheet.getRange('A3').values = [[scope]];
  sheet.getRange('A3').format = { font: { name: 'Arial', size: 10, italic: true, color: '#4B5563' } };

  const statRow = 5;
  sheet.getRange(`A${statRow}:${dimEndCol}${statRow}`).values = [[dimTitle, ...dimLabels]];
  sheet.getRange(`A${statRow}:${dimEndCol}${statRow}`).format = {
    fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center', verticalAlignment: 'center',
  };
  let r = statRow + 1;
  sheet.getRange(`A${r}:${dimEndCol}${r}`).values = [[spec.label, ...dimLabels.map(l => Number(counts[l] || 0))]];
  sheet.getRange(`A${statRow + 1}:${dimEndCol}${r}`).format = {
    font: { name: 'Arial', size: 10, color: '#1F2937' }, horizontalAlignment: 'center',
    borders: { preset: 'all', style: 'thin', color: '#D9E2F3' },
  };
  sheet.getRange(`A${statRow + 1}:A${r}`).format.horizontalAlignment = 'left';

  const head = r + 2;
  sheet.getRange(`A${head}:L${head}`).values = [DETAIL_HEADERS];
  const last = head + Math.max(0, rows.length);
  if (rows.length) sheet.getRange(`A${head + 1}:L${last}`).values = rows;
  sheet.getRange(`A${head}:L${head}`).format = {
    fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' },
    horizontalAlignment: 'center', verticalAlignment: 'center', wrapText: true,
  };
  sheet.getRange(`A${head}:L${last}`).format.borders = { preset: 'all', style: 'thin', color: '#D9E2F3' };
  if (rows.length) {
    sheet.getRange(`A${head + 1}:L${last}`).format = {
      font: { name: 'Arial', size: 10, color: '#1F2937' }, verticalAlignment: 'top', wrapText: true,
      borders: { preset: 'inside', style: 'thin', color: '#D9E2F3' },
    };
    sheet.getRange(`C${head + 1}:C${last}`).format.numberFormat = 'yyyy-mm-dd';
    sheet.getRange(`A${head + 1}:L${last}`).format.rowHeight = 52;
  }
  COL_WIDTHS.forEach((w, i) => { sheet.getRangeByIndexes(0, i, 1, 1).format.columnWidth = w; });
  sheet.getRange('A2:L2').format.rowHeight = 28;
  sheet.freezePanes.freezeRows(head);

  workbook.recalculate();
  const errorCheck = await workbook.inspect({
    kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!',
    options: { useRegex: true, maxResults: 50 }, summary: 'final formula error scan',
  });

  await fs.mkdir(outputDir, { recursive: true });
  const safe = spec.label.replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, '');
  const baseName = `负反馈申诉汇总_${safe}_${business}`;
  const outputPath = path.join(outputDir, `${baseName}.xlsx`);
  const previewPath = path.join(outputDir, `${baseName}.png`);

  // 允许本次运行另一平台的文件共存；只拒绝非本批次的遗留/外来 xlsx
  const others = (await fs.readdir(outputDir)).filter(n => n.endsWith('.xlsx') && !(expectedNames && expectedNames.has(n)));
  if (others.length) throw Error(`daily-output-has-other-workbooks:${others.join(',')}`);

  // 辅助预览只显示前20条；下方导出的Excel保留所有平台明细。
  const preview = await workbook.render({ sheetName: sheet.name, range: `A2:L${previewLastRow(head, last)}`, scale: 1.2, format: 'png' });
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(outputPath);

  return {
    platformKey: spec.key, label: spec.label, mode, outputPath, previewPath,
    counts, recordCount: rows.length, errorCheck: errorCheck.ndjson,
  };
}

export async function buildReports({ window, outputDir } = {}) {
  const business = businessDate();
  const win = window || recentRange();
  // 用户2026-10-24恢复双平台汇总；淘宝是否能提交与报表采集分开。
  const REPORT_PLATFORMS = PLATFORMS;
  const collected = await collectAll({ platforms: REPORT_PLATFORMS.map(p => p.key), window: win });
  const facts = await localFacts(business);

  // 已核验提交却不在页面快照：需区分「合法移除」与「采集异常」
  const snapshotKeys = new Set();
  for (const spec of REPORT_PLATFORMS) for (const item of collected.platforms[spec.key]?.rows || []) snapshotKeys.add(item.key);
  const missing = [...facts].filter(([key, f]) => f.status === 'verified_submitted' && !snapshotKeys.has(key)).map(([key]) => key);
  //  - 快照确有内容：平台已在申诉成功后把该评价从差评列表移除 = 合法终态 → 跳过不报错
  //  - 快照为空：多为采集失败/连接异常，不能据此判定已移除 → 保持 fail-closed 抛错，避免漏判导致重提交
  let snapshotTotalRows = 0;
  for (const spec of REPORT_PLATFORMS) snapshotTotalRows += (collected.platforms[spec.key]?.rows || []).length;
  const snapshotLooksAlive = snapshotTotalRows > 0;
  if (missing.length && !snapshotLooksAlive) throw Error(`platform-snapshot-missing-verified-submissions:${missing.length}`);
  if (missing.length && snapshotLooksAlive) console.warn(`[report_builder] ${missing.length} 条 verified_submitted 记录已不在平台快照中（申诉成功后被移除，视为合法终态，跳过）: ${missing.join(', ')}`);

  const safeNames = REPORT_PLATFORMS.map(s => `负反馈申诉汇总_${s.label.replace(/[^\u4e00-\u9fa5A-Za-z0-9]/g, '')}_${business}.xlsx`);
  const expectedNames = new Set(safeNames);
  const reports = [];
  for (const spec of REPORT_PLATFORMS) {
    const snap = collected.platforms[spec.key];
    if (!snap) throw Error(`platform-snapshot-missing:${spec.key}`);
    reports.push(await buildOnePlatform(spec, snap, facts, { business, win, outputDir, expectedNames }));
  }
  const manifest = {
    ok: true, businessDate: business, window: win, outputDir, localFacts: facts.size,
    reports: reports.map(r => ({
      platformKey: r.platformKey, label: r.label, mode: r.mode,
      outputPath: r.outputPath, previewPath: r.previewPath, recordCount: r.recordCount,
    })),
  };
  await fs.writeFile(path.join(outputDir, 'reports-manifest.json'), JSON.stringify(manifest, null, 1));
  return manifest;
}
