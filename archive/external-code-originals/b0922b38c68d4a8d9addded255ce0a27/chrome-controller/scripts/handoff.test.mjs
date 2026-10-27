import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {checkPhase, checkIdentity, checkListeners, withProfileLock, handoffConfig, publicUrl} from './session_guard.mjs';
import {classifyJinsha, classifyMeituan, requireUnique, canRelease, inViewport, shouldOpenJinshaContextMenu} from './handoff.mjs';

test('manual confirmation gates every connection and binds the instance',()=>{
 const s={mode:'visible-handoff',phase:'MANUAL_LOGIN',instanceId:'new'};
 for(const action of ['probe','open','inspect','close','takeover','release-login-window'])assert.throws(()=>checkPhase(s,{instance:'new'},action));
 assert.throws(()=>checkPhase({...s,phase:'USER_CONFIRMED'},{instance:'old'},'takeover'),/instance/);
 assert.doesNotThrow(()=>checkPhase({...s,phase:'USER_CONFIRMED'},{instance:'new'},'takeover'));
 for(const phase of ['BLOCKED','CLOSING','VERIFYING'])assert.throws(()=>checkPhase({...s,phase},{instance:'new'},'takeover'));
 assert.throws(()=>checkPhase({mode:'visible'},{},'takeover'),/legacy-visible/);
});
test('PID reuse and profile-prefix collisions fail identity checks',()=>{
 const p={profile:'/tmp/profile'};const s={pid:123,processStartedAt:'A',mode:'headless',port:9233};
 const cmd='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --user-data-dir=/tmp/profile --remote-debugging-port=9233 --headless=new';
 assert.doesNotThrow(()=>checkIdentity(p,s,{cmd,start:'A'}));
 assert.throws(()=>checkIdentity(p,s,{cmd,start:'B'}),/identity/);
 assert.throws(()=>checkIdentity(p,s,{cmd:cmd.replace('/tmp/profile ','/tmp/profile-other '),start:'A'}),/identity/);
});
test('only owned loopback listener is accepted',()=>{
 assert.doesNotThrow(()=>checkListeners('p123\nn127.0.0.1:9233\n',123,9233));
 for(const x of ['p124\nn127.0.0.1:9233\n','p123\nn*:9233\n','p123\nn127.0.0.1:9233\np124\nn[::1]:9233\n',''])assert.throws(()=>checkListeners(x,123,9233));
});
test('production profile and port are fixed; fixture mode is temporary only',()=>{
 assert.equal(handoffConfig({profile:'meituan-merchant',port:'9233'}).prefix,'https://waimaie.meituan.com/');
 assert.deepEqual(handoffConfig({profile:'jinsha-business',port:'9232'}),{
  site:'jinsha',prefix:'https://data.guoshuyufen.com/',url:'https://data.guoshuyufen.com/#/businessData/realTimeData',port:9232
 });
 assert.throws(()=>handoffConfig({profile:'meituan-merchant',port:'9232'}));
 assert.throws(()=>handoffConfig({profile:'jinsha-business',port:'9233'}));
 assert.throws(()=>handoffConfig({profile:'meituan-merchant',port:'9233','test-url':'http://127.0.0.1:1234/'}));
 assert.throws(()=>handoffConfig({profile:'test-x',port:'19441','profile-root':'/tmp/a','test-url':'https://example.com/'}));
});
test('Jinsha authentication uses route and independent business structures',()=>{
 const body='数据中心 实时数据 评价&AI申述 差评列表 活动监控 菜品监控 排行中心';
 assert.equal(classifyJinsha(body,{title:'臻肆外卖运营',url:'https://data.guoshuyufen.com/#/businessData/realTimeData'}).authenticated,true);
 assert.equal(classifyJinsha(body,{title:'金鲨数据',url:'https://data.guoshuyufen.com/#/negativeAnalyse'}).authenticated,true);
 assert.equal(classifyJinsha('数据中心 实时数据',{title:'金鲨数据',url:'https://data.guoshuyufen.com/#/businessData/realTimeData'}).authenticated,false);
 assert.equal(classifyJinsha(body,{title:'金鲨数据',url:'https://data.guoshuyufen.com/#/login'}).reason,'LOGIN_REQUIRED');
 assert.equal(classifyJinsha(body+' 滑动验证',{title:'金鲨数据',url:'https://data.guoshuyufen.com/#/businessData/realTimeData'}).reason,'SECURITY_CHALLENGE');
 assert.equal(classifyJinsha('',{title:'金鲨数据',url:'https://data.guoshuyufen.com/#/businessData/realTimeData'}).reason,'PAGE_NOT_READY');
 const current='总览 营业 顾客 推广魔方 辅助驾驶 店铺列表 今日实时数据';
 assert.equal(classifyJinsha(current,{title:'臻肆外卖运营',url:'https://data.guoshuyufen.com/#/businessData/realTimeData'}).authenticated,true);
 const warning=classifyJinsha(current+' 授权失败',{title:'臻肆外卖运营',url:'https://data.guoshuyufen.com/#/businessData/realTimeData'});
 assert.equal(warning.authenticated,true);assert.equal(warning.reason,'AUTHENTICATED');assert.deepEqual(warning.contextMarkers,['授权失败']);
});
test('blank and login pages cannot be marked authenticated',()=>{
 assert.equal(classifyMeituan('').reason,'PAGE_NOT_READY');
 assert.equal(classifyMeituan('商家中心 全部门店 今日有效订单 今日预计收入').authenticated,true);
 assert.equal(classifyMeituan('商家中心 全部门店 全部订单 订单状态 有订单配送异常').authenticated,true);
 assert.equal(classifyMeituan('商家中心 全部门店 全部订单 订单状态 安全验证').reason,'SECURITY_CHALLENGE');
 assert.equal(classifyMeituan('商家中心 全部门店 全部订单 订单状态 扫码登录').reason,'LOGIN_REQUIRED');
 assert.equal(classifyMeituan('商家首页 今日营业概况 数据中心').authenticated,false);
});
test('target ambiguity and unsafe window closure fail closed',()=>{
 assert.throws(()=>requireUnique([]),/TARGET_AMBIGUOUS/);assert.throws(()=>requireUnique([1,2]),/TARGET_AMBIGUOUS/);
 assert.equal(requireUnique([3]),3);
 assert.throws(()=>canRelease({phase:'TAKEOVER_VERIFIED'},1,1,[1]));
 assert.throws(()=>canRelease({phase:'TAKEOVER_VERIFIED'},1,2,[1,3]));
 assert.doesNotThrow(()=>canRelease({phase:'TAKEOVER_VERIFIED'},1,2,[1]));
});
test('profile operations are exclusive and errors release the lock',async()=>{
 const meta=await fs.mkdtemp(path.join(os.tmpdir(),'handoff-lock-'));const p={meta};
 try{await withProfileLock(p,async()=>{await assert.rejects(withProfileLock(p,async()=>{}),/profile-operation-busy/);});
 await assert.rejects(withProfileLock(p,async()=>{throw Error('test');}),/test/);
 await withProfileLock(p,async()=>{});}finally{await fs.rm(meta,{recursive:true,force:true});}
});
test('receipts redact query and fragment',()=>assert.equal(publicUrl('https://waimaie.meituan.com/?secret=x#secret=y'),'https://waimaie.meituan.com/'));

