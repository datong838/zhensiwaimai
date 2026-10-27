#!/usr/bin/env node
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import net from 'node:net';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { spawn } from 'node:child_process';
import {randomUUID} from 'node:crypto';
import {withProfileLock, atomicState, processIdentity, assertProcess, assertListener, guardConnection, handoffConfig, publicUrl} from './session_guard.mjs';

const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const DEFAULT_ROOT = path.join(os.homedir(), 'Library/Application Support/AOS Background Chrome');
const FORBIDDEN_ROOT = path.join(os.homedir(), 'Library/Application Support/Google/Chrome');

function parse(argv) {
  const [command, ...rest] = argv; const options = {};
  for (let i=0;i<rest.length;i++) {
    if (!rest[i].startsWith('--')) throw new Error(`unexpected-argument:${rest[i]}`);
    const key=rest[i].slice(2); const value=rest[i+1];
    if (!value || value.startsWith('--')) options[key]=true;
    else { options[key]=value; i++; }
  }
  return {command,options};
}

function safeProfileName(value='') {
  if (!/^[a-z0-9][a-z0-9-]{0,62}$/.test(value)) throw new Error('invalid-profile-name');
  return value;
}

function canonicalPath(value) {
  const resolved=path.resolve(value);
  if(fs.existsSync(resolved))return fs.realpathSync(resolved);
  const parent=path.dirname(resolved);
  return parent===resolved?resolved:path.join(canonicalPath(parent),path.basename(resolved));
}

function pathsFor(options) {
  const name=safeProfileName(options.profile);
  const requested=path.resolve(options['profile-root'] || DEFAULT_ROOT);
  const root=canonicalPath(requested);
  const candidate=path.join(root,name);
  const profile=canonicalPath(candidate);
  const forbidden=fs.existsSync(FORBIDDEN_ROOT)?fs.realpathSync(FORBIDDEN_ROOT):path.resolve(FORBIDDEN_ROOT);
  if (profile===forbidden || profile.startsWith(forbidden+path.sep)) throw new Error('daily-chrome-profile-forbidden');
  return {name,root,profile,meta:path.join(profile,'.aos-background-chrome'),state:path.join(profile,'.aos-background-chrome/state.json')};
}

function validPort(value) {
  const port=Number(value); if (!Number.isInteger(port) || port<1024 || port>65535) throw new Error('invalid-port'); return port;
}

function optionalLaunchArgs(options={}) {
  const args=[];
  if(options['disable-background-mode']===true)args.push('--disable-background-mode');
  if(options['restore-last-session']===true)args.push('--restore-last-session');
  return args;
}

function portAvailable(port) {
  return new Promise(resolve=>{const server=net.createServer();server.once('error',()=>resolve(false));server.listen(port,'127.0.0.1',()=>server.close(()=>resolve(true)));});
}

async function readState(p) { try{return JSON.parse(await fsp.readFile(p.state,'utf8'));}catch{return null;} }
function pidAlive(pid) { if(!Number.isInteger(pid)||pid<=1)return false;try{process.kill(pid,0);return true;}catch{return false;} }
async function writeState(p,value) {await fsp.mkdir(p.meta,{recursive:true,mode:0o700});await atomicState(p,value);}

async function init(options) {
  const p=pathsFor(options);await fsp.mkdir(p.meta,{recursive:true,mode:0o700});
  return {ok:true,command:'init',profile:p.name,profilePath:p.profile};
}

async function launch(options,mode) {
  return withProfileLock(pathsFor(options),()=>launchUnlocked(options,mode));
}
async function launchUnlocked(options,mode) {
  if(!fs.existsSync(CHROME))throw new Error('chrome-not-installed');
  const p=pathsFor(options);await init(options);
  const old=await readState(p);if(old&&pidAlive(old.pid))throw new Error('profile-already-running');
  if(!['visible','visible-handoff','headless'].includes(mode))throw Error('invalid-mode');
  const config=mode==='visible-handoff'?handoffConfig(options):null;
  // Chrome's own profile lock also catches an unrecorded live instance.
  try{await fsp.lstat(path.join(p.profile,'SingletonLock'));throw Error('profile-lock-present');}catch(e){if(e.code!=='ENOENT')throw e;}
  const url=config?.url || options.url || 'about:blank';
  const args=[`--user-data-dir=${p.profile}`,'--no-first-run','--no-default-browser-check',...optionalLaunchArgs(options)];
  let port=null;
  if(mode==='headless'||config){
    port=config?.port??validPort(options.port || '9230');if(!(await portAvailable(port)))throw new Error('cdp-port-in-use');
    args.push('--remote-debugging-address=127.0.0.1',`--remote-debugging-port=${port}`);
    if(mode==='headless')args.push('--headless=new','--disable-gpu');
  }
  args.push(url);
  const child=spawn(CHROME,args,{detached:true,stdio:'ignore'});child.unref();
  const state={schemaVersion:1,profile:p.name,profilePath:p.profile,mode,port,pid:child.pid,startedAt:new Date().toISOString(),url,
    ...(config?{instanceId:randomUUID(),phase:'MANUAL_LOGIN',site:config.site,prefix:config.prefix,cdpEnabled:true,automationAttached:false}:{}),
    disableBackgroundMode:options['disable-background-mode']===true,restoreLastSession:options['restore-last-session']===true};
  const identity=await processIdentity(child.pid);
  state.processStartedAt=identity.start;
  await writeState(p,state);
  if(mode==='visible')return {ok:true,command:'login',profile:p.name,mode,pid:child.pid,automationAttached:false,cdpEnabled:false};
  if(config){
    const until=Date.now()+10000;
    while(Date.now()<until){
      await assertProcess(p,state);
      try{await assertListener(state);return {ok:true,command:'login-handoff',profile:p.name,mode,port,pid:child.pid,instanceId:state.instanceId,phase:state.phase,automationAttached:false,cdpEnabled:true};}catch(e){if(e.message!=='cdp-listener-unavailable')throw e;}
      await new Promise(r=>setTimeout(r,150));
    }
    throw Error('cdp-listener-unavailable');
  }
  const deadline=Date.now()+10000;
  while(Date.now()<deadline){
    if(!pidAlive(child.pid))throw new Error('chrome-exited-during-start');
    try{const response=await fetch(`http://127.0.0.1:${port}/json/version`);if(response.ok)return {ok:true,command:mode==='headless'?'start':'login',profile:p.name,mode,port,pid:child.pid};}catch{}
    await new Promise(r=>setTimeout(r,150));
  }
  throw new Error('cdp-not-ready');
}

