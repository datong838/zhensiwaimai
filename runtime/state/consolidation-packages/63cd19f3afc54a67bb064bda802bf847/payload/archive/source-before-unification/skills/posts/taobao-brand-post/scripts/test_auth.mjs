import test from 'node:test';
import assert from 'node:assert/strict';
import { assertOrigin, assertAuthenticated } from './auth.mjs';
import { describeChannel } from './channel.mjs';

test('origin 断言：品牌商 app 路径放行，其它拒绝', () => {
  assert.equal(assertOrigin('https://melody.shop.ele.me/app/shop/123/activity__myActivity'), true);
  assert.throws(() => assertOrigin('https://melody.shop.ele.me/login'), /taobao-brand-origin-changed/);
  assert.throws(() => assertOrigin('https://evil.com/'), /taobao-brand-origin-changed/);
});

test('登录态：未落在 app 路径 → brand-login-required（保留既有错误码）', () => {
  assert.equal(assertAuthenticated('https://melody.shop.ele.me/app/shop/123/'), true);
  assert.throws(() => assertAuthenticated('https://melody.shop.ele.me/login'), /brand-login-required/);
});

test('固定通道契约：端口/origin/forbidden 冻结正确', () => {
  const ch = describeChannel();
  assert.equal(ch.port, 9230);
  assert.equal(ch.appOrigin, 'https://melody.shop.ele.me/app/');
  assert.ok(ch.forbidden.includes('switch-profile-or-port'));
});
