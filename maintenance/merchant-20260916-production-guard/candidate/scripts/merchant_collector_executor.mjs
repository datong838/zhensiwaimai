import crypto from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { pathToFileURL } from "node:url";

const CHROME = "com.google.Chrome";
const BASE_HOME_URL = "https://open.shop.ele.me/manager/base/home";
const STATE_DIR = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/state/taobao-agent-new-merchants";
const PHONE_VENV_PYTHON = "/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python";
const CG_CLICK = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/daily-top10-to-wechat-group/scripts/cg_click.py";
const OCR_BIN = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/daily-top10-to-wechat-group/scripts/ocr_vision";
const DESKTOP_BRIDGE = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/daily-agent-new-merchants-to-wechat/scripts/chrome_desktop_bridge.py";
const MENU_INTENTION = "意向商户管理";
const MENU_CUSTOMER = "客户管理";
const MENU_AGENT = "代运营";


export function todayInShanghai(now = new Date()) {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(now);
}

export function cursorFileForGroup(groupName) {
  if (groupName === "电销+直播攻坚组") return path.join(STATE_DIR, "cursor.json");
  if (groupName === "臻肆测试群") return path.join(STATE_DIR, "cursor.test.json");
  throw new Error(`unsupported-group:${groupName}`);
}

function roleId(line, role) {
  const match = line?.match(new RegExp(`(\\d+) ${role}`));
  return match ? Number(match[1]) : null;
}

function linesWithinRows(text) {
  const lines = text.split("\n");
  const listIndex = lines.findIndex((line) => /内容列表/.test(line));
  const tableIndices = lines.flatMap((line, index) => /\s\d+ 表格$/.test(line) ? [index] : []);
  const start = tableIndices.filter((index) => listIndex < 0 || index < listIndex).at(-1) ?? -1;
  return start >= 0 ? lines.slice(start + 1, listIndex > start ? listIndex : lines.length) : [];
}

export function parseRowsFromAx(text, page = 1) {
  const lines = linesWithinRows(text);
  const rows = [];
  for (let index = 0; index < lines.length; index += 1) {
    const rowMatch = lines[index].match(/^(\s*)(\d+) row$/);
    if (!rowMatch) continue;
    const indent = rowMatch[1].length;
    const block = [];
    for (let cursor = index + 1; cursor < lines.length; cursor += 1) {
      const currentIndent = lines[cursor].match(/^\s*/)?.[0].length ?? 0;
      if (currentIndent <= indent) break;
      block.push(lines[cursor]);
    }
    const values = block.flatMap((line) => {
      const match = line.match(/^\s*\d+ (?:文本|text) (.+)$/);
      return match ? [match[1].trim()] : [];
    });
    const recommendTime = [...values].reverse().find((value) => /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/.test(value));
    const detailLine = block.find((line) => /按钮 详情$/.test(line));
    if (!recommendTime || values.length < 7 || !/^\d+$/.test(values[1] ?? "") || !detailLine) continue;
    const timeIndex = values.indexOf(recommendTime);
    // 列序：名称、ID、地址、门店类型、市场经理、城市、来源、状态、剩余时间、推荐时间。
    const city = timeIndex >= 4 ? values[timeIndex - 4] : "";
    rows.push({
      merchantName: values[0] ?? "",
      merchantId: values[1] ?? "",
      listAddress: values[2] ?? "",
      city,
      sourceType: timeIndex >= 3 ? values[timeIndex - 3] : "",
      status: timeIndex >= 2 ? values[timeIndex - 2] : "",
      recommendTime,
      page,
      pageOrder: rows.length + 1,
      detailButtonId: roleId(detailLine, "按钮"),
    });
  }
  return rows;
}

function valueAfterLabel(lines, label) {
  const index = lines.findIndex((line) => new RegExp(`\\d+ text ${label}$`).test(line));
  if (index < 0) return "";
  for (let cursor = index + 1; cursor < Math.min(lines.length, index + 8); cursor += 1) {
    const match = lines[cursor].match(/^\s*\d+ (?:文本|text) (.+)$/);
    if (match && !["商家名称", "商家ID", "商家地址", "商家联系人", "是否已告知价格", "商家意愿度", "意向举证", "备注", "推荐人"].includes(match[1])) return match[1].trim();
  }
  return "";
}

export function parseDetailFromAx(text) {
  const start = text.indexOf("container 推荐商家详情");
  if (start < 0) throw new Error("detail-modal-missing");
  const lines = text.slice(start).split("\n");
  return {
    merchantName: valueAfterLabel(lines, "商家名称"),
    merchantId: valueAfterLabel(lines, "商家ID"),
    address: valueAfterLabel(lines, "商家地址"),
    contact: valueAfterLabel(lines, "商家联系人").replace(/\s*，\s*/g, "，").trim(),
  };
}

