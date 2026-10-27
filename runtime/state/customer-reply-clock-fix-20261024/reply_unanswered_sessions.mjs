// 美团智能客服·逐条回复执行器（2026-10-03 大同授权 (b)）
// 每轮：队列门禁 → 全新逐条检查（未回复列表逐会话打开读取）→ 符合规则的真实回复
//（个人话术不自动使用；一律政策承接型兜底）→ 回显核验 → 当场写入当日临时台账。
// 判定为确定性保守规则：排除项命中一律不回；无法确认超时/无人工回复一律不回。
// --dry-run：只收集+判定+输出决策，不填字、不发送、不写台账。
// 铁律：不读 Cookie/存储；除会话卡片打开与发送按钮外不点击任何控件；
//       发送后必须回显核验，未回显视为失败并如实上报（不重试、不伪造）。
import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import fs from "node:fs/promises";
import { connectToPost } from "../../../posts/meituan-post/scripts/connect.mjs";
import { acquirePostLease, releasePostLease } from "../../../posts/meituan-post/scripts/lease.mjs";
import { runWithUnansweredQueue } from "./ensure_unanswered_queue.mjs";

const TARGET_HOST = "waimaie.meituan.com";
const TARGET_PATH = "/imworkbench/";
const DRY = process.argv.includes("--dry-run");
// 2026-10-04：移除本文件自带的 12 条覆盖上限（该上限非授权规则，与授权 (b)「每轮全新逐条检查」冲突）。
// 现为「滚动遍历到底、按视图全量逐条检查」；--max N 仍可显式收窄（0/缺省＝不限），MAX_GUARD 仅作失控护栏。
const MAX_GUARD = 500;
const MAX_SESSIONS = (() => {
  const i = process.argv.indexOf("--max");
  const v = i >= 0 ? Number(process.argv[i + 1]) : 0;
  // 缺省（不传 --max）＝真正的全量不限（Infinity）；仅当显式 --max N 时才以 min(N, MAX_GUARD=500) 作失控护栏。
  // 2026-10-11 修正：原默认返回 MAX_GUARD(500) 与上文注释「缺省＝不限」及大同「不要限制消息数量」的明确要求冲突；
  // 正常门店一日会话数远小于 500 故此前未触发漏检，但语义必须对齐为真正不限。
  if (!Number.isFinite(v) || v <= 0) return Infinity;
  return Math.min(v, MAX_GUARD);
})();
// 两视图全量检查：门禁视图「未回复」+「正在接待」主标签。
const VIEWS = ["未回复", "正在接待"];

const REPLY_DEFAULT =
  "您好，理解这件事给您带来的不便，抱歉让您久等了。我会尽快联系商家核实处理；具体处理方式需要以门店确认的实际情况为准，您也可以直接联系门店，以便更快处理。";
const REPLY_DELIVERY_NOTE =
  "您好，收到您希望将餐品放在前台的需求。麻烦您通过平台联系商家备注好，方便门店和配送人员安排，谢谢。";

// —— 确定性判定规则（源自 references/qualification-and-reply-policy.md）——
const EXCLUDE_RE = /加微信|加下我|加个微信|微信号|加V|薇信|威信|V信|联系方式|打给我|来电|电话\s*\d|广告|推广|招聘|兼职|刷单|贷款|引流|http|www\.|秀信|私信/;
const DELIVERY_NOTE_RE = /放前台|放门口|放驿站|放快递柜|代收点|送达时备注|放在前台|放在门口/;
const QUALIFY_RE = /少送|漏送|漏放|没放|错送|送错|发错|没送到|未送到|没收到|未收到|还没收到|洒了|撒了|漏了|凉了|冷了|退款|退单|取消|补送|补发|赔付|发票|开票|配送|骑手|超时|等太久|没餐|缺餐|分量|餐具|异物|头发|虫子|变质|过期|异味|卫生|催单|改地址|送错地址/;
const AUTO_RIGHT_RE = /自动回复|系统提示|已向顾客发起|已接单|骑手已|退款成功|已退款|平台客服|机器人|处理中|订单已完成|已送达|已取消|优惠券|红包已|评价邀请|温馨提示/;
const ROBOT_RIGHT_RE = /\[AI客服\]|总部商家客服|商家客服小|小慧/;
// 顾客侧的「非诉求」消息：订单咨询卡片模板、平台系统通知（含发票任务催促）。命中即不回。
const NOTICE_LEFT_RE = /您收到一条|请及时点击|切勿直接在对话|下单时间|订单编号[:：]|我要咨询以下订单|以上是订单|订单详情/;
const TIME_RE = /(\d{1,2}):(\d{2})/;

