// Reporting projection only. Never publishes a plan, task, or completion.
export const inspectionRecordKey = r => [r.platform, r.name, r.city].join('\x1f');
export function inspectionReportScope(scope, { month, sourceSha256, records, completeRoster }) {
  if (scope.month !== month || scope.reportOnly !== true || scope.executionEnabled !== false
      || scope.sourceSha256 !== sourceSha256 || scope.completeRoster !== completeRoster
      || !Number.isSafeInteger(scope.requestedShops) || scope.requestedShops < 1
      || !Array.isArray(scope.mappings) || scope.mappings.length !== scope.requestedShops)
    throw Error('inspection-report-scope-invalid');
  const date = new Date(scope.confirmedAt);
  if (Number.isNaN(date.getTime())) throw Error('inspection-report-confirmation-date-invalid');
  const start = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
  if (start.slice(0, 7) !== month) throw Error('inspection-report-confirmation-month-mismatch');
  const sourceKeys = new Set(records.map(inspectionRecordKey));
  if (sourceKeys.size !== records.length) throw Error('inspection-report-source-identity-ambiguous');
  const selected = new Set(), matchedKeys = new Set(), candidateKeys = new Set();
  let matchedShops = 0;
  for (const mapping of scope.mappings) {
    if (!/^\d+$/.test(String(mapping.selected?.shopId || '')) || typeof mapping.selected?.name !== 'string' || !mapping.selected.name.trim()
        || typeof mapping.state !== 'string' || !mapping.state.trim()
        || selected.has(String(mapping.selected.shopId))
        || !Array.isArray(mapping.matched) || !Array.isArray(mapping.candidates))
      throw Error('inspection-report-requested-identity-invalid');
    selected.add(String(mapping.selected.shopId));
    if (mapping.matched.length) matchedShops++;
    for (const row of mapping.matched) {
      const key = inspectionRecordKey(row);
      if (!row.city || !sourceKeys.has(key) || matchedKeys.has(key)) throw Error('inspection-report-matched-identity-invalid');
      matchedKeys.add(key);
    }
    for (const row of mapping.candidates) {
      const key = inspectionRecordKey(row);
      if (!row.city || !sourceKeys.has(key)) throw Error('inspection-report-candidate-identity-invalid');
      candidateKeys.add(key);
    }
  }
  if (scope.matchedShops !== matchedShops || scope.matchedPlatformRecords !== matchedKeys.size
      || [...candidateKeys].some(key => matchedKeys.has(key))) throw Error('inspection-report-control-count-mismatch');
  const [year, number] = month.split('-').map(Number), end = new Date(Date.UTC(year, number, 0)).getUTCDate();
  const first = Number(start.slice(8)), perDay = Math.ceil(matchedKeys.size / (end - first + 1));
  const calendarCounts = new Map();
  let remaining = matchedKeys.size;
  for (let day = first; day <= end; day++) {
    const count = Math.min(perDay, remaining);
    calendarCounts.set(`${month}-${String(day).padStart(2, '0')}`, count);
    remaining -= count;
  }
  return { requestedShops: selected.size, matchedShops, plannedRecords: matchedKeys.size,
    matchedKeys, candidateKeys, calendarCounts,
    scopeRows: scope.mappings.map((mapping, index) => [index + 1, String(mapping.selected.shopId), mapping.selected.name,
      mapping.matched.filter(r => r.platform === '淘宝闪购').map(r => `${r.name} / ${r.city}`).join('；') || '未找到',
      [...mapping.matched.filter(r => r.platform === '美团外卖').map(r => `${r.name} / ${r.city}`),
        ...mapping.candidates.map(r => `待核：${r.name} / ${r.city}`)].join('；') || '暂无对应记录', mapping.state]) };
}
