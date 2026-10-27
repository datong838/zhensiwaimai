import assert from 'node:assert/strict';
import { selectExistingBrandPage, restoreSelectedBrandPage } from '../js/brand_page_selector.mjs';
const ctx = {}, other = {};
const page = (route, context = ctx) => ({ url: () => `https://melody.shop.ele.me${route}`, context: () => context });
const home = page('/app/chain/95708808/dashboard#app.chainshop.dashboard');
const stats = page('/app/chain/95708808/stats__center#app.chainshop.stats.center');
const single = page('/app/shop/123/decorate');
assert.equal(selectExistingBrandPage([single]), single);
assert.equal(selectExistingBrandPage([home, stats]), home);
assert.equal(selectExistingBrandPage([stats, home]), home);
for (const pages of [[], [home, page('/app/chain/1/stats__center')],
  [home, page('/app/chain/95708808/stats__center', other)],
  [home, page('/app/chain/95708808/dashboard')], [stats, stats], [home, single],
  [home, page('/app/chain/95708808/unknown')]]) {
  assert.throws(() => selectExistingBrandPage(pages), /brand-tab-not-unique/);
}
let current = home.url(), navigations = [];
const tracked = {url: () => current, goto: async (url, options) => { navigations.push({url,options}); current = url; }};
await restoreSelectedBrandPage(tracked, home.url());
assert.equal(navigations.length, 0);
current = 'https://melody.shop.ele.me/app/shop/123/activity__myActivity';
await restoreSelectedBrandPage(tracked, home.url());
assert.deepEqual(navigations, [{url:home.url(),options:{waitUntil:'domcontentloaded',timeout:30000}}]);
await restoreSelectedBrandPage(undefined, undefined);
await assert.rejects(() => restoreSelectedBrandPage({url:()=> 'changed',goto:async()=>{throw Error('restore-failed');}}, home.url()), /restore-failed/);
console.log(JSON.stringify({ok: true, tests: 14, sendAttempts: 0}));
