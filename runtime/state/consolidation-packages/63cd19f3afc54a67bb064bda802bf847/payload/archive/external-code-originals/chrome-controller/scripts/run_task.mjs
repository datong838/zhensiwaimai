#!/usr/bin/env node
import path from 'node:path';
import fs from 'node:fs/promises';
import {pathToFileURL} from 'node:url';
import { createRequire } from 'node:module';
import {pathsFor,readState} from './background_chrome.mjs';
import {withProfileLock,guardConnection,publicUrl} from './session_guard.mjs';

const require=createRequire(import.meta.url);
const {chromium}=require('../../headless-playwright/node_modules/playwright-core');

function parse(argv){const [command,...rest]=argv;const o={};for(let i=0;i<rest.length;i++){const k=rest[i].slice(2);o[k]=rest[++i];}return{command,o};}
export function safeTaskId(value){return /^[a-z0-9][a-z0-9-]{0,62}$/.test(value||'');}

async function ownedPages(context,taskId){
  const marker=`aos-background-task:${taskId}`;const matches=[];
  for(const page of context.pages()){
    try{if(await page.evaluate(()=>window.name)===marker)matches.push(page);}catch{}
  }
  return matches;
}

export async function inspectPage(page,o,command){
  await page.waitForTimeout(3000);
  if(o.profile==='meituan-merchant'){
    const observation=await (await import('./handoff.mjs')).observe(page,{site:'meituan',prefix:'https://waimaie.meituan.com/'});
    const receipt={ok:true,command,profile:o.profile,taskId:o['task-id'],...observation};
    if(o.screenshot){const shot=path.resolve(o.screenshot);await fs.mkdir(path.dirname(shot),{recursive:true});await page.screenshot({path:shot,fullPage:false});receipt.screenshot=shot;}
    if(o.receipt){const out=path.resolve(o.receipt);await fs.mkdir(path.dirname(out),{recursive:true});await fs.writeFile(out,JSON.stringify(receipt,null,2));}
    return receipt;
  }
  const frameBodies=[];
  for(const frame of page.frames()){
    try{const text=(await frame.evaluate(()=>document.body?.innerText||'')).trim();if(text)frameBodies.push(text);}catch{}
  }
  const body=[...new Set(frameBodies)].join('\n---FRAME---\n');
  const loginMarkers=['账号密码','扫码登录','没有账号，去开店','无法登录？'];
  const signedInMarkers=['商家首页','今日营业概况','数据中心','订单管理','门店管理'];
  const seenLogin=loginMarkers.filter(value=>body.includes(value));const seenSignedIn=signedInMarkers.filter(value=>body.includes(value));
  const receipt={ok:true,command,profile:o.profile,taskId:o['task-id'],url:page.url(),title:await page.title(),frameCount:page.frames().length,textLength:body.length,
    loginPage:seenLogin,signedInMarkers:seenSignedIn,authenticated:seenLogin.length===0&&seenSignedIn.length>=3};
  if(o['expected-url-prefix']&&!page.url().startsWith(o['expected-url-prefix']))throw Error('unexpected-task-url');
  if(o.screenshot){const shot=path.resolve(o.screenshot);await fs.mkdir(path.dirname(shot),{recursive:true});await page.screenshot({path:shot,fullPage:false});receipt.screenshot=shot;}
  if(o.receipt){const out=path.resolve(o.receipt);await fs.mkdir(path.dirname(out),{recursive:true});await fs.writeFile(out,JSON.stringify(receipt,null,2));}
  return receipt;
}

