// Read existing pages only. Keep ambiguity closed without closing other business pages.
export function selectExistingBrandPage(allPages) {
  const pages = allPages.filter(page => page.url().startsWith('https://melody.shop.ele.me/'));
  if (pages.length === 1) return pages[0];
  const reject = () => { throw new Error('brand-tab-not-unique'); };
  if (!pages.length) return reject();
  const context = pages[0].context();
  const routes = pages.map(page => {
    if (page.context() !== context) return reject();
    const url = new URL(page.url());
    const match = /^\/app\/chain\/(\d+)\/(dashboard|stats__center)$/.exec(url.pathname);
    if (!match) return reject();
    return { page, chain: match[1], route: match[2] };
  });
  if (new Set(routes.map(item => item.chain)).size !== 1) return reject();
  const homes = routes.filter(item => item.route === 'dashboard');
  if (homes.length !== 1) return reject();
  return homes[0].page;
}

export async function restoreSelectedBrandPage(page, initialUrl) {
  if (page && initialUrl && page.url() !== initialUrl) {
    await page.goto(initialUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
  }
}
