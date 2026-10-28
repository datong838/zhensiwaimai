// 本地化副本 · 供 meituan-waimai-negative-review-appeals 独立工作流使用
// 2026-10-05 大同要求：工作流独立、不跨 skill 耦合。源 = taobao-flash-sale-negative-review-appeals/scripts/full_appeal_report_builder.mjs
// 仅 import 改为本地 ./all_appeals_collector.mjs（同为本技能本地化副本）。其余逻辑与源一致。
import fs from 'node:fs/promises';
import path from 'node:path';
import { SpreadsheetFile, Workbook } from '@oai/artifact-tool';
import { collectAllAppeals } from './all_appeals_collector.mjs';

const statuses = ['全部', '申诉成功', '申诉失败', '申诉中', '未申诉'];
const field = (text, label) => (text.match(new RegExp(`^- ${label}：([^\\n\\r]*)`, 'm')) || [])[1]?.trim() || '';

async function localFacts(recordDir) {
  try {
    const facts = new Map();
    for (const name of (await fs.readdir(recordDir)).filter(name => name.endsWith('.md'))) {
      const text = await fs.readFile(path.join(recordDir, name), 'utf8');
      if (!['verified_submitted', 'blocked', 'unknown'].includes(field(text, '记录状态'))) continue;
      facts.set(field(text, '记录键'), {
        status: field(text, '记录状态'),
        suggestion: field(text, '平台建议回复'),
        appealType: field(text, '申诉类型'),
        verification: field(text, '页面核验结果'),
      });
    }
    return facts;
  } catch (error) {
    if (error.code === 'ENOENT') return new Map();
    throw error;
  }
}

