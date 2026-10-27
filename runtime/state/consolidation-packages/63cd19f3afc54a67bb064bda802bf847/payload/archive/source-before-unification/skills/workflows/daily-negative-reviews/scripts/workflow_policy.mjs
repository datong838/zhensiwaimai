import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const SCRIPT_DIR=path.dirname(fileURLToPath(import.meta.url));
const SKILL_DIR=path.dirname(SCRIPT_DIR);
const PROJECT_ROOT=path.resolve(SKILL_DIR,'../../..');
const WORKSPACE_ROOT=path.dirname(PROJECT_ROOT);
const POLICY_VERSION='daily-negative-reviews-code-enforced-v1';
const INTERNAL_INVOCATION='daily-negative-reviews-workflow-executor-v1';
const PHASES=['created','browser_validated','downloaded','reconciled','report_built','sent','screenshot','complete'];
const FIELDS=['店铺名称','总分','评价日期','店铺类型','差评内容','点踩商品','评论订单详情'];
const PLATFORMS=[['美团外卖','1'],['淘宝闪购','2'],['京东外卖','4']];
const FIXED={
  cdp:'http://127.0.0.1:9232',origin:'https://data.guoshuyufen.com',negativeUrl:'https://data.guoshuyufen.com/#/negativeAnalyse',homeUrl:'https://data.guoshuyufen.com/#/businessData/realTimeData',
  themeMode:'taoBaoShanGou',businessMarkers:['智能斗金','推广魔方','全站推广列表'],
  group:'上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰',groupSearch:'上海臻肆外卖运营-盯个盯',
  authorization:'zhensi-negative-review-main-wechat-shanghai-zhensi-operations-ding-fandang-v1-user-20260918',
  analysisPython:'/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3',
  wechatPython:'/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python',
  node:'/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node',
  wechatBridge:path.join(PROJECT_ROOT,'skills/wechat-messaging/scripts/workflow_bridge_windows.py'),
  runsRoot:path.join(PROJECT_ROOT,'.local/runs/daily-negative-reviews'),
  sendLedger:path.join(PROJECT_ROOT,'.local/state/negative-review-send-shanghai-zhensi-operations-ding-fandang-v1.desktop-attempts'),
  summaryAuthorization:'zhensi-negative-review-summary-main-wechat-shanghai-zhensi-operations-ding-fandang-v1-user-20261022',
  summaryLedger:path.join(PROJECT_ROOT,'.local/state/negative-review-summary-send-shanghai-zhensi-operations-ding-fandang-v1.desktop-attempts'),
  outputsRoot:path.join(PROJECT_ROOT,'outputs'),
};

