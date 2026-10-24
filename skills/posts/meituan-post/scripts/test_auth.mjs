import test from 'node:test';
import assert from 'node:assert/strict';
import { assertOrigin, assertAuthenticated } from './auth.mjs';

test('origin 断言：美团商家端 host 放行，其它拒绝', () => {
  assert.equal(assertOrigin('https://waimaie.meituan.com/imworkbench/home?appId=4'), true);
  assert.equal(assertOrigin('https://waimaie.meituan.com/new_fe/business'), true);
  assert.throws(() => assertOrigin('https://evil.com/x'), /meituan-origin-changed/);
  assert.throws(() => assertOrigin('not-a-url'), /meituan-origin-changed/);
});

test('登录态：命中登录入口特征 → meituan-authentication-required', () => {
  assert.equal(assertAuthenticated('经营 门店 订单 营业'), true);
  assert.throws(() => assertAuthenticated('请登录后查看'), /meituan-authentication-required/);
  assert.throws(() => assertAuthenticated('使用手机号登录'), /meituan-authentication-required/);
  assert.throws(() => assertAuthenticated('请使用扫码登录'), /meituan-authentication-required/);
});