test('ambiguity recovery requires the confirmed instance and runs once',()=>{
 const s={mode:'visible-handoff',phase:'BLOCKED',failure:'TARGET_AMBIGUOUS',instanceId:'new',confirmationInstance:'new'};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'recover-target'));
 for(const patch of [{failure:'LOGIN_REQUIRED'},{recoveryAttempted:true},{confirmationInstance:'old'},{phase:'MANUAL_LOGIN'}])assert.throws(()=>checkPhase({...s,...patch},{instance:'new'},'recover-target'));
});
test('legacy structure failure without a bound target permits one diagnostic recovery',()=>{
 const s={mode:'visible-handoff',phase:'BLOCKED',failure:'STRUCTURE_UNVERIFIED',instanceId:'new',confirmationInstance:'new'};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'recover-target'));
 assert.throws(()=>checkPhase({...s,recoveryAttempted:true},{instance:'new'},'recover-target'));
 assert.throws(()=>checkPhase({...s,loginTargetId:'bound',loginMarker:'marker'},{instance:'new'},'recover-target'));
});

test('failed-target diagnosis stays bound and work-page verification is bounded',()=>{
 const s={mode:'visible-handoff',phase:'BLOCKED',failure:'STRUCTURE_UNVERIFIED',instanceId:'new',confirmationInstance:'new',activeTargetId:'target',activeMarker:'marker'};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'diagnose-target'));
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'verify-work-page'));
 assert.throws(()=>checkPhase({...s,workVerifyAttempts:2},{instance:'new'},'verify-work-page'),/limit/);
 for(const failure of ['SECURITY_CHALLENGE','LOGIN_REQUIRED'])assert.throws(()=>checkPhase({...s,failure},{instance:'new'},'verify-work-page'));
});
test('Jinsha context failures remain diagnosable without reopening repair budget',()=>{
 const observation={authenticated:false,reason:'STRUCTURE_UNVERIFIED',title:'臻肆外卖运营',url:'https://data.guoshuyufen.com/',markers:['总览','营业','顾客','辅助驾驶','店铺列表','今日实时数据'],loginMarkers:[],securityMarkers:[]};
 const s={mode:'visible-handoff',site:'jinsha',phase:'BLOCKED',failure:'CONTEXT_WAIMAI_NOT_UNIQUE',instanceId:'new',confirmationInstance:'new',loginTargetId:'target',loginMarker:'marker',contextRepairAttempts:2,lastDiagnosticObservation:observation};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'diagnose-target'));
 assert.throws(()=>checkPhase(s,{instance:'new'},'verify-work-page'));
 assert.throws(()=>checkPhase({...s,lastDiagnosticObservation:{...observation,securityMarkers:['安全验证']}},{instance:'new'},'diagnose-target'));
});
test('an authenticated Jinsha context diagnosis permits one read-only post-repair verification',()=>{
 const observation={authenticated:true,reason:'AUTHENTICATED',title:'臻肆外卖运营',url:'https://data.guoshuyufen.com/',markers:['数据中心','实时数据','活动监控'],loginMarkers:[],securityMarkers:[],contextMarkers:['授权失败']};
 const s={mode:'visible-handoff',site:'jinsha',phase:'BLOCKED',failure:'CONTEXT_WAIMAI_NOT_UNIQUE',instanceId:'new',confirmationInstance:'new',loginTargetId:'target',loginMarker:'marker',contextRepairAttempts:2,workVerifyAttempts:2,lastDiagnosticObservation:observation};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'verify-work-page'));
 assert.throws(()=>checkPhase({...s,contextPostVerifyAttempts:1},{instance:'new'},'verify-work-page'));
 assert.throws(()=>checkPhase({...s,lastDiagnosticObservation:{...observation,authenticated:false,reason:'STRUCTURE_UNVERIFIED'}},{instance:'new'},'verify-work-page'));
});
test('pre-close handoff failure permits diagnosis only for a fully bound work target',()=>{
 const s={mode:'visible-handoff',site:'jinsha',phase:'BLOCKED',failure:'HANDOFF_OPERATION_FAILED',instanceId:'new',confirmationInstance:'new',loginTargetId:'login',loginMarker:'login-marker',taskTargetId:'work',taskMarker:'work-marker'};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'diagnose-target'));
 for(const patch of [{taskTargetId:null},{taskMarker:null},{loginTargetId:null},{loginMarker:null},{phase:'CLOSE_OUTCOME_UNKNOWN'}])assert.throws(()=>checkPhase({...s,...patch},{instance:'new'},'diagnose-target'));
});
test('a verified pre-close work target permits one exact release resume',()=>{
 const observation={authenticated:true,reason:'AUTHENTICATED',title:'臻肆外卖运营',url:'https://data.guoshuyufen.com/',loginMarkers:[],securityMarkers:[]};
 const s={mode:'visible-handoff',site:'jinsha',phase:'BLOCKED',failure:'HANDOFF_OPERATION_FAILED',instanceId:'new',confirmationInstance:'new',loginTargetId:'login',loginMarker:'login-marker',taskTargetId:'work',taskMarker:'work-marker',lastReleaseTargetDiagnosticObservation:observation};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'release-login-window'));
 for(const patch of [{releaseResumeAttempts:1},{taskTargetId:null},{taskMarker:null},{lastReleaseTargetDiagnosticObservation:{...observation,authenticated:false}},{phase:'CLOSE_OUTCOME_UNKNOWN'}])assert.throws(()=>checkPhase({...s,...patch},{instance:'new'},'release-login-window'));
});
test('a known pre-close phase mismatch permits one diagnosed correction without another target',()=>{
 const observation={authenticated:true,reason:'AUTHENTICATED',title:'臻肆外卖运营',url:'https://data.guoshuyufen.com/',loginMarkers:[],securityMarkers:[]};
 const s={mode:'visible-handoff',site:'jinsha',phase:'BLOCKED',failure:'WINDOW_RELEASE_UNSAFE',instanceId:'new',confirmationInstance:'new',loginTargetId:'login',loginMarker:'login-marker',taskTargetId:'work',taskMarker:'work-marker',releaseResumeAttempts:1,lastReleaseTargetDiagnosticObservation:observation};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'diagnose-target'));
 assert.throws(()=>checkPhase(s,{instance:'new'},'release-login-window'));
 assert.doesNotThrow(()=>checkPhase({...s,releaseCorrectionReady:true},{instance:'new'},'release-login-window'));
 assert.throws(()=>checkPhase({...s,releaseCorrectionReady:true,releaseCorrectionAttempts:1},{instance:'new'},'release-login-window'));
});
test('an internal reconnect self-rejection permits one final diagnosed resume',()=>{
 const observation={authenticated:true,reason:'AUTHENTICATED',title:'臻肆外卖运营',url:'https://data.guoshuyufen.com/',loginMarkers:[],securityMarkers:[]};
 const s={mode:'visible-handoff',site:'jinsha',phase:'BLOCKED',failure:'handoff-release-resume-forbidden',instanceId:'new',confirmationInstance:'new',loginTargetId:'login',loginMarker:'login-marker',taskTargetId:'work',taskMarker:'work-marker',releaseResumeAttempts:1,releaseCorrectionAttempts:1,lastReleaseTargetDiagnosticObservation:observation};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'diagnose-target'));
 assert.throws(()=>checkPhase(s,{instance:'new'},'release-login-window'));
 assert.doesNotThrow(()=>checkPhase({...s,releaseInternalReady:true},{instance:'new'},'release-login-window'));
 assert.throws(()=>checkPhase({...s,releaseInternalReady:true,releaseInternalCorrectionAttempts:1},{instance:'new'},'release-login-window'));
});
test('a unique takeover target remains diagnosable when its first structure check fails',()=>{
 const s={mode:'visible-handoff',phase:'BLOCKED',failure:'STRUCTURE_UNVERIFIED',instanceId:'new',confirmationInstance:'new',loginTargetId:'login-target',loginMarker:'login-marker'};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'new'},'diagnose-target'));
});

