import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import http from 'node:http';
import net from 'node:net';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {createRequire} from 'node:module';
import {launch,stop,pathsFor,readState,probe} from './background_chrome.mjs';
import {runHandoff,inspectHandoff} from './handoff.mjs';
import {withProfileLock,guardConnection,sleep,processIdentity} from './session_guard.mjs';
const exec=promisify(execFile);const require=createRequire(import.meta.url);
const {chromium}=require('../../headless-playwright/node_modules/playwright-core');
const enabled=process.env.RUN_BROWSER_INTEGRATION==='1';
async function cli(command,o){const args=[path.join(dir,'background_chrome.mjs'),command];for(const [key,value] of Object.entries(o)){args.push('--'+key);if(value!==true)args.push(String(value));}
 const result=await exec(process.execPath,args);return JSON.parse(result.stdout);}
const dir=path.dirname(new URL(import.meta.url).pathname);
async function freePort(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p;}
async function foreground(){return (await exec('/usr/bin/osascript',['-l','JavaScript','-e','ObjC.import("AppKit"); $.NSWorkspace.sharedWorkspace.frontmostApplication.bundleIdentifier.js'])).stdout.trim();}

test('isolated Chrome: zero-attachment gate, confirmation, reconnect and safe window release',{skip:!enabled,timeout:90000},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'aos-handoff-test-'));
 let seeded=false,sessionReused=false;
 const server=http.createServer((req,res)=>{
  res.setHeader('Content-Type','text/html; charset=utf-8');
  // Synthetic session cookie only: no account, credentials or external site.
  if(!seeded){seeded=true;res.setHeader('Set-Cookie','fixture_session=local; Path=/; SameSite=Lax');}
  else if(!String(req.headers.cookie||'').includes('fixture_session=local')){res.end('<body>扫码登录</body>');return;}
  else if(req.url==='/')sessionReused=true;
  res.end('<html><title>Local handoff fixture</title><body>商家中心 全部门店 全部订单 订单状态 商家首页 今日营业概况 数据中心</body></html>');
 });
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const url=`http://127.0.0.1:${server.address().port}/`;
 const o={profile:'test-meituan','profile-root':root,port:String(await freePort()),'test-url':url};let state;
 try{
  const start=await launch(o,'visible-handoff');state=await readState(pathsFor(o));
  assert.equal(start.automationAttached,false);assert.equal(state.phase,'MANUAL_LOGIN');
  const confirmed={...o,instance:start.instanceId,'user-confirmed':true,'task-id':'fixture-handoff'};
  for(const command of ['probe','takeover','release-login-window']){
   await assert.rejects(command==='probe'?probe(confirmed):runHandoff(command,confirmed),/phase-forbids/);
  }
  for(const command of ['open','inspect','close']){
   try{await exec(process.execPath,[path.join(dir,'run_task.mjs'),command,'--profile',o.profile,'--profile-root',root,'--port',o.port,'--instance',start.instanceId,'--task-id','fixture-handoff','--url',url]);assert.fail('manual command connected');}
   catch(e){assert.match(e.stderr||'',/phase-forbids/);}
  }
  await assert.rejects(runHandoff('confirm-login',{...confirmed,instance:'stale'}),/instance/);
  await assert.rejects(runHandoff('confirm-login',{...confirmed,'user-confirmed':false}),/CONFIRMATION/);
  await cli('confirm-login',confirmed);
  await assert.rejects(runHandoff('confirm-login',confirmed),/phase-forbids/);
  await withProfileLock(pathsFor(o),()=>assert.rejects(runHandoff('takeover',confirmed),/profile-operation-busy/));
  const verified=await cli('takeover',confirmed);assert.equal(verified.phase,'TAKEOVER_VERIFIED');assert.equal(verified.observations.length,2);
  const before=await foreground();
  const released=await cli('release-login-window',confirmed);assert.equal(released.phase,'WINDOW_RELEASED');assert.equal(sessionReused,true,'new task window must reuse the synthetic session');
  assert.equal(await foreground(),before,'release must not steal foreground');
  const minimized=await cli('minimize-work-window',confirmed);assert.equal(minimized.workWindowState,'minimized');assert.equal(minimized.reconnectedWhileMinimized,true);
  const final=await readState(pathsFor(o));assert.equal(final.pid,state.pid);assert.equal(final.processStartedAt,state.processStartedAt);
  assert.equal((await inspectHandoff(pathsFor(o),final,confirmed)).observation.authenticated,true);
  await assert.rejects(runHandoff('release-login-window',confirmed),/phase-forbids/);
  await assert.rejects(stop(confirmed),/explicit-process-exit/);
  // Inspect only the synthetic session and task targets, never real profiles.
  const b=await chromium.connectOverCDP(`http://127.0.0.1:${o.port}`);
  try{const ids=[];for(const page of b.contexts()[0].pages()){const c=await b.contexts()[0].newCDPSession(page);ids.push((await c.send('Target.getTargetInfo')).targetInfo.targetId);await c.detach();}
   assert.ok(!ids.includes(final.loginTargetId));assert.ok(ids.includes(final.taskTargetId));
  }finally{await b.close();}
 }finally{
  const current=await readState(pathsFor(o));
  if(current)await stop({...o,instance:current.instanceId,'allow-process-exit':true});
  await new Promise(r=>server.close(r));await fs.rm(root,{recursive:true,force:true});
 }
});

