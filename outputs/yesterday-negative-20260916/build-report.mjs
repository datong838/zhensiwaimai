import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';

const root = new URL('.', import.meta.url).pathname;
const rows = JSON.parse(await fs.readFile(root + 'final-data.json', 'utf8'));
const headers = ['店铺名称', '总分', '评价日期', '店铺类型', '差评内容', '点踩商品', '评论订单详情'];
const workbook = Workbook.create();
const sheet = workbook.worksheets.add('差评分析数据');
const endRow = rows.length + 1;

function safe(value) {
  if (typeof value === 'string' && value.startsWith('=')) return `'${value}`;
  return value ?? '';
}

const values = [headers, ...rows.map((row) => [
  safe(row['店铺名称']),
  Number(row['总分']),
  new Date(`${String(row['评价日期']).slice(0, 10)}T00:00:00Z`),
  safe(row['店铺类型']),
  safe(row['差评内容']),
  safe(row['点踩商品']),
  safe(row['评论订单详情']),
])];

sheet.showGridLines = false;
sheet.getRange(`A1:G${endRow}`).values = values;
sheet.getRange('A1:G1').format = {
  fill: '#29455F',
  font: { name: 'Arial', size: 11, bold: true, color: '#FFFFFF' },
  horizontalAlignment: 'center', verticalAlignment: 'center', wrapText: true, rowHeight: 30,
};
sheet.getRange(`A2:G${endRow}`).format = {
  font: { name: 'Arial', size: 10, color: '#22344A' }, verticalAlignment: 'top', wrapText: true,
};
sheet.getRange(`B2:B${endRow}`).format.horizontalAlignment = 'center';
sheet.getRange(`C2:D${endRow}`).format.horizontalAlignment = 'center';
sheet.getRange(`C2:C${endRow}`).setNumberFormat('yyyy-mm-dd');

const widths = [280, 60, 105, 105, 520, 240, 390];
for (let index = 0; index < widths.length; index += 1) {
  const column = String.fromCharCode(65 + index);
  sheet.getRange(`${column}1:${column}${endRow}`).format.columnWidthPx = widths[index];
}

function displayWidth(value) {
  if (value instanceof Date) return 10;
  return [...String(value ?? '')].reduce((total, character) => total + (character.charCodeAt(0) > 255 ? 1.9 : 1), 0);
}

for (let rowIndex = 2; rowIndex <= endRow; rowIndex += 1) {
  const data = values[rowIndex - 1];
  const lineCounts = data.map((value, columnIndex) => {
    const availableCharacters = Math.max(4, (widths[columnIndex] - 16) / 7);
    const text = value instanceof Date ? value.toISOString().slice(0, 10) : String(value ?? '');
    return text.split('\n').reduce((total, line) => total + Math.max(1, Math.ceil(displayWidth(line) / availableCharacters)), 0);
  });
  sheet.getRange(`A${rowIndex}:G${rowIndex}`).format.rowHeightPx = Math.min(180, Math.max(44, Math.max(...lineCounts) * 18 + 10));
}

sheet.tables.add(`A1:G${endRow}`, true, 'NegativeReviews').style = 'TableStyleMedium2';
sheet.getRange('A1:G1').format.fill = '#29455F';
sheet.getRange('A1:G1').format.font = { name: 'Arial', size: 11, bold: true, color: '#FFFFFF' };
sheet.freezePanes.freezeRows(1);

const inspection = await workbook.inspect({ kind: 'region', sheetId: sheet.id ?? sheet.name, range: 'A1:G8', maxChars: 4000, tableMaxRows: 8, tableMaxCols: 7 });
console.log(inspection.ndjson);
const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(root + '差评分析数据_2026-09-16_2026-09-16.xlsx');
const preview = await workbook.render({ sheetName: '差评分析数据', range: 'A1:G10', scale: 1, format: 'png' });
await fs.writeFile(root + '报表预览.png', new Uint8Array(await preview.arrayBuffer()));
console.log(`saved rows=${rows.length}`);