test('real Meituan image branding needs title plus independent dashboard structures',()=>{
 const body='全部门店 今日有效订单 今日预计收入 巡店助手 巡检门店';
 assert.equal(classifyMeituan(body,{title:'美团外卖商家版',site:'meituan'}).authenticated,true);
 assert.equal(classifyMeituan(body,{title:'Unrelated',site:'meituan'}).authenticated,false);
 assert.equal(classifyMeituan('全部门店 今日有效订单 今日预计收入',{title:'美团外卖商家版',site:'meituan'}).authenticated,false);
 assert.equal(classifyMeituan(body+' 扫码登录',{title:'美团外卖商家版',site:'meituan'}).authenticated,false);
});

test('offscreen blank frame is not a visible foreign security surface',()=>{
 const viewport={width:1124,height:596};
 assert.equal(inViewport({x:0,y:596,width:300,height:150},viewport),false);
 assert.equal(inViewport({x:0,y:595,width:300,height:150},viewport),true);
});

test('minimization requires a verified and matching instance',()=>{
 const s={mode:'visible-handoff',phase:'TAKEOVER_VERIFIED',instanceId:'current'};
 assert.doesNotThrow(()=>checkPhase(s,{instance:'current'},'minimize-work-window'));
 for(const phase of ['MANUAL_LOGIN','USER_CONFIRMED','BLOCKED'])assert.throws(()=>checkPhase({...s,phase},{instance:'current'},'minimize-work-window'));
});
test('Jinsha context repair is limited to its bound current task',()=>{
 const base={mode:'visible-handoff',site:'jinsha',phase:'BLOCKED',failure:'CONTEXT_AUTHORIZATION_FAILED',instanceId:'current',confirmationInstance:'current',activeTargetId:'target',activeMarker:'marker'};
 assert.doesNotThrow(()=>checkPhase(base,{instance:'current'},'ensure-jinsha-context'));
 assert.doesNotThrow(()=>checkPhase({...base,failure:'SECURITY_CHALLENGE',observations:[{authenticated:true}]},{instance:'current'},'ensure-jinsha-context'));
 const partial={...base,failure:'STRUCTURE_UNVERIFIED',lastDiagnosticObservation:{authenticated:false,reason:'STRUCTURE_UNVERIFIED',title:'臻肆外卖运营',url:'https://data.guoshuyufen.com/',markers:['总览','营业','顾客','辅助驾驶','店铺列表','今日实时数据'],loginMarkers:[],securityMarkers:[]}};
 assert.doesNotThrow(()=>checkPhase(partial,{instance:'current'},'ensure-jinsha-context'));
 assert.equal(shouldOpenJinshaContextMenu(0),true);
 assert.equal(shouldOpenJinshaContextMenu(1),false);
 assert.equal(shouldOpenJinshaContextMenu(2),false);
 for(const failure of ['CONTEXT_MENU_NOT_UNIQUE','CONTEXT_WAIMAI_NOT_UNIQUE','CONTEXT_TAOBAO_NOT_UNIQUE','CONTEXT_SELECTION_UNVERIFIED'])assert.doesNotThrow(()=>checkPhase({...partial,failure,contextRepairAttempts:1},{instance:'current'},'ensure-jinsha-context'));
 assert.throws(()=>checkPhase({...partial,failure:'CONTEXT_WAIMAI_NOT_UNIQUE',contextRepairAttempts:2},{instance:'current'},'ensure-jinsha-context'));
 for(const observation of [
  {...partial.lastDiagnosticObservation,title:'其他站点'},
  {...partial.lastDiagnosticObservation,url:'https://example.com/'},
  {...partial.lastDiagnosticObservation,reason:'LOGIN_REQUIRED'},
  {...partial.lastDiagnosticObservation,loginMarkers:['账号登录']},
  {...partial.lastDiagnosticObservation,securityMarkers:['安全验证']},
  {...partial.lastDiagnosticObservation,markers:['总览','营业','顾客']},
 ])assert.throws(()=>checkPhase({...partial,lastDiagnosticObservation:observation},{instance:'current'},'ensure-jinsha-context'));
 assert.throws(()=>checkPhase({...base,site:'meituan'},{instance:'current'},'ensure-jinsha-context'));
 assert.throws(()=>checkPhase({...base,activeTargetId:null,activeMarker:null},{instance:'current'},'ensure-jinsha-context'));
});

test('Meituan homepage without optional patrol panel requires complete dashboard and exact origin',()=>{
 const parts=['全部门店','商家首页','商品管理','店铺设置','今日有效订单','今日预计收入','今日预约单','到期预约单','未读违规','未读预警'];
 const meta={site:'meituan',title:'美团外卖商家版',url:'https://waimaie.meituan.com/?ignoreSetRouterProxy=true'};
 assert.equal(classifyMeituan(parts.join(' '),meta).authenticated,true);
 for(let i=0;i<parts.length;i++)assert.equal(classifyMeituan(parts.filter((_,j)=>i!==j).join(' '),meta).authenticated,false);
 for(const url of ['https://example.com/','https://waimaie.meituan.com/login','http://waimaie.meituan.com/'])assert.equal(classifyMeituan(parts.join(' '),{...meta,url}).authenticated,false);
 for(const text of ['扫码登录','安全验证','账号存在风险'])assert.equal(classifyMeituan(parts.join(' ')+' '+text,meta).authenticated,false);
});