async function probe(options) {return withProfileLock(pathsFor(options),()=>probeUnlocked(options));}
async function probeUnlocked(options) {
  const p=pathsFor(options);const state=await readState(p);await guardConnection(p,state,options,'probe');
  const port=validPort(options.port || state.port);if(port!==state.port)throw new Error('state-port-mismatch');
  const response=await fetch(`http://127.0.0.1:${port}/json/list`,{signal:AbortSignal.timeout(5000)});if(!response.ok)throw new Error('cdp-probe-failed');
  const pages=await response.json();const prefix=state.prefix||options['expected-url-prefix'];
  const matches=prefix?pages.filter(page=>typeof page.url==='string'&&page.url.startsWith(prefix)):[];
  return {ok:true,command:'probe',profile:p.name,mode:state.mode,port,targetMatches:matches.length,
    target:matches.length===1?{url:publicUrl(matches[0].url),title:matches[0].title}:null};
}

async function stop(options) {return withProfileLock(pathsFor(options),()=>stopUnlocked(options));}
async function stopUnlocked(options) {
  const p=pathsFor(options);const state=await readState(p);await assertProcess(p,state);
  if(state.mode==='visible-handoff'&&(options.instance!==state.instanceId||options['allow-process-exit']!==true))throw Error('explicit-process-exit-required');
  process.kill(state.pid,'SIGTERM');
  const deadline=Date.now()+8000;while(pidAlive(state.pid)&&Date.now()<deadline)await new Promise(r=>setTimeout(r,100));
  if(pidAlive(state.pid))throw new Error('managed-process-did-not-stop');
  await writeState(p,{...state,stoppedAt:new Date().toISOString(),status:'stopped'});
  return {ok:true,command:'stop',profile:p.name,pid:state.pid};
}

async function selfTest() {
  let rejected=false;try{pathsFor({profile:'x','profile-root':FORBIDDEN_ROOT});}catch(error){rejected=error.message==='daily-chrome-profile-forbidden';}
  if(!rejected||safeProfileName('taobao-brand')!=='taobao-brand'||validPort('9230')!==9230)throw new Error('self-test-failed');
  return {ok:true,command:'self-test',tests:4,loginAutomationAttached:false};
}

export { parse,safeProfileName,pathsFor,validPort,optionalLaunchArgs,portAvailable,readState,pidAlive,init,launch,probe,stop,selfTest };

async function main(){
  const {command,options}=parse(process.argv.slice(2));
  try{
    let result;
    if(command==='init')result=await init(options);else if(command==='login')result=await launch(options,'visible');
    else if(command==='login-handoff')result=await launch(options,'visible-handoff');
    else if(['confirm-login','takeover','release-login-window','recover-target','release-recovered-pages','diagnose-target','verify-work-page','ensure-jinsha-context','minimize-work-window'].includes(command))result=await (await import('./handoff.mjs')).runHandoff(command,options);
    else if(command==='start')result=await launch(options,'headless');else if(command==='probe')result=await probe(options);
    else if(command==='stop')result=await stop(options);else if(command==='self-test')result=await selfTest();else throw new Error('unknown-command');
    console.log(JSON.stringify(result));
  }catch(error){console.error(JSON.stringify({ok:false,command,reason:String(error.message||error)}));process.exitCode=1;}
}

if(import.meta.url===`file://${process.argv[1]}`)main().catch(()=>{console.error(JSON.stringify({ok:false,reason:'command-failed'}));process.exitCode=1;});