async function main(){
  const {command,o}=parse(process.argv.slice(2));
  return withProfileLock(pathsFor(o),()=>run(command,o));
}
async function run(command,o){if(!safeTaskId(o.profile))throw Error('invalid-profile-name');
  if(!safeTaskId(o['task-id']))throw Error('invalid-task-id');
  const p=pathsFor(o);const state=await readState(p);
  const port=Number(o.port??state?.port??9230);if(!Number.isInteger(port))throw Error('invalid-port');
  await guardConnection(p,state,o,command);
  if(state.mode==='visible-handoff'){
    if(command!=='inspect')throw Error('handoff-use-dedicated-entrypoint');
    console.log(JSON.stringify(await (await import('./handoff.mjs')).inspectHandoff(p,state,o)));return;
  }
  const browser=await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  try{
    const context=browser.contexts()[0];if(!context)throw Error('context-missing');
    if(command==='open'){
      if(!o.url)throw Error('url-required');
      if((await ownedPages(context,o['task-id'])).length!==0)throw Error('task-page-already-exists');
      const page=await context.newPage();
      await page.addInitScript(taskId=>{window.name=`aos-background-task:${taskId}`;},o['task-id']);
      await page.goto(o.url,{waitUntil:'domcontentloaded',timeout:30000});
      await page.evaluate(taskId=>{window.name=`aos-background-task:${taskId}`;},o['task-id']);
      console.log(JSON.stringify(await inspectPage(page,o,command)));
    }else if(command==='inspect'||command==='close'||command==='diagnose'){
      const matches=await ownedPages(context,o['task-id']);if(matches.length!==1)throw Error(`task-page-match-count:${matches.length}`);
      if(command==='diagnose'){
        const page=matches[0];if(o.profile!=='meituan-merchant'||!page.url().startsWith('https://waimaie.meituan.com/'))throw Error('diagnosis-target-forbidden');
        const frames=[];for(const frame of page.frames()){let box=null;if(frame!==page.mainFrame()){const el=await frame.frameElement();try{box=await el.boundingBox();}finally{await el.dispose();}}frames.push({url:publicUrl(frame.url()),main:frame===page.mainFrame(),box});}
        console.log(JSON.stringify({ok:true,command,profile:o.profile,taskId:o['task-id'],url:publicUrl(page.url()),title:await page.title(),viewport:await page.evaluate(()=>({width:innerWidth,height:innerHeight})),mainTextLength:await page.evaluate(()=>document.body?.innerText.length||0),resources:await page.evaluate(()=>performance.getEntriesByType('resource').filter(r=>r.initiatorType==='script').map(r=>({url:new URL(r.name).origin+new URL(r.name).pathname,status:r.responseStatus??null,duration:Math.round(r.duration)}))),readyState:await page.evaluate(()=>document.readyState),frames}));
      }else if(command==='close'){await matches[0].close();console.log(JSON.stringify({ok:true,command,profile:o.profile,taskId:o['task-id']}));}
      else console.log(JSON.stringify(await inspectPage(matches[0],o,command)));
    }else throw Error('unknown-task-command');
  }finally{await browser.close();}
}
if(import.meta.url===pathToFileURL(process.argv[1]).href)main().catch(error=>{console.error(JSON.stringify({ok:false,reason:error.message}));process.exit(1);});

// Bound transport for site-specific fixed readers. The caller enforces its business read-only contract.
export async function withTaskPage(o,callback){
 const p=pathsFor(o);
 return withProfileLock(p,async()=>{
  const state=await readState(p);await guardConnection(p,state,o,'inspect');
  if(state.mode!=='visible-handoff'||state.taskId!==o['task-id'])throw Error('task-binding-mismatch');
  const target=state.activeTargetId||(state.phase==='WINDOW_RELEASED'?state.taskTargetId:state.loginTargetId);
  const marker=state.activeMarker||(state.phase==='WINDOW_RELEASED'?state.taskMarker:state.loginMarker);
  const browser=await chromium.connectOverCDP(`http://127.0.0.1:${state.port}`,{timeout:10000});
  try{
   const context=browser.contexts()[0];if(!context)throw Error('context-missing');const matches=[];
   for(const page of context.pages()){
    if(!page.url().startsWith(state.prefix))continue;
    if(await page.evaluate(()=>window.name)!==marker)continue;
    const session=await context.newCDPSession(page);let id;
    try{id=(await session.send('Target.getTargetInfo')).targetInfo.targetId;}finally{await session.detach();}
    if(id!==target)throw Error('task-target-changed');matches.push(page);
   }
   if(matches.length!==1)throw Error('task-page-not-unique');
   return await callback({page:matches[0],state});
  }finally{await browser.close();}
 });
}
