// 负反馈列表申诉汇总 Excel 生成入口（09:30 申诉跑完后，12:30 汇总时点调用）
// 产出双平台各自独立文件：美团一份、淘宝一份。
import path from 'node:path';
import { buildReports } from './report_builder.mjs';
import { FLOW_ID, ROOT, businessDate, shanghaiDay, recentRange } from './jinsha.mjs';

const runDate = shanghaiDay();
const business = businessDate();
const outputDir = path.join(ROOT, 'outputs', `${FLOW_ID}-${runDate.replaceAll('-', '')}`);

buildReports({
  window: recentRange(business),
  outputDir,
})
  .then(r => console.log(JSON.stringify(r)))
  .catch(e => { console.error(JSON.stringify({ ok: false, reason: String(e.message || e) })); process.exitCode = 1; });
