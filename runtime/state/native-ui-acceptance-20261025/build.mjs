import fs from 'node:fs/promises';
import { Workbook, SpreadsheetFile } from '@oai/artifact-tool';
const root = new URL('.', import.meta.url).pathname;
const id = 'NATIVE-20261025-A04';
const workbook = Workbook.create();
const sheet = workbook.worksheets.add('合成测试');
sheet.getRange('A1:B5').values = [
 ['原生UI实操验收', id],
 ['载荷', '合成测试，无客户数据'],
 ['文字', '完整单条'],
 ['Excel', '文件附件'],
 ['图片', '直接展示图片']
];
sheet.getRange('A1:B5').format.font = {name:'Arial',size:14};
sheet.getRange('A1:B5').format.columnWidth = 33;
sheet.getRange('A1:B5').format.rowHeight = 30;
sheet.getRange('A1:B1').format.fill = '#E0F2FE';
workbook.recalculate();
console.log((await workbook.inspect({kind:'table',range:'合成测试!A1:B5',include:'values',tableMaxRows:5,tableMaxCols:2})).ndjson);
await (await SpreadsheetFile.exportXlsx(workbook)).save(root + id + '.xlsx');
const image = await workbook.render({sheetName:'合成测试',range:'A1:B5',scale:1.5});
await fs.writeFile(root + id + '.png', new Uint8Array(await image.arrayBuffer()));