function sha256(value){return crypto.createHash('sha256').update(value).digest('hex');}
async function fileIdentity(file){const data=await fs.readFile(file);return {path:path.resolve(file),name:path.basename(file),size:data.length,sha256:sha256(data)};}
async function assertDependencyHashes(){const manifest=JSON.parse(await fs.readFile(path.join(SKILL_DIR,'dependencies.json'),'utf8'));for(const [file,expected] of Object.entries(manifest.files||{})){const resolved=path.isAbsolute(file)?file:path.join(SKILL_DIR,file);const actual=sha256(await fs.readFile(resolved));if(actual!==expected)throw Error(`dependency-hash-mismatch:${file}`);}return {ok:true,count:Object.keys(manifest.files||{}).length};}
async function dependencyManifestDigest(){return sha256(await fs.readFile(path.join(SKILL_DIR,'dependencies.json')));}
async function releasePolicy(){return JSON.parse(await fs.readFile(path.join(SKILL_DIR,'runtime-policy.json'),'utf8'));}
async function assertReleasePolicy(config){const policy=await releasePolicy();const digest=await dependencyManifestDigest();if(policy.authorizationRef!==FIXED.authorization)throw Error('release-authorization-mismatch');if(policy.status==='SEALED'){if(policy.dependencyDigest!==digest)throw Error('sealed-dependency-digest-mismatch');return policy;}if(policy.status==='UNSEALED_ACCEPTANCE'){if(policy.candidateDependencyDigest!==digest)throw Error('acceptance-dependency-digest-mismatch');if(policy.allowedBusinessDate!==config.businessDate)throw Error('acceptance-business-date-mismatch');return policy;}throw Error('workflow-release-blocked');}
async function sealAcceptance(config,summary){const policy=await releasePolicy();if(policy.status!=='UNSEALED_ACCEPTANCE')return policy;const sealed={schemaVersion:1,status:'SEALED',authorizationRef:FIXED.authorization,dependencyDigest:await dependencyManifestDigest(),acceptedBusinessDate:config.businessDate,acceptedAt:new Date().toISOString(),acceptedSummary:config.summary,acceptedReportSha256:summary.report?.sha256||null};const file=path.join(SKILL_DIR,'runtime-policy.json'),temp=file+'.tmp';await fs.writeFile(temp,JSON.stringify(sealed,null,2),{mode:0o600});await fs.rename(temp,file);return sealed;}
function shanghaiDay(now=new Date()){return new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(now);}
function previousBusinessDate(today){if(!/^\d{4}-\d{2}-\d{2}$/.test(today))throw Error('production-day-invalid');const date=new Date(`${today}T00:00:00+08:00`);date.setUTCDate(date.getUTCDate()-1);return shanghaiDay(date);}
function nextPhase(phase){const index=PHASES.indexOf(phase);if(index<0)throw Error(`phase-invalid:${phase}`);return index===PHASES.length-1?null:PHASES[index+1];}
function assertTransition(from,to){if(nextPhase(from)!==to)throw Error(`phase-transition-forbidden:${from}:${to}`);return true;}
function buildConfig(now=new Date()){
  const runDay=shanghaiDay(now),businessDate=previousBusinessDate(runDay),compact=businessDate.replaceAll('-','');
  const runDir=path.join(FIXED.runsRoot,compact),outputDir=path.join(FIXED.outputsRoot,`yesterday-negative-${compact}`);
  const reportName=`差评分析数据_${businessDate}_${businessDate}.xlsx`;
  const screenshotName=`差评分析长图_${businessDate}_${businessDate}.jpg`;
  return {policyVersion:POLICY_VERSION,runDay,businessDate,runDir,outputDir,config:path.join(runDir,'config.json'),
    raw:path.join(runDir,'raw',reportName),browserReceipt:path.join(runDir,'browser-receipt.json'),uiStatus:path.join(runDir,'ui-status.json'),
    finalData:path.join(runDir,'final-data.json'),analysis:path.join(runDir,'analysis.json'),report:path.join(outputDir,reportName),reportValidation:path.join(runDir,'report-validation.json'),
    sendOutput:path.join(runDir,'wechat-send'),sendReceipt:path.join(runDir,'wechat-send','receipt.json'),state:path.join(runDir,'workflow-state.json'),summary:path.join(runDir,'workflow-summary.json'),
    screenshot:path.join(outputDir,screenshotName),screenshotReceipt:path.join(runDir,'screenshot-receipt.json'),
    screenshotSendOutput:path.join(runDir,'wechat-screenshot-send'),screenshotSendReceipt:path.join(runDir,'wechat-screenshot-send','receipt.json'),
    sendMarker:`negative-review-${businessDate}.json`,screenshotSendMarker:`negative-review-summary-${businessDate}.json`};
}
function buildCorrectionConfig(base){const reportName=`差评分析数据_${base.businessDate}_${base.businessDate}_更正.xlsx`;return {...base,config:path.join(base.runDir,'correction-config.json'),finalData:path.join(base.runDir,'correction-final-data.json'),analysis:path.join(base.runDir,'correction-analysis.json'),report:path.join(base.outputDir,reportName),reportValidation:path.join(base.runDir,'correction-report-validation.json'),sendOutput:path.join(base.runDir,'wechat-correction-send'),sendReceipt:path.join(base.runDir,'wechat-correction-send','receipt.json'),sendMarker:`negative-review-${base.businessDate}-correction-v1.json`,correctionOf:base.sendMarker};}
function assertConfig(config,now=new Date()){
  const base=buildConfig(now),expected=config?.correctionOf?buildCorrectionConfig(base):base;const keys=Object.keys(expected);
  if(!config||Object.keys(config).length!==keys.length||keys.some(key=>config[key]!==expected[key]))throw Error('production-config-mismatch');
  return true;
}
function assertInternal(env=process.env){if(env.NEGATIVE_REVIEW_INTERNAL!==INTERNAL_INVOCATION)throw Error('direct-stage-invocation-forbidden');}
function completionReview(state){
  const grouped=new Map();for(const row of state.reviewItems||[]){const item=grouped.get(row.stage)||{stage:row.stage,label:row.label,attempts:0,elapsedMs:0,status:row.status,pitfalls:[]};item.attempts+=row.attempts||1;item.elapsedMs+=row.elapsedMs||0;item.status=row.status;item.pitfalls.push(...(row.pitfalls||[]));grouped.set(row.stage,item);}
  const reviewItems=[...grouped.values()].map((item,index)=>({item:index+1,...item}));
  return {codeEnforced:true,totalElapsedMs:reviewItems.reduce((sum,item)=>sum+item.elapsedMs,0),reviewItems,pitfalls:reviewItems.flatMap(item=>item.pitfalls)};
}
function unattendedRecovery(state,stage){const priorFailures=(state.reviewItems||[]).filter(item=>item.stage===stage&&item.status==='failed').length;return {allowed:true,stage,priorFailures,nextAttempt:priorFailures+1};}

export {SCRIPT_DIR,SKILL_DIR,PROJECT_ROOT,WORKSPACE_ROOT,POLICY_VERSION,INTERNAL_INVOCATION,PHASES,FIELDS,PLATFORMS,FIXED,sha256,fileIdentity,assertDependencyHashes,dependencyManifestDigest,releasePolicy,assertReleasePolicy,sealAcceptance,shanghaiDay,previousBusinessDate,nextPhase,assertTransition,buildConfig,buildCorrectionConfig,assertConfig,assertInternal,completionReview,unattendedRecovery};
