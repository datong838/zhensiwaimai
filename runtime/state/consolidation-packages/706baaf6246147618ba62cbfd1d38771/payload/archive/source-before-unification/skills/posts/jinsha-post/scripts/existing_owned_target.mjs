// Read-only selection of an existing Jinsha work target; never creates/closes/navigates pages.
import fs from 'node:fs/promises';
import path from 'node:path';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
const exec=promisify(execFile);
const ORIGIN='https://data.guoshuyufen.com/';
const PROOFS='/tmp/zhensi_daily_download/background-browser';
const STATE='/Users/ddt/Library/Application Support/AOS Background Chrome/jinsha-business/.aos-background-chrome/state.json';
export function ownerMarker(receipt,pid){
 const profile=receipt?.profiles?.jinsha;
 if(!Number.isInteger(pid)||pid<=1||receipt?.executor!=='background-browser-executor'||receipt.ok!==true||receipt.stage!=='completed'||receipt.phase!=='completed'||receipt.cleanupStatus!=='completed'||receipt.jinshaTaskStrategy!=='reused-existing-work-target'||profile?.profile!=='jinsha-business'||profile.port!==9232||profile.pid!==pid||!/^\d{4}-\d{2}-\d{2}$/.test(receipt.businessDate||'')||!/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(receipt.runId||''))return null;
 return `aos-background-task:taobao-jinsha-${receipt.runId.toLowerCase().slice(0,30)}`;
}
export function ownedTargetDecision(pages,proofs,pid,startedAt,now=Date.now()){
 if(!Number.isFinite(startedAt)||startedAt<=0)throw Error('jinsha-owner-process-start-missing');
 const matches=[];
 for(const page of pages){
  if(page.type!=='page'||!String(page.url||'').startsWith(ORIGIN)||page.url.includes('#/login'))continue;
  const owners=proofs.filter(p=>p.createdAt>=startedAt&&p.createdAt<=now&&ownerMarker(p.receipt,pid)!==null&&ownerMarker(p.receipt,pid)===page.marker);
  if(owners.length>1)throw Error('jinsha-owner-proof-not-unique');
  if(owners.length===1)matches.push({...page,jinshaOwnerMarker:page.marker});
 }
 if(matches.length!==1)throw Error(`jinsha-owned-page-not-unique:${matches.length}`);
 return matches[0];
}
async function readProofs(pid){
 const proofs=[];
 for(const entry of await fs.readdir(PROOFS,{withFileTypes:true})){
  if(!entry.isDirectory()||entry.isSymbolicLink())continue;
  try{
   const file=path.join(PROOFS,entry.name,'receipt.json'),stat=await fs.lstat(file);
   if(!stat.isFile()||stat.isSymbolicLink()||stat.size>2000000)continue;
   const receipt=JSON.parse(await fs.readFile(file,'utf8'));
   if(entry.name!==`${receipt.businessDate}-${receipt.runId}`||!ownerMarker(receipt,pid))continue;
   proofs.push({receipt,createdAt:stat.birthtimeMs});
  }catch{/* Incomplete or unreadable receipts cannot confer ownership. */}
 }
 return proofs;
}
async function readMarker(target){
 const ws=new WebSocket(target.webSocketDebuggerUrl);
 try{
  await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('jinsha-owner-probe-connect-timeout')),3000);ws.addEventListener('open',()=>{clearTimeout(timer);resolve();},{once:true});ws.addEventListener('error',()=>{clearTimeout(timer);reject(Error('jinsha-owner-probe-connect-error'));},{once:true});});
  return await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('jinsha-owner-probe-timeout')),3000);ws.addEventListener('message',event=>{const out=JSON.parse(event.data);if(out.id!==1)return;clearTimeout(timer);if(out.error||out.result?.exceptionDetails)return reject(Error('jinsha-owner-probe-failed'));const value=out.result?.result?.value;if(value?.url!==target.url)return reject(Error('jinsha-owner-probe-url-changed'));resolve(value.marker);});ws.send(JSON.stringify({id:1,method:'Runtime.evaluate',params:{expression:'({url:location.href,marker:window.name})',returnByValue:true}}));});
 }finally{ws.close();}
}
export async function selectExistingJinshaTarget(targets,{probe=readMarker,context}={}){
 const pages=targets.filter(p=>p.type==='page'&&String(p.url||'').startsWith(ORIGIN));
 if(pages.length===1)return pages[0];
 if(pages.length===0)throw Error('jinsha-page-count:0');
 let authority=context;
 if(!authority){
  const state=JSON.parse(await fs.readFile(STATE,'utf8'));
  if(state.profile!=='jinsha-business'||state.port!==9232||!Number.isInteger(state.pid)||state.pid<=1)throw Error('jinsha-owner-profile-mismatch');
  process.kill(state.pid,0);
  const started=await exec('/bin/ps',['-p',String(state.pid),'-o','lstart=']);
  authority={pid:state.pid,startedAt:Date.parse(started.stdout.trim()),proofs:await readProofs(state.pid)};
 }
 const descriptors=[];
 for(const page of pages)descriptors.push({...page,marker:await probe(page)});
 return ownedTargetDecision(descriptors,authority.proofs,authority.pid,authority.startedAt);
}
export async function assertSelectedJinshaTarget(cdp,target){
 if(!target.jinshaOwnerMarker)return;
 const current=await cdp.eval('({url:location.href,marker:window.name})');
 if(current.url!==target.url||current.marker!==target.jinshaOwnerMarker)throw Error('jinsha-owned-page-binding-changed');
}