export function formatMerchantMessage(merchant) {
  const usable = (value) => {
    const normalized = String(value ?? "").trim();
    return normalized && !["-", "--", "暂无", "无"].includes(normalized) ? normalized : "";
  };
  return [
    usable(merchant.city) || "（城市字段缺失）",
    usable(merchant.contact) || "（商家联系人字段缺失）",
    usable(merchant.merchantName) || "（商家名称字段缺失）",
    usable(merchant.address) || "（商家地址字段缺失）",
  ].join("\n");
}

export function stableAscending(rows) {
  return rows.map((row, index) => ({ ...row, sourceOrder: row.sourceOrder ?? index + 1 }))
    .sort((a, b) => a.recommendTime.localeCompare(b.recommendTime) || a.sourceOrder - b.sourceOrder);
}

export function isAscending(rows) {
  return rows.every((row, index) => index === 0 || rows[index - 1].recommendTime.localeCompare(row.recommendTime) <= 0);
}

export function selectIncremental(rows, cursor, businessDate) {
  if (!cursor) throw new Error("cursor-required");
  const ordered = stableAscending(rows).map((row, index) => ({ ...row, tableOrder: index + 1 }));
  const dayStart = `${businessDate} 00:00:00`;
  if (cursor.recommendTime < dayStart) return ordered;
  const exact = ordered.findIndex((row) => row.merchantId === cursor.merchantId
    && row.recommendTime === cursor.recommendTime);
  if (exact >= 0) return ordered.slice(exact + 1);
  const strictlyAfter = ordered.filter((row) => row.recommendTime > cursor.recommendTime);
  if (strictlyAfter.length && !ordered.some((row) => row.recommendTime === cursor.recommendTime)) {
    throw new Error("same-day-cursor-not-found");
  }
  return strictlyAfter;
}

async function readJson(file) {
  try { return JSON.parse(await fs.readFile(file, "utf8")); } catch { return null; }
}

async function writeJsonAtomic(file, value) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${Date.now()}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(value, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, file);
}

async function getState(sky) {
  return sky.get_app_state({ app: CHROME, disableDiff: true });
}

function isIntentionListOpen(text) {
  return text.includes(MENU_INTENTION) && text.includes("商家意向列表");
}

export function declutterOverlays() {
  // D1：挪开桌面微信/企微/AOS Dedicated「第三方应用」，避免与服务商窗同框叠盖。
  execFileSync(PHONE_VENV_PYTHON, [DESKTOP_BRIDGE, "--declutter"], { encoding: "utf8" });
}

export function seizeChromeFocus() {
  // 任何点击前必须清遮挡并 Raise 服务商窗，否则必点错。
  declutterOverlays();
}

function openBaseHomeInChrome({ reloadEntry = false } = {}) {
  // 只附着已有 open.shop 标签；默认不重载、绝不 make new window/tab。
  seizeChromeFocus();
  const flag = reloadEntry ? "true" : "false";
  try {
    return execFileSync("osascript", ["-e", `
tell application "Google Chrome"
  activate
  set hit to false
  set wi to 1
  set foundUrl to ""
  repeat with w in windows
    set ti to 1
    repeat with t in tabs of w
      set u to URL of t as text
      if u contains "open.shop.ele.me" then
        set active tab index of window wi to ti
        set index of window wi to 1
        if ${flag} then
          set URL of t to "${BASE_HOME_URL}"
          delay 1.2
        end if
        set foundUrl to URL of t as text
        set hit to true
        exit repeat
      end if
      set ti to ti + 1
    end repeat
    if hit then exit repeat
    set wi to wi + 1
  end repeat
  if not hit then error "existing-open-shop-tab-missing"
  return foundUrl
end tell
`], { encoding: "utf8" }).trim();
  } catch {
    throw new Error("existing-browser-required:需要已打开并登录的 open.shop.ele.me 标签，禁止自动新开浏览器");
  }
}

function chromeServiceWindowBounds() {
  const script = `
import Quartz, json
opts = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
wins = [w for w in Quartz.CGWindowListCopyWindowInfo(opts, Quartz.kCGNullWindowID)
        if w.get("kCGWindowOwnerName") == "Google Chrome" and w.get("kCGWindowLayer", 0) == 0]
preferred = [w for w in wins if "淘宝闪购服务商" in (w.get("kCGWindowName") or "")]
target = preferred[0] if preferred else sorted(
  wins, key=lambda w: -(w.get("kCGWindowBounds", {}).get("Width", 0) * w.get("kCGWindowBounds", {}).get("Height", 0))
)[0]
print(json.dumps({"id": int(target["kCGWindowNumber"]), "bounds": dict(target["kCGWindowBounds"]), "name": target.get("kCGWindowName") or ""}))
`;
  return JSON.parse(execFileSync(PHONE_VENV_PYTHON, ["-c", script], { encoding: "utf8" }));
}

