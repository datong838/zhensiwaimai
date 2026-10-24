import { pathToFileURL } from "node:url";
import { resolve } from "node:path";
import { connectToPost } from "../../../posts/meituan-post/scripts/connect.mjs";
import { acquirePostLease, releasePostLease } from "../../../posts/meituan-post/scripts/lease.mjs";
import { assertOrigin, MEITUAN_HOST } from "../../../posts/meituan-post/scripts/auth.mjs";

const ENDPOINT = "http://127.0.0.1:9233";
const TARGET_PATH = "/imworkbench/";

function normalized(text) {
  return String(text ?? "").replace(/\s+/g, " ").trim();
}

function requireExactlyOne(items, expected, kind) {
  const values = Array.isArray(items) ? items.map(normalized) : [];
  if (values.length !== 1 || values[0] !== expected) {
    throw new Error(`${kind}-selection-not-verified`);
  }
}

function assertWorkbenchUrl(value) {
  let url;
  try {
    url = new URL(value);
  } catch {
    throw new Error("workbench-url-invalid");
  }
  // 岗位域原语：host 必须是 waimaie.meituan.com（美团商家端），否则 meituan-origin-changed。
  assertOrigin(value);
  if (!url.pathname.startsWith(TARGET_PATH)) {
    throw new Error("not-isolated-meituan-workbench");
  }
}

export function isFraudAcknowledgement(text) {
  const t = normalized(text).replace(/\s+/g, "");
  return t.includes("会话疑似存在欺诈风险")
    && t.includes("请勿脱离平台交易或向未核实身份者转账")
    && t.endsWith("我知道了")
    && !/登录|验证码|滑块|身份验证|重新认证|授权登录/.test(t);
}

export async function dismissFraudAcknowledgement(page) {
  const modal = page.locator('.roo-modal-dialog[class*="riskControlModal"]').filter({hasText:"会话疑似存在欺诈风险"});
  if (await modal.count() !== 1 || !await modal.isVisible()) return false;
  if (!isFraudAcknowledgement(await modal.innerText())) return false;
  const button = modal.getByText("我知道了", {exact:true});
  if (await button.count() !== 1) return false;
  await button.click({timeout:4000});
  await modal.waitFor({state:"hidden",timeout:4000});
  return true;
}

/**
 * 2026-10-12 站点新增弹窗消解：「多个工作台同时打开」roo-modal 全屏拦截所有 tab 点击，
 * 导致 12/15 档连败（locator.click timeout, subtree intercepts pointer events）。
 * 仅消解白名单文案（多个工作台同时打开）：点其自带的「刷新页面」按钮——站点自荐的中性
 * 动作（页面重载后服务端以本页为最新工作台）。其他文案 fail-closed 不碰，让后续点击
 * 自行暴露真实拦截。对齐 2026-10-11 activity_collector dismissBindModal 先例。
 * 返回 true=已消解（页面已刷新并等回 tab 渲染）；false=无白名单弹窗（原样继续）。
 */
export async function dismissWorkbenchModal(page) {
  if (await dismissFraudAcknowledgement(page)) return true;
  const text = await page.evaluate(() => {
    const m = document.querySelector(".roo-modal");
    if (!m) return null;
    const s = getComputedStyle(m);
    if (s.display === "none" || s.visibility === "hidden") return null;
    return (m.innerText || "").replace(/\s+/g, "");
  }).catch(() => null);
  if (!text || !text.includes("多个工作台同时打开")) return false;
  const btn = page.locator(".roo-modal button").filter({ hasText: /刷新页面/ }).first();
  if (!(await btn.count().catch(() => 0))) return false;
  await btn.click({ timeout: 4000 });
  // 刷新后等待 IM 主体重新渲染（判据与 runCli 开页路径一致：tab>=3，上限 60s）；
  // 渲染等待超时不在此抛错，交给后续队列门禁暴露真实错误（fail-closed）。
  const deadline = Date.now() + 60000;
  while (Date.now() < deadline) {
    const tabCount = await page.locator("ul.roo-tabs-nav li.tab-item").count().catch(() => 0);
    if (tabCount >= 3) return true;
    await page.waitForTimeout(1000);
  }
  return true;
}

