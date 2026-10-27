import {session} from '../../../skills/workflows/daily-store-metrics-rotation-to-wechat/scripts/lib/cdp.mjs';
let s;try{
 s=await session();await s.rearm();const c=await s.ctxForFrame(/melody-stats-next/);if(!c.id)throw Error('no-frame');const ev=s.frameEval(c.id);
 const b=await s.mainEval(`(()=>{const r=[...document.querySelectorAll('iframe')].find(e=>e.clientWidth>300).getBoundingClientRect();return {x:r.x,y:r.y}})()`);
 await s.clickAt(b.x+490,b.y+87);await s.sleep(2600);
 console.log(JSON.stringify(await ev(`(()=>{const v=e=>e.getBoundingClientRect().width>0;return {tab:location.hash,radios:[...document.querySelectorAll('.ant-radio-button-wrapper')].filter(v).map(e=>({t:e.innerText,y:e.getBoundingClientRect().y+scrollY})),times:[...document.querySelectorAll('*')].filter(e=>e.children.length===0&&v(e)&&['今日实时','昨日','近7日','近30日','自定义'].includes((e.innerText||'').trim())).map(e=>({t:e.innerText,c:e.className,parent:e.parentElement.outerHTML.slice(0,900),y:e.getBoundingClientRect().y+scrollY})),head:[...document.querySelectorAll('*')].filter(e=>e.children.length===0&&v(e)&&(e.innerText||'').trim()==='商品明细').map(e=>e.parentElement.outerHTML.slice(0,800))}})()`)));
}finally{if(s){await s.cdp.send('Page.navigate',{url:'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center'});await s.sleep(2000);s.cdp.close();}}process.exit(0);