function captureChromeServiceWindow(shotPath) {
  seizeChromeFocus();
  const window = chromeServiceWindowBounds();
  execFileSync("/usr/sbin/screencapture", ["-x", "-l", String(window.id), shotPath]);
  return window;
}

function clickSidebarLabelByOcr(label) {
  const shotPath = `/tmp/zhensi-agent-menu-${Date.now()}.png`;
  const window = captureChromeServiceWindow(shotPath);
  const entries = parseOcrTsv(execFileSync(OCR_BIN, [shotPath, "zh-Hans"], { encoding: "utf8" }));
  const meta = execFileSync("/usr/bin/sips", ["-g", "pixelWidth", "-g", "pixelHeight", shotPath], { encoding: "utf8" });
  const imageWidth = Number(meta.match(/pixelWidth:\s*(\d+)/)?.[1]);
  const imageHeight = Number(meta.match(/pixelHeight:\s*(\d+)/)?.[1]);
  if (!imageWidth || !imageHeight) throw new Error("sidebar-ocr-image-size-missing");
  const scaleX = imageWidth / window.bounds.Width;
  const scaleY = imageHeight / window.bounds.Height;
  const exact = entries.filter((entry) => entry.text.replace(/\s/g, "") === label.replace(/\s/g, "")
    && entry.x < imageWidth * 0.45);
  let chosen = exact;
  if (exact.length > 1) {
    // 侧栏 + 页标题可能同时出现同文案；取最左侧一条。
    const leftmostX = Math.min(...exact.map((entry) => entry.x));
    chosen = exact.filter((entry) => Math.abs(entry.x - leftmostX) < 40);
  }
  if (chosen.length !== 1) {
    throw new Error(`sidebar-ocr-count:${label}:${chosen.length}:${chosen.map((e) => e.text).join("|")}`);
  }
  const entry = chosen[0];
  const screenX = window.bounds.X + entry.x / scaleX;
  const screenY = window.bounds.Y + entry.y / scaleY;
  seizeChromeFocus();
  execFileSync(PHONE_VENV_PYTHON, [CG_CLICK, String(screenX), String(screenY)]);
}

function intentionListVisibleByOcr() {
  const shotPath = `/tmp/zhensi-agent-intention-check-${Date.now()}.png`;
  captureChromeServiceWindow(shotPath);
  const entries = parseOcrTsv(execFileSync(OCR_BIN, [shotPath, "zh-Hans"], { encoding: "utf8" }));
  const texts = entries.map((entry) => entry.text);
  const joined = texts.join("\n");
  const hasMenu = texts.some((text) => text.replace(/\s/g, "") === MENU_INTENTION);
  if (!hasMenu) return false;
  // D3：标题 OCR 偶发漏读时，待处理+详情足以证明已在意向列表。
  if (joined.includes("商家意向列表")) return true;
  return texts.some((text) => text.includes("待处理")) && texts.some((text) => text.includes("详情"));
}

function axClickSidebarLabel(label) {
  // D3：优先 System Events 精确文案点击，失败再 OCR。
  const result = execFileSync(PHONE_VENV_PYTHON, ["-c", `
from importlib.machinery import SourceFileLoader
bridge = SourceFileLoader("bridge", "${DESKTOP_BRIDGE}").load_module()
print("ok" if bridge.ax_click_label(${JSON.stringify(label)}) else "miss")
`], { encoding: "utf8" }).trim();
  return result === "ok";
}

async function clickUniqueAxLabel(sky, label) {
  seizeChromeFocus();
  const state = await getState(sky);
  const lines = state.text.split("\n").filter((line) => {
    const match = line.match(/^\s*\d+ (?:文本|按钮|text) (.+)$/);
    return match && match[1].replace(/\s/g, "") === label.replace(/\s/g, "");
  });
  if (lines.length !== 1) return false;
  const id = roleId(lines[0], lines[0].includes("按钮") ? "按钮" : (lines[0].includes("文本") ? "文本" : "text"));
  if (id == null) return false;
  await sky.click({ app: CHROME, element_index: id });
  return true;
}

