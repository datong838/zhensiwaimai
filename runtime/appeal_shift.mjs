// Afternoon orchestration only. All business effects remain in original CLIs.
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
import fs from 'node:fs/promises';
import {businessPath} from './business_storage.mjs';
const exec=promisify(execFile);
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const flows={
  taobao:{appeal:'taobao-shangou-negative-review-appeals',report:'taobao-flash-sale-negative-review-appeals',build:'build_batch_excel.mjs'},
  meituan:{appeal:'meituan-waimai-negative-review-appeals',report:'meituan-waimai-negative-review-appeals',build:'build_single_batch_excel.mjs'},
};
export function shiftPlan(platform,date=new Date()) {
  if (!Object.hasOwn(flows,platform)) throw Error('unsupported-appeal-platform');
  const parts=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(date);
  const minutes=Number(parts.find(p=>p.type==='hour').value)*60+Number(parts.find(p=>p.type==='minute').value);
  if (minutes<780 || minutes>=1140) throw Error('outside-authorized-afternoon-window');
  const slot=minutes>=1110?'18:30':minutes>=1020?'17:00':minutes>=900?'15:00':'13:00';
  const spec=flows[platform];
  const steps=[{stage:'appeal',flow:spec.appeal,script:'appeal_executor.mjs',args:['--execute']}];
  if (slot==='18:30') steps.push({stage:'build',flow:spec.report,script:spec.build,args:[]},{stage:'deliver',flow:spec.report,script:'deliver_batch.mjs',args:['--execute']});
  return {platform,slot,steps};
}
export function parseOriginalReceipt(stdout,exitCode=0) {
  const line=String(stdout||'').trim().split('\n').findLast(value=>value.startsWith('{'));
  if(!line)throw Error('missing-original-stage-receipt');
  const receipt=JSON.parse(line);
  if(!receipt||typeof receipt.ok!=='boolean')throw Error('invalid-original-stage-receipt');
  if(exitCode!==0&&receipt.ok===true)throw Error('original-stage-exit-receipt-conflict');
  return receipt;
}
async function originalCli(step) {
  const cwd=path.join(root,'skills/workflows',step.flow);
  try {
    const {stdout}=await exec(process.execPath,[path.join(cwd,'scripts',step.script),...step.args],{cwd,maxBuffer:16*1024*1024});
    return parseOriginalReceipt(stdout);
  } catch(error) {
    if(typeof error.stdout==='string'&&error.stdout.trim())return parseOriginalReceipt(error.stdout,error.code??1);
    throw error;
  }
}
export function closingReadOnlyDecision(excel,image){
  const group='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';
  if(excel?.groupName!==group||excel.payloadType!=='file'||excel.ok!==true||excel.verified!==true||excel.state!=='verified'
    ||!Number.isSafeInteger(excel.sendAttempts)||excel.sendAttempts<1||image?.groupName!==group||image.payloadType!=='image')return null;
  if(image.ok===true&&image.verified===true&&image.state==='verified'&&Number.isSafeInteger(image.sendAttempts)&&image.sendAttempts>=1)return {complete:true};
  if(['unknown','attempted'].includes(image.state)||image.sendAttempts!==0)return {complete:false};
  return null;
}
export function closingBusinessDate(date=new Date()){
  const format=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'});
  const day=format.format(date);return format.format(new Date(Date.parse(day+'T12:00:00+08:00')-86400000));
}
export async function readOriginalClosing(platform,date=new Date()){
  if(!Object.hasOwn(flows,platform))throw Error('unsupported-appeal-platform');
  const businessDate=closingBusinessDate(date);
  const prefix=platform==='meituan'?'meituan-waimai-appeals':'taobao-flash-appeals';
  const base=businessPath(platform==='meituan'?'meituan-appeals':'taobao-appeals');
  async function read(file){try{return JSON.parse(await fs.readFile(file,'utf8'));}catch(error){if(error.code==='ENOENT')return null;throw error;}}
  const excel=await read(path.join(base,'wechat-attempts',prefix+'-'+businessDate+'.json'));
  const image=await read(path.join(base,'summary-attempts',prefix+'-summary-'+businessDate+'.json'));
  const decision=closingReadOnlyDecision(excel,image);
  return decision?{...decision,businessDate}:null;
}
export async function runShift(platform,{date=new Date(),runner=originalCli,readClosing=readOriginalClosing}={}) {
  const plan=shiftPlan(platform,date),results=[];
  if(plan.slot==='18:30'){
    let prior;
    try{prior=await readClosing(platform,date);}catch(error){return {ok:false,platform,slot:plan.slot,stage:'deliver',reason:'closing-prior-evidence-unreadable:'+String(error.message||error),results,sendAttempts:0};}
    if(prior)return {ok:prior.complete,platform,slot:plan.slot,stage:'deliver',status:prior.complete?'closing-already-verified':'closing-verification-pending',
      ...(prior.complete?{}:{reason:'closing-prior-submission-readonly-reconciliation-required'}),businessDate:prior.businessDate,results,sendAttempts:0,newSendAttempts:0,runtimeModelDecisions:0};
  }
  for (const step of plan.steps) {
    let receipt;
    try { receipt=await runner(step); }
    catch(error) {return {ok:false,platform,slot:plan.slot,stage:step.stage,reason:String(error.message||error),results};}
    results.push({stage:step.stage,receipt});
    if (receipt?.ok!==true || (step.stage==='deliver' && receipt.verified!==true)) {
      return {ok:false,platform,slot:plan.slot,stage:step.stage,reason:String(receipt?.reason||receipt?.error||'original-stage-not-complete'),results};
    }
  }
  return {ok:true,platform,slot:plan.slot,status:plan.slot==='18:30'?'closing-complete':'appeal-round-complete',results,runtimeModelDecisions:0};
}
if (process.argv[1] && path.resolve(process.argv[1])===fileURLToPath(import.meta.url)) {
  const args=process.argv.slice(2);
  if (args.length!==3 || args[0]!=='--platform' || args[2]!=='--execute') {
    console.log(JSON.stringify({ok:false,reason:'usage: --platform taobao|meituan --execute'}));process.exitCode=1;
  } else {
    try {const result=await runShift(args[1]);console.log(JSON.stringify(result));if(!result.ok)process.exitCode=1;}
    catch(error){console.log(JSON.stringify({ok:false,reason:String(error.message||error)}));process.exitCode=1;}
  }
}
