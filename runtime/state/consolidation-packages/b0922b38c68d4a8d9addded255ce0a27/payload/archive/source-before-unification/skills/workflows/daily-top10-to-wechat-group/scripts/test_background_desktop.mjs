import assert from 'node:assert/strict';
import {assertCanonicalBrowser,rowsFromCellMatrix,loginAssessment,validateProfileState,yesterdayDataState,safeId,selfTest} from './desktop_background_executor.mjs';

assert.equal(selfTest().tests,7);
assert.doesNotThrow(()=>assertCanonicalBrowser('taobao-brand',9230));
assert.throws(()=>assertCanonicalBrowser('other-profile',9230),/runtime-policy-browser-profile-mismatch/);
assert.throws(()=>assertCanonicalBrowser('taobao-brand',9222),/runtime-policy-browser-port-mismatch/);
assert.equal(safeId('top10-11111111-1111-4111-8111-111111111111'),true);
assert.equal(safeId('../top10'),false);
assert.equal(loginAssessment('商家首页 今日营业概况 数据中心 建议绑定手机号').authenticated,true);
assert.equal(loginAssessment('商家首页 今日营业概况 数据中心 账号密码').authenticated,false);
assert.equal(validateProfileState({profile:'taobao-brand',mode:'visible',port:9230,pid:2},'taobao-brand',9230),false);
assert.equal(yesterdayDataState('暂无数据 -- -- -- -- -- --',0),'NOT_READY');
assert.equal(yesterdayDataState('暂无数据 -- -- -- -- -- --',1),'LOADING');
assert.deepEqual(rowsFromCellMatrix([[''],['门店甲','99','第1名','9,999.20','5','88']]),[{store:'门店甲',rank:'第1名',revenue:9999.2,orders:88}]);
console.log(JSON.stringify({ok:true,tests:12,runtimeModelDecisions:0}));