export async function openIntentionMerchantPage(sky, { reloadEntry = false } = {}) {
  seizeChromeFocus();
  // 已在意向列表：零导航，不碰 URL。
  if (intentionListVisibleByOcr()) {
    return sky ? getState(sky) : { text: `${MENU_INTENTION}\n商家意向列表` };
  }
  openBaseHomeInChrome({ reloadEntry });
  await new Promise((resolve) => setTimeout(resolve, reloadEntry ? 1_500 : 800));

  if (sky) {
    let state = await getState(sky);
    if (isIntentionListOpen(state.text)) return state;
    // 固定侧栏：代运营 → 客户管理 → 意向商户管理
    for (const label of [MENU_AGENT, MENU_CUSTOMER, MENU_INTENTION]) {
      seizeChromeFocus();
      const clicked = await clickUniqueAxLabel(sky, label);
      if (!clicked) {
        try {
          clickSidebarLabelByOcr(label);
        } catch (error) {
          if (label === MENU_INTENTION) throw error;
        }
      }
      await new Promise((resolve) => setTimeout(resolve, 1_200));
      state = await getState(sky);
      if (label === MENU_INTENTION && isIntentionListOpen(state.text)) return state;
    }
    state = await pollState(sky, isIntentionListOpen, 8_000);
    if (isIntentionListOpen(state.text)) return state;
  }

  // 无 sky 或 AX 未命中时：桌面桥 AX 点击 → OCR 侧栏（仍先清遮挡抢焦点）。
  const probeShot = `/tmp/zhensi-agent-menu-probe-${Date.now()}.png`;
  captureChromeServiceWindow(probeShot);
  const probeEntries = parseOcrTsv(execFileSync(OCR_BIN, [probeShot, "zh-Hans"], { encoding: "utf8" }));
  if (intentionListVisibleByOcr()) {
    return sky ? getState(sky) : { text: `${MENU_INTENTION}\n商家意向列表` };
  }
  const intentionVisible = probeEntries.some((entry) => entry.text.replace(/\s/g, "") === MENU_INTENTION && entry.x < 1200);
  const labels = intentionVisible ? [MENU_INTENTION] : [MENU_AGENT, MENU_CUSTOMER, MENU_INTENTION];
  for (const label of labels) {
    try {
      if (!axClickSidebarLabel(label)) clickSidebarLabelByOcr(label);
    } catch (error) {
      if (label === MENU_INTENTION) throw error;
    }
    await new Promise((resolve) => setTimeout(resolve, 1_600));
  }
  if (!intentionListVisibleByOcr()) {
    throw new Error("intention-merchant-page-not-open");
  }
  return sky ? getState(sky) : { text: `${MENU_INTENTION}\n商家意向列表` };
}

async function restoreChromeRoot(sky, state) {
  // 兼容旧调用点：统一走入口 URL + 侧栏菜单，不再假定已在 agent/home。
  return openIntentionMerchantPage(sky);
}

async function pollState(sky, predicate, timeoutMs = 5_000) {
  const deadline = performance.now() + timeoutMs;
  let latest = null;
  do {
    latest = await getState(sky);
    if (predicate(latest.text)) return latest;
    await new Promise((resolve) => setTimeout(resolve, 180));
  } while (performance.now() < deadline);
  return latest;
}

function fullscreenStatus(text) {
  if (/^\s*\d+ 退出全屏幕(?:,|$)/m.test(text)) return "fullscreen";
  if (/^\s*\d+ 进入全屏幕(?:,|$)/m.test(text)) return "windowed";
  return "unknown";
}

async function ensureChromeFullscreen(sky, state) {
  seizeChromeFocus();
  if (/^\s*0 菜单 Secondary Actions: Cancel/m.test(state.text)) {
    await sky.perform_secondary_action({ app: CHROME, element_index: 0, action: "Cancel" });
    state = await getState(sky);
  }
  const windowLine = state.text.split("\n").find((line) => /^\s*0 标准窗口/.test(line));
  if (windowLine) {
    await sky.perform_secondary_action({ app: CHROME, element_index: 0, action: "Raise" });
    state = await getState(sky);
  }
  const viewLine = state.text.split("\n").find((line) => /^\s*\d+ 显示$/.test(line));
  const viewId = roleId(viewLine, "显示");
  if (viewId == null) throw new Error("chrome-view-menu-not-found");
  await sky.click({ app: CHROME, element_index: viewId });
  let menu = await getState(sky);
  let status = fullscreenStatus(menu.text);
  if (status === "windowed") {
    const enterLine = menu.text.split("\n").find((line) => /^\s*\d+ 进入全屏幕(?:,|$)/.test(line));
    const enterId = Number(enterLine?.match(/(\d+) 进入全屏幕/)?.[1]);
    if (!Number.isFinite(enterId)) throw new Error("chrome-enter-fullscreen-not-found");
    await sky.click({ app: CHROME, element_index: enterId });
    await new Promise((resolve) => setTimeout(resolve, 700));
    state = await getState(sky);
    const newViewLine = state.text.split("\n").find((line) => /^\s*\d+ 显示$/.test(line));
    const newViewId = roleId(newViewLine, "显示");
    if (newViewId == null) throw new Error("chrome-view-menu-not-found-after-fullscreen");
    await sky.click({ app: CHROME, element_index: newViewId });
    menu = await getState(sky);
    status = fullscreenStatus(menu.text);
  }
  if (status !== "fullscreen") throw new Error(`chrome-fullscreen-not-verified:${status}`);
  await sky.perform_secondary_action({ app: CHROME, element_index: 0, action: "Cancel" });
  return pollState(sky, isIntentionListOpen, 2_000);
}

