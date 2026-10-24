// 美团岗（meituan-post）工位身份与登录态断言 —— 通用域原语
// 岗位 = 9233（美团外卖商家端 waimaie.meituan.com）
// 职责：工位 origin 断言 + 登录态判定。不掺任何 IM 业务（队列/筛选/回复），那是工作流的事。
// 与 store-inspection 静默探测、IM 工作台门禁的登录判定逐字一致。
// 本文件不依赖 playwright（纯字符串判定），可脱离浏览器离线自测。

export const MEITUAN_PORT = 9233;
export const MEITUAN_CDP = 'http://127.0.0.1:9233';
export const MEITUAN_HOST = 'waimaie.meituan.com';

// 登录态判定：页面正文出现任一登录入口特征 → 未登录（与探测脚本 loginIndicators 一致）。
const LOGIN_RISK_RE = /(扫码|二维码|手机号登录|请登录)/;

/**
 * 工位身份（origin）断言：必须落在美团商家端 host，否则 meituan-origin-changed。
 * @param {string} url 页面 URL
 */
export function assertOrigin(url) {
  let host;
try {
    host = new URL(String(url)).hostname;
  } catch {
    host = '';
  }
  if (host !== MEITUAN_HOST) throw Error('meituan-origin-changed');
  return true;
}

/**
 * 登录态校验：正文命中任一登录入口特征 → meituan-authentication-required。
 * 调用方先取 body.innerText 传入，省一次浏览器读取。
 * @param {string} body 已取到的 body.innerText
 */
export function assertAuthenticated(body) {
  const text = String(body ?? '');
  if (LOGIN_RISK_RE.test(text)) throw Error('meituan-authentication-required');
  return true;
}