function shanghaiNow() {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
  }).formatToParts(new Date()).reduce((a, p) => ((a[p.type] = p.value), a), {});
  return { date: `${parts.year}-${parts.month}-${parts.day}`, clock: `${parts.hour}:${parts.minute}:${parts.second}`, h: Number(parts.hour), m: Number(parts.minute) };
}

function norm(t) { return String(t ?? "").replace(/\s+/g, " ").trim(); }

function judge(cardText, messages, now) {
  const leftMsgs = messages.filter((x) => x.side === "left" && norm(x.text));
  const rightTexts = messages.filter((x) => x.side === "right" && norm(x.text));
  const lastCustomer = leftMsgs.length ? leftMsgs[leftMsgs.length - 1] : null;
  const base = { card: norm(cardText).slice(0, 90), qualify: false, reason: "", reply: "", customerText: norm(lastCustomer?.text).slice(0, 80) };
  if (!lastCustomer) return { ...base, reason: "no-customer-message" };
  const text = norm(lastCustomer.text);
  if (EXCLUDE_RE.test(text)) return { ...base, reason: "excluded-by-policy(无关/引流/联系方式)" };
  if (NOTICE_LEFT_RE.test(text)) return { ...base, reason: "system-notice-or-order-card(非明确诉求,不回)" };
  // 店主人工回复检查：右侧任何非自动/非系统/非机器人文本消息都视为人工接管
  //（政策：自动回复、机器人回复、平台卡片不算店主人工回复；[AI客服]与总部商家客服(小慧)均为机器人，9-28 先例同口径）。
  // 我们自己上一轮的兜底回复不含这些标记，仍会被正确视为人工回复 → 天然防同会话重复回复。
  const human = rightTexts.find((x) => !AUTO_RIGHT_RE.test(norm(x.text)) && !ROBOT_RIGHT_RE.test(norm(x.text)) && !norm(x.nick).includes("小美"));
  if (human) return { ...base, reason: `owner-human-reply-present[right="${norm(human.text).slice(0, 40)}" nick=${norm(human.nick).slice(0, 20)}]` };
  if (!QUALIFY_RE.test(text)) return { ...base, reason: "not-catering-request(保守不回)" };
  // 超时：优先顾客最后一条消息内的时间，其次卡片预览时间；都没有 → 不作超时结论
  let tm = text.match(TIME_RE);
  if (!tm) tm = norm(cardText).match(TIME_RE);
  if (!tm) return { ...base, reason: "no-parseable-time(不作超时结论)" };
  const then = Number(tm[1]) * 60 + Number(tm[2]);
  const nowMin = now.h * 60 + now.m;
  if (nowMin - then < 10) return { ...base, reason: `not-yet-10min(${tm[0]})` };
  const reply = DELIVERY_NOTE_RE.test(text) ? REPLY_DELIVERY_NOTE : REPLY_DEFAULT;
  return { ...base, qualify: true, reason: `qualified(${tm[0]}诉求超10min,无人工接管)`, reply };
}