function exactLineId(text, pattern, role) {
  const matches = text.split("\n").filter((line) => pattern.test(line));
  if (matches.length !== 1) throw new Error(`element-count:${pattern}:${matches.length}`);
  return roleId(matches[0], role);
}

function parseOcrTsv(output) {
  return output.split("\n").flatMap((line) => {
    const [box, confidence, ...textParts] = line.split("\t");
    if (!box || textParts.length === 0) return [];
    const [x, y, w, h] = box.split(",").map(Number);
    if (![x, y, w, h].every(Number.isFinite)) return [];
    return [{ x, y, w, h, confidence: Number(confidence), text: textParts.join("\t").trim() }];
  });
}

export async function openDetailByVisualRow(sky, target) {
  // 浏览器查找只负责把唯一商家 ID 滚到可见区；详情仍由同屏 OCR 精确定位。
  seizeChromeFocus();
  await sky.press_key({ app: CHROME, key: "super+f" });
  await sky.type_text({ app: CHROME, text: target.merchantId });
  await sky.press_key({ app: CHROME, key: "Escape" });
  await new Promise((resolve) => setTimeout(resolve, 350));
  seizeChromeFocus();
  const screenshot = `/tmp/zhensi-merchant-row-${target.merchantId}.png`;
  execFileSync("/usr/sbin/screencapture", ["-x", screenshot]);
  const entries = parseOcrTsv(execFileSync(OCR_BIN, [screenshot, "zh-Hans"], { encoding: "utf8" }));
  const idMatches = entries.filter((entry) => entry.text.replace(/\s/g, "") === target.merchantId);
  if (idMatches.length !== 1) throw new Error(`visual-row-id-count:${target.merchantId}:${idMatches.length}`);
  const rowY = idMatches[0].y;
  const actions = entries.filter((entry) => entry.text.includes("详情") && entry.x > 1700 && Math.abs(entry.y - rowY) < 90);
  if (actions.length !== 1) throw new Error(`visual-detail-action-count:${target.merchantId}:${actions.length}`);
  const action = actions[0];
  const left = action.x - action.w / 2;
  const detailX = action.text.replace(/\s/g, "") === "详情" ? action.x : left + action.w * 0.12;
  seizeChromeFocus();
  execFileSync(PHONE_VENV_PYTHON, [CG_CLICK, String(detailX / 2), String(action.y / 2)]);
  let modal = null;
  for (let attempt = 0; attempt < 12; attempt += 1) {
    modal = await getState(sky);
    try {
      if (parseDetailFromAx(modal.text).merchantId === target.merchantId) return modal;
    } catch { /* 等待详情弹层。 */ }
    await new Promise((resolve) => setTimeout(resolve, 180));
  }
  throw new Error(`visual-detail-not-opened:${target.merchantId}`);
}

async function setTodayAndQuery(sky, state, businessDate) {
  const startLine = state.text.split("\n").find((line) => /文本栏 (?:\(settable\) )?推荐时间,(?: Value: .*?,)? Placeholder: 开始日期/.test(line));
  const startId = roleId(startLine, "文本栏");
  if (startId == null) throw new Error("start-date-not-found");
  // Ant Design 日期输入框在 AX 中偶尔不标记 settable；聚焦后键盘输入更稳定。
  await sky.click({ app: CHROME, element_index: startId });
  await sky.press_key({ app: CHROME, key: "super+a" });
  await sky.type_text({ app: CHROME, text: businessDate });
  await sky.press_key({ app: CHROME, key: "Return" });
  state = await pollState(sky, (text) => text.includes(`Value: ${businessDate}, Placeholder: 开始日期`), 2_000);
  const endLine = state.text.split("\n").find((line) => /文本栏 (?:\(settable\) )?(?:(?:推荐时间, )?(?:Value: .*?, )?Placeholder: )?结束日期$/.test(line));
  const endId = roleId(endLine, "文本栏");
  if (endId == null) throw new Error("end-date-not-found");
  await sky.click({ app: CHROME, element_index: endId });
  await sky.press_key({ app: CHROME, key: "super+a" });
  await sky.type_text({ app: CHROME, text: businessDate });
  await sky.press_key({ app: CHROME, key: "Return" });
  state = await pollState(sky, (text) => text.includes(`Value: ${businessDate}, Placeholder: 结束日期`), 2_000);
  const queryId = exactLineId(state.text, /^\s*\d+ 按钮 查询$/, "按钮");
  await sky.click({ app: CHROME, element_index: queryId });
  for (let attempt = 0; attempt < 8; attempt += 1) {
    state = await getState(sky);
    if (state.text.includes(`Value: ${businessDate}, Placeholder: 开始日期`)
      && state.text.includes(`Value: ${businessDate}, Placeholder: 结束日期`)
      && state.text.includes("商家意向列表")
      && (parseRowsFromAx(state.text, 1).length > 0 || state.text.includes("暂无数据"))) return state;
  }
  throw new Error("today-query-not-ready");
}

