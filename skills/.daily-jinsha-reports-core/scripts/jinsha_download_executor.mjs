import { execFile as execFileCallback } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";

const execFile = promisify(execFileCallback);
const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const CHECKBOX_PROBE = path.join(SCRIPT_DIR, "checkbox_probe.py");
const OCR_BIN = path.resolve(SCRIPT_DIR, "../../workflows/daily-top10-to-wechat-group/scripts/ocr_vision");
const PYTHON = "/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python";

export function yesterdayInShanghai(now = new Date()) {
  const value = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now).map((part) => [part.type, part.value]));
  const date = new Date(`${value.year}-${value.month}-${value.day}T00:00:00+08:00`);
  date.setUTCDate(date.getUTCDate() - 1);
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit",
  }).format(date);
}

function elementIndex(text, pattern) {
  const line = text.split("\n").find((value) => pattern.test(value));
  return Number(line?.match(/^\s*(\d+)/)?.[1]);
}

async function runningAppPath() {
  const { stdout } = await execFile("/bin/ps", ["-axo", "command="], { maxBuffer: 4 * 1024 * 1024 });
  const executable = stdout.split("\n").map((line) => line.trim())
    .find((line) => /\/金鲨数据\.app\/Contents\/MacOS\/jinsha$/.test(line));
  if (!executable) throw new Error("jinsha-process-not-running");
  return executable.replace(/\/Contents\/MacOS\/jinsha$/, "");
}

async function inventory(directory) {
  return new Map((await fs.readdir(directory, { withFileTypes: true }))
    .filter((entry) => entry.isFile() && /\.xlsx$/i.test(entry.name))
    .map((entry) => [entry.name, true]));
}

async function validateXlsx(file) {
  const { stdout } = await execFile("/usr/bin/unzip", ["-Z1", file], { maxBuffer: 8 * 1024 * 1024 });
  const names = new Set(stdout.split("\n"));
  if (!names.has("[Content_Types].xml") || !names.has("xl/workbook.xml")) throw new Error("xlsx-structure-invalid");
}

async function sha256(file) {
  return crypto.createHash("sha256").update(await fs.readFile(file)).digest("hex");
}

async function waitNewWorkbook(directory, baseline, timeoutMs = 60_000) {
  const deadline = performance.now() + timeoutMs;
  let prior = null;
  let stable = 0;
  while (performance.now() <= deadline) {
    const current = await inventory(directory);
    const names = [...current.keys()].filter((name) => !baseline.has(name));
    if (names.length > 1) throw new Error(`new-workbook-ambiguous:${names.length}`);
    if (names.length === 1) {
      const file = path.join(directory, names[0]);
      const stat = await fs.stat(file);
      stable = stat.size > 0 && stat.size === prior ? stable + 1 : 0;
      prior = stat.size;
      if (stable >= 2) {
        await validateXlsx(file);
        return { file, name: names[0], size: stat.size, sha256: await sha256(file) };
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 350));
  }
  throw new Error("download-result-unknown");
}

function reportName(platform, businessDate) {
  return `金鲨${platform === "meituan" ? "美团" : "淘宝闪购"}_${businessDate}至${businessDate}.xlsx`;
}

async function finishSavePanel(sky, app, downloadDir, platform, businessDate, baseline) {
  let state;
  const deadline = performance.now() + 4_000;
  do {
    state = await sky.get_app_state({ app, disableDiff: true });
    if (state.text.includes("ID: save-panel")) break;
    await new Promise((resolve) => setTimeout(resolve, 180));
  } while (performance.now() < deadline);
  if (!state.text.includes("ID: save-panel")) throw new Error(`${platform}-save-panel-not-open`);
  const nameField = elementIndex(state.text, /^\s*\d+ 文本栏 \(settable\) Value: .*ID: saveAsNameTextField$/);
  if (!Number.isFinite(nameField)) throw new Error(`${platform}-save-name-field-missing`);
  const name = reportName(platform, businessDate);
  await sky.set_value({ app, element_index: nameField, value: name });
  state = await sky.get_app_state({ app, disableDiff: true });
  if (!state.text.includes(`Value: ${name}, ID: saveAsNameTextField`)) throw new Error(`${platform}-save-name-mismatch`);
  const saveButton = elementIndex(state.text, /^\s*\d+ 按钮 存储, ID: OKButton$/);
  if (!Number.isFinite(saveButton)) throw new Error(`${platform}-save-button-missing`);
  await sky.click({ app, element_index: saveButton });
  const report = await waitNewWorkbook(downloadDir, baseline);
  if (report.name !== name) throw new Error(`${platform}-saved-name-mismatch:${report.name}`);
  return report;
}

