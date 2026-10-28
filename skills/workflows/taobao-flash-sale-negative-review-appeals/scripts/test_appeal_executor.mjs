import assert from 'node:assert/strict';
import {APPEAL_BUTTON_SELECTOR,buildMarkdown,eligible,parseRecordStatus,sameCandidateSignature,shouldRetryEmptyList,stableRecordKey} from './appeal_executor.mjs';

const base={store:'门店A',date:'2026-09-21',score:'1',comment:'差评内容',auto:'自动申诉已关闭',hasAppeal:true};
assert.equal(stableRecordKey(base),stableRecordKey({...base,score:'3'}));
assert.notEqual(stableRecordKey(base),stableRecordKey({...base,comment:'另一条差评'}));
assert.equal(eligible(base),true);
// 2026-10-22/24用户裁定：淘宝有唯一立即申诉按钮时，自动申诉开启也受理。
assert.equal(eligible({...base,auto:'自动申诉已开启'}),true);
assert.equal(eligible({...base,hasAppeal:false}),false);
assert.equal(shouldRetryEmptyList(0,1),true);
assert.equal(shouldRetryEmptyList(1,1),false);
assert.equal(shouldRetryEmptyList(0,3),false);
assert.equal(sameCandidateSignature('', ''),true);
assert.equal(sameCandidateSignature(null, ''),false);
assert.match(APPEAL_BUTTON_SELECTOR,/button/);
assert.match(APPEAL_BUTTON_SELECTOR,/div/);
const md=buildMarkdown({businessDate:base.date,key:stableRecordKey(base),store:base.store,date:base.date,score:base.score,commentExcerpt:base.comment,pageState:'淘宝闪购 / 昨日 / 未申诉',auto:'已关闭',verification:'已准备',status:'ready_for_confirmation',createdAt:'2026-09-22T00:00:00+08:00'});
assert.equal(parseRecordStatus(md),'ready_for_confirmation');
for(const required of ['业务日期：','记录键：','门店：','平台建议回复：','页面核验结果：','异常原因：'])assert.ok(md.includes(required));
console.log(JSON.stringify({ok:true,tests:18,runtimeModelDecisions:0}));