async function goFirstPage(sky, state) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (parseRowsFromAx(state.text, 1).length === 0 && !state.text.includes("暂无数据")) {
      state = await pollState(sky, (text) => parseRowsFromAx(text, 1).length > 0 || text.includes("暂无数据"), 5_000);
    }
    const left = state.text.split("\n").find((line) => /按钮 .*left$/.test(line));
    if (!left || left.includes("disabled")) return state;
    const previousFirst = parseRowsFromAx(state.text, 1)[0]?.merchantId;
    await sky.click({ app: CHROME, element_index: roleId(left, "按钮") });
    state = await pollState(sky, (text) => {
      const currentFirst = parseRowsFromAx(text, 1)[0]?.merchantId;
      return Boolean(currentFirst && currentFirst !== previousFirst);
    }, 4_000);
    if (parseRowsFromAx(state.text, 1)[0]?.merchantId === previousFirst) {
      throw new Error("pagination-previous-did-not-change-page");
    }
  }
  throw new Error("pagination-first-page-failed");
}

async function collectAllPages(sky, state) {
  state = await goFirstPage(sky, state);
  const rows = [];
  let page = 1;
  while (true) {
    const pageRows = parseRowsFromAx(state.text, page);
    if (!pageRows.length && !state.text.includes("暂无数据")) throw new Error(`page-rows-not-ready:${page}`);
    pageRows.forEach((row) => rows.push({ ...row, sourceOrder: rows.length + 1 }));
    // 当前平台固定每页 10 条；不足 10 条即末页，避免依赖未暴露 disabled 的右箭头状态。
    if (pageRows.length < 10) break;
    const right = state.text.split("\n").find((line) => /按钮 .*right$/.test(line));
    if (!right || right.includes("disabled")) break;
    await sky.click({ app: CHROME, element_index: roleId(right, "按钮") });
    const previousFirst = pageRows[0]?.merchantId;
    state = await pollState(sky, (text) => parseRowsFromAx(text, page + 1)[0]?.merchantId !== previousFirst, 4_000);
    if (parseRowsFromAx(state.text, page + 1)[0]?.merchantId === previousFirst) {
      throw new Error(`pagination-next-did-not-change-page:${page}`);
    }
    page += 1;
    if (page > 100) throw new Error("pagination-overflow");
  }
  return { state, rows, pages: page };
}

async function ensureAscendingAndCollect(sky, state) {
  state = await goFirstPage(sky, state);
  const collected = await collectAllPages(sky, state);
  const rows = stableAscending(collected.rows.filter((row) => row.status === "待处理"));
  if (!isAscending(rows)) throw new Error("recommend-time-not-ascending");
  return { ...collected, rows, sortMethod: "local-stable-ascending" };
}

async function navigateToPage(sky, state, targetPage) {
  state = await goFirstPage(sky, state);
  let page = 1;
  while (page < targetPage) {
    const right = state.text.split("\n").find((line) => /按钮 .*right$/.test(line) && !line.includes("disabled"));
    if (!right) throw new Error(`page-not-reachable:${targetPage}`);
    const previousFirst = parseRowsFromAx(state.text, page)[0]?.merchantId;
    await sky.click({ app: CHROME, element_index: roleId(right, "按钮") });
    state = await pollState(sky, (text) => {
      const currentFirst = parseRowsFromAx(text, page + 1)[0]?.merchantId;
      return Boolean(currentFirst && currentFirst !== previousFirst);
    }, 4_000);
    if (parseRowsFromAx(state.text, page + 1)[0]?.merchantId === previousFirst) {
      throw new Error(`page-navigation-did-not-change:${page + 1}`);
    }
    page += 1;
  }
  const reached = parseRowsFromAx(state.text, targetPage);
  if (!reached.length) throw new Error(`page-content-not-ready:${targetPage}`);
  return state;
}

