import { session, sleep } from '../scripts/lib/cdp.mjs';
const s = await session({ port: 9230, width: 1440, height: 1500 });
await s.rearm();
const tree = await s.cdp.send('Page.getFrameTree');
const flat=[];
const walk=(n,d=0)=>{ flat.push({id:n.frame.id,d,url:(n.frame.url||'').slice(0,90),name:n.frame.name||''}); (n.childFrames||[]).forEach(c=>walk(c,d+1)); };
walk(tree.frameTree);
console.log('FRAMES=' + JSON.stringify(flat,null,1));
// 列出所有 execution context
const ctxs=[];
s.on('Runtime.executionContextCreated', (p)=>{ ctxs.push({id:p.context.id,origin:(p.context.origin||'').slice(0,60),name:p.context.name,aux:p.context.auxData&&p.context.auxData.frameId}); });
await s.cdp.send('Runtime.enable');
await sleep(1500);
console.log('CTXS=' + JSON.stringify(ctxs,null,1));
s.cdp.close(); process.exit(0);
