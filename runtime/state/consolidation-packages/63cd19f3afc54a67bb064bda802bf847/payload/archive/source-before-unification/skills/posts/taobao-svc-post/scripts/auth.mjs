// 淘宝服务商岗（taobao-svc-post）工位身份与登录态断言 —— 通用域原语
// 岗位 = 9231（淘宝闪购·服务商平台 open.shop.ele.me）
// 职责：工位 origin 断言 + 登录态判定。不掺任何业务（意向商户游标采集 / 核对）。
// 与 daily-agent-new-merchants background_merchant_collector 既有语义逐字一致。
// 本文件不依赖 playwright（纯字符串判定），可脱离浏览器离线自测。

export const TAOBAO_SVC_PORT = 9231;
export const TAOBAO_SVC_CDP = 'http://127.0.0.1:9231';
export const TAOBAO_SVC_PREFIX = 'https://open.shop.ele.me/';

// 登录态判定：页面正文出现任一登录入口特征 → 未登录（与采集器 LOGIN_MARKERS 一致）。
const LOGIN_MARKERS = ['账号密码', '扫码登录', '验证码登录', '立即登录', '无法登录'];

/**
 * 工位身份（origin）断言：必须落在服务商平台 prefix，否则 service-origin-changed。
 * @param {string} url 页面 URL
 */
export function assertOrigin(url) {
  if (!String(url).startsWith(TAOBAO_SVC_PREFIX)) throw Error('service-origin-changed');
  return true;
}

/**
 * 登录态校验：正文命中任一登录入口特征 → service-login-required。
 * 调用方先取 body.innerText 传入，省一次浏览器读取。
 * @param {string} body 已取到的 body.innerText
 */
export function assertAuthenticated(body) {
  const text = String(body ?? '');
  if (LOGIN_MARKERS.some((marker) => text.includes(marker))) throw Error('service-login-required');
  return true;
}
