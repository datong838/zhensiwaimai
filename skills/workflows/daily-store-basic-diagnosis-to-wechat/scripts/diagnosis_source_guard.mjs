// Self-contained: the original page.evaluate serializes this function.
export async function collectMetricPages({rec, metrics, pageSize, maxPages}) {
  const result = {};
  for (const [code, name] of metrics) {
    const body = JSON.parse(rec.reqBody);
    body.agentCode = code; body.pageSize = pageSize; body.shopIdListIn = '';
    let total = null, collected = [], complete = false;
    for (let current = 1; current <= maxPages; current++) {
      body.current = current;
      const response = await fetch(rec.url, {method:'POST', headers:{...rec.headers},
        body:JSON.stringify(body), credentials:'include'});
      if (!response.ok) throw Error(`diag-http-error:${name}:${response.status}`);
      const value = await response.json();
      if (!value || value.code !== 0) throw Error(`diag-response-error:${name}`);
      if (!Number.isSafeInteger(value.totalCount) || value.totalCount < 0)
        throw Error(`diag-total-invalid:${name}`);
      if (total === null) total = value.totalCount;
      if (value.totalCount !== total) throw Error(`diag-total-drift:${name}`);
      if (!Array.isArray(value.data) || value.data.length > pageSize)
        throw Error(`diag-page-invalid:${name}`);
      collected.push(...value.data);
      if (collected.length > total) throw Error(`diag-count-exceeds-total:${name}`);
      if (collected.length === total) {complete = true; break;}
      if (!value.data.length) throw Error(`diag-empty-page-before-total:${name}`);
    }
    if (!complete) throw Error(`diag-pagination-incomplete:${name}`);
    result[name] = {totalCount:total, rows:collected};
  }
  return result;
}

export function validateMetricResults(results, metrics) {
  if (!results || typeof results !== 'object' || Array.isArray(results)
      || Object.keys(results).length !== metrics.length)
    throw Error('diag-metric-set-incomplete');
  for (const [, name] of metrics) {
    const metric = results[name];
    if (!metric || metric.error || metric.truncated || !Array.isArray(metric.rows)
        || !Number.isSafeInteger(metric.totalCount) || metric.totalCount < 0
        || metric.rows.length !== metric.totalCount)
      throw Error(`diag-metric-incomplete:${name}`);
    const identities = new Set();
    for (const row of metric.rows) {
      const id = row && (typeof row.shop_id === 'string' || typeof row.shop_id === 'number')
        ? String(row.shop_id).trim() : '';
      if (!row || !/^\d+$/.test(id) || typeof row.shop_name !== 'string'
          || !row.shop_name.trim() || row.task_status !== '未完成')
        throw Error(`diag-row-invalid:${name}`);
      if (identities.has(id)) throw Error(`diag-duplicate-shop:${name}`);
      identities.add(id);
    }
  }
  return results;
}