function createPlaywrightDriver(page) {
  return {
    // 2026-10-12：暴露 page 供队列门禁消解白名单弹窗（ensure_unanswered_queue 的
    // dismissWorkbenchModal：多个工作台同时打开→刷新页面）。两份 driver 拷贝需同步维护。
    page,
    url: () => page.url(),
    countExact(text) {
      if (text === "未回复") {
        return page.locator("[class*=historySessionFilter] > div").filter({ hasText: /^\s*未回复\s*$/ }).count();
      }
      return page.getByText(text, { exact: true }).count();
    },
    async clickExact(text) {
      const current = await this.readState();
      const active = text === "全部顾客消息" ? current.activeMainTabs : current.activeFilters;
      if (Array.isArray(active) && active.length === 1 && active[0] === text) return;
      const target = text === "未回复"
        ? page.locator("[class*=historySessionFilter] > div").filter({ hasText: /^\s*未回复\s*$/ })
        : page.getByText(text, { exact: true });
      await target.click({ timeout: 3000 });
      await page.waitForTimeout(350);
    },
    async waitForSelected(kind, text) {
      const deadline = Date.now() + 3000;
      while (Date.now() < deadline) {
        const state = await this.readState();
        const selected = kind === "main-tab" ? state.activeMainTabs : state.activeFilters;
        if (Array.isArray(selected) && selected.length === 1 && selected[0] === text) return;
        await page.waitForTimeout(100);
      }
      throw new Error(`${kind}-selection-timeout`);
    },
    async readState() {
      return page.evaluate(() => {
        const n = (v) => String(v ?? "").replace(/\s+/g, " ").trim();
        return {
          activeMainTabs: [...document.querySelectorAll("ul.roo-tabs-nav > li.tab-item.active")].map((i) => n(i.querySelector(".tab-text")?.innerText)),
          activeFilters: [...document.querySelectorAll("[class*=historySessionFilter] > div")].filter((i) => [...i.classList].some((c) => c === "active" || c.startsWith("active_"))).map((i) => n(i.innerText)),
        };
      });
    },
  };
}

async function readConversation(page) {
  return page.evaluate(() => {
    const n = (v) => String(v ?? "").replace(/\s+/g, " ").trim();
    const items = [...document.querySelectorAll(".message-item")].slice(-40).map((el) => {
      const w = el.querySelector(".message-wrapper");
      const side = w ? (String(w.className).includes("right-message") ? "right" : "left") : "unknown";
      const nick = n(w?.querySelector(".sender-nickname")?.innerText).slice(0, 40);
      return { side, nick, text: n(el.innerText).slice(0, 400) };
    });
    // message-item 嵌套去重：保留相邻不重复项
    return items.filter((x, i) => i === 0 || x.text !== items[i - 1].text || x.side !== items[i - 1].side);
  });
}

// 全量收集当前视图的会话卡片：滚动到底逐屏收集并去重。
// 适配两视图：未回复 / 正在接待 的列表容器 class 名不同，需通用定位可滚动祖先。
async function collectAllCards(page) {
  return page.evaluate(async () => {
    const norm = (t) => String(t ?? "").replace(/\s+/g, " ").trim().slice(0, 120);
    const firstCard = document.querySelector("[class*='sessionListItemContainer']");
    // 列表容器：优先 sessionListContent；否则回退到包含卡片的可滚动祖先（任一 *scroll/*list/*List/*content/*Content）。
    let sc = document.querySelector("[class*='sessionListContent']");
    if (!sc && firstCard) {
      sc = firstCard.closest("[class*='scroll'], [class*='list'], [class*='List'], [class*='content'], [class*='Content']") || firstCard.parentElement;
    }
    const seen = new Set();
    const order = [];
    const collect = () => {
      for (const el of document.querySelectorAll("[class*='sessionListItemContainer']")) {
        const t = norm(el.innerText);
        if (t && !seen.has(t)) { seen.add(t); order.push(t); }
      }
    };
    collect();
    if (sc) {
      const startTop = sc.scrollTop;
      let guard = 0;
      const step = Math.max(200, Math.floor(sc.clientHeight * 0.8));
      while (sc.scrollTop + sc.clientHeight < sc.scrollHeight - 5 && guard < 300) {
        sc.scrollTop = Math.min(sc.scrollTop + step, sc.scrollHeight);
        await new Promise((r) => setTimeout(r, 300));
        collect();
        guard++;
      }
      await new Promise((r) => setTimeout(r, 500));
      collect();
      sc.scrollTop = startTop; // 复位视点，避免留下滚动副作用
    }
    return order;
  });
}

