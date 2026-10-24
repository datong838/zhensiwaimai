// 金鲨岗登录态/路由/风控判定契约测试 —— 纯字符串/对象，不依赖浏览器
// 验证 auth.mjs 与历史工作流内联判定逐字等价。
import { assertJinshaEntry, assertJinshaLoginGate, isJinshaLoginUrl, JINSHA_HOME, JINSHA_NEGATIVE, JINSHA_TITLE } from './auth.mjs';
import assert from 'node:assert/strict';
import { test } from 'node:test';

const OK_ENTRY = { url: JINSHA_HOME, title: JINSHA_TITLE, risk: false };

test('assertJinshaEntry 放行正常金鲨首页快照', () => {
  assert.doesNotThrow(() => assertJinshaEntry(OK_ENTRY));
});

test('assertJinshaEntry 路由不符抛默认错误码', () => {
  assert.throws(() => assertJinshaEntry({ ...OK_ENTRY, url: JINSHA_NEGATIVE }), /jinsha-entry-or-login-gate/);
});

test('assertJinshaEntry 支持自定义 home 与 errorCode（NEGATIVE 路由 + route 错误码）', () => {
  assert.doesNotThrow(() => assertJinshaEntry({ ...OK_ENTRY, url: JINSHA_NEGATIVE }, { home: JINSHA_NEGATIVE }));
  assert.throws(
    () => assertJinshaEntry({ ...OK_ENTRY, url: JINSHA_HOME }, { home: JINSHA_NEGATIVE, errorCode: 'jinsha-route-login-or-risk-gate' }),
    /jinsha-route-login-or-risk-gate/,
  );
});

test('assertJinshaEntry 标题不符抛错', () => {
  assert.throws(() => assertJinshaEntry({ ...OK_ENTRY, title: '金鲨数据' }), /jinsha-entry-or-login-gate/);
});

test('assertJinshaEntry risk=true 抛错（覆盖「登录失效」风险词场景）', () => {
  assert.throws(() => assertJinshaEntry({ ...OK_ENTRY, risk: true }), /jinsha-entry-or-login-gate/);
});

test('assertJinshaLoginGate 放行正常日报页', () => {
  assert.doesNotThrow(() => assertJinshaLoginGate(JINSHA_HOME, '美团外卖 淘宝闪购 下载数据'));
});

test('assertJinshaLoginGate origin 不符抛 jinsha-origin-changed', () => {
  assert.throws(() => assertJinshaLoginGate('https://evil.example.com/', 'x'), /jinsha-origin-changed/);
});

test('assertJinshaLoginGate 登录页抛 jinsha-login-required', () => {
  assert.throws(() => assertJinshaLoginGate('https://data.guoshuyufen.com/#/login', 'x'), /jinsha-login-required/);
});

test('assertJinshaLoginGate 命中登录标记抛 jinsha-login-required', () => {
  assert.throws(() => assertJinshaLoginGate(JINSHA_HOME, '请输入手机号 完成登录'), /jinsha-login-required/);
  assert.throws(() => assertJinshaLoginGate(JINSHA_HOME, '扫码登录即可'), /jinsha-login-required/);
});

test('isJinshaLoginUrl 仅金鲨 login 路由为真', () => {
  assert.equal(isJinshaLoginUrl('https://data.guoshuyufen.com/#/login'), true);
  assert.equal(isJinshaLoginUrl(JINSHA_HOME), false);
  assert.equal(isJinshaLoginUrl('https://other.com/#/login'), false);
});
