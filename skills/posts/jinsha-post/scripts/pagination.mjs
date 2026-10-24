// 金鲨岗（jinsha-post）分页一致性核对 —— 通用
// 从 daily-negative-reviews/browser_collect.mjs 的 waitReady/collectPlatform 收敛，
// 语义不变：el-pagination 的「总数 / 每页条数 / 当前页 / 可见行数」四方一致且稳定
// 两次才放行；跨页核对总数与页大小不漂移。
// 泛化为通用函数：不依赖差评专属的 .cryptonym 行选择器，行选择器由调用方传入。

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const now = () => Date.now();

/**
 * 等待金鲨列表页分页稳定：总数、每页条数、当前页、可见行数四方一致，稳定两次放行。
 * @param {import('playwright-core').Page} page
 * @param {object} opts
 * @param {number} opts.pageNumber 目标页码
 * @param {string} opts.rowSelector 可见行选择器（如 '.cryptonym:visible'）
 * @param {object} [opts.prior] 上一页的 {expected,pageSize}，用于跨页漂移校验
 * @returns {Promise<{expected:number,actual:number,pageSize:number,pageNumber:number,totalPages:number}>}
 */
export async function waitPaginationStable(page, {pageNumber = 1, rowSelector = '.cryptonym:visible', prior = null} = {}) {
  let last = '';
  let stable = 0;
  const end = now() + 60000;
  while (now() < end) {
    const totals = page.locator('.el-pagination__total:visible');
    const sizes = page.locator('input[placeholder="请选择"]:visible');
    if ((await totals.count()) !== 1 || (await sizes.count()) !== 1) throw Error('visible-pagination-controls-not-unique');
    const totalText = await totals.innerText();
    const sizeText = await sizes.inputValue();
    const totalMatch = totalText.match(/共\s*(\d+)\s*条/);
    const sizeMatch = sizeText.match(/^(\d+)条\/页$/);
    const total = totalMatch ? Number(totalMatch[1]) : NaN;
    const pageSize = sizeMatch ? Number(sizeMatch[1]) : NaN;
    const active = page.locator('.el-pager li.active:visible');
    const activeNumber = (await active.count()) === 1 ? Number((await active.innerText()).trim()) : total === 0 ? 1 : NaN;
    const actual = await page.locator(rowSelector).count();
    const expectedOnPage = Number.isFinite(total) && pageSize > 0 ? Math.min(pageSize, Math.max(0, total - (pageNumber - 1) * pageSize)) : NaN;
    const key = `${total}:${pageSize}:${activeNumber}:${actual}`;
    stable = key === last ? stable + 1 : 1;
    last = key;
    if (prior && (total !== prior.expected || pageSize !== prior.pageSize)) throw Error(`visible-pagination-drift:${key}`);
    if (Number.isFinite(expectedOnPage) && activeNumber === pageNumber && actual === expectedOnPage && stable >= 2)
      return {expected: total, actual, pageSize, pageNumber, totalPages: Math.max(1, Math.ceil(total / pageSize))};
    await sleep(300);
  }
  throw Error(`jinsha-list-not-stable:${last || 'none'}`);
}

/**
 * 翻到下一页并等待稳定。跨页总数/页大小漂移即抛错。
 * @returns 下一页的稳定快照
 */
export async function nextPage(page, ready, {rowSelector = '.cryptonym:visible'} = {}) {
  const next = page.locator('.el-pagination .btn-next:visible');
  if ((await next.count()) !== 1 || (await next.isDisabled())) throw Error('visible-pagination-next-unavailable');
  await next.click();
  return waitPaginationStable(page, {pageNumber: ready.pageNumber + 1, rowSelector, prior: ready});
}

/**
 * 遍历所有分页收集行（泛化版），调用方提供 extract 函数。
 * @param {import('playwright-core').Page} page
 * @param {object} ready 首页稳定快照
 * @param {(page:any)=>Promise<any[]>} extract 从当前页提取行数组
 */
export async function collectAllPages(page, ready, extract, {rowSelector = '.cryptonym:visible'} = {}) {
  const rows = [];
  if (ready.expected === 0) return rows;
  let current = ready;
  while (true) {
    const batch = await extract(page);
    if (batch.length !== current.actual) throw Error(`visible-page-count:${current.pageNumber}:${batch.length}:${current.actual}`);
    rows.push(...batch);
    if (rows.length > current.expected) throw Error('visible-page-overflow');
    if (current.pageNumber === current.totalPages) {
      if (rows.length !== current.expected) throw Error(`visible-total-mismatch:${rows.length}:${current.expected}`);
      return rows;
    }
    current = await nextPage(page, current, {rowSelector});
  }
}
