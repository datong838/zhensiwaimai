import assert from 'node:assert/strict';
import {freshRealtimePage} from './desktop_cua_executor.mjs';
const fixture=`Window: 商家, URL: https://melody.shop.ele.me/app/chain/95708808/store-analysis?dateType=realTime
1 HTML 内容 melody-stats-new, URL: https://melody-stats-next.ele.me/new/#/storeAnalysisDetail?tab=1&dateType=realTime&orderCol=valid_ord_amt
2 单选按钮 今日实时, Value: 1
3 单选按钮 昨日, Value: 0`;
assert.equal(freshRealtimePage(fixture),true);
assert.equal(freshRealtimePage(fixture.replace('今日实时, Value: 1','今日实时, Value: 0').replace('昨日, Value: 0','昨日, Value: 1')),false);
assert.equal(freshRealtimePage(fixture.replace('/95708808/store-analysis','/95708808/dashboard')),false);
assert.equal(freshRealtimePage(fixture+'\n'+fixture.split('\n')[1]),false);
console.log(JSON.stringify({ok:true,tests:4}));
