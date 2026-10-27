import {spawn} from 'node:child_process';
import {createInterface} from 'node:readline';
import {fileURLToPath,pathToFileURL} from 'node:url';
import path from 'node:path';
import {runDesktopCua} from './desktop_cua_executor.mjs';
const dir=path.dirname(fileURLToPath(import.meta.url));
export function createNativeApp(){
 const child=spawn('/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python',[path.join(dir,'native_chrome_bridge.py')],{stdio:['pipe','pipe','pipe']});
 let pending=null,errors='';child.stderr.on('data',x=>errors+=x);
 const reject=e=>{if(pending){clearTimeout(pending.timer);pending.reject(e);pending=null;}};
 child.on('error',reject);child.on('exit',()=>reject(Error('native-bridge-exited:'+errors.slice(0,500))));
 createInterface({input:child.stdout}).on('line',line=>{const p=pending;if(!p)return;pending=null;clearTimeout(p.timer);try{const r=JSON.parse(line);r.ok?p.resolve(r.value):p.reject(Error(r.error));}catch(e){p.reject(e);}});
 const call=q=>new Promise((resolve,rejectFn)=>{if(pending)return rejectFn(Error('concurrent-native-operation'));pending={resolve,reject:rejectFn,timer:setTimeout(()=>{reject(Error('native-command-timeout:'+q.op));child.kill();},12000)};child.stdin.write(JSON.stringify(q)+'\n');});
 return {activate:()=>call({op:'activate'}),foreground:()=>call({op:'foreground'}),ensureFullscreen:()=>call({op:'fullscreen'}),getAXState:()=>call({op:'state'}),click:index=>call({op:'click',index}),hover:index=>call({op:'hover',index}),visualClickText:text=>call({op:'visual_click_text',text}),pressKey:key=>call({op:'key',key}),scroll:(index,direction,pages)=>call({op:'scroll',index,direction,pages}),captureOriginal:path=>call({op:'screenshot',path}),getCropGeometry:()=>call({op:'crop_geometry'}),close:()=>child.kill()};
}
export async function runNativeDesktop(){const app=createNativeApp();try{return await runDesktopCua({app});}finally{app.close();}}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){const r=await runNativeDesktop();console.log(JSON.stringify(r));process.exitCode=r.ok?0:1;}
