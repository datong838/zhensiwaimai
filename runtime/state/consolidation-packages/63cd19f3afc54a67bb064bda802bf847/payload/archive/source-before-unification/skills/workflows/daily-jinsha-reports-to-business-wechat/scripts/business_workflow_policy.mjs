import { businessPath } from '../../../../runtime/business_storage.mjs';
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const SCRIPT_DIR=path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR=path.dirname(SCRIPT_DIR);
const PROJECT_ROOT=path.resolve(SKILL_DIR,'../../..');
const FROZEN_CORE=path.resolve(SKILL_DIR,'../../.daily-jinsha-reports-core');

const POLICY_VERSION='jinsha-business-code-enforced-v1';
const INTERNAL_INVOCATION='business-workflow-executor-v1';
const FIXED={
  jinshaChannel:'browser',profile:'jinsha-business',port:9232,urlPrefix:'https://data.guoshuyufen.com/',
  wechatChannel:'desktop',group:'上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰',authorization:'zhensi-business-main-wechat-shanghai-zhensi-operations-ding-fandang-daily-v2-reauthorized-20260917',
  python:'/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python',
  runsRoot:path.join(PROJECT_ROOT,'.local/runs/jinsha-business-production'),
  outputRoot:businessPath('jinsha-reports'),
};
const PLATFORMS=['meituan','taobao'];
const ALLOWED_CONFIG_KEYS=new Set(['runId','businessDate','jinshaChannel','wechatChannel','group','authorization','raw','downloadUiReceipt','downloadReceipt','buildReceipt','preflightReceipt','sendReceipt','verifyReceipt','examReceipt','workflowState','workflowSummary','outputDir','sendNames','python','resumeDownload']);
const PHASE_ORDER=['created','downloaded','prepared','sent','verified','complete'];
const FROZEN_HASHES={
  'BASELINE.md':'a3c1442e6ec71446a731baf5645bb0321e43c1ab503ff80afeb7dd62b8bb8780',
  'agents/openai.yaml':'33b44794079ef3b9ebfc1cbd749879c7ea9b00d8ec33e339ac3890ab9d6757fa',
  'references/workflow-contract.md':'97cb90490acf5793a291189af37ae2b2598909c5bf5846620bab353f4acc645c',
  'references/20260905-第13轮稳定性维护与整链复验方案.md':'6de04c7d56975c87746005de86c0875ce86a6311cef05618936a9a1d23ded004',
  // 2026-09-29「我授权 你修改到能确实 验收通过」：`zhensi_waimai` →
  // `zhensi_waimai_back` 路径迁移把本文件内 3 行收据绝对路径重写了，字节变了；
  // 与冻结副本 diff 逐行核对确认唯一的差异就是那 3 行路径，正文无语义变化，
  // 故同步引脚到迁移后字节（其余 17 个引脚不动，仍然只认精确字节）。
  'references/20260905-第13至14轮稳定性维护与复验.md':'0dffb5442541ce7a403593dbfc95a8863e5a7e6593cbd49a8f87290fb9c9f3b8',
  'references/20260905-第14轮正式封板方案.md':'c0cac087b3bfbd9accd421ea9d32436a9b636206e78e122d995e384f3a6e066e',
  'scripts/package.json':'3ca9d4afd21425087cf31893b8f9f63c81b0b8408db5e343ca76e5f8aa26ab9a',
  'scripts/jinsha_cua_exam.js':'3508be5e38618e226c176baed54283541ced64cbf7f31601431bef3c4ac1ab1a',
  'scripts/download_receipt_contract.mjs':'359f9cd65f3858cdf9c8181b9c54a90ea67106414cf9bd1af5fb495d59079721',
  'scripts/exam_pipeline.mjs':'13527807aef389b9522ea859a5faa0983a71f60a362a17c8b460b6304ac454ff',
  'scripts/build_reports.mjs':'73c81f118e9d215a3999f15abca64b4fbf848cc6d0e74beeeeb0cb857c84a4e3',
  'scripts/wechat_file_sender.py':'1ad3219fef2b78aa0c8c15c0bc6481a7c857ce57609c0421f3cae938e63fc530',
  'scripts/resume_flow.py':'97e34b4dcaf9a3a7e3c0fe7f2bbfe913cd797fa7ea2b9cb242c4c321cc8e5f14',
  'scripts/test_jinsha_cua_exam.mjs':'a3694a2bf4cf9857ee8adfa937f4cde0361bbf05365e15afe4b1fafa0aa3278e',
  'scripts/test_download_receipt_contract.mjs':'e970aa3e8ca4d180ac6c579319b129d0c1832651da38c2c8605ea8c031657244',
  'scripts/test_wechat_file_sender.py':'a389252568dfdd4c11c665f2e6d6deb3cc35aec8dfa5c180152a67d5bbaf241f',
  'scripts/test_resume_flow.py':'ead45e6439349fc392f98c14085305180c7f4da64a5efc524919a1f18b6725ae',
  'scripts/test_saved_reports.mjs':'931d25ddebfa09c91c337b430b6788e7236a6ea4525e86dbcfeeb17882e49e40',
};

