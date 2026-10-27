// 只读诊断：品牌岗 9230 切换到指定店铺时，头部店名 span / 搜索下拉 li 的真实 DOM。
// 不发送任何消息；仅连接现有页面做读取与一次切店（采集器本就要做同样动作）。
import { connectToPost } from '../skills/posts/taobao-brand-post/scripts/connect.mjs';
import { acquirePostLease, releasePostLease } from '../skills/posts/taobao-brand-post/scripts/lease.mjs';

const want = process.argv[2] || '甬潮·宁波小市';
const lease = await acquirePostLease(`probe-shop-${Date.now()}`);
if (!lease) { console.log(JSON.stringify({ status: 'skipped', reason: 'post-lease-busy' })); process.exit(0); }
let browser;
// 2026-10-11 教训加固：弹窗（cook-modal-wrap/ant-modal-wrap）会拦截 caret/搜索框点击，
// 且 probe 曾误切已下线店后触发「店铺无效」弹窗，殃及后续流程（daemon 采集器点击全被拦）。
// 进入操作前先消解提示类弹窗（仅中性按钮/关闭X，不做表单提交）。
async function dismissModal(page) {
  for (let i = 0; i < 3; i++) {
    const visible = await page.evaluate(() => {
      const w = document.querySelector('.ant-modal-wrap, .cook-modal-wrap');
      if (!w) return false;
      const s = getComputedStyle(w);
      return s.display !== 'none' && s.visibility !== 'hidden';
    });
    if (!visible) return;
    const btn = page.locator('.ant-modal-root .ant-modal-footer button, .cook-modal-wrap button')
      .filter({ hasText: /跳|知道了|我知道|确/ }).first();
    if (await btn.count()) await btn.click({ timeout: 4000 }).catch(() => {});
    else await page.locator('.ant-modal-close, .cook-modal-close').first().click({ timeout: 4000 }).catch(() => {});
    await page.waitForTimeout(800);
  }
}
try {
  const conn = await connectToPost();
  browser = conn.browser;
  const pages = browser.contexts().flatMap(c => c.pages()).filter(p => p.url().startsWith('https://melody.shop.ele.me/'));
  console.log('brand pages=', pages.length);
  const page = pages[0];
  console.log('url=', page.url());
  await dismissModal(page);
  const nameOf = async () => {
    const l = page.locator('span[class^="shop-name__"]').first();
    const c = await l.count().catch(() => -1);
    const t = c > 0 ? await l.innerText().catch(e => 'ERR:' + e.message) : '<no-span>';
    return { count: c, text: t };
  };
  console.log('current header name=', JSON.stringify(await nameOf()));

  const caret = page.locator('span[role="img"][aria-label="caret-down"]').first();
  console.log('caret count=', await caret.count());
  if (await caret.count()) await caret.click({ timeout: 5000 }).catch(e => console.log('caret click err:', e.message));
  else await page.locator('span[class^="shop-name__"]').first().click({ timeout: 5000 }).catch(e => console.log('name click err:', e.message));
  await page.waitForTimeout(1200);

  const input = page.getByPlaceholder('搜索店铺名称/ID').first();
  console.log('search-input count=', await input.count());
  if (await input.count()) {
    await input.fill(want).catch(e => console.log('fill err:', e.message));
    await page.waitForTimeout(1500);
  }
  const lis = page.locator('li.cook-cascader-menu-item');
  const n = await lis.count();
  console.log('li.cook-cascader-menu-item count=', n);
  for (let i = 0; i < Math.min(n, 30); i++) {
    const t = (await lis.nth(i).innerText().catch(() => '')).replace(/\s*\n\s*/g, ' ¦ ').slice(0, 90);
    const dv = await lis.nth(i).getAttribute('data-value').catch(() => null);
    console.log(`   li[${i}] ${JSON.stringify(t)} dv=${dv}`);
  }
  const match = page.locator('li.cook-cascader-menu-item', { hasText: want });
  const mc = await match.count();
  // 2026-10-11 误切教训：同品牌多店共享前缀且括号全/半角混排时，hasText 的 first() 可能命中
  // 已下线店（切过去会弹「店铺无效」弹窗殃及流程）。诊断工具默认不切店：只报告候选；
  // 仅当「营业中」候选唯一时才执行切店验证（与采集器 fail-closed 语义一致）。
  let pick = null;
  const cands = [];
  for (let i = 0; i < mc; i++) {
    const item = match.nth(i);
    const txt = (await item.innerText().catch(() => '')).replace(/\s+/g, '');
    if (txt.includes('营业中')) cands.push(item);
  }
  console.log('match count=', mc, '营业中候选=', cands.length);
  if (cands.length === 1) {
    pick = cands[0];
    console.log('切店目标 dv=', await pick.getAttribute('data-value').catch(() => null));
  } else {
    console.log('候选不唯一/无营业中 ⇒ 只读模式，不切店');
  }
  if (pick) {
    await pick.click({ timeout: 5000 }).catch(e => console.log('li click err:', e.message));
    for (let i = 0; i < 26; i++) {
      await page.waitForTimeout(500);
      const u = page.url();
      const nm = await nameOf();
      console.log(`   t+${((i + 1) * 0.5).toFixed(1)}s name.count=${nm.count} name=${JSON.stringify(nm.text)} url=…${u.slice(-72)}`);
      if (nm.text && String(nm.text).trim() === want) { console.log('*** MATCHED ***'); break; }
    }
  }
} catch (e) {
  console.log('PROBE-ERROR:', e.message);
  console.log(String(e.stack || '').split('\n').slice(0, 6).join(' ⏎ '));
} finally {
  await browser?.close().catch(() => {});
  if (lease) await releasePostLease(lease).catch(() => {});
}