test('legacy headless entrypoints still work against a local fixture',{skip:!enabled,timeout:45000},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'aos-legacy-test-'));
 const server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end('<body>商家首页 今日营业概况 数据中心</body>');});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const url=`http://127.0.0.1:${server.address().port}/`;
 const o={profile:'test-legacy','profile-root':root,port:String(await freePort()),url};
 try{
  await launch(o,'headless');assert.equal((await probe({...o,'expected-url-prefix':url})).targetMatches,1);
  const result=await exec(process.execPath,[path.join(dir,'run_task.mjs'),'open','--profile',o.profile,'--profile-root',root,'--task-id','legacy-fixture','--url',url]);
  assert.equal(JSON.parse(result.stdout).authenticated,true);
 }finally{if(await readState(pathsFor(o)))await stop(o);await new Promise(r=>server.close(r));await fs.rm(root,{recursive:true,force:true});}
});

test('blank, security challenge and duplicate targets block takeover without closing the login page',{skip:!enabled,timeout:60000},async()=>{
 const root=await fs.mkdtemp(path.join(os.tmpdir(),'aos-negative-test-'));
 const server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html; charset=utf-8');res.end(req.url==='/blank'?'<body></body>':req.url==='/risk'?'<body>商家中心 全部门店 全部订单 订单状态 安全验证</body>':'<body>商家中心 全部门店 全部订单 订单状态</body>');});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));const origin=`http://127.0.0.1:${server.address().port}`;
 try{
 for(const [route,reason] of [['blank','PAGE_NOT_READY'],['risk','SECURITY_CHALLENGE'],['duplicate','TARGET_AMBIGUOUS']]){
  const o={profile:'test-'+route,'profile-root':root,port:String(await freePort()),'test-url':origin+'/'+route,'task-id':'fixture-'+route};
  try{
   const started=await launch(o,'visible-handoff');o.instance=started.instanceId;o['user-confirmed']=true;
   await runHandoff('confirm-login',o);
   if(route==='duplicate'){
    const browser=await chromium.connectOverCDP(`http://127.0.0.1:${o.port}`);
    try{const extra=await browser.contexts()[0].newPage();await extra.goto(origin+'/second');}finally{await browser.close();}
   }
   await assert.rejects(runHandoff('takeover',o),new RegExp(reason));
   const s=await readState(pathsFor(o));assert.equal(s.phase,'BLOCKED');assert.equal(s.failure,reason);
   assert.ok((await processIdentity(s.pid)).cmd.includes(s.profilePath));
   await assert.rejects(runHandoff('takeover',o),/phase-forbids/);
   await assert.rejects(runHandoff('release-login-window',o),/phase-forbids/);
   if(route==='duplicate'){
    const recovered=await cli('recover-target',o);assert.equal(recovered.phase,'TAKEOVER_VERIFIED');assert.equal(recovered.pid,s.pid);
    assert.equal((await inspectHandoff(pathsFor(o),await readState(pathsFor(o)),o)).observation.authenticated,true);
    await assert.rejects(runHandoff('recover-target',o),/recovery-forbidden/);
    const released=await cli('release-recovered-pages',o);assert.equal(released.phase,'WINDOW_RELEASED');assert.equal(released.closedPreviousTargets,2);
    assert.equal((await inspectHandoff(pathsFor(o),await readState(pathsFor(o)),o)).observation.authenticated,true);
   }
  }finally{const s=await readState(pathsFor(o));if(s)await stop({...o,instance:s.instanceId,'allow-process-exit':true});}
 }
 }finally{await new Promise(r=>server.close(r));await fs.rm(root,{recursive:true,force:true});}
});