function sha256Buffer(value){return crypto.createHash('sha256').update(value).digest('hex');}
function shanghaiDateParts(now=new Date()){return Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now).map(part=>[part.type,part.value]));}
function productionDay(now=new Date()){const p=shanghaiDateParts(now);return `${p.year}${p.month}${p.day}`;}
function previousBusinessDate(day){if(!/^\d{8}$/.test(day))throw Error('production-day-invalid');const date=new Date(`${day.slice(0,4)}-${day.slice(4,6)}-${day.slice(6)}T00:00:00+08:00`);date.setUTCDate(date.getUTCDate()-1);return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(date);}
function exactObjectKeys(value,allowed=ALLOWED_CONFIG_KEYS){for(const key of Object.keys(value))if(!allowed.has(key))throw Error(`production-config-key-forbidden:${key}`);}
function assertExact(actual,expected,reason){if(actual!==expected)throw Error(reason);}

function buildProductionConfig({runDir,runId,businessDate,outputDir}){
  const suffix=runId.match(/-(\d{2})$/)?.[1];if(!suffix)throw Error('production-run-id-invalid');
  return {
    runId,businessDate,jinshaChannel:FIXED.jinshaChannel,wechatChannel:FIXED.wechatChannel,group:FIXED.group,authorization:FIXED.authorization,
    raw:{
      meituan:path.join(runDir,`美团原始数据_${businessDate}_production${suffix}.xlsx`),
      taobao:path.join(runDir,`淘宝闪购原始数据_${businessDate}_production${suffix}.xlsx`),
    },
    downloadUiReceipt:path.join(runDir,'download-ui.json'),downloadReceipt:path.join(runDir,'download-receipt.json'),
    buildReceipt:path.join(runDir,'build-receipt.json'),preflightReceipt:path.join(runDir,'send-preflight.json'),
    sendReceipt:path.join(runDir,'send-receipt.json'),verifyReceipt:path.join(runDir,'send-verify-receipt.json'),
    examReceipt:path.join(runDir,'exam-receipt.json'),workflowState:path.join(runDir,'workflow-state.json'),workflowSummary:path.join(runDir,'workflow-summary.json'),outputDir,
    sendNames:{meituan:`美团外卖日报_${businessDate}.xlsx`,taobao:`淘宝闪购日报_${businessDate}.xlsx`},python:FIXED.python,
  };
}

