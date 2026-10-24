import fs from 'node:fs/promises';
import path from 'node:path';
import { buildFullAppealReport } from './full_appeal_report_builder.mjs';

const root = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
const shanghaiDay = (date = new Date()) => new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
const runDate = shanghaiDay();
const yesterday = new Date(`${runDate}T00:00:00+08:00`); yesterday.setUTCDate(yesterday.getUTCDate() - 1);
const businessDate = shanghaiDay(yesterday);
// 2026-09-30 大同授权「verified 后幂等跳过」：该业务日期日报已 verified 投递后，
// 不再重采线上数据（申诉状态白天会演变，重建的文件与已投递载荷不一致），
// 也不给下游投递步骤制造内容漂移。SKILL.md 约定业务日期为唯一事件键，
// verified 即该日终态；确需更新内容走 --correction-v1 通道（不受此守卫限制）。
const markerPath = `/Users/ddt/work/projects/ai_agent/state/taobao-flash-sale-negative-review-appeals/wechat-attempts/taobao-flash-appeals-${businessDate}.json`;
try {
  const marker = JSON.parse(await fs.readFile(markerPath, 'utf8'));
  if (marker && marker.ok === true && marker.verified === true && marker.state === 'verified') {
    console.log(JSON.stringify({ ok: true, status: 'already_verified', skipped: true, businessDate, marker: markerPath, runtimeModelDecisions: 0 }));
    process.exit(0);
  }
} catch {}
const outputDir = path.join(root, 'outputs', `taobao-flash-sale-negative-review-appeals-${runDate.replaceAll('-', '')}`);
console.log(JSON.stringify(await buildFullAppealReport({ channelLabel: '淘宝闪购', contextLabel: '淘宝', platformValue: '2', businessDate, recordDir: path.join(root, 'records', 'taobao-flash-sale-negative-review-appeals', businessDate), outputDir, outputPath: path.join(outputDir, `淘宝闪购差评申诉汇总-${businessDate}.xlsx`), previewPath: path.join(outputDir, `淘宝闪购差评申诉汇总-${businessDate}.png`) })));