// 逐条处理一个视图内的全部会话（全量；MAX_SESSIONS 仅作失控护栏，缺省不限）。
async function processCards(page, identities, receipt, now, done, view = "未回复") {
  let checked = 0;
  for (const identity of identities) {
    if (done.has(identity)) continue;
    if (done.size >= MAX_SESSIONS) break;
    done.add(identity);
    checked++;
    receipt.scanned++;
    const key = identity.slice(0, 18);
    const card = page.locator("[class*='sessionListItemContainer']").filter({ hasText: key }).first();
    if ((await card.count()) === 0) {
      receipt.decisions.push({ card: identity, qualify: false, reason: "card-vanished-from-filter(可能已读/已回)" });
      continue;
    }
    await card.click({ timeout: 5000 });
    await page.waitForTimeout(1000);
    const messages = await readConversation(page);
    const decision = judge(identity, messages, now);
    decision.session = maskSession(identity);
    receipt.decisions.push(decision);
    if (!decision.qualify || DRY) continue;

    // 真实回复：聚焦 → 真实键盘输入（触发受控组件 onChange）→ 输入自检 → 发送 → 回显核验（含 Enter 兜底）。
    const ta = page.locator("textarea[class*='chatInputTextarea']");
    if ((await ta.count()) !== 1) throw new Error("composer-textarea-not-unique");
    await ta.click({ timeout: 5000 });
    // 1) 首选：真实键盘逐字输入，确保 React 受控组件收到 onChange（fill 不触发，按钮会保持 disabled）。
    await ta.pressSequentially(decision.reply, { delay: 25 });
    await page.waitForTimeout(400);
    // 2) 输入自检：读 textarea 实际值，若未含回复前 20 字，用原生 setter + dispatch input 事件兜底（React 受控组件最可靠触发手法）。
    let inputVal = (await ta.inputValue().catch(() => "")) || "";
    if (!norm(inputVal).includes(norm(decision.reply).slice(0, 20))) {
      await page.evaluate((text) => {
        const el = document.querySelector("textarea[class*='chatInputTextarea']");
        if (!el) return;
        const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, "value").set;
        setter.call(el, text);
        el.dispatchEvent(new Event("input", { bubbles: true }));
        el.dispatchEvent(new Event("change", { bubbles: true }));
      }, decision.reply);
      await page.waitForTimeout(400);
      inputVal = (await ta.inputValue().catch(() => "")) || "";
    }
    // 3) 选主发送按钮：文本精确「发送」、可见且 enabled；排除快捷回复/推荐语面板内的按钮，多匹配取与输入框几何最近。
    // 2026-10-17：美团前端组件库升级（roo-*），发送按钮 class 由 btn-send 变为 roo-btn roo-btn-brand roo-btn-normal，
    // 原 button.btn-send 定位归零致 send-button-not-enabled（15:00/17:00 档误报，页面本身正常）。
    // 定位改为不依赖具体 class：按文本全量匹配，靠下方可见/enabled/非快捷区/几何最近四级筛选保正确，抗后续改版。
    const taBox = await ta.boundingBox();
    if (!taBox) throw new Error("composer-textarea-no-box");
    const btn = page.locator("button").filter({ hasText: /^\s*发送\s*$/ });
    const btnCount = await btn.count();
    const candidates = [];
    for (let k = 0; k < btnCount; k++) {
      const el = btn.nth(k);
      const box = await el.boundingBox();
      if (!box || !(await el.isVisible())) continue;
      const inQuick = await el.evaluate((n) => !!(n.closest("[class*='quick'], [class*='fast'], [class*='suggest'], [class*='recommend'], [class*='shortcut']"))).catch(() => false);
      if (inQuick) continue;
      if (!(await el.isEnabled())) continue;
      candidates.push({ el, box });
    }
    if (candidates.length === 0) throw new Error("send-button-not-enabled");
    const dist = (b) => Math.hypot(b.x + b.width / 2 - (taBox.x + taBox.width / 2), b.y + b.height / 2 - (taBox.y + taBox.height / 2));
    candidates.sort((a, b) => dist(a.box) - dist(b.box));
    await candidates[0].el.click({ timeout: 5000 });
    const rightAfterClick = (await readConversation(page)).filter((x) => x.side === "right").slice(-1)[0]?.text || null;
    // 4) 回显核验（最多 ~10s）；匹配前 12 字 + 去标点版本，容错美团渲染/富文本差异。
    const probe = norm(decision.reply).slice(0, 12);
    const strip = (s) => norm(s).replace(/[，。、！？；：,.!?;:\s]/g, "");
    const probePlain = strip(decision.reply).slice(0, 12);
    const echoHit = (after) => after.some((x) => x.side === "right" && (norm(x.text).includes(probe) || strip(x.text).includes(probePlain)));
    let echoed = false;
    for (let t = 0; t < 12 && !echoed; t++) {
      await page.waitForTimeout(800);
      echoed = echoHit(await readConversation(page));
    }
    // 5) Enter 兜底：点按钮未回显时，对输入框按 Enter 再核验一轮（部分 IM 需回车触发提交）。
    if (!echoed) {
      await ta.press("Enter");
      for (let t = 0; t < 6 && !echoed; t++) {
        await page.waitForTimeout(800);
        echoed = echoHit(await readConversation(page));
      }
    }
    const rightAfterPoll = (await readConversation(page)).filter((x) => x.side === "right").slice(-1)[0]?.text || null;
    // 信号2（大同 2026-10-04 铁律：任何迹象探查到发送成功就算成功）：
    // 回显未逐字命中时，检查会话是否已从「未回复」列表消失——实测打开会话不移出队列、
    // 只有回复成功才移出 ⇒ 消失即「已回复」的平台铁证，与回显等价判成功。
    let verifiedBy = echoed ? "echo" : null;
    if (!echoed && view === "未回复") {
      const idToken = (decision.session.match(/[^\s（(]{1,6}\*\*/) || [""])[0];
      const storeToken = (decision.session.match(/[（(]([^（）()]{2,30})[）)]\s*$/) || ["", ""])[1];
      for (let t = 0; t < 3 && !verifiedBy && idToken; t++) {
        await page.waitForTimeout(1500);
        try {
          const cards = await collectAllCards(page);
          if (!cards.some((c) => c.includes(idToken) && (!storeToken || c.includes(storeToken)))) verifiedBy = "list-gone";
        } catch {}
      }
    }
    const sentAt = shanghaiNow();
    // 铁律（2026-10-04 用户明确）：一旦点击发送就必须记账 md——核验只是二次自检，
    // 绝不能作为记账闸门（15:00 档曾因回显误判把合格投诉整条弄丢、md 未记，属信息丢失故障）。
    // 因此：点击完成后无条件 appendLedger；多信号（回显/列表消失）任一命中即判成功。
    const echoStatus = echoed
      ? "已发送，回显已核验"
      : verifiedBy === "list-gone"
        ? "已发送；会话已移出待回复列表（回复成功的平台铁证），回显未逐字命中"
        : "已点击发送；回显与列表消失信号均未探查到，需人工在美团后台确认是否真实发出";
    await appendLedger({
      date: receipt.date, sentAt: `${sentAt.h}:${sentAt.m}:${sentAt.s}`,
      session: decision.session, store: decision.session.split("（")[1]?.replace("）", "") || "未知门店",
      question: decision.customerText || norm(decision.card).slice(0, 60), reply: decision.reply,
      status: echoStatus,
      note: `发送前复核${decision.reason}；未承诺退款、补偿或处理结果。`,
    });
    receipt.sent.push({
      session: decision.session, sentAt: `${sentAt.h}:${sentAt.m}:${sentAt.s}`, question: decision.customerText || norm(decision.card).slice(0, 60), reply: decision.reply, verifiedBy,
    });
    if (!verifiedBy) {
      // 不丢账、不静默：派发已完成但回显/列表消失两信号均未命中 → 挂人工复核标记 + 诊断快照。
      // 该条已记账进 sent（ledgerRows 含它），failed 仅作为「需人工确认」的红灯标记，不再是丢账的理由。
      receipt.failed.push({ session: decision.session, reason: "echo-unverified-needs-manual-check", inputValueLen: inputVal.length, replyProbe: probe, rightAfterClick: rightAfterClick ? rightAfterClick.slice(0, 60) : null, rightAfterPoll: rightAfterPoll ? rightAfterPoll.slice(0, 60) : null });
    }
  }
  return checked;
}

