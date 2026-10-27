// 负反馈列表申诉工作流 · 金鲨 CDP 与页面契约（岗位自包含）
//
// 归属：金鲨岗（9232）。页面域 = 评价&负反馈 → 负反馈列表（#/evaluationManagement/feedback），
// 与「差评列表」(#/negativeAnalyse) 是**两个不同页面**，DOM 契约完全不同，本工作流不复用差评页选择器。
//
// 2026-10-06 实机只读勘察（work/probe-feedback/out/probe3.json）确认的契约：
//   平台 tab  .option > .optionli（全部/美团/淘宝，optionliUp = 选中）
//   时间快捷  .reviewListB > .reviewLi（昨日/近7日/近1个月/近2个月，activate = 选中）
//   申诉类型  .appeal-filters-box > .nav-item（全部/AI申诉/商家申诉）
//   状态 tab  .status-btn-group > .status-btn（全部/未申诉/申诉中/申诉成功/申诉失败）
//   卡片      .feedback > .feedback_bottom > .feedback_list，卡内
//             .info_name .info_score .order_time .order_no .order_type .order_problem
//             .appeal_content（平台预申诉语句） .appeal_btn（「立即申诉(通过率x%)」）
//   分页      .el-pagination__total（「共 N 条」）
//   申诉弹窗  .el-dialog.appeal-custom-dialog（常驻 DOM）→ .appeal-dialog-body textarea、
//             .dialog-footer 三个按钮（取消 / 换一个 / 确定）
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { assertJinshaEntry, JINSHA_TITLE } from '../../../posts/jinsha-post/scripts/auth.mjs';
import { selectExistingJinshaTarget, assertSelectedJinshaTarget } from '../../../posts/jinsha-post/scripts/existing_owned_target.mjs';

export const ENDPOINT = 'http://127.0.0.1:9232';
export const ORIGIN = 'https://data.guoshuyufen.com/';
export const HOME = `${ORIGIN}#/businessData/realTimeData`;
export const FEEDBACK = `${ORIGIN}#/evaluationManagement/feedback`;
export const ROOT = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back';
export const RECORDS = `${ROOT}/records/negative-feedback-list-appeals`;
export const FLOW_ID = 'negative-feedback-list-appeals';
export const GROUP = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰';

// 2026-10-06 实机勘察结论（重要，勿改）：
//
// 顶部 `.optionli`（全部 / 美团 / 淘宝）是**同一负反馈页内的平台切换器**，切换的是同一份
// 列表数据。切到「淘宝」后读到的就是淘宝自己的数据（如「共 139 条」）。
//
// 踩坑记录：最初实现还去点左侧渠道 `.cutli` 切「淘宝」，结果整页被换成淘宝渠道后台
// —— 顶部变成「总览/营业/顾客/智能斗金」业务菜单，`.appeal-filters-box`（申诉类型大 tab）
// 与 `.status-btn`（申诉状态 tab）**双双消失**（count=0），且日期默认跳到「近1个月」。
// ⇒ 正确做法：**不切左侧渠道**，全程留在默认（美团）渠道，只用顶部 `.optionli` 切平台。
//
// 2026-10-06 二次实机勘察（diag_taobao4，用户决策「淘宝就只有全部」）：两个平台的
// **筛选结构完全不同**，必须分模式处理：
//   • 美团（mode:'status'）：有 `.appeal-filters-box`（申诉类型：全部/AI申诉/商家申诉）
//     与 `.status-btn`（状态：全部/未申诉/申诉中/申诉成功/申诉失败）。申诉源 = 申诉类型「全部」
//     + 状态「未申诉」，仅该页带「立即申诉」按钮的卡片可点（实测 9 条）。
//   • 淘宝（mode:'category'）：**没有** 申诉类型 / 状态 tab，取而代之是 `.nav_li`
//     （分类：全部 / 食品安全负反馈率 / 服务负反馈率）。默认激活「食品安全负反馈率」，
//     需显式点「全部」。该视图下**所有卡片都带「立即申诉」按钮**（无已/未申诉维度），
//     故申诉源 = 分类「全部」视图下的全部卡片。已申诉与否只能靠**跨日本地账本**去重
//     （页面不呈现申诉状态），详见 appeal_executor 的 existingStatusAnyDate 防重。
export const PLATFORMS = [
  { key: 'meituan', option: '美团', label: '美团外卖', mode: 'status', appealStatus: '未申诉' },
  { key: 'taobao', option: '淘宝', label: '淘宝闪购', mode: 'category', category: '全部' },
];
/** 淘宝分类筛选器（.nav_li）的「全部」项——用户明确：淘宝只用全部。 */
export const TAOBAO_CATEGORY_ALL = '全部';
export const TAOBAO_CATEGORY_ORDER = ['全部', '食品安全负反馈率', '服务负反馈率'];
export const TIME_RANGE = '近7日';
export const APPEAL_STATUS = '未申诉';
export const ALL_STATUS = '全部';
export const STATUS_ORDER = ['全部', '未申诉', '申诉中', '申诉成功', '申诉失败'];
/** 时间快捷 tab 跨度天数：近7日 = 7 天。 */
export const RANGE_DAYS = 7;

export const sleep = ms => new Promise(r => setTimeout(r, ms));
export const clean = v => String(v ?? '').replace(/\s+/g, ' ').trim();
export const excerpt = (v, n = 80) => clean(v).slice(0, n);
export const shanghaiDay = (date = new Date()) =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date);
export const now = () =>
  new Intl.DateTimeFormat('sv-SE', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })
    .format(new Date()).replace(' ', 'T') + '+08:00';