async function enrichDetails(sky, state, targets, businessDate) {
  const enriched = [];
  let currentPage = null;
  for (const target of targets) {
    if (currentPage !== target.page) {
      state = await navigateToPage(sky, state, target.page);
      currentPage = target.page;
    }
    let modal = null;
    const row = parseRowsFromAx(state.text, currentPage).find((item) => item.merchantId === target.merchantId);
    if (row?.detailButtonId) {
      await sky.click({ app: CHROME, element_index: row.detailButtonId });
      for (let attempt = 0; attempt < 10; attempt += 1) {
        modal = await getState(sky);
        try {
          if (parseDetailFromAx(modal.text).merchantId === target.merchantId) break;
        } catch { /* 弹层尚未进入可读态，继续轮询。 */ }
        await new Promise((resolve) => setTimeout(resolve, 180));
      }
    } else {
      modal = await openDetailByVisualRow(sky, target);
    }
    const detail = parseDetailFromAx(modal.text);
    if (detail.merchantId && detail.merchantId !== target.merchantId) throw new Error(`detail-id-mismatch:${target.merchantId}`);
    const closeId = exactLineId(modal.text, /^\s*\d+ 按钮 Close$/, "按钮");
    await sky.click({ app: CHROME, element_index: closeId });
    state = await pollState(sky, (text) => {
      let visibleId = "";
      try { visibleId = parseDetailFromAx(text).merchantId; } catch { /* 弹层节点已移除。 */ }
      return visibleId !== target.merchantId && parseRowsFromAx(text, currentPage).length > 0;
    }, 4_000);
    let remainingId = "";
    try { remainingId = parseDetailFromAx(state.text).merchantId; } catch { /* 已关闭。 */ }
    if (remainingId === target.merchantId) throw new Error(`detail-close-timeout:${target.merchantId}`);
    const merchant = {
      ...target,
      merchantName: detail.merchantName || target.merchantName,
      address: detail.address || target.listAddress,
      contact: detail.contact,
    };
    const message = formatMerchantMessage(merchant);
    enriched.push({ ...merchant, message, messageSha256: crypto.createHash("sha256").update(message).digest("hex") });
  }
  return { state, merchants: enriched };
}

export async function runMerchantCollector({
  sky,
  groupName = "臻肆测试群",
  businessDate = todayInShanghai(),
  initialCursor = null,
  receiptFile = "/tmp/zhensi_agent_merchants/collection_receipt.json",
} = {}) {
  if (!sky) throw new Error("sky-is-required");
  const started = performance.now();
  const receipt = { ok: false, executor: "merchant-collector", groupName, businessDate, stage: "preflight" };
  try {
    const cursorFile = cursorFileForGroup(groupName);
    const storedCursor = await readJson(cursorFile);
    const cursor = storedCursor?.verified === true ? storedCursor : initialCursor;
    if (!cursor) throw new Error("cursor-recovery-required");
    receipt.cursor = cursor;
    receipt.cursorSource = storedCursor?.verified === true ? "local" : "user-initial";
    receipt.entryUrl = BASE_HOME_URL;
    receipt.menuPath = [MENU_AGENT, MENU_CUSTOMER, MENU_INTENTION];

    seizeChromeFocus();
    let state = await openIntentionMerchantPage(sky);
    let preflightDetailId = "";
    try { preflightDetailId = parseDetailFromAx(state.text).merchantId; } catch { /* 无详情节点。 */ }
    if (/^\d+$/.test(preflightDetailId)) {
      seizeChromeFocus();
      const preflightClose = exactLineId(state.text, /^\s*\d+ 按钮 Close$/, "按钮");
      await sky.click({ app: CHROME, element_index: preflightClose });
      state = await pollState(sky, (text) => {
        let currentId = "";
        try { currentId = parseDetailFromAx(text).merchantId; } catch { /* 节点已移除。 */ }
        return isIntentionListOpen(text) && currentId !== preflightDetailId;
      }, 4_000);
    }
    state = await ensureChromeFullscreen(sky, state);
    if (!isIntentionListOpen(state.text)) {
      seizeChromeFocus();
      await sky.press_key({ app: CHROME, key: "super+r" });
      state = await pollState(sky, isIntentionListOpen, 10_000);
      receipt.retryCount = 1;
      receipt.preflightRecovery = "reload-stale-ax-modal";
    }
    if (!isIntentionListOpen(state.text)) {
      throw new Error("target-page-not-open");
    }
    receipt.stage = "query_today";
    seizeChromeFocus();
    state = await setTodayAndQuery(sky, state, businessDate);
    receipt.stage = "sort_and_collect";
    const collected = await ensureAscendingAndCollect(sky, state);
    receipt.rowCount = collected.rows.length;
    receipt.eligibility = "status=待处理";
    receipt.pages = collected.pages;
    receipt.sortMethod = collected.sortMethod;
    const targets = selectIncremental(collected.rows, cursor, businessDate);
    receipt.targetCount = targets.length;
    receipt.targets = targets.map(({ merchantName, merchantId, city, recommendTime, page, tableOrder }) => ({
      merchantName, merchantId, city, recommendTime, page, tableOrder,
    }));
    receipt.stage = "details";
    const details = await enrichDetails(sky, collected.state, targets, businessDate);
    receipt.merchants = details.merchants;
    receipt.messages = details.merchants.map((merchant) => ({
      merchantId: merchant.merchantId,
      merchantName: merchant.merchantName,
      recommendTime: merchant.recommendTime,
      tableOrder: merchant.tableOrder,
      text: merchant.message,
      sha256: merchant.messageSha256,
    }));
    receipt.ok = true;
    receipt.stage = "complete";
    receipt.elapsedMs = Math.round(performance.now() - started);
    await writeJsonAtomic(receiptFile, receipt);
    return receipt;
  } catch (error) {
    receipt.error = String(error?.message ?? error);
    receipt.elapsedMs = Math.round(performance.now() - started);
    await writeJsonAtomic(receiptFile, receipt);
    return receipt;
  }
}

