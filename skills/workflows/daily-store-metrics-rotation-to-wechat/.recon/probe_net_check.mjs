/** 验证 Network 事件是否可达 + 探测页面内存里是否已预载整棵树 */
import { session, sleep } from '../scripts/lib/cdp.mjs';

const s = await session({ port: 9230, width: 1440, height: 1500 });
let n = 0; const urls = [];
s.cdp.on('Network.requestWillBeSent', (p) => { n++; if (urls.length < 40) urls.push((p.type || '?') + ' ' + p.request.url.slice(0, 120)); });
await s.cdp.send('Network.enable');
await s.rearm();
await sleep(800);

// 触发一次真实请求（重新加载当前 iframe 之外的东西不好做，直接 fetch 自己的域名探针）
await s.mainEval(`fetch('/rest/ofc/isLogin',{credentials:'include'}).then(r=>r.status).catch(e=>'err')`);
await sleep(1500);
console.log('NET_EVENTS=' + n);
urls.forEach((u) => console.log('  ' + u));

// 页面内存里找店铺树
const mem = await s.mainEval(`(()=>{
  const hits=[];
  const seen=new Set();
  const walk=(o,path,depth)=>{
    if(!o||typeof o!=='object'||depth>4||seen.has(o))return;
    seen.add(o);
    for(const k of Object.keys(o).slice(0,60)){
      let v; try{v=o[k]}catch{continue}
      if(Array.isArray(v)&&v.length>50){
        const s0=v[0];
        const txt=JSON.stringify(s0||null).slice(0,120);
        if(/shop|SHOP|store/i.test(txt)) hits.push({path:path+'.'+k,len:v.length,sample:txt});
      } else if(v&&typeof v==='object') walk(v,path+'.'+k,depth+1);
    }
  };
  walk(window,'window',0);
  return JSON.stringify(hits.slice(0,25),null,1);
})()`);
console.log('MEM_HITS:\n' + mem);
s.cdp.close();
process.exit(0);