export async function finalizeOpenSavePanel({ sky, app, platform, businessDate = yesterdayInShanghai(), downloadDir = path.join(os.homedir(), "Downloads") }) {
  const baseline = await inventory(downloadDir);
  return finishSavePanel(sky, app, downloadDir, platform, businessDate, baseline);
}

function platformReady(text, platform, businessDate) {
  const selected = platform === "meituan"
    ? /单选按钮 美团外卖, Value: 1/.test(text)
    : /单选按钮 淘宝闪购, Value: 1/.test(text);
  const plan = platform === "meituan"
    ? /下载方案[\s\S]*Value: .*美团.*日报/.test(text)
    : /下载方案[\s\S]*Value: .*?(?:饿了么|淘宝).*日报/.test(text);
  return selected && plan
    && text.includes("多店数据")
    && text.includes(`Value: ${businessDate}, Placeholder: 开始日期`)
    && text.includes(`Value: ${businessDate}, Placeholder: 结束日期`)
    && (platform === "meituan" ? /已选择 \(36\)/.test(text) : /已选择 \((?:34|36)\)/.test(text));
}

async function ensurePlan(sky, app, state, platform) {
  const exact = platform === "meituan" ? "最终美团最新日报" : null;
  const selectedPattern = platform === "meituan"
    ? new RegExp(`Value: ${exact}`)
    : /Value: 饿了么.*最新最新/;
  if (selectedPattern.test(state.text)) return state;
  const pattern = platform === "meituan"
    ? new RegExp(`^\\s*\\d+ 文本 ${exact}$`)
    : /^\s*\d+ 文本 饿了么.*最新最新$/;
  let option = elementIndex(state.text, pattern);
  if (!Number.isFinite(option)) {
    const field = elementIndex(state.text, /^\s*\d+ 文本栏 \(settable\) 请选择下载方案$/);
    if (!Number.isFinite(field)) throw new Error(`${platform}-plan-field-not-found`);
    await sky.click({ app, element_index: field });
    state = await sky.get_app_state({ app, disableDiff: true });
    option = elementIndex(state.text, pattern);
  }
  if (!Number.isFinite(option)) throw new Error(`${platform}-plan-option-not-found`);
  await sky.click({ app, element_index: option });
  return sky.get_app_state({ app, disableDiff: true });
}

async function selectPlatform(sky, app, state, platform, businessDate) {
  const alreadySelected = platform === "meituan"
    ? /单选按钮 美团外卖, Value: 1/.test(state.text)
    : /单选按钮 淘宝闪购, Value: 1/.test(state.text);
  if (!alreadySelected) {
    const expected = platform === "meituan" ? "美团外卖" : "淘宝闪购";
    const index = elementIndex(state.text, new RegExp(`^\\s*\\d+ 单选按钮 ${expected}, Value:`));
    if (!Number.isFinite(index)) throw new Error(`${platform}-radio-not-found`);
    await sky.click({ app, element_index: index });
    state = await sky.get_app_state({ app, disableDiff: true });
  }
  state = await ensurePlan(sky, app, state, platform);
  if (!platformReady(state.text, platform, businessDate)) throw new Error(`${platform}-page-contract-failed`);
  return state;
}

async function checkboxState(screenshot, labels) {
  const { stdout } = await execFile(PYTHON, [CHECKBOX_PROBE, fileURLToPath(screenshot.url), OCR_BIN, ...labels]);
  return JSON.parse(stdout);
}

async function ensureTaobaoMetrics(sky, app, state) {
  if (!state.screenshot) throw new Error("taobao-screenshot-missing");
  let result = await checkboxState(state.screenshot, ["单均实付", "单均到手"]);
  for (const label of ["单均实付", "单均到手"]) {
    if (result[label]?.ok) continue;
    const point = result[label]?.click;
    if (!Array.isArray(point)) throw new Error(`taobao-metric-not-locatable:${label}`);
    try {
      await sky.click({ app, x: point[0], y: point[1] });
    } catch (error) {
      if (!String(error).includes("noWindowsAvailable")) throw error;
      await sky.perform_secondary_action({ app, element_index: 0, action: "Raise" });
      state = await sky.get_app_state({ app, disableDiff: true });
      if (!state.screenshot) throw error;
      result = await checkboxState(state.screenshot, ["单均实付", "单均到手"]);
      const retryPoint = result[label]?.click;
      if (!Array.isArray(retryPoint)) throw error;
      await sky.click({ app, x: retryPoint[0], y: retryPoint[1] });
    }
    state = await sky.get_app_state({ app, disableDiff: true });
    if (!state.screenshot) throw new Error("taobao-screenshot-missing-after-toggle");
    result = await checkboxState(state.screenshot, ["单均实付", "单均到手"]);
  }
  if (!["单均实付", "单均到手"].every((label) => result[label]?.ok)) throw new Error("taobao-extra-metrics-not-selected");
  if (!/已选择 \(36\)/.test(state.text)) throw new Error("taobao-selected-count-not-36");
  return { state, metrics: result };
}

