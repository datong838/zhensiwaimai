// 金鲨岗（jinsha-post）登录态 / 路由 / 风控权威判定 —— 纯函数，不依赖 playwright-core
// 从工作流内联实现收敛而来，与下游工作流判定逐字等价。
// 下游：meituan-waimai（all_appeals_collector / appeal_executor）、daily-jinsha-reports（business_jinsha_browser_exam）
// 保留各自原始错误码，确保下游逻辑零变化。
//
// 与 connect.mjs 的关系：connect.mjs 的 assertAuthenticated 面向 playwright Page、且风险词集含「安全验证」
// 不含「登录失效」，与历史工作流不一致；本文件提供与历史工作流逐字一致的纯判定，供裸 CDP 工作流收敛。

export const JINSHA_ORIGIN = 'https://data.guoshuyufen.com/';
export const JINSHA_HOME = 'https://data.guoshuyufen.com/#/businessData/realTimeData';
export const JINSHA_NEGATIVE = 'https://data.guoshuyufen.com/#/negativeAnalyse';
export const JINSHA_TITLE = '臻肆外卖运营';

// 与 meituan-waimai 内联 risk 正则逐字一致（含「登录失效」）
const ENTRY_RISK_RE = /验证码|滑块|账号风险|请重新登录|登录失效/;

// 与 daily-jinsha-reports 内联 LOGIN_MARKERS 逐字一致
export const JINSHA_LOGIN_MARKERS = ['请输入手机号', '请输入密码', '账号登录', '验证码登录', '扫码登录'];

export function isJinshaLoginUrl(url) {
  return typeof url === 'string' && url.startsWith(JINSHA_ORIGIN) && url.includes('#/login');
}

/**
 * 金鲨入口门禁：路由（home 由调用方传入，兼容 HOME / NEGATIVE 两套）+ 标题 + 风控，
 * 三者任一不符即抛 errorCode。与 meituan-waimai 内联判定逐字等价。
 * @param {{url:string,title:string,risk:boolean}} entry cdp.eval 返回的页面快照
 * @param {object} [opts]
 * @param {string} [opts.home] 期望路由（默认 JINSHA_HOME）
 * @param {string} [opts.errorCode] 未通过时抛出的错误码（默认 jinsha-entry-or-login-gate）
 */
export function assertJinshaEntry(entry, { home = JINSHA_HOME, errorCode = 'jinsha-entry-or-login-gate' } = {}) {
  const { url, title, risk } = entry;
  if (url !== home || title !== JINSHA_TITLE || risk) throw new Error(errorCode);
}

/**
 * 金鲨日报登录态门禁：origin 前缀 + 登录页/登录标记，保留 jinsha-origin-changed / jinsha-login-required。
 * 与 daily-jinsha-reports pageTextGuard 逐字等价。
 * @param {string} url 页面 URL
 * @param {string} text 已采集的页面正文（多 frame 合并）
 */
export function assertJinshaLoginGate(url, text) {
  if (!url.startsWith(JINSHA_ORIGIN)) throw new Error('jinsha-origin-changed');
  if (isJinshaLoginUrl(url) || JINSHA_LOGIN_MARKERS.some((m) => String(text).includes(m)))
    throw new Error('jinsha-login-required');
}
