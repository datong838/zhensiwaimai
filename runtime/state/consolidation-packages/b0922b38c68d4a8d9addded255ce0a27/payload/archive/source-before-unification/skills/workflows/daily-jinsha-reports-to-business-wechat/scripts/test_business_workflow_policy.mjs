import assert from 'node:assert/strict';
import path from 'node:path';
import {
  POLICY_VERSION,INTERNAL_INVOCATION,FIXED,FROZEN_HASHES,productionDay,previousBusinessDate,buildProductionConfig,
  assertProductionConfig,assertFrozenCoreHashes,assertInternalInvocation,nextStage,assertTransition,assertStagePermission,
  classifyDownloadRecovery,classifyDesktopRecovery,desktopAttemptIdentity,
} from './business_workflow_policy.mjs';

assert.equal(POLICY_VERSION,'jinsha-business-code-enforced-v1');
assert.equal(productionDay(new Date('2026-09-11T10:00:00+08:00')),'20260911');
assert.equal(previousBusinessDate('20260911'),'2026-09-10');
const runDir=path.join(FIXED.runsRoot,'20260911','01');
const configPath=path.join(runDir,'config.json');
const config=buildProductionConfig({runDir,runId:'jinsha-business-production-20260911-01',businessDate:'2026-09-10',outputDir:path.join(FIXED.outputRoot,'2026-09-10-业务发布-production01')});
assert.equal(assertProductionConfig(config,configPath).suffix,'01');
assert.equal(config.jinshaChannel,'browser');
assert.equal(config.wechatChannel,'desktop');
assert.equal(config.group,'上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰');
assert.equal(config.sendNames.meituan,'美团外卖日报_2026-09-10.xlsx');
assert.equal(config.sendNames.taobao,'淘宝闪购日报_2026-09-10.xlsx');
for(const [key,value] of [['wechatChannel','auto'],['jinshaChannel','desktop'],['group','相似群']])assert.throws(()=>assertProductionConfig({...config,[key]:value},configPath),/production-config-mismatch/);
assert.throws(()=>assertProductionConfig({...config,sender:'/tmp/custom.py'},configPath),/production-config-key-forbidden:sender/);
assert.throws(()=>assertProductionConfig({...config,sendNames:{...config.sendNames,meituan:'日报.xlsx'}},configPath),/production-send-name-mismatch/);
assert.throws(()=>assertProductionConfig({...config,raw:{...config.raw,taobao:'/tmp/a.xlsx'}},configPath),/production-raw-path-mismatch/);
assert.throws(()=>assertProductionConfig({...config,resumeDownload:false},configPath),/production-resume-flag-invalid/);
assert.equal(nextStage('created'),'downloaded');
assert.equal(nextStage('verified'),'complete');
assert.equal(assertTransition('prepared','sent'),true);
assert.throws(()=>assertTransition('created','sent'),/workflow-transition-forbidden/);
assert.equal(assertStagePermission('created','--download'),true);
assert.equal(assertStagePermission('prepared','--verify-only'),true);
assert.throws(()=>assertStagePermission('created','--send'),/workflow-stage-forbidden/);
assert.equal(classifyDownloadRecovery({clicks:{meituan:0,taobao:0},files:{}}),'retry-download');
assert.equal(classifyDownloadRecovery({clicks:{meituan:1,taobao:0},files:{meituan:{file:'/x'}}}),'resume-taobao');
assert.equal(classifyDownloadRecovery({clicks:{meituan:1,taobao:0},files:{}}),'blocked-unknown-download');
assert.equal(classifyDownloadRecovery({ok:true,clicks:{meituan:1,taobao:1},files:{meituan:{},taobao:{}}}),'downloaded');
assert.equal(classifyDesktopRecovery({markerExists:false}),'retry-send');
assert.equal(classifyDesktopRecovery({markerExists:true}),'verify-only');
assert.equal(desktopAttemptIdentity('g',[{sha256:'a'},{sha256:'b'}]),desktopAttemptIdentity('g',[{sha256:'a'},{sha256:'b'}]));
assert.throws(()=>assertInternalInvocation({}),/direct-stage-invocation-forbidden/);
assert.doesNotThrow(()=>assertInternalInvocation({JINSHA_WORKFLOW_INTERNAL:INTERNAL_INVOCATION}));
assert.equal((await assertFrozenCoreHashes()).count,Object.keys(FROZEN_HASHES).length);
await assert.rejects(()=>assertFrozenCoreHashes(async()=>Buffer.from('drift')),/frozen-core-hash-mismatch/);
console.log(JSON.stringify({ok:true,tests:32,policyVersion:POLICY_VERSION,runtimeModelDecisions:0}));