async function writeReceipt(file, receipt) {
  await fs.mkdir(path.dirname(file), { recursive: true });
  const temporary = `${file}.${Date.now()}.tmp`;
  await fs.writeFile(temporary, `${JSON.stringify(receipt, null, 2)}\n`, { mode: 0o600 });
  await fs.rename(temporary, file);
}

async function downloadPlatform(sky, app, state, platform, businessDate, downloadDir, receipt) {
  state = await selectPlatform(sky, app, state, platform, businessDate);
  if (platform === "taobao") {
    const checked = await ensureTaobaoMetrics(sky, app, state);
    state = checked.state;
    receipt.taobaoMetrics = checked.metrics;
  }
  const baseline = await inventory(downloadDir);
  const button = elementIndex(state.text, /^\s*\d+ 按钮 .*下载数据$/);
  if (!Number.isFinite(button)) throw new Error(`${platform}-download-button-not-found`);
  receipt.clickAttempts[platform] += 1;
  await sky.click({ app, element_index: button });
  const report = await finishSavePanel(sky, app, downloadDir, platform, businessDate, baseline);
  return { state: await sky.get_app_state({ app, disableDiff: true }), report };
}

export async function runJinshaDownload({
  sky,
  app = null,
  businessDate = yesterdayInShanghai(),
  downloadDir = path.join(os.homedir(), "Downloads"),
  receiptFile = "/tmp/zhensi_jinsha_reports/download_receipt.json",
  resumeMeituanFile = null,
} = {}) {
  if (!sky) throw new Error("sky-is-required");
  const started = performance.now();
  const receipt = { ok: false, executor: "jinsha-download", businessDate, clickAttempts: { meituan: 0, taobao: 0 }, stage: "preflight" };
  try {
    app = app ?? await runningAppPath();
    let state = await sky.get_app_state({ app, disableDiff: true });
    if (!state.text.includes("data.guoshuyufen.com/#/reportDownload")) throw new Error("jinsha-report-page-not-open");
    let result;
    if (resumeMeituanFile) {
      const file = path.resolve(resumeMeituanFile);
      const stat = await fs.stat(file);
      await validateXlsx(file);
      receipt.meituan = { file, name: path.basename(file), size: stat.size, sha256: await sha256(file), resumed: true };
      if (receipt.meituan.name !== reportName("meituan", businessDate)) throw new Error("meituan-resume-name-mismatch");
    } else {
      receipt.stage = "meituan";
      result = await downloadPlatform(sky, app, state, "meituan", businessDate, downloadDir, receipt);
      receipt.meituan = result.report;
      state = result.state;
    }
    receipt.stage = "taobao";
    result = await downloadPlatform(sky, app, state, "taobao", businessDate, downloadDir, receipt);
    receipt.taobao = result.report;
    receipt.ok = true;
    receipt.stage = "complete";
    receipt.elapsedMs = Math.round(performance.now() - started);
    await writeReceipt(receiptFile, receipt);
    return receipt;
  } catch (error) {
    receipt.reason = String(error?.message ?? error);
    receipt.elapsedMs = Math.round(performance.now() - started);
    await writeReceipt(receiptFile, receipt);
    throw error;
  }
}

export async function selfTest() {
  const failures = [];
  if (yesterdayInShanghai(new Date("2026-09-03T02:00:00Z")) !== "2026-09-02") failures.push("date");
  if (!platformReady("单选按钮 美团外卖, Value: 1\n多店数据\n文本栏 Value: 2026-09-02, Placeholder: 开始日期\n文本栏 Value: 2026-09-02, Placeholder: 结束日期\n下载方案\n文本栏 Value: 最终美团最新日报\n已选择 (36)", "meituan", "2026-09-02")) failures.push("meituan-contract");
  if (failures.length) throw new Error(`self-test-failed:${failures.join(",")}`);
  return { ok: true, tests: 2 };
}