/** 业务日期 = 运行当日（近7日窗口含今天，日报口径以运行日为准）。 */
export const businessDate = () => shanghaiDay();

/**
 * 近7日窗口的起止日期。
 *
 * 2026-10-06 实机实测：平台「近7日」= **今天-7 至 今天-1，不含今天**（页面回读
 * 「已选时间: 2026-09-29 (周二) 至 2026-10-05 (周一)」，当天为 10-06）。
 * 这里曾按「含今天」算成 09-30~10-06，被 assertState 的日期窗口门禁当场拦下 ——
 * 门禁有效，故按平台真实口径实现。
 */
export function recentRange(today = shanghaiDay()) {
  const base = new Date(`${today}T00:00:00+08:00`);
  const end = new Date(base);
  end.setUTCDate(end.getUTCDate() - 1);
  const start = new Date(base);
  start.setUTCDate(start.getUTCDate() - RANGE_DAYS);
  return [shanghaiDay(start), shanghaiDay(end)];
}

/** 稳定记录键：平台|门店|评价日期|订单编号|问题分类。任一变化即视为新条目。 */
export function stableRecordKey({ platform, store, date, orderNo, category }) {
  return crypto.createHash('sha256')
    .update([platform, clean(store), clean(date), clean(orderNo), clean(category)].join('|'))
    .digest('hex').slice(0, 12);
}

/** 「立即申诉(通过率75%)」→ 75；解析失败返回 ''。 */
export function parsePassRate(text) {
  const m = clean(text).match(/通过率\s*(\d+)\s*%/);
  return m ? Number(m[1]) : '';
}

/** 候选资格：同一可见卡片内有且仅有一个可见 .appeal_btn。 */
export const eligible = card => card.hasAppealBtn === true;

export class Cdp {
  constructor(ws) { this.ws = ws; this.next = 0; this.pending = new Map(); }
  static async open() {
    const targets = await (await fetch(`${ENDPOINT}/json/list`)).json();
    const selected = await selectExistingJinshaTarget(targets);
    const ws = new WebSocket(selected.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      const timer = setTimeout(() => reject(Error('cdp-connect-timeout')), 20000);
      ws.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
      ws.addEventListener('error', e => { clearTimeout(timer); reject(Error('cdp-connect-error:' + (e?.message || 'unknown'))); }, { once: true });
    });
    const cdp = new Cdp(ws);
    ws.addEventListener('message', event => {
      const m = JSON.parse(event.data);
      const done = cdp.pending.get(m.id);
      if (done) { cdp.pending.delete(m.id); m.error ? done.reject(Error(m.error.message)) : done.resolve(m.result); }
    });
    try { await assertSelectedJinshaTarget(cdp, selected); } catch (error) { cdp.close(); throw error; }
    return cdp;
  }
  call(method, params = {}, timeoutMs = 45000) {
    return new Promise((resolve, reject) => {
      const id = ++this.next;
      const timer = setTimeout(() => { this.pending.delete(id); reject(Error(`cdp-call-timeout:${method}`)); }, timeoutMs);
      this.pending.set(id, {
        resolve: v => { clearTimeout(timer); resolve(v); },
        reject: e => { clearTimeout(timer); reject(e); },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }
  async eval(expression) {
    const out = await this.call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
    if (out.exceptionDetails) throw Error(out.exceptionDetails.exception?.description || out.exceptionDetails.text || 'cdp-evaluate-failed');
    return out.result.value;
  }
  close() { this.ws.close(); }
}

export async function navigate(cdp, url, waitMs = 2500) {
  await cdp.call('Page.enable');
  await cdp.call('Page.navigate', { url });
  await sleep(waitMs);
}

export const entryProbe = `(()=>({url:location.href,title:document.title,risk:/验证码|滑块|账号风险|请重新登录|登录失效/.test(document.body.innerText)}))()`;

export { assertJinshaEntry, JINSHA_TITLE };

/** 原子写 + 回读校验（防半截文件）。 */
export async function atomicWrite(file, text) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temp = `${file}.${process.pid}.tmp`;
  await fs.writeFile(temp, text, { mode: 0o600 });
  await fs.rename(temp, file);
  if (await fs.readFile(file, 'utf8') !== text) throw Error('record-readback-mismatch');
}

export const parseRecordStatus = text =>
  (String(text).match(/^- 记录状态：([^\n\r]+)/m) || [])[1]?.trim() || '';

export async function existingStatus(file) {
  try { return parseRecordStatus(await fs.readFile(file, 'utf8')); }
  catch (error) { if (error.code === 'ENOENT') return ''; throw error; }
}

/**
 * 跨日账本查重：遍历 RECORDS 下所有业务日期子目录，查找指定记录键的终态。
 *
 * 为什么需要它：淘宝「全部」视图**不呈现申诉状态**（所有卡片都带「立即申诉」），
 * 单日账本（existingStatus）无法挡住跨日的重复申诉。任何历史日期里已是终态
 * （verified_submitted / blocked / unknown / submitted_once）的键都禁止再次提交。
 */
export async function existingStatusAnyDate(key) {
  try {
    const dates = await fs.readdir(RECORDS);
    for (const date of dates.sort().reverse()) {
      const file = path.join(RECORDS, date, `${key}.md`);
      const status = await existingStatus(file);
      if (status) return status;
    }
  } catch (error) { if (error.code !== 'ENOENT') throw error; }
  return '';
}
