import test from 'node:test';
import assert from 'node:assert/strict';
import { assertOrigin, assertAuthenticated } from './auth.mjs';

test('origin 断言：服务商平台 prefix 放行，其它拒绝', () => {
  assert.equal(assertOrigin('https://open.shop.ele.me/manager/base/home'), true);
  assert.equal(assertOrigin('https://open.shop.ele.me/manager/intention'), true);
  assert.throws(() => assertOrigin('https://evil.com/'), /service-origin-changed/);
});

test('登录态：命中任一登录入口特征 → service-login-required', () => {
  assert.equal(assertAuthenticated('代运营 客户管理 意向商户管理'), true);
  assert.throws(() => assertAuthenticated('请扫码登录您的账号'), /service-login-required/);
  assert.throws(() => assertAuthenticated('账号密码登录'), /service-login-required/);
  assert.throws(() => assertAuthenticated('立即登录'), /service-login-required/);
});
