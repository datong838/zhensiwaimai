// Read-only positive/negative checks against the two receipt-bound saved workbooks.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { FileBlob, SpreadsheetFile } from '@oai/artifact-tool';
import { verifySavedWorkbook, verifyBodyStyles } from './build_reports.mjs';
const receipt = JSON.parse(await fs.readFile(process.argv[2] || '/tmp/zhensi_jinsha_reports/build_receipt.json', 'utf8'));
assert.equal(receipt.ok, true);
for (const [platform, col, bars] of [['meituan', 'AK', 7], ['taobao', 'AD', 6]]) {
  const item = receipt.files[platform];
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(item.file));
  const expected = wb.worksheets.getItemAt(0).getRange(`A2:${col}${item.rows + 2}`).values;
  const result = await verifySavedWorkbook(item.file, expected, col, bars);
  await assert.rejects(verifySavedWorkbook(item.file, expected, col, bars + 1), /saved-conditional-format-missing/);
  const wrong = structuredClone(expected);
  wrong[1][0] = 'incorrect-date';
  await assert.rejects(verifySavedWorkbook(item.file, wrong, col, bars), /saved-values-mismatch/);
  console.log(platform, result);
}
console.log('6 saved-workbook checks passed; no files modified');
const styles='<cellXfs><xf borderId="0" numFmtId="0"/><xf borderId="1" numFmtId="10"/></cellXfs>';
const good='<c r="A3" s="1"/><c r="N3" s="1"/><c r="AK3" s="1"/><c r="A481" s="1"/><c r="N481" s="1"/><c r="AK481" s="1"/>';
assert.doesNotThrow(()=>verifyBodyStyles(good,styles,'AK',481));
assert.throws(()=>verifyBodyStyles(good.replace('r="N481" s="1"','r="N481"'),' '+styles,'AK',481),/saved-body-border-missing/);
assert.throws(()=>verifyBodyStyles(good,styles.replace('numFmtId="10"','numFmtId="0"'),'AK',481),/saved-body-percentage-missing/);
console.log('3 body-style regression checks passed');