/**
 * The only supported entry gate before reading or opening a customer row.
 * Driver contract: url(), countExact(text), clickExact(text),
 * waitForSelected(kind, text), and readState().
 */
async function ensureUnansweredQueue(driver) {
  const url = await driver.url();
  assertWorkbenchUrl(url);

  // 2026-10-12：先消解「多个工作台同时打开」白名单弹窗（若有），再进 tab 选择。
  // driver 不带 page 句柄（纯 DOM 原语接口），故通过 page 引用直调；见函数头说明。
  if (driver.page) await dismissWorkbenchModal(driver.page);

  const steps = [
    { kind: "main-tab", label: "全部顾客消息", stateKey: "activeMainTabs" },
    { kind: "filter", label: "未回复", stateKey: "activeFilters" },
  ];

  for (const step of steps) {
    const count = await driver.countExact(step.label);
    if (count !== 1) throw new Error(`${step.kind}-target-not-unique`);
    await driver.clickExact(step.label);
    await driver.waitForSelected(step.kind, step.label);
    const state = await driver.readState();
    requireExactlyOne(state?.[step.stateKey], step.label, step.kind);
  }

  return { ok: true, page: "imworkbench", mainTab: "全部顾客消息", filter: "未回复" };
}

/** Run any list-reading callback only after the queue state is verified. */
export async function runWithUnansweredQueue(driver, scan) {
  if (typeof scan !== "function") throw new Error("scan-callback-required");
  const receipt = await ensureUnansweredQueue(driver);
  return scan(driver, receipt);
}

function createPlaywrightDriver(page) {
  return {
    // 2026-10-12：暴露 page 供队列门禁消解白名单弹窗（dismissWorkbenchModal）。
    page,
    url: () => page.url(),
    countExact(text) {
      if (text === "未回复") {
        return page.locator("[class*=historySessionFilter] > div")
          .filter({ hasText: /^\s*未回复\s*$/ }).count();
      }
      return page.getByText(text, { exact: true }).count();
    },
    async clickExact(text) {
      const current = await this.readState();
      const active = text === "全部顾客消息" ? current.activeMainTabs : current.activeFilters;
      if (Array.isArray(active) && active.length === 1 && normalized(active[0]) === text) return;
      const target = text === "未回复"
        ? page.locator("[class*=historySessionFilter] > div").filter({ hasText: /^\s*未回复\s*$/ })
        : page.getByText(text, { exact: true });
      await target.click({ timeout: 3000 });
      // The tab can render the filter controls before its click handler settles;
      // verify the active state only after the UI has had a short settle window.
      await page.waitForTimeout(350);
    },
    async waitForSelected(kind, text) {
      const deadline = Date.now() + 3000;
      while (Date.now() < deadline) {
        const state = await this.readState();
        const selected = kind === "main-tab" ? state.activeMainTabs : state.activeFilters;
        if (Array.isArray(selected) && selected.length === 1 && normalized(selected[0]) === text) return;
        await page.waitForTimeout(100);
      }
      throw new Error(`${kind}-selection-timeout`);
    },
    async readState() {
      return page.evaluate(() => {
        const norm = (value) => String(value ?? "").replace(/\s+/g, " ").trim();
        return {
          activeMainTabs: [...document.querySelectorAll("ul.roo-tabs-nav > li.tab-item.active")]
            .map((item) => norm(item.querySelector(".tab-text")?.innerText)),
          activeFilters: [...document.querySelectorAll("[class*=historySessionFilter] > div")]
            .filter((item) => [...item.classList].some((name) => name === "active" || name.startsWith("active_")))
            .map((item) => norm(item.innerText)),
        };
      });
    },
  };
}

