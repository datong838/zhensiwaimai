// 淘宝品牌商岗（taobao-brand-post）工位身份与登录态断言 —— 通用域原语
// 岗位 = 9230（淘宝闪购·商家版 melody.shop.ele.me/app/）
// 职责：工位 origin 断言 + 登录态判定。不掺任何业务（店铺选择/活动核验/报表下载）。
// 与 daily-new-stores-activity-audit activity_collector 既有语义逐字一致：
// 未落在 app 路径即未登录（品牌商登录后会重定向到登录页，故 origin 即登录态）。
// 本文件不依赖 playwright（纯字符串判定），可脱离浏览器离线自测。

import { TAOBAO_BRAND_APP_ORIGIN } from './channel.mjs';

/**
 * 工位身份（origin）断言：必须落在品牌商 app 路径，否则 taobao-brand-origin-changed。
 * @param {string} url 页面 URL
 */
export function assertOrigin(url) {
  if (!String(url).startsWith(TAOBAO_BRAND_APP_ORIGIN)) throw Error('taobao-brand-origin-changed');
  return true;
}

/**
 * 登录态校验：未落在品牌商 app 路径 → brand-login-required（保留既有错误码，下游据此转人工认证）。
 * @param {string} url 页面 URL
 */
export function assertAuthenticated(url) {
  if (!String(url).startsWith(TAOBAO_BRAND_APP_ORIGIN)) throw Error('brand-login-required');
  return true;
}