export async function buildFullAppealReport(config, { collect = collectAllAppeals } = {}) {
  const { channelLabel, platformValue, contextLabel, businessDate, recordDir, outputDir, outputPath, previewPath } = config;
  const snapshot = await collect({ businessDate, platformValue, channelLabel, contextLabel });
  const facts = await localFacts(recordDir);
  const snapshotKeys = new Set(snapshot.rows.map(item => item.key));
  const missingVerifiedKeys = [...facts].filter(([key, fact]) => fact.status === 'verified_submitted' && !snapshotKeys.has(key)).map(([key]) => key);
  // 区分「合法移除」与「采集异常」：
  //  - 快照确有内容(rows>0)：平台已在申诉成功后把该评价从差评列表移除 = 合法终态 → 跳过不报错
  //  - 快照为空(rows=0)：多为采集失败/平台连接异常，不能据此判定已移除 → 保持 fail-closed 抛错，避免漏判导致 step1 重提交
  const snapshotLooksAlive = snapshot.rows.length > 0;
  if (missingVerifiedKeys.length && !snapshotLooksAlive) throw Error(`platform-snapshot-missing-verified-submissions:${missingVerifiedKeys.length}`);
  if (missingVerifiedKeys.length && snapshotLooksAlive) console.warn(`[appeal_report_builder] ${missingVerifiedKeys.length} 条 verified_submitted 记录已不在平台快照中（申诉成功后被平台移除，视为合法终态，跳过）: ${missingVerifiedKeys.join(', ')}`);
  const rows = snapshot.rows.map(item => {
    const fact = facts.get(item.key) || {};
    return [item.key, item.store, new Date(`${item.date}T00:00:00+08:00`), item.score, item.comment, item.appealMethod || '页面未提供', item.appealTime || '未读取', item.auto || '页面未提供', item.appealContent || fact.suggestion || '未读取', fact.appealType || '未读取', fact.verification || '页面未提供'];
  });
  if (rows.length !== snapshot.total) throw Error('full-appeal-report-row-count-mismatch');

  const workbook = Workbook.create();
  const sheet = workbook.worksheets.add('申诉汇总');
  sheet.showGridLines = false;
  sheet.getRange('A2:K2').merge();
  sheet.getRange('A2').values = [[`${channelLabel}差评申诉汇总`]];
  sheet.getRange('A2').format = { font: { name: 'Arial', size: 14, bold: true, color: '#1F2937' }, verticalAlignment: 'center' };
  sheet.getRange('A3:K3').merge();
  sheet.getRange('A3').values = [[`业务日期：${businessDate}；范围：${channelLabel}、全部状态；明细 ${snapshot.total} 条。注：「未申诉」为平台当前状态；自动申诉开关以明细「自动申诉状态」列为准，不代表已提交`]];
  sheet.getRange('A3').format = { font: { name: 'Arial', size: 10, italic: true, color: '#4B5563' } };
  sheet.getRange('A5:J5').values = [[statuses[0], Number(snapshot.counts.全部 || 0), statuses[1], Number(snapshot.counts.申诉成功 || 0), statuses[2], Number(snapshot.counts.申诉失败 || 0), statuses[3], Number(snapshot.counts.申诉中 || 0), statuses[4], Number(snapshot.counts.未申诉 || 0)]];
  sheet.getRange('A5:J5').format = { font: { name: 'Arial', size: 10, bold: true }, fill: '#E8F1FB', horizontalAlignment: 'center' };
  sheet.getRange('A5:J5').format.borders = { preset: 'all', style: 'thin', color: '#D9E2F3' };
  sheet.getRange('A7:K7').values = [['记录键', '门店', '评价日期', '星级', '评价最小摘录', '申诉方式', '申诉时间', '自动申诉状态', '平台智能申诉内容', '申诉类型', '页面核验']];
  const last = Math.max(7, rows.length + 7);
  if (rows.length) sheet.getRange(`A8:K${last}`).values = rows;
  sheet.getRange('A7:K7').format = { fill: '#1F4E78', font: { name: 'Arial', size: 10, bold: true, color: '#FFFFFF' }, horizontalAlignment: 'center', verticalAlignment: 'center', wrapText: true };
  sheet.getRange(`A7:K${last}`).format.borders = { preset: 'all', style: 'thin', color: '#D9E2F3' };
  if (rows.length) {
    sheet.getRange(`A8:K${last}`).format = { font: { name: 'Arial', size: 10, color: '#1F2937' }, verticalAlignment: 'top', wrapText: true, borders: { preset: 'inside', style: 'thin', color: '#D9E2F3' } };
    sheet.getRange(`C8:C${last}`).format.numberFormat = 'yyyy-mm-dd';
    sheet.getRange(`D8:D${last}`).format.numberFormat = '0';
    sheet.getRange(`A8:K${last}`).format.rowHeight = 52;
  }
  [16, 28, 14, 8, 48, 15, 20, 16, 56, 20, 34].forEach((width, index) => { sheet.getRangeByIndexes(0, index, 1, 1).format.columnWidth = width; });
  sheet.getRange('A2:J2').format.rowHeight = 28;
  sheet.freezePanes.freezeRows(7);
  if (rows.length) sheet.tables.add(`A7:K${last}`, true, `${platformValue === '1' ? 'Meituan' : 'Taobao'}AllAppeals`);
  workbook.recalculate();
  const tableCheck = await workbook.inspect({ kind: 'table', range: `申诉汇总!A2:K${last}`, include: 'values,formulas', tableMaxRows: Math.min(last, 15), tableMaxCols: 11 });
  const errorCheck = await workbook.inspect({ kind: 'match', searchTerm: '#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A|#NUM!|#NULL!|#SPILL!|#CALC!', options: { useRegex: true, maxResults: 50 }, summary: 'final formula error scan' });
  await fs.mkdir(outputDir, { recursive: true });
  const others = (await fs.readdir(outputDir)).filter(name => name.endsWith('.xlsx') && name !== path.basename(outputPath));
  if (others.length) throw Error(`daily-output-has-other-workbooks:${others.join(',')}`);
  const preview = await workbook.render({ sheetName: '申诉汇总', range: `A2:K${last}`, scale: 1.2, format: 'png' });
  await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));
  const xlsx = await SpreadsheetFile.exportXlsx(workbook);
  await xlsx.save(outputPath);
  return { ok: true, businessDate, channelLabel, outputPath, previewPath, counts: snapshot.counts, recordCount: rows.length, tableCheck: tableCheck.ndjson, errorCheck: errorCheck.ndjson, runtimeModelDecisions: 0 };
}
