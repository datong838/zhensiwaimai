// 淘宝品牌商岗（taobao-brand-post）固定通道契约 —— 域原语
// 岗位 = 9230（淘宝闪购·商家版 melody.shop.ele.me）
// 固定通道身份（端口 / CDP / origin）不可变；本岗是「专人专岗」，通道契约由岗位拥有，
// 流水线（daily-taobao-download-to-jinsha / daily-top10-to-wechat-group /
// daily-new-stores-activity-audit-to-wechat / daily-new-stores-decoration-audit-to-wechat）
// 只消费，不自己定义端口或 origin。
//
// 注意：固定通道契约之外的「认证锚点恢复」「冷启动预算」是业务耦合逻辑，仍留在各工作流
// 的执行器内（每天登录态不同、恢复预算与业务上下文绑定），不进本原语——本文件只钉死身份。
//
// 2026-10-12 新增消费者 daily-new-stores-decoration-audit-to-wechat（新店装修巡检：
// 顶部招牌/店内海报「已配置」徽标读取）。该流经本岗通道的全部动作（连接 9230 / lease /
// 菜单导航进装修页 / 读组件徽标）均不触碰 CHANNEL_FORBIDDEN 五项；读取为纯只读，无外发副作用。

export const TAOBAO_BRAND_PORT = 9230;
export const TAOBAO_BRAND_CDP = 'http://127.0.0.1:9230';
export const TAOBAO_BRAND_APP_ORIGIN = 'https://melody.shop.ele.me/app/';

// 固定通道契约下的禁止动作（与 daily-taobao-download entrypoint.mjs 的 forbidden 清单对齐）。
export const CHANNEL_FORBIDDEN = [
  'create-or-copy-profile',
  'switch-profile-or-port',
  'open-new-browser-tab',
  'read-or-copy-cookie',
  'retry-external-effect',
];

/**
 * 返回冻结的通道契约描述（供工作流只读核对，不得改写）。
 */
export function describeChannel() {
  return Object.freeze({
    authority: 'post-owned-fixed-channel',
    port: TAOBAO_BRAND_PORT,
    cdp: TAOBAO_BRAND_CDP,
    appOrigin: TAOBAO_BRAND_APP_ORIGIN,
    forbidden: CHANNEL_FORBIDDEN,
  });
}
