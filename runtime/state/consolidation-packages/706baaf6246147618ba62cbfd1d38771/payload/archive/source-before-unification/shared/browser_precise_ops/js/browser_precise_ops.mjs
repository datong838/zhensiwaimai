// browser_precise_ops.mjs — ① ② ③ ④ 的 Node 镜像（供 merchant_collector_executor.mjs 等复用）。
// 与 Python 版 shared/browser_precise_ops 行为对齐。纯 stdlib（node:fs/node:path/node:crypto）。
//
// 能力：
//   waitUntil(predicate, {timeoutMs, pollMs, label})  -> ② 成功校验 + 超时重试
//   humanDelay(minMs, maxMs) / typeCharDelay()        -> ③ 拟人节奏
//   antiDetectLaunchArgs(extra)                       -> ③ 反检测启动参数
//   writeStatus/readStatus/readSmsCode                -> ① 登录/挑战状态文件协议
//   scan(text) / guardOrDie(text) / redact(text)      -> ④ fail-closed 出站内容闸门

import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

const STATES = ["starting", "qr_ready", "scanned", "sms_required", "verifying", "success", "expired", "error"];

// ── ② 成功校验 + 超时重试 ────────────────────────────────────────────────
export async function waitUntil(predicate, { timeoutMs = 10_000, pollMs = 300, label = "condition" } = {}) {
  const deadline = performance.now() + timeoutMs;
  let last = null;
  while (performance.now() < deadline) {
    try {
      last = predicate();
    } catch {
      last = null;
    }
    if (last) return last;
    await new Promise((r) => setTimeout(r, pollMs));
  }
  throw new Error(`waitUntil-timeout:${label}:>${timeoutMs}ms`);
}

// ── ③ 拟人节奏 ───────────────────────────────────────────────────────────
export function humanDelay(minMs = 120, maxMs = 420) {
  const ms = Math.floor(minMs + Math.random() * (maxMs - minMs));
  return new Promise((r) => setTimeout(r, ms)).then(() => ms);
}
export function typeCharDelay() {
  const ms = 30 + Math.floor(Math.random() * 80); // 30~110ms
  return new Promise((r) => setTimeout(r, ms)).then(() => ms);
}
export function antiDetectLaunchArgs(extra = []) {
  return ["--disable-blink-features=AutomationControlled", "--lang=zh-CN", "--no-first-run", "--no-default-browser-check", ...extra];
}

// ── ① 登录/挑战状态文件协议 ─────────────────────────────────────────────
export function writeStatus(file, state, { message = "", qr = "" } = {}) {
  if (!file) return;
  if (!STATES.includes(state)) throw new Error(`bad-state:${state}`);
  const data = { state, message, qr, ts: Math.floor(Date.now() / 1000) };
  const dir = path.dirname(file);
  fs.mkdirSync(dir, { recursive: true });
  const tmp = `${file}.${Date.now()}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(data), { mode: 0o600 });
  fs.renameSync(tmp, file);
}
export function readStatus(file) {
  try {
    const data = JSON.parse(fs.readFileSync(file, "utf8"));
    if (STATES.includes(data.state)) return data;
  } catch { /* 损坏/缺失 */ }
  return { state: "unknown", message: "", qr: "", ts: 0 };
}
export function readSmsCode(file) {
  if (!file || !fs.existsSync(file)) return "";
  try {
    const code = fs.readFileSync(file, "utf8").trim();
    fs.unlinkSync(file); // 一次性消费
    return code;
  } catch {
    return "";
  }
}

// ── ④ fail-closed 出站内容闸门 ──────────────────────────────────────────
const BLOCK_PATTERNS = [
  [/(\b(?:sk-|api[_-]?key|secret|token|access[_-]?key|password)\s*[:=]\s*\S+)/i],
  [/\bsk-(?:proj-)?[A-Za-z0-9]{20,}/i],
  [/(\/Users\/ddt\/\S+|\/home\/\w+\/\S+|C:\\[\\A-Za-z0-9 ._-]+)/],
  [/\b(AOS_[A-Z_]+|EASEL_[A-Z_]+|OPENAI_API_KEY|ANTHROPIC_API_KEY|HTTPS?_PROXY)\b/i],
  [/\b(proxy|代理)\b[^\n]{0,12}?\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b/i],
  [/\b((?:localhost|127\.0\.0\.1|taobao-agent-service|easel-gateway|openclaw)[.:]\S*)\b/i],
];
const WARN_PATTERNS = [
  [/(由\s?AI\s?生成|AI\s?生成|OpenAI|Claude|Anthropic|system\s?prompt|大模型|人工智能生成)/i],
  [/\b(claude-[a-z0-9.-]+|gpt-[a-z0-9.-]+|gpt-image-\d|deepseek-[a-z0-9.-]+)\b/i],
];
export const EXIT_LEAK = 7;

export function scan(text) {
  const block = BLOCK_PATTERNS.filter(([re]) => re.test(text)).map(([re]) => re.source);
  const warn = WARN_PATTERNS.filter(([re]) => re.test(text)).map(([re]) => re.source);
  return { block, warn };
}
export function redact(text) {
  let out = text;
  for (const [re] of BLOCK_PATTERNS) out = out.replace(re, "[已隐藏]");
  return out;
}
export function guardOrDie(text, { label = "outbound" } = {}) {
  const res = scan(text);
  if (res.block.length) {
    process.stderr.write(`CONTENT_GUARD BLOCK: ${label} 含内部泄露 [${res.block.join(",")}]，已拦发\n`);
    process.exit(EXIT_LEAK);
  }
  if (res.warn.length) {
    process.stderr.write(`CONTENT_GUARD WARN: ${label} 含 AI 措辞/模型名 [${res.warn.join(",")}]，仅告警不拦\n`);
  }
  return res;
}

// ── selftest ──────────────────────────────────────────────────────────────
export async function selfTest() {
  let n = 0;
  const ok = (c) => { if (!c) throw new Error("self-test-fail"); n += 1; };
  ok(scan("api_key=sk-abc123def456ghi789jkl").block.length >= 1);
  ok(scan("see /Users/ddt/work/x/secret.txt").block.length === 1);
  ok(scan("proxy 192.168.1.50").block.length === 1);
  ok(scan("AOS_DATABASE_URL=xxx").block.length === 1);
  ok(scan("（商家联系人字段缺失）\n贵州水城羊肉粉").block.length === 0);
  ok(scan("本文由 AI 生成").warn.length === 1);
  // waitUntil 满足
  const r = await waitUntil(() => true, { timeoutMs: 500, pollMs: 50, label: "t" });
  ok(r === true);
  // waitUntil 超时
  let threw = false;
  try { await waitUntil(() => false, { timeoutMs: 200, pollMs: 50, label: "never" }); } catch { threw = true; }
  ok(threw);
  // 状态协议
  const dir = fs.mkdtempSync("/tmp/bpo-js-selftest-");
  const sp = path.join(dir, "login.json");
  const cp = path.join(dir, "x.code");
  writeStatus(sp, "qr_ready", { message: "请扫码" });
  ok(readStatus(sp).state === "qr_ready");
  writeStatus(sp, "sms_required");
  ok(readStatus(sp).state === "sms_required");
  fs.writeFileSync(cp, "654321");
  ok(readSmsCode(cp) === "654321");
  ok(readSmsCode(cp) === "");
  return { ok: true, tests: n };
}
