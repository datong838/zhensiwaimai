import assert from 'node:assert/strict';
import {eligible} from './appeal_executor.mjs';
for (const channel of ['taobao-flash-sale', 'meituan-waimai']) {
  for (const auto of ['自动申诉已开启', '自动申诉已关闭', '']) {
    for (const hasAppeal of [true, false]) {
      const expected = hasAppeal && (auto === '自动申诉已关闭' || (channel === 'taobao-flash-sale' && auto === '自动申诉已开启'));
      assert.equal(eligible({auto, hasAppeal}, channel), expected, `${channel}/${auto}/${hasAppeal}`);
    }
  }
}
console.log('PASS: 12 candidate cases; no browser or submission');
