import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import { acquireJinshaLease, releaseJinshaLease, runJinshaCuaExam } from './jinsha_cua_exam.js';
const config={runId:'jinsha-test-run',businessDate:'2026-09-02',names:{meituan:'mt-exam.xlsx',taobao:'tb-exam.xlsx'},metrics:{paid:[1,2],net:[3,4]}};
class App {
  constructor(mode='ok') {this.mode=mode;this.platform='taobao';this.plan='';this.open=false;this.polls=0;this.count=0;this.save=false;this.name='';this.downloads=0;this.saves=0;this.calls=0;}
  async performSecondaryAction(i,a){this.calls++;assert.equal(i,0);assert.equal(a,'Raise');}
  async getAXState(){
    this.calls++;
    const full=this.platform==='meituan'?'最终美团最新日报':'饿了么日报数据📊6.18最新最新';
    const lines=['0 标准窗口','1 HTML data.guoshuyufen.com/#/reportDownload',
      `2 单选按钮 美团外卖, Value: ${Number(this.platform==='meituan')}`,
      `3 单选按钮 淘宝闪购, Value: ${Number(this.platform==='taobao')}`,
      `4 文本栏 Value: ${this.mode==='date'?'2026-09-01':config.businessDate}, Placeholder: 开始日期`,
      `5 文本栏 Value: ${config.businessDate}, Placeholder: 结束日期`,
      `6 文本栏 ${this.plan?'Value: '+this.plan+', Placeholder: ':''}请选择下载方案`,
      `7 text 已选择 (${this.count})`, '8 按钮 下载数据'];
    if(this.open){
      this.polls++;
      if(this.mode==='stale'&&this.polls<4)lines.push('9 文本 饿了么...最新最新');
      else {lines.push('9 文本 '+(this.platform==='meituan'?full:'饿了么...最新最新'));if(this.mode==='duplicate')lines.push('10 文本 '+full);}
    }
    if(this.save)lines.push(`11 文本栏 Value: ${this.name}, ID: saveAsNameTextField`,'12 按钮 存储, ID: OKButton');
    return lines.join('\n');
  }
  async click(i){
    this.calls++;
    if(Array.isArray(i)){this.count++;return;}
    if(i===2||i===3){this.platform=i===2?'meituan':'taobao';this.plan='';this.count=0;this.open=false;this.polls=0;return;}
    if(i===6){this.open=true;return;}
    if(i===9){this.plan=this.platform==='meituan'?'最终美团最新日报':'饿了么日报数据📊6.18最新最新';this.open=false;this.count=this.platform==='meituan'?36:34;return;}
    if(i===8){this.downloads++;this.save=true;return;}
    if(i===12){this.saves++;this.save=false;return;}
    throw Error('unexpected-click:'+i);
  }
  async setValue(i,value){this.calls++;if(i===4||i===5){assert.equal(value,config.businessDate);return;}assert.equal(i,11);this.name=value;}
  async pressKey(key){this.calls++;assert.ok(['Tab','Return'].includes(key));}
}
for(const mode of ['ok','stale','duplicate','date']){
  const app=new App(mode),r=await runJinshaCuaExam(app,config);
  const expected=['ok','stale'].includes(mode);
  assert.equal(r.ok,expected,JSON.stringify(r));
  assert.equal(app.downloads,expected?2:0);
  assert.equal(app.saves,expected?2:0);
  if(expected){
    assert.equal(r.runId,config.runId);
    assert.equal(r.jinshaResourceReleased,true);
    assert.ok(Number.isFinite(r.jinshaReleasedAt));
    assert.ok(Number.isFinite(r.receiptIssuedAt));
    assert.deepEqual(Object.keys(r.files),['meituan','taobao']);
    assert.ok(r.files.meituan.downloadStartedAt<=r.files.meituan.savedAt);
    assert.ok(r.files.taobao.downloadStartedAt<=r.files.taobao.savedAt);
    assert.ok(r.files.meituan.savedAt<=r.files.taobao.savedAt);
    const releasedCalls=app.calls;
    await Promise.resolve();
    assert.equal(app.calls,releasedCalls);
  }
  if(mode==='duplicate')assert.match(r.reason,/element-not-unique/);
  if(mode==='date')assert.match(r.reason,/date-not-yesterday/);
}
await assert.rejects(runJinshaCuaExam(new App(),{businessDate:config.businessDate}),/run-id-required/);
const resumeApp=new App();
const resume=await runJinshaCuaExam(resumeApp,{...config,platforms:['taobao'],completedFiles:{meituan:{name:'mt-exam.xlsx',downloadStartedAt:Date.now()-2000,savedAt:Date.now()-1000}}});
assert.equal(resume.ok,true);
assert.deepEqual(resume.clicks,{meituan:0,taobao:1});
assert.equal(resumeApp.downloads,1);
assert.equal(resumeApp.saves,1);
assert.equal(resume.jinshaResourceReleased,true);
const incomplete=await runJinshaCuaExam(new App(),{...config,platforms:['taobao']});
assert.equal(incomplete.ok,false);
assert.match(incomplete.reason,/download-files-incomplete/);
const leasePath=path.join(await fs.mkdtemp(path.join(os.tmpdir(),'jinsha-lease-test-')),'lease');
const lease=await acquireJinshaLease('owner-a',leasePath);
await assert.rejects(acquireJinshaLease('owner-b',leasePath),/jinsha-lease-busy:owner-a/);
assert.equal(await releaseJinshaLease(lease),true);
const reacquired=await acquireJinshaLease('owner-b',leasePath);
assert.equal(await releaseJinshaLease(reacquired),true);
console.log(JSON.stringify({ok:true,tests:8,externalActions:0,cases:['full-save-flow-platform-timestamps-and-release','stale-platform-list','duplicate-option-no-download','wrong-date-no-download','run-id-required','resume-taobao-only','resume-missing-completed-file','cross-process-lease']}));