async function runCli() {
  // 岗位实体化 L1-4：经 meituan-post 连接独占工位 9233，并取工位互斥锁（同端口流水线串行）。
  const lease = await acquirePostLease(`meituan-${Date.now()}`);
  if (!lease) {
    // 工位被同端口其它流水线占用（忙）→ 跳过本轮，绝不驱动浏览器（对齐 daemon SKIPPED_BUSY）
    process.stdout.write(`${JSON.stringify({ status: 'skipped', reason: 'post-lease-busy', port: 9233 })}\n`);
    return;
  }
  try {
    const { browser } = await connectToPost();
    const pages = browser.contexts().flatMap((context) => context.pages());
    let matches = pages.filter((page) => {
      try {
        const url = new URL(page.url());
        return url.hostname === MEITUAN_HOST && url.pathname.startsWith(TARGET_PATH);
      } catch {
        return false;
      }
    });
    if (matches.length > 1) throw new Error("isolated-workbench-not-unique");
    if (matches.length === 0) {
      // 2026-10-04 美团入口变更自愈：服务端网关已拒绝直 GET /imworkbench/（50001
      // no matched api config），关页重开+直 goto 的旧复位方式失效。IM 工作台必须
      // 经商家后台顶栏 IM 入口（.wme-im-entry，位于 /new_fe/imChat_gw 的 iframe 内）
      // 打开，新页 URL 形如 /imworkbench/home?appId=4&clientType=140006#/im/page/workbench/。
      const homePage = pages.find((page) => {
        try {
          const url = new URL(page.url());
          return url.hostname === MEITUAN_HOST && !url.pathname.startsWith(TARGET_PATH);
        } catch {
          return false;
        }
      });
      if (!homePage) throw new Error("workbench-entry-page-missing");
      let clicked = false;
      for (const frame of homePage.frames()) {
        const count = await frame.locator(".wme-im-entry").count().catch(() => 0);
        if (count > 0) {
          await homePage.bringToFront();
          await frame.locator(".wme-im-entry").first().click({ timeout: 10000 });
          clicked = true;
          break;
        }
      }
      if (!clicked) throw new Error("workbench-entry-not-found");
      const deadline = Date.now() + 30000;
      while (Date.now() < deadline) {
        matches = browser.contexts().flatMap((context) => context.pages()).filter((page) => {
          try {
            const url = new URL(page.url());
            return url.hostname === MEITUAN_HOST && url.pathname.startsWith(TARGET_PATH);
          } catch {
            return false;
          }
        });
        if (matches.length >= 1) break;
        await new Promise((resolve) => setTimeout(resolve, 500));
      }
      if (matches.length !== 1) throw new Error("isolated-workbench-not-unique-after-entry");
      // 新页弹出 ≠ IM 主体已渲染（roo-tabs/筛选区晚到数十秒），先等渲染再置位。
      const renderDeadline = Date.now() + 60000;
      let rendered = false;
      while (Date.now() < renderDeadline) {
        const tabCount = await matches[0].locator("ul.roo-tabs-nav li.tab-item").count().catch(() => 0);
        if (tabCount >= 3) { rendered = true; break; }
        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
      if (!rendered) throw new Error("workbench-render-timeout");
    }
    const result = await ensureUnansweredQueue(createPlaywrightDriver(matches[0]));
    // 2026-10-03 修复工位租约泄漏：stdout 写回的回调里直接 process.exit(0) 会在
    // finally 释放租约之前终止进程，实测 13:57 的一次只读探测退出后锁文件仍残留到
    // TTL(30min) 才过期，期间同工位档位会被 post-lease-busy 跳过（#7 13:19 档即命中）。
    // 先显式释放租约，再按原语义退出本 Node 客户端（不 browser.close 常驻 Chrome）。
    await releasePostLease(lease).catch(() => {});
    // This is a read-only queue selection check. End only this Node client after
    // stdout flushes; never call browser.close() on the persistent Chrome profile.
    process.stdout.write(`${JSON.stringify(result)}\n`, () => process.exit(0));
  } finally {
    // 兜底：异常路径仍在此释放；成功路径已释放，此处为幂等 no-op。
    await releasePostLease(lease).catch(() => {});
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  runCli().catch((error) => {
    process.stderr.write(`${JSON.stringify({ ok: false, reason: error?.message ?? "queue-gate-failed" })}\n`, () => process.exit(1));
  });
}