function assertProductionConfig(config,configPath){
  if(!config||typeof config!=='object'||Array.isArray(config))throw Error('production-config-invalid');
  exactObjectKeys(config);
  const match=String(config.runId||'').match(/^jinsha-business-production-(\d{8})-(\d{2})$/);if(!match)throw Error('production-run-id-invalid');
  const [,day,suffix]=match;const runDir=path.join(FIXED.runsRoot,day,suffix);const outputDir=path.join(FIXED.outputRoot,`${previousBusinessDate(day)}-业务发布-production${suffix}`);
  assertExact(path.resolve(configPath),path.join(runDir,'config.json'),'production-config-path-mismatch');
  const expected=buildProductionConfig({runDir,runId:config.runId,businessDate:previousBusinessDate(day),outputDir});
  for(const key of ['businessDate','jinshaChannel','wechatChannel','group','authorization','downloadUiReceipt','downloadReceipt','buildReceipt','preflightReceipt','sendReceipt','verifyReceipt','examReceipt','workflowState','workflowSummary','outputDir','python'])assertExact(config[key],expected[key],`production-config-mismatch:${key}`);
  for(const platform of PLATFORMS){assertExact(config.raw?.[platform],expected.raw[platform],`production-raw-path-mismatch:${platform}`);assertExact(config.sendNames?.[platform],expected.sendNames[platform],`production-send-name-mismatch:${platform}`);}
  if(config.resumeDownload!==undefined&&config.resumeDownload!==true)throw Error('production-resume-flag-invalid');
  return {day,suffix,runDir,outputDir};
}

async function assertFrozenCoreHashes(readFile=fs.readFile){for(const [relative,expected] of Object.entries(FROZEN_HASHES)){const actual=sha256Buffer(await readFile(path.join(FROZEN_CORE,relative)));if(actual!==expected)throw Error(`frozen-core-hash-mismatch:${relative}`);}return {ok:true,count:Object.keys(FROZEN_HASHES).length};}
function assertInternalInvocation(env=process.env){if(env.JINSHA_WORKFLOW_INTERNAL!==INTERNAL_INVOCATION)throw Error('direct-stage-invocation-forbidden');}
function nextStage(phase){const index=PHASE_ORDER.indexOf(phase);if(index<0)throw Error(`workflow-phase-invalid:${phase}`);return index===PHASE_ORDER.length-1?null:PHASE_ORDER[index+1];}
function assertTransition(from,to){if(nextStage(from)!==to)throw Error(`workflow-transition-forbidden:${from}:${to}`);return true;}
function assertStagePermission(phase,mode){const allowed={'--download':['created'],'--prepare':['downloaded'],'--send':['prepared'],'--verify-only':['prepared','sent']};if(!allowed[mode]?.includes(phase))throw Error(`workflow-stage-forbidden:${phase}:${mode}`);return true;}
function classifyDownloadRecovery(receipt={}){const clicks=receipt.clicks||{},files=receipt.files||{};if(receipt.ok===true&&clicks.meituan===1&&clicks.taobao===1&&files.meituan&&files.taobao)return 'downloaded';if((clicks.meituan||0)===0&&(clicks.taobao||0)===0&&!files.meituan&&!files.taobao)return 'retry-download';if(clicks.meituan===1&&(clicks.taobao||0)===0&&files.meituan&&!files.taobao)return 'resume-taobao';return 'blocked-unknown-download';}
function classifyDesktopRecovery({markerExists=false,markerVerified=false}={}){if(markerVerified)return 'verify-only';if(markerExists)return 'verify-only';return 'retry-send';}
function desktopAttemptIdentity(group,items){return sha256Buffer(`${group}\n${items.map(item=>item.sha256).join('\n')}`);}

export {SCRIPT_DIR,SKILL_DIR,PROJECT_ROOT,FROZEN_CORE,POLICY_VERSION,INTERNAL_INVOCATION,FIXED,PLATFORMS,PHASE_ORDER,FROZEN_HASHES,productionDay,previousBusinessDate,buildProductionConfig,assertProductionConfig,assertFrozenCoreHashes,assertInternalInvocation,nextStage,assertTransition,assertStagePermission,classifyDownloadRecovery,classifyDesktopRecovery,desktopAttemptIdentity,sha256Buffer};
