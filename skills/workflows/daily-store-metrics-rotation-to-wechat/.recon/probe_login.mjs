import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
console.log('NOW=' + await s.mainEval('location.href'));
// 真实导航到一个业务页，看是否被弹回 login
await s.cdp.send('Page.navigate', { url: 'https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard' });
await sleep(9000);
await s.rearm();
const u = await s.mainEval('location.href');
console.log('AFTER_NAV=' + u);
const t = await s.mainEval(`(()=>{const b=document.body;return (b?b.innerText:'').replace(/\s+/g,' ').slice(0,200)})()`);
console.log('TEXT=' + t);
const logged = !/\/login/.test(u);
console.log('LOGGED_IN=' + logged);
s.cdp.close(); process.exit(logged?0:3);