export function selfTestMerchantCollector() {
  const sample = [
    { merchantName: "贵州水城羊肉粉", merchantId: "1338859678", recommendTime: "2026-09-02 16:08:45", sourceOrder: 1 },
    { merchantName: "冰屿季三文鱼", merchantId: "1352896942", recommendTime: "2026-09-02 16:29:13", sourceOrder: 2 },
    { merchantName: "御京荷北京烤鸭", merchantId: "1332573048", recommendTime: "2026-09-02 19:16:10", sourceOrder: 3 },
    { merchantName: "吉满洞朝鲜族汤饭", merchantId: "1340954969", recommendTime: "2026-09-02 20:54:19", sourceOrder: 4 },
  ];
  const cursor = { merchantId: "1352896942", recommendTime: "2026-09-02 16:29:13" };
  const selected = selectIncremental(sample, cursor, "2026-09-02");
  if (selected.map((row) => row.merchantId).join(",") !== "1332573048,1340954969") throw new Error("incremental-order-test");
  const sameTime = stableAscending([
    { merchantId: "2", recommendTime: "2026-09-02 10:00:00", sourceOrder: 2 },
    { merchantId: "1", recommendTime: "2026-09-02 10:00:00", sourceOrder: 1 },
  ]);
  if (sameTime.map((row) => row.merchantId).join(",") !== "1,2") throw new Error("same-time-stability-test");
  if (!formatMerchantMessage({ city: "", contact: "", merchantName: "店", address: "" }).includes("（商家联系人字段缺失）")) throw new Error("missing-field-test");
  if (cursorFileForGroup("臻肆测试群").endsWith("cursor.json")) throw new Error("group-isolation-test");
  const crossDay = selectIncremental(sample, { merchantId: "x", recommendTime: "2026-09-01 23:59:59" }, "2026-09-02");
  if (crossDay.length !== sample.length) throw new Error("cross-day-test");
  if (BASE_HOME_URL !== "https://open.shop.ele.me/manager/base/home") throw new Error("base-home-url-test");
  if (MENU_INTENTION !== "意向商户管理") throw new Error("menu-label-test");
  if (!isIntentionListOpen(`${MENU_INTENTION}\n商家意向列表`)) throw new Error("intention-open-predicate-test");
  if (!DESKTOP_BRIDGE.endsWith("chrome_desktop_bridge.py")) throw new Error("desktop-bridge-path-test");
  const bridgeSelf = JSON.parse(execFileSync(PHONE_VENV_PYTHON, [DESKTOP_BRIDGE, "--self-test"], { encoding: "utf8" }));
  if (!bridgeSelf.ok) throw new Error("desktop-bridge-self-test");
  return { ok: true, tests: 10, bridgeSelfTest: bridgeSelf };
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  const args = new Set(process.argv.slice(2));
  if (args.has("--self-test")) {
    const result = selfTestMerchantCollector();
    console.log(JSON.stringify(result, null, 2));
    process.exit(result.ok ? 0 : 1);
  }
  if (args.has("--preflight-nav")) {
    // 计时前预检统一走桌面桥，避免会话无 sky 时临场拼脚本。
    try {
      const output = execFileSync(PHONE_VENV_PYTHON, [DESKTOP_BRIDGE, "--preflight-nav"], { encoding: "utf8" });
      process.stdout.write(output.endsWith("\n") ? output : `${output}\n`);
      const payload = JSON.parse(output);
      process.exit(payload.ok ? 0 : 1);
    } catch (error) {
      console.log(JSON.stringify({ ok: false, mode: "preflight-nav", error: String(error?.message || error) }, null, 2));
      process.exit(1);
    }
  }
  if (args.has("--collect-ocr-bridge")) {
    const group = process.argv.includes("--group")
      ? process.argv[process.argv.indexOf("--group") + 1]
      : "臻肆测试群";
    const out = process.argv.includes("--out")
      ? process.argv[process.argv.indexOf("--out") + 1]
      : "/tmp/zhensi_agent_merchants/collection_receipt.json";
    try {
      const output = execFileSync(
        PHONE_VENV_PYTHON,
        [DESKTOP_BRIDGE, "--collect", "--group", group, "--out", out],
        { encoding: "utf8" },
      );
      process.stdout.write(output.endsWith("\n") ? output : `${output}\n`);
      const payload = JSON.parse(output);
      process.exit(payload.ok ? 0 : 1);
    } catch (error) {
      console.log(JSON.stringify({ ok: false, mode: "collect-ocr-bridge", error: String(error?.stderr || error?.message || error) }, null, 2));
      process.exit(1);
    }
  }
}