function maskSession(cardText) {
  const masked = cardText.match(/([^\s(（]{1,4}\*\*(?:（尾号\d+）)?)/);
  const storeMatch = cardText.match(/[（(]([^（）()]{4,30})[）)]/g) || [];
  const store = (storeMatch.map((s) => s.slice(1, -1)).find((s) => /店|菜|餐|饭|肉|火烧|火锅|湘|小吃|米线|汉堡|粥|麻辣/.test(s)) || storeMatch[0]?.slice(1, -1) || "未知门店");
  return `${masked ? masked[1] : "会话"}（${store}）`;
}

async function appendLedger(record) {
  const path = new URL("../records/", import.meta.url).pathname + `待整理客户回复-${record.date}.md`;
  let header = "";
  try {
    await fs.access(path);
  } catch {
    header = `# ${record.date} 美团客服临时台账\n\n| 日期 | 发送时间 | 脱敏会话标识 | 门店 | 客户问题摘要 | 实际回复 | 平台核验状态 | 备注 |\n| --- | --- | --- | --- | --- | --- | --- | --- |\n`;
  }
  const cell = (v) => String(v).replace(/\|/g, "，").replace(/\n/g, " ");
  const line = `| ${record.date} | ${record.sentAt} | ${cell(record.session)} | ${cell(record.store)} | ${cell(record.question)} | ${cell(record.reply)} | ${cell(record.status)} | ${cell(record.note)} |\n`;
  await fs.appendFile(path, header + line, "utf-8");
  return path;
}

async function main() {
  const now = shanghaiNow();
  const lease = await acquirePostLease(`meituan-reply-${now.date}-${now.clock.replace(/:/g, "")}`);
  if (!lease) {
    console.log(JSON.stringify({ ok: false, skipped: true, reason: "post-lease-busy", dryRun: DRY }));
    return;
  }
  const receipt = { ok: true, dryRun: DRY, date: now.date, gate: null, views: [], scanned: 0, candidateCount: 0, decisions: [], sent: [], failed: [] };
  try {
    const { browser } = await connectToPost();
    const pages = browser.contexts().flatMap((c) => c.pages());
    const matches = pages.filter((p) => {
      try { const u = new URL(p.url()); return u.hostname === TARGET_HOST && u.pathname.startsWith(TARGET_PATH); }
      catch { return false; }
    });
    if (matches.length !== 1) throw new Error("isolated-workbench-not-unique");
    const page = matches[0];
    receipt.gate = await runWithUnansweredQueue(createPlaywrightDriver(page), async () => ({ ok: true }));

    const driver = createPlaywrightDriver(page);
    const done = new Set();
    for (const view of VIEWS) {
      if (view !== VIEWS[0]) {
        // 切到下一视图（主标签）并确认选中态；切换失败不静默吞掉，写入收据 views[].error。
        try {
          const n = await driver.countExact(view);
          if (n !== 1) throw new Error(`view-tab-not-unique:${view}:${n}`);
          await driver.clickExact(view);
          await driver.waitForSelected("main-tab", view);
          await page.waitForTimeout(800); // 等列表按新视图重渲染，避免收集到上一视图的残留 DOM
        } catch (e) {
          receipt.views.push({ view, total: null, checked: 0, error: String(e?.message || e).slice(0, 160) });
          continue;
        }
      }
      const identities = await collectAllCards(page);
      const checked = await processCards(page, identities, receipt, now, done, view);
      receipt.views.push({ view, total: identities.length, checked });
    }
    // 真实候选计数（已核验待回复 = qualify 数）落盘，供 step3 矛盾检测：
    // 候选>0 却无记账（ledgerRows=0）→ 当轮 FAIL + CRITICAL（方案 §52②）。
    receipt.candidateCount = receipt.decisions.filter((d) => d.qualify).length;
    if (!DRY) {
      const scanPath = new URL(`../records/.last-scan-${now.date}.json`, import.meta.url);
      await fs.writeFile(scanPath, JSON.stringify({
        date: now.date, scanned: receipt.scanned, candidateCount: receipt.candidateCount,
        ledgerRows: receipt.sent.length, unverifiedCount: receipt.sent.filter((s) => !s.verifiedBy).length, views: receipt.views, ts: Date.now(),
      })).catch(() => {});
    }
    // 队列门禁复位到「未回复」视角，保持工作台状态一致（只点已活动的标签，幂等）
    try { await runWithUnansweredQueue(createPlaywrightDriver(page), async () => ({ ok: true })); } catch {}
    // 先释放租约再显式退出：CDP 长连接会让事件循环挂着不退出，
    // daemon 步骤会一直等到 timeout（1800s），必须显式收口。
    await releasePostLease(lease).catch(() => {});
    process.stdout.write(`${JSON.stringify(receipt)}\n`, () => process.exit(0));
  } finally {
    // 兜底：异常路径仍在此释放；成功路径已释放，此处为幂等 no-op。
    await releasePostLease(lease).catch(() => {});
  }
}

main().catch((e) => {
  console.error(JSON.stringify({ ok: false, reason: String(e?.message || e).slice(0, 300) }));
  process.exit(1);
});
