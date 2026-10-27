// 监理每日环境复位：关闭并重新打开美团 IM 工作台页面（工位 9233 CDP）
// 铁律：全程只读 —— 不点击任何业务元素、不发消息、不改业务数据。
import pw from '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/posts/meituan-post/scripts/node_modules/playwright-core/index.js';

const CDP = 'http://127.0.0.1:9233';
const TARGET_URL =
  'https://waimaie.meituan.com/imworkbench/home?appId=4&clientType=140006#/im/page/workbench/reception';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const b = await pw.chromium.connectOverCDP(CDP);
const ctx = b.contexts()[0];

// 1) 关闭所有 imworkbench 页面
const before = ctx.pages().map((p) => p.url());
let closed = 0;
for (const p of ctx.pages()) {
  if (p.url().includes('/imworkbench/')) {
    try {
      await p.close();
      closed += 1;
    } catch (e) {
      console.log('close-failed:', e.message);
    }
  }
}

// 2) 新开页面并 goto
const page = await ctx.newPage();
try {
  await page.goto(TARGET_URL, { waitUntil: 'domcontentloaded', timeout: 60000 });
} catch (e) {
  console.log('goto-warn:', e.message);
}
await sleep(15000);

// 3) 只读校验
let text = '';
try {
  text = await page.evaluate(() => document.body.innerText || '');
} catch (e) {
  console.log('eval-warn:', e.message);
}
const hasWeihuifu = text.includes('未回复');
const hasDaigong = text.includes('待人工回复');
const ok = hasWeihuifu || hasDaigong;

// 4) 只读取证截图
const shotPath =
  process.env.OUT_PNG ||
  `/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/outputs/im_workbench_reset_${new Date()
    .toISOString()
    .slice(0, 10)
    .replace(/-/g, '')}.png`;
try {
  await page.screenshot({ path: shotPath, fullPage: false });
} catch (e) {
  console.log('shot-warn:', e.message);
}

console.log(
  JSON.stringify(
    {
      shot: shotPath,
      closedPages: closed,
      pagesBefore: before,
      finalUrl: page.url(),
      textLen: text.length,
      hit_weihuifu: hasWeihuifu,
      hit_dairengonghuifu: hasDaigong,
      reset_ok: ok,
    },
    null,
    2
  )
);
await b.close();
