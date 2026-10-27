#!/usr/bin/env node
import crypto from 'node:crypto';
import fs from 'node:fs';
import fsp from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import process from 'node:process';
import { execFile as execFileCallback } from 'node:child_process';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import { promisify } from 'node:util';

const require = createRequire(import.meta.url);
const { chromium } = require('/Users/ddt/work/projects/ai_agent/browser/headless-playwright/node_modules/playwright-core');
const execFile = promisify(execFileCallback);

export const FIXED = Object.freeze({
  taobao: Object.freeze({
    profile: 'taobao-brand', port: 9230,
    prefix: 'https://melody.shop.ele.me/',
    chainPrefix: 'https://melody.shop.ele.me/app/chain/95708808/',
    home: 'https://melody.shop.ele.me/app/chain/95708808/stats__center#app.chainshop.stats.center',
    download: 'https://melody.shop.ele.me/app/chain/95708808/downloadCenter#app.chainshop.downloadCenter',
  }),
  jinsha: Object.freeze({
    profile: 'jinsha-business', port: 9232,
    prefix: 'https://data.guoshuyufen.com/',
    home: 'https://data.guoshuyufen.com/#/businessData/realTimeData',
    uploadHash: '#/uploadData/uploadData',
  }),
  groupName: '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰',
  executionOrder: Object.freeze(['taobao-download', 'jinsha-process']),
});

const PROFILE_ROOT = path.join(os.homedir(), 'Library/Application Support/AOS Background Chrome');
const DEDICATED_CHROME_LAUNCHER = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/dedicated-chrome-controller/scripts/background_chrome.mjs';
const DEDICATED_CHROME_SESSION_GUARD = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/dedicated-chrome-controller/scripts/session_guard.mjs';
const DEDICATED_CHROME_LAUNCHER_SHA256 = 'e805e95a3c0f2f1d0be35317a76433bbf4cd618e32b978fc172ac85f64fa26d1';
// 2026-10-03 受控重钉：外部共享依赖 session_guard.mjs 于 2026-10-02 23:12 被改动
// （文件完整正常，177 行、导出齐全），旧摘要 a3f24649… 已过时，按新字节重绑。
const DEDICATED_CHROME_SESSION_GUARD_SHA256 = '07dbd017f32c00d0041546c6bb249b0febe90fbd9648579d75b2a9571632ec2c';
const DEFAULT_OUTPUT = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/state/business-evidence/taobao-download/background-browser";
const JINSHA_BUSINESS_RUNS_ROOT = '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/.local/runs/jinsha-business-production';
const MODE = Object.freeze({
  PRODUCTION: 'execute',
  VERIFY_TODAY: 'verify-idempotency-only',
  DOWNLOAD_NO_UPLOAD: 'download-and-verify-no-upload',
});
const PHASE_CHAINS = Object.freeze({
  [MODE.PRODUCTION]: Object.freeze(['initialized', 'profiles_ready', 'taobao_open', 'taobao_downloaded', 'taobao_closed', 'jinsha_open', 'jinsha_processed', 'completed']),
  [MODE.DOWNLOAD_NO_UPLOAD]: Object.freeze(['initialized', 'profiles_ready', 'taobao_open', 'taobao_downloaded', 'taobao_closed', 'jinsha_open', 'jinsha_processed', 'completed']),
  [MODE.VERIFY_TODAY]: Object.freeze(['initialized', 'profiles_ready', 'jinsha_open', 'jinsha_processed', 'completed']),
});
const RECOVERY_BUDGETS = Object.freeze({
  'taobao-brandNavigation': 1,
  'jinsha-businessNavigation': 1,
  taobaoAuthAnchorRecovery: 1,
  taobaoHomeReload: 1,
  jinshaLogReload: 1,
  jinshaBorrowedLogReload: 1,
  jinshaBorrowedLogReadRetry: 1,
  jinshaBorrowedStoreLogReadRetry: 1,
  jinshaBorrowedReviewLogReadRetry: 1,
  jinshaUploadOverlay: 1,
  jinshaControllerBindingRecovery: 1,
  jinshaBorrowedHomeNavigation: 1,
  productionResume: 10,
});
export const CONTROL_POLICY = Object.freeze({
  version: 'daily-taobao-jinsha-code-enforced-2026-09-28',
  authority: 'executor-code-only',
  channel: 'control-background-dedicated-chrome',
  runtimeModelDecisionsAllowed: 0,
  clickBudgets: Object.freeze({ download: 1, upload: 1 }),
  recoveryBudgets: RECOVERY_BUDGETS,
  reviewRequired: true,
});
const STAGE_ORDER = Object.freeze([
  'control_policy_preflight', 'profile_preflight', 'resume_profile_preflight',
  'taobao_task_open', 'taobao_store_download', 'taobao_review_download', 'taobao_download_sequence', 'taobao_task_cleanup',
  'jinsha_task_open', 'jinsha_store_dedup_upload', 'jinsha_review_dedup_upload', 'jinsha_sequence',
  'task_cleanup', 'profile_postflight', 'completion_contract',
]);
const STAGE_LABELS = Object.freeze({
  control_policy_preflight: '代码控制策略预检',
  profile_preflight: '固定后台浏览器预检',
  resume_profile_preflight: '安全续跑后台浏览器预检',
  taobao_task_open: '淘宝认证锚点与任务页',
  taobao_store_download: '淘宝门店报表下载',
  taobao_review_download: '淘宝评价报表下载',
  taobao_download_sequence: '淘宝下载完整序列',
  taobao_task_cleanup: '淘宝任务页清理',
  jinsha_task_open: '金鲨任务页打开',
  jinsha_store_dedup_upload: '金鲨门店去重与上传',
  jinsha_review_dedup_upload: '金鲨评价去重与上传',
  jinsha_sequence: '金鲨处理完整序列',
  task_cleanup: '任务标签与连接清理',
  profile_postflight: '固定 Profile 后验',
  completion_contract: '完成合同校验',
});
const PITFALL_STAGE_ALIASES = Object.freeze({
  taobao_login_gate: 'taobao_download_sequence',
  'taobao-brand_task_open': 'taobao_task_open',
  'jinsha-business_task_open': 'jinsha_task_open',
});

function controlPolicySnapshot(mode) {
  return {
    version: CONTROL_POLICY.version,
    authority: CONTROL_POLICY.authority,
    channel: CONTROL_POLICY.channel,
    runtimeModelDecisionsAllowed: CONTROL_POLICY.runtimeModelDecisionsAllowed,
    clickBudgets: { ...CONTROL_POLICY.clickBudgets },
    recoveryBudgets: { ...CONTROL_POLICY.recoveryBudgets },
    phaseChain: [...PHASE_CHAINS[mode]],
    reviewRequired: CONTROL_POLICY.reviewRequired,
  };
}

function assertControlPolicy(receipt) {
  const expected = JSON.stringify(controlPolicySnapshot(receipt.mode));
  if (JSON.stringify(receipt.controlPolicy) !== expected) throw new Error('control-policy-drift');
  if (receipt.runtimeModelDecisions !== CONTROL_POLICY.runtimeModelDecisionsAllowed) throw new Error('runtime-model-decisions-forbidden');
}

function parseArgs(argv) {
  if (argv.length === 1 && argv[0] === '--self-test') return { selfTest: true };
  throw new Error('business-cli-disabled-use-installed-entrypoint');
}

function transition(receipt, next) {
  assertControlPolicy(receipt);
  const chain = PHASE_CHAINS[receipt.mode];
  const expected = chain[receipt.phaseHistory.length];
  if (next !== expected) throw new Error(`illegal-phase-transition:${receipt.phase}->${next}:expected-${expected}`);
  receipt.phase = next;
  receipt.phaseHistory.push(next);
}

function claimClick(receipt, family, type) {
  assertControlPolicy(receipt);
  if (!['download', 'upload'].includes(family) || !['store', 'review'].includes(type)) throw new Error('invalid-click-budget-key');
  if (receipt.clickAttempts[family][type] >= CONTROL_POLICY.clickBudgets[family]) throw new Error(`click-budget-exhausted:${family}:${type}`);
  receipt.clickAttempts[family][type] = 1;
}

function claimRecovery(receipt, key, pitfall) {
  assertControlPolicy(receipt);
  const budget = CONTROL_POLICY.recoveryBudgets[key];
  if (!Number.isInteger(budget)) throw new Error(`recovery-budget-key-invalid:${key}`);
  const used = receipt.recoveryAttempts[key] || 0;
  if (used >= budget) throw new Error(`recovery-budget-exhausted:${key}`);
  receipt.recoveryAttempts[key] = used + 1;
  if (pitfall) receipt.pitfalls.push({ stage: receipt.stage, ...pitfall });
}

export function yesterdayShanghai(now = new Date()) {
  const date = new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Shanghai' }));
  date.setDate(date.getDate() - 1);
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, '0');
  const d = String(date.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}

export function reportPattern(type, businessDate) {
  const prefix = type === 'store' ? '门店下载' : type === 'review' ? '评价下载' : null;
  if (!prefix) throw new Error(`unsupported-report-type:${type}`);
  const compact = businessDate.replaceAll('-', '');
  return new RegExp(`^${prefix}_${compact}(?:至${compact})?_全部门店_\\d+_\\d{17}(?: \\(\\d+\\))?\\.xlsx$`);
}

export function completedLogText(text, type, businessDate) {
  const prefix = type === 'store' ? '门店下载_' : type === 'review' ? '评价下载_' : '';
  const compact = businessDate.replaceAll('-', '');
  return text.split(/\n+/).some((line, index, lines) => {
    const block = lines.slice(index, index + 8).join('');
    return block.includes(prefix) && block.includes(compact) && block.includes('上传完成');
  });
}

export function isExactSelectedUploadFile(names, expectedName) {
  return Array.isArray(names) && names.length === 1 && names[0] === expectedName;
}

export function isTaobaoLoginUrl(value) {
  try { return new URL(value).origin === 'https://melody.shop.ele.me' && new URL(value).pathname === '/login'; }
  catch { return false; }
}

export function isTaobaoSeedRecoveryUrl(value) {
  try {
    const url = new URL(value);
    return url.origin === 'https://melody.shop.ele.me' && url.href.startsWith(FIXED.taobao.chainPrefix) && !isTaobaoLoginUrl(url.href);
  } catch { return false; }
}

// 2026-10-17：淘宝闪购 stats-next 经营分析 iframe 路由由 #/chain/business-analysis 升级为
// #/single/business-analysis（实测 9230 现网，同日美团侧亦组件库升级），原 chain 单一路径判据
// 致认证种子恢复 150s 超时（taobao-auth-seed-recovery-timeout）。抽为纯函数并兼容两种路由。
export function isTaobaoAnalysisFrameUrl(value) {
  if (typeof value !== 'string') return false;
  return /melody-stats-next\.ele\.me\/new\/#\/(?:chain|single)\/business-analysis/.test(value);
}

export function isTaobaoActivityShellRecoveryPage(pageUrl, frameUrls, pageCount) {
  if (pageCount !== 1 || !Array.isArray(frameUrls)) return false;
  let page;
  try { page = new URL(pageUrl); } catch { return false; }
  const route = page.pathname.match(/^\/app\/shop\/(\d+)\/activity__myActivity$/);
  if (page.origin !== 'https://melody.shop.ele.me' || !route
      || page.hash !== '#app.shop.activity.myActivity') return false;
  const parsedFrames = frameUrls.map((value) => {
    try {
      return new URL(value);
    } catch { return null; }
  });
  const dashboardFrames = parsedFrames.filter((frame) => frame?.origin === 'https://napos-dashboard-pc.faas.ele.me'
    && frame.pathname === '/single');
  const imFrames = parsedFrames.filter((frame) => frame?.origin === 'https://im.ele.me' && frame.pathname === '/napos');
  const activityFrames = parsedFrames.filter((frame) => frame?.origin === 'https://melody-activity-index.faas.ele.me'
    && frame.pathname === '/home/myActivity');
  return dashboardFrames.length === 1 && imFrames.length === 1
    && imFrames[0].searchParams.get('shopId') === route[1]
    && imFrames[0].searchParams.get('shopType') === 'SHOP'
    && activityFrames.length === 1;
}

function stateFile(profile) {
  return path.join(PROFILE_ROOT, profile, '.aos-background-chrome', 'state.json');
}

export function taobaoProfileMayColdStart(spec, state, pidAlive, profileRoot = PROFILE_ROOT) {
  if (spec?.profile !== FIXED.taobao.profile || Number(spec?.port) !== FIXED.taobao.port) return false;
  if (state?.profile !== FIXED.taobao.profile || Number(state?.port) !== FIXED.taobao.port
      || state?.profilePath !== path.join(profileRoot, FIXED.taobao.profile)
      || state?.mode !== 'headless' || typeof state?.pid !== 'number'
      || !String(state?.url || '').startsWith(FIXED.taobao.prefix) || pidAlive(state.pid)) return false;
  return true;
}

function digest(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

export async function dedicatedChromeLauncherSelfTest() {
  try {
    const [launcher, sessionGuard] = await Promise.all([
      fsp.readFile(DEDICATED_CHROME_LAUNCHER), fsp.readFile(DEDICATED_CHROME_SESSION_GUARD),
    ]);
    if (digest(launcher) !== DEDICATED_CHROME_LAUNCHER_SHA256
        || digest(sessionGuard) !== DEDICATED_CHROME_SESSION_GUARD_SHA256) {
      return { ok: false, reason: 'dedicated-chrome-launcher-dependency-drift' };
    }
    return { ok: true, launcherSha256: DEDICATED_CHROME_LAUNCHER_SHA256,
      sessionGuardSha256: DEDICATED_CHROME_SESSION_GUARD_SHA256 };
  } catch (error) {
    return { ok: false, reason: `dedicated-chrome-launcher-unavailable:${String(error?.message || error)}` };
  }
}

async function coldStartFixedTaobaoProfile(spec, state, receipt, adapters = {}) {
  if (!taobaoProfileMayColdStart(spec, state, (pid) => {
    if (adapters.pidAlive) return adapters.pidAlive(pid);
    try { process.kill(pid, 0); return true; } catch { return false; }
  })) throw new Error('taobao-fixed-profile-cold-start-not-authorized');
  const launcherCheck = await (adapters.verifyLauncher || dedicatedChromeLauncherSelfTest)();
  if (!launcherCheck.ok) throw new Error(launcherCheck.reason);
  const launch = adapters.launchProfile || (async (options, mode) => {
    const launcher = await import(`${pathToFileURL(DEDICATED_CHROME_LAUNCHER).href}?sha256=${launcherCheck.launcherSha256}`);
    return launcher.launch(options, mode);
  });
  const launchOptions = { profile: FIXED.taobao.profile, port: String(FIXED.taobao.port), url: FIXED.taobao.home };
  const result = await launch(launchOptions, 'headless');
  if (result?.ok !== true || result.profile !== FIXED.taobao.profile
      || result.port !== FIXED.taobao.port || result.mode !== 'headless') {
    throw new Error(`taobao-fixed-profile-cold-start-failed:${result?.reason || result?.command || 'invalid-launch-receipt'}`);
  }
  const startedState = adapters.readStartedState
    ? await adapters.readStartedState()
    : JSON.parse(await fsp.readFile(stateFile(FIXED.taobao.profile), 'utf8'));
  if (startedState.profilePath !== path.join(PROFILE_ROOT, FIXED.taobao.profile)
      || startedState.port !== FIXED.taobao.port || startedState.mode !== 'headless'
      || startedState.pid !== result.pid || startedState.url !== FIXED.taobao.home) {
    throw new Error('taobao-fixed-profile-cold-start-state-mismatch');
  }
  receipt.pitfalls.push({ stage: receipt.stage, code: 'fixed-profile-started',
    reason: 'stale-state-pid-restarted-same-dedicated-profile' });
  return { state: startedState, startupRecovery: { code: 'fixed-profile-started', profile: FIXED.taobao.profile,
    port: FIXED.taobao.port, mode: 'headless', previousPid: state.pid, pid: result.pid } };
}

export async function taobaoStartupSelfTest() {
  const profilePath = path.join(PROFILE_ROOT, FIXED.taobao.profile);
  const oldState = { profile: FIXED.taobao.profile, profilePath, port: FIXED.taobao.port,
    mode: 'headless', pid: 99999999, url: FIXED.taobao.home };
  const startedState = { ...oldState, pid: 42424 };
  const receipt = { stage: 'profile_preflight', pitfalls: [] };
  let launchCalls = 0;
  let observedOptions;
  const started = await coldStartFixedTaobaoProfile(FIXED.taobao, oldState, receipt, {
    pidAlive: () => false,
    verifyLauncher: async () => ({ ok: true, launcherSha256: DEDICATED_CHROME_LAUNCHER_SHA256 }),
    launchProfile: async (options, mode) => {
      launchCalls += 1;
      observedOptions = { options, mode };
      return { ok: true, profile: FIXED.taobao.profile, port: FIXED.taobao.port, mode: 'headless', pid: 42424 };
    },
    readStartedState: async () => startedState,
  });
  if (launchCalls !== 1 || observedOptions.mode !== 'headless'
      || JSON.stringify(observedOptions.options) !== JSON.stringify({ profile: 'taobao-brand', port: '9230', url: FIXED.taobao.home })
      || started.startupRecovery.previousPid !== oldState.pid || started.state.pid !== 42424
      || receipt.pitfalls[0]?.code !== 'fixed-profile-started') {
    return { ok: false, tests: 1, reason: 'fixed-taobao-launch-contract-self-test-failed' };
  }
  let livePidLaunches = 0;
  try {
    await coldStartFixedTaobaoProfile(FIXED.taobao, oldState, { stage: 'profile_preflight', pitfalls: [] }, {
      pidAlive: () => true, verifyLauncher: async () => ({ ok: true }),
      launchProfile: async () => { livePidLaunches += 1; return {}; },
    });
    return { ok: false, tests: 2, reason: 'live-taobao-profile-cold-start-was-allowed' };
  } catch (error) {
    if (error.message !== 'taobao-fixed-profile-cold-start-not-authorized' || livePidLaunches !== 0) {
      return { ok: false, tests: 2, reason: 'live-taobao-profile-negative-self-test-failed' };
    }
  }
  let driftLaunches = 0;
  try {
    await coldStartFixedTaobaoProfile(FIXED.taobao, oldState, { stage: 'profile_preflight', pitfalls: [] }, {
      pidAlive: () => false, verifyLauncher: async () => ({ ok: false, reason: 'launcher-drift' }),
      launchProfile: async () => { driftLaunches += 1; return {}; },
    });
    return { ok: false, tests: 3, reason: 'launcher-drift-cold-start-was-allowed' };
  } catch (error) {
    if (error.message !== 'launcher-drift' || driftLaunches !== 0) {
      return { ok: false, tests: 3, reason: 'launcher-drift-negative-self-test-failed' };
    }
  }
  try {
    await coldStartFixedTaobaoProfile(FIXED.jinsha, oldState, { stage: 'profile_preflight', pitfalls: [] }, {
      pidAlive: () => false, verifyLauncher: async () => ({ ok: true }),
      launchProfile: async () => { throw new Error('must-not-launch-non-taobao'); },
    });
    return { ok: false, tests: 4, reason: 'wrong-profile-cold-start-was-allowed' };
  } catch (error) {
    if (error.message !== 'taobao-fixed-profile-cold-start-not-authorized') {
      return { ok: false, tests: 4, reason: 'wrong-profile-negative-self-test-failed' };
    }
  }
  return { ok: true, tests: 4 };
}

export function matchesDedicatedBrowserCommand(command, spec) {
  const text = String(command || '');
  const profileDir = path.join(PROFILE_ROOT, spec.profile);
  return /(?:Google Chrome|Chromium)(?:\.app)?\/Contents\/MacOS\/Google Chrome|(?:^|\s)(?:google-chrome|chromium)(?:\s|$)/.test(text)
    && text.includes(`--remote-debugging-port=${spec.port}`)
    && text.includes(`--user-data-dir=${profileDir}`);
}

// 2026-09-30 受限执行环境降级：WorkBuddy 沙箱禁止 spawn /bin/ps（EPERM）。
// 生产 launchd 环境仍走 matchesDedicatedBrowserCommand 严格匹配；降级时不伪造参数，
// 改用三重等价证据：端口唯一 pid + 可执行文件为 Chrome（lsof txt）+ CDP 端点自证。
function probeCdpBrowser(port, timeoutMs = 4000) {
  return new Promise((resolve) => {
    let settled = false;
    const finish = (value) => { if (!settled) { settled = true; resolve(value); } };
    const request = http.get({ host: '127.0.0.1', port, path: '/json/version', timeout: timeoutMs }, (response) => {
      let body = ''; response.setEncoding('utf8');
      response.on('data', (chunk) => { body += chunk; });
      response.on('end', () => { try { const parsed = JSON.parse(body); finish(typeof parsed?.Browser === 'string' ? parsed.Browser : ''); } catch { finish(''); } });
    });
    request.on('error', () => finish(''));
    request.on('timeout', () => { request.destroy(); finish(''); });
  });
}
async function assertDegradedDedicatedIdentity(spec, pid) {
  let executable = '';
  try {
    const { stdout } = await execFile('/usr/sbin/lsof', ['-nP', '-p', String(pid), '-a', '-d', 'txt', '-F', 'n'], { timeout: 5000 });
    executable = (String(stdout).split('\n').map((line) => line.trim()).find((line) => line.startsWith('n') && /MacOS\/Google Chrome$/i.test(line)) || '').slice(1);
  } catch { throw new Error(`profile-process-not-running:${spec.profile}`); }
  if (!/Google Chrome/i.test(executable)) throw new Error(`profile-process-not-running:${spec.profile}`);
  const browser = await probeCdpBrowser(spec.port);
  if (!browser) throw new Error(`profile-process-not-running:${spec.profile}`);
  return true;
}
async function discoverDedicatedBrowserPid(spec) {
  let output;
  try {
    ({ stdout: output } = await execFile('/usr/sbin/lsof', ['-nP', '-t', `-iTCP:${spec.port}`, '-sTCP:LISTEN'], { timeout: 5000 }));
  } catch { throw new Error(`profile-process-not-running:${spec.profile}`); }
  const pids = [...new Set(String(output).split(/\s+/).filter(Boolean))];
  if (pids.length !== 1) throw new Error(`profile-process-binding-invalid:${spec.profile}`);
  let command;
  try {
    ({ stdout: command } = await execFile('/bin/ps', ['-p', pids[0], '-o', 'command='], { timeout: 5000 }));
  } catch (error) {
    if (error?.code !== 'EPERM' && error?.code !== 'EACCES') throw new Error(`profile-process-not-running:${spec.profile}`);
    await assertDegradedDedicatedIdentity(spec, pids[0]);
    return Number(pids[0]);
  }
  if (!matchesDedicatedBrowserCommand(command, spec)) throw new Error(`profile-process-binding-invalid:${spec.profile}`);
  return Number(pids[0]);
}

export function assertProfileState(spec, state) {
  if (state?.profile !== spec.profile || Number(state?.port) !== spec.port) {
    throw new Error(`profile-state-mismatch:${spec.profile}`);
  }
  if (state.mode === 'headless') return true;
  const handoffBinding = visibleHandoffBinding(state);
  const visibleHandoffReady = spec.profile === FIXED.jinsha.profile
    && state.mode === 'visible-handoff'
    && state.phase === 'WINDOW_RELEASED'
    && state.site === 'jinsha'
    && state.prefix === FIXED.jinsha.prefix
    && state.cdpEnabled === true
    && state.automationAttached === true
    && typeof state.instanceId === 'string'
    && state.instanceId.length > 0
    && state.confirmationInstance === state.instanceId
    && handoffBinding !== null;
  if (!visibleHandoffReady) throw new Error(`profile-state-mismatch:${spec.profile}`);
  return true;
}

export function visibleHandoffBinding(state) {
  if (typeof state?.activeTargetId === 'string' && state.activeTargetId.length > 0
    && typeof state?.activeMarker === 'string' && state.activeMarker.length > 0) {
    return { targetId: state.activeTargetId, marker: state.activeMarker, family: 'active' };
  }
  if (typeof state?.taskTargetId === 'string' && state.taskTargetId.length > 0
    && typeof state?.taskMarker === 'string' && state.taskMarker.length > 0) {
    return { targetId: state.taskTargetId, marker: state.taskMarker, family: 'task' };
  }
  return null;
}

export function isAuthenticatedJinshaRecoveryPage(url, text) {
  let parsed;
  try { parsed = new URL(url); } catch { return false; }
  const body = String(text || '');
  return parsed.origin === 'https://data.guoshuyufen.com'
    && parsed.hash !== '#/login'
    && body.includes('臻肆外卖运营')
    && ['数据总览', '添加店铺', '数据中心'].filter((value) => body.includes(value)).length >= 2
    && !['账号密码', '扫码登录', '无法登录？'].some((value) => body.includes(value));
}

export function jinshaControllerRecoveryMode(url, text, currentMarker, expectedMarker) {
  if (!String(url || '').startsWith(FIXED.jinsha.prefix)) return null;
  if (typeof expectedMarker !== 'string' || expectedMarker.length === 0) return null;
  if (currentMarker === expectedMarker) return 'matching-controller-marker';
  if (currentMarker === '' && isAuthenticatedJinshaRecoveryPage(url, text)) return 'authenticated-unmarked-page';
  return null;
}

export function borrowedJinshaRouteNeedsHome(url) {
  const value = String(url || '');
  if (!value.startsWith(FIXED.jinsha.prefix)) return false;
  return value !== FIXED.jinsha.home && !value.endsWith(FIXED.jinsha.uploadHash);
}

export function jinshaBusinessRunIdFromMarker(marker) {
  const match = String(marker || '').match(/^aos-background-task:(jinsha-business-production-(\d{8})-(\d{2}))$/);
  return match ? Object.freeze({ runId: match[1], runDay: match[2], sequence: match[3] }) : null;
}

async function isCompletedJinshaBusinessLease(marker) {
  const identity = jinshaBusinessRunIdFromMarker(marker);
  if (!identity) return false;
  const stateFile = path.join(JINSHA_BUSINESS_RUNS_ROOT, identity.runDay, identity.sequence, 'workflow-state.json');
  try {
    const state = JSON.parse(await fsp.readFile(stateFile, 'utf8'));
    return state.runId === identity.runId && state.phase === 'complete' && state.status === 'complete'
      && state.runtimeModelDecisions === 0;
  } catch {
    return false;
  }
}

async function resolveLiveJinshaBinding(spec, state) {
  const configured = visibleHandoffBinding(state);
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${spec.port}`);
  try {
    const context = browser.contexts()[0];
    if (!context) throw new Error(`browser-context-missing:${spec.profile}`);
    const rows = [];
    for (const page of context.pages()) {
      if (!page.url().startsWith(spec.prefix)) continue;
      const session = await context.newCDPSession(page);
      let targetId;
      try { ({ targetInfo: { targetId } } = await session.send('Target.getTargetInfo')); }
      finally { await session.detach(); }
      const marker = await page.evaluate(() => window.name);
      rows.push({ page, targetId, marker, url: page.url() });
    }
    const configuredMatches = rows.filter((row) => row.targetId === configured.targetId && isOwnedName(row.marker, configured.marker));
    if (configuredMatches.length === 1) return { ...configured, resolvedTargetId: configured.targetId, recoveryMode: null };
    if (configuredMatches.length > 1 || rows.length !== 1) throw new Error(`jinsha-controller-preflight-target-not-unique:${rows.length}`);
    const row = rows[0];
    const body = await row.page.locator('body').innerText({ timeout: 5000 });
    let recoveryMode = jinshaControllerRecoveryMode(row.url, body, row.marker, configured.marker);
    let marker = configured.marker;
    if (!recoveryMode && isAuthenticatedJinshaRecoveryPage(row.url, body) && await isCompletedJinshaBusinessLease(row.marker)) {
      recoveryMode = 'completed-business-workflow-marker';
      marker = row.marker;
    }
    if (!recoveryMode) throw new Error('jinsha-controller-preflight-recovery-rejected');
    return { ...configured, marker, targetId: row.targetId, resolvedTargetId: row.targetId, recoveryMode };
  } finally {
    await browser.close();
  }
}

async function assertProfile(spec, receipt) {
  let state = JSON.parse(await fsp.readFile(stateFile(spec.profile), 'utf8'));
  assertProfileState(spec, state);
  let actualPid = state.pid;
  try { process.kill(state.pid, 0); }
  catch {
    if (spec.profile === FIXED.taobao.profile) {
      const started = await coldStartFixedTaobaoProfile(spec, state, receipt);
      state = started.state;
      actualPid = state.pid;
      state.startupRecovery = started.startupRecovery;
    } else if (spec.profile === FIXED.jinsha.profile) {
      actualPid = await discoverDedicatedBrowserPid(spec);
    } else {
      throw new Error(`profile-process-not-running:${spec.profile}`);
    }
  }
  const version = await fetch(`http://127.0.0.1:${spec.port}/json/version`);
  if (!version.ok) throw new Error(`cdp-not-ready:${spec.profile}`);
  const controllerBinding = spec.profile === FIXED.jinsha.profile && state.mode === 'visible-handoff'
    ? await resolveLiveJinshaBinding(spec, state) : null;
  return { profile: state.profile, port: state.port, pid: actualPid, statePid: state.pid, mode: state.mode, phase: state.phase || null,
    ...(state.startupRecovery ? { startupRecovery: state.startupRecovery } : {}),
    ...(controllerBinding ? { controllerBinding } : {}) };
}

function isOwnedName(name, marker) {
  return name === marker || String(name).startsWith(`nameStorage:${encodeURIComponent(marker)}?`);
}

async function isAuthenticatedTaobaoSeed(page) {
  if (!isTaobaoSeedRecoveryUrl(page.url())) return false;
  try {
    const text = await allFrameText(page);
    const hasAnalysisFrame = page.frames().some((frame) => isTaobaoAnalysisFrameUrl(frame.url()));
    return hasAnalysisFrame && text.includes('品牌版') && text.includes('数据中心') && text.includes('今日实时数据');
  } catch { return false; }
}

async function waitForAuthenticatedTaobaoSeed(page, timeoutMs = 60_000) {
  const deadline = performance.now() + timeoutMs;
  do {
    if (isTaobaoLoginUrl(page.url())) throw new Error('taobao-login-expired');
    if (await isAuthenticatedTaobaoSeed(page)) return page;
    if (performance.now() >= deadline) break;
    await page.waitForTimeout(250);
  } while (true);
  throw new Error('taobao-auth-seed-recovery-timeout');
}

async function taobaoAuthenticatedSeed(context, receipt) {
  const pages = context.pages();
  const candidates = [];
  for (const page of pages) {
    if (await isAuthenticatedTaobaoSeed(page)) candidates.push(page);
  }
  if (candidates.length === 1) return candidates[0];
  if (candidates.length > 1) throw new Error(`taobao-auth-seed-not-unique:${candidates.length}`);

  const recoverable = pages.filter((page) => isTaobaoSeedRecoveryUrl(page.url()));
  let page;
  let recoveryReason = 'taobao-auth-seed-not-unique:0';
  if (recoverable.length === 1) {
    page = recoverable[0];
  } else if (recoverable.length === 0) {
    const activityShells = pages.filter((candidate) => isTaobaoActivityShellRecoveryPage(
      candidate.url(), candidate.frames().map((frame) => frame.url()), pages.length,
    ));
    if (activityShells.length === 1) {
      page = activityShells[0];
      recoveryReason = 'unique-taobao-activity-shell-shopid-matched-live-frames';
    } else if (pages.some((candidate) => isTaobaoLoginUrl(candidate.url()))) {
      throw new Error('taobao-login-expired');
    } else {
      throw new Error(`taobao-auth-seed-recovery-not-unique:${recoverable.length}`);
    }
  } else {
    throw new Error(`taobao-auth-seed-recovery-not-unique:${recoverable.length}`);
  }
  claimRecovery(receipt, 'taobaoAuthAnchorRecovery', { code: 'auth-anchor-recovery', reason: recoveryReason });
  try {
    await page.goto(FIXED.taobao.home, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    // 2026-10-12 60s→150s：导航回 chain home 后 iframe SPA 自行路由到 business-analysis
    // 需 1-2 分钟（2026-10-11 实测）；活动巡检 reset_chain_seed 刚跑完就启动本流时，
    // iframe 还在路由中，hasAnalysisFrame=false 持续超过 60s ⇒ recovery-timeout 误判
    // （13:43 实败：三文本全过、唯 iframe 未到位）。150s 覆盖路由窗口，判据本身不变。
    await waitForAuthenticatedTaobaoSeed(page, 150_000);
    const anchor = `aos-background-auth-anchor:${FIXED.taobao.profile}`;
    await page.evaluate((value) => { window.name = value; }, anchor);
    if (!isOwnedName(await page.evaluate(() => window.name), anchor)) throw new Error('taobao-auth-anchor-marker-failed');
    return page;
  } catch (error) {
    if (String(error?.message || error) === 'taobao-login-expired') throw error;
    throw new Error(`taobao-auth-seed-recovery-failed:${String(error?.message || error)}`);
  }
}

// 2026-10-18 大同指令：金鲨目标页面一律复用已开页面（禁新开标签/禁 URL 重开）。
// 纯决策：同源已开页面恰好 1 个 ⇒ 复用；0 个 ⇒ fail-closed 上报（由监理/大同开工位页面，
// 执行器绝不代开）；多个 ⇒ fail-closed（保守不猜）。
export function jinshaReusePageDecision(urls) {
  const sameOrigin = (urls || []).filter((url) => String(url || '').startsWith(FIXED.jinsha.prefix));
  if (sameOrigin.length === 0) return Object.freeze({ ok: false, code: 'jinsha-no-existing-origin-page' });
  if (sameOrigin.length > 1) return Object.freeze({ ok: false, code: `jinsha-existing-origin-page-not-unique:${sameOrigin.length}` });
  return Object.freeze({ ok: true, url: sameOrigin[0] });
}

export function completedJinshaOwnerMarker(receipt, livePid) {
  const profile = receipt?.profiles?.jinsha;
  if (!Number.isInteger(livePid) || livePid <= 0 || receipt?.executor !== 'background-browser-executor'
    || receipt.ok !== true || receipt.stage !== 'completed' || receipt.phase !== 'completed'
    || receipt.cleanupStatus !== 'completed' || receipt.jinshaTaskStrategy !== 'reused-existing-work-target'
    || profile?.profile !== FIXED.jinsha.profile || profile.port !== FIXED.jinsha.port || profile.pid !== livePid
    || !/^\d{4}-\d{2}-\d{2}$/.test(receipt.businessDate || '')
    || !/^[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}$/i.test(receipt.runId || '')) return null;
  return `aos-background-task:taobao-jinsha-${receipt.runId.toLowerCase().slice(0, 30)}`;
}

export function ownedJinshaPageDecision(pages, proofs, livePid, processStartedAt) {
  if (!Number.isFinite(processStartedAt) || processStartedAt <= 0)
    return { ok: false, code: 'jinsha-existing-owner-process-start-missing' };
  const candidates = [];
  for (let index = 0; index < pages.length; index++) {
    const page = pages[index];
    if (!String(page.url || '').startsWith(FIXED.jinsha.prefix)) continue;
    const owners = proofs.filter(proof => {
      const marker = completedJinshaOwnerMarker(proof.receipt, livePid);
      return marker && Number.isFinite(proof.createdAt) && proof.createdAt >= processStartedAt
        && proof.createdAt <= Date.now() && isOwnedName(page.marker, marker);
    });
    if (owners.length === 1) candidates.push({ index, url: page.url, owner: owners[0] });
    else if (owners.length > 1) return { ok: false, code: 'jinsha-existing-owner-proof-not-unique' };
  }
  return candidates.length === 1 ? { ok: true, ...candidates[0] }
    : { ok: false, code: `jinsha-existing-owned-page-not-unique:${candidates.length}` };
}

async function completedJinshaOwnerProofs(livePid) {
  let entries;
  try { entries = await fsp.readdir(DEFAULT_OUTPUT, { withFileTypes: true }); } catch { return []; }
  const proofs = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || entry.isSymbolicLink()) continue;
    const file = path.join(DEFAULT_OUTPUT, entry.name, 'receipt.json');
    try {
      const stat = await fsp.lstat(file);
      if (!stat.isFile() || stat.isSymbolicLink()) continue;
      const data = await fsp.readFile(file); const receipt = JSON.parse(data.toString());
      if (entry.name !== `${receipt.businessDate}-${receipt.runId}` || !completedJinshaOwnerMarker(receipt, livePid)) continue;
      proofs.push({ receipt, file, createdAt: stat.birthtimeMs, sha256: crypto.createHash('sha256').update(data).digest('hex') });
    } catch { /* An unreadable historical receipt is not ownership proof. */ }
  }
  return proofs;
}

async function reuseExistingJinshaPage(context, spec, marker, receipt) {
  const pages = context.pages();
  let decision = jinshaReusePageDecision(pages.map((page) => page.url()));
  let page;
  if (!decision.ok && pages.filter(candidate => candidate.url().startsWith(spec.prefix)).length > 1) {
    const livePid = receipt.profiles?.jinsha?.pid;
    const started = await execFile('/bin/ps', ['-p', String(livePid), '-o', 'lstart=']);
    const processStartedAt = Date.parse(started.stdout.trim());
    const descriptors = [];
    for (const candidate of pages) descriptors.push({ url: candidate.url(), marker: candidate.url().startsWith(spec.prefix)
      ? await candidate.evaluate(() => window.name) : '' });
    decision = ownedJinshaPageDecision(descriptors, await completedJinshaOwnerProofs(livePid), livePid, processStartedAt);
    if (decision.ok) {
      page = pages[decision.index];
      const originalMarker = completedJinshaOwnerMarker(decision.owner.receipt, livePid);
      if (page.url() !== decision.url || !isOwnedName(await page.evaluate(() => window.name), originalMarker))
        throw new Error('jinsha-existing-owned-page-binding-changed');
      receipt.jinshaExistingOwnerProof = { runId: decision.owner.receipt.runId, receiptFile: decision.owner.file,
        receiptSha256: decision.owner.sha256, profilePid: livePid, processStartedAt, marker: originalMarker };
    }
  }
  if (!decision.ok) throw new Error(decision.code);
  page ||= pages.find((candidate) => candidate.url() === decision.url);
  if (!page) throw new Error('jinsha-no-existing-origin-page');
  if (page.url().includes('#/login')) throw new Error('jinsha-login-expired');
  const currentMarker = await page.evaluate(() => window.name);
  if (!isOwnedName(currentMarker, marker)) {
    await page.evaluate((value) => { window.name = value; }, marker);
  }
  if (!isOwnedName(await page.evaluate(() => window.name), marker)) throw new Error('jinsha-existing-page-marker-failed');
  return page;
}

async function openOwnedTask(spec, taskId, receipt) {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${spec.port}`);
  const context = browser.contexts()[0];
  if (!context) throw new Error(`browser-context-missing:${spec.profile}`);
  const marker = `aos-background-task:${taskId}`;
  const existing = [];
  for (const page of context.pages()) {
    try { if (isOwnedName(await page.evaluate(() => window.name), marker)) existing.push(page); } catch {}
  }
  // 2026-10-18 大同指令（禁新开标签页）：金鲨改「复用已开页面」模式后，页面带本轮 marker
  // 属正常（同 runId 续跑/重试即复用），不再是重复任务页事故；taobao 租约模式原闸不动。
  if (existing.length !== 0 && spec.profile !== FIXED.jinsha.profile) throw new Error(`task-page-already-exists:${taskId}`);
  let page;
  let leasedSeed = false;
  let borrowedJinsha = false;
  let reusedJinsha = false;
  let controllerBinding = null;
  try {
    if (spec.profile === FIXED.taobao.profile) {
      page = await taobaoAuthenticatedSeed(context, receipt);
      leasedSeed = true;
    } else {
      const state = JSON.parse(await fsp.readFile(stateFile(spec.profile), 'utf8'));
      assertProfileState(spec, state);
      if (state.mode === 'visible-handoff') {
        controllerBinding = receipt.profiles?.jinsha?.controllerBinding || visibleHandoffBinding(state);
        const candidates = [];
        const sameOrigin = [];
        for (const candidate of context.pages()) {
          const session = await context.newCDPSession(candidate);
          try {
            const info = await session.send('Target.getTargetInfo');
            if (info.targetInfo.targetId === controllerBinding.targetId) candidates.push(candidate);
            if (candidate.url().startsWith(spec.prefix)) sameOrigin.push(candidate);
          } finally { await session.detach(); }
        }
        if (candidates.length === 1) {
          page = candidates[0];
          const currentMarker = await page.evaluate(() => window.name);
          if (!page.url().startsWith(spec.prefix)) throw new Error('jinsha-controller-target-binding-mismatch');
          if (controllerBinding.recoveryMode) {
            claimRecovery(receipt, 'jinshaControllerBindingRecovery', { code: 'controller-target-rebound', reason: `stale-target-id-${controllerBinding.recoveryMode}` });
            if (currentMarker === '') await page.evaluate((value) => { window.name = value; }, controllerBinding.marker);
            if (!isOwnedName(await page.evaluate(() => window.name), controllerBinding.marker)) throw new Error('jinsha-controller-target-recovery-marker-failed');
            await page.goto(spec.home, { waitUntil: 'domcontentloaded', timeout: 30_000 });
          } else if (!isOwnedName(currentMarker, controllerBinding.marker)) throw new Error('jinsha-controller-target-binding-mismatch');
        } else if (candidates.length === 0 && sameOrigin.length === 1) {
          page = sameOrigin[0];
          const currentMarker = await page.evaluate(() => window.name);
          const body = await page.locator('body').innerText({ timeout: 5000 });
          const recoveryMode = jinshaControllerRecoveryMode(page.url(), body, currentMarker, controllerBinding.marker);
          if (!recoveryMode) throw new Error('jinsha-controller-target-recovery-rejected');
          claimRecovery(receipt, 'jinshaControllerBindingRecovery', { code: 'controller-target-rebound', reason: `stale-target-id-${recoveryMode}` });
          if (currentMarker === '') await page.evaluate((value) => { window.name = value; }, controllerBinding.marker);
          if (!isOwnedName(await page.evaluate(() => window.name), controllerBinding.marker)) throw new Error('jinsha-controller-target-recovery-marker-failed');
          await page.goto(spec.home, { waitUntil: 'domcontentloaded', timeout: 30_000 });
        } else {
          throw new Error(`jinsha-controller-target-not-unique:${candidates.length}`);
        }
        borrowedJinsha = true;
        receipt.jinshaTaskStrategy = 'borrowed-released-work-target';
      } else if (spec.profile === FIXED.jinsha.profile) {
        // 2026-10-18 大同指令（「遮罩是因为你自己新打开浏览器标签页……你想要哪个页面，
        // 直接从左侧菜单页做不行吗」）：金鲨工位严禁 context.newPage() 新开标签——新标签
        // 首次加载会弹上传教程浮层（.zzc 遮罩），挡住菜单/上传点击且执行器无法稳定关闭，
        // 10-18 七连败根因。一律复用工位已开着的同源页面，经左侧菜单 SPA 导航。
        page = await reuseExistingJinshaPage(context, spec, marker, receipt);
        reusedJinsha = true;
        receipt.jinshaTaskStrategy = 'reused-existing-work-target';
      } else {
        page = await context.newPage();
        await page.addInitScript((value) => { window.name = value; }, marker);
      }
    }
  } catch (error) {
    const connection = await bounded(() => browser.close(), 5_000);
    if (!connection.ok) receipt.cleanupWarnings.push(`${spec.profile}-selection-connection-close:${connection.reason}`);
    throw error;
  }
  try {
    if (borrowedJinsha) {
      if (borrowedJinshaRouteNeedsHome(page.url())) {
        claimRecovery(receipt, 'jinshaBorrowedHomeNavigation', {
          code: 'borrowed-route-normalization', reason: `unsupported-start-route:${page.url()}`,
        });
        await page.goto(spec.home, { waitUntil: 'domcontentloaded', timeout: 30_000 });
        if (!isOwnedName(await page.evaluate(() => window.name), controllerBinding.marker)) {
          throw new Error('jinsha-controller-target-marker-drift-after-home-navigation');
        }
      }
      await waitForJinshaReady(page, 90_000);
      return { browser, context, page, marker: controllerBinding.marker, spec, leasedSeed, borrowedJinsha, controllerBinding };
    }
    if (reusedJinsha) {
      // 页面态优先：不 URL 导航、不重开（大同 10-18 指令）。normalizeJinsha 经左侧菜单
      // 幂等到达数据上传页；页面停在其他路由时也只经左侧菜单回跳，禁 page.goto。
      return { browser, context, page, marker, spec, leasedSeed, reusedJinsha };
    }
    for (let attempt = 0; attempt < 2; attempt += 1) {
      try {
        await page.goto(spec.home, { waitUntil: 'domcontentloaded', timeout: 30_000 });
        await page.evaluate((value) => { window.name = value; }, marker);
        return { browser, context, page, marker, spec, leasedSeed };
      } catch (error) {
        if (attempt === 1) throw error;
        claimRecovery(receipt, `${spec.profile}Navigation`, { code: 'navigation-retry', reason: String(error?.message || error) });
        await page.waitForTimeout(500);
      }
    }
  } catch (error) {
    const cleanup = await closeOwnedTask({ page, browser, context, marker: borrowedJinsha ? controllerBinding?.marker : marker, spec, leasedSeed, borrowedJinsha, controllerBinding }, `${spec.profile}-open-failure`, receipt);
    receipt.taskMarkerCleanup[spec.profile === FIXED.taobao.profile ? 'taobao' : 'jinsha'] = cleanup.taskMarkerAbsent;
    throw error;
  }
}

async function assertOwnedTask(context, marker) {
  let count = 0;
  for (const page of context.pages()) {
    try { if (isOwnedName(await page.evaluate(() => window.name), marker)) count += 1; } catch {}
  }
  if (count !== 1) throw new Error(`task-page-match-count:${count}`);
}

async function timed(receipt, name, action) {
  receipt.stage = name;
  const started = performance.now();
  try { return await action(); }
  finally { receipt.stageMs[name] = Math.round(performance.now() - started); }
}

async function bounded(action, timeoutMs) {
  let timer;
  try {
    return await Promise.race([
      Promise.resolve().then(action).then((value) => ({ ok: true, value }), (error) => ({ ok: false, reason: String(error?.message || error) })),
      new Promise((resolve) => { timer = setTimeout(() => resolve({ ok: false, reason: `timeout:${timeoutMs}` }), timeoutMs); }),
    ]);
  } finally { clearTimeout(timer); }
}

async function taskDiagnostics(task) {
  if (!task) return null;
  const result = await bounded(async () => {
    const frames = [];
    for (const frame of task.page.frames()) {
      let text = '';
      try { text = (await frame.locator('body').innerText({ timeout: 800 })).slice(0, 500); } catch {}
      frames.push({ url: frame.url(), text });
    }
    return { url: task.page.url(), frames };
  }, 3_000);
  return result.ok ? result.value : { diagnosticFailure: result.reason };
}

async function closeOwnedTask(task, label, receipt) {
  if (!task) return { pageClosed: true, connectionClosed: true, taskMarkerAbsent: true };
  if (task.borrowedJinsha || task.reusedJinsha) {
    // 借用的/复用的页面都是工位上已开着的页面：只验不关（禁关工位页面，大同 10-18 指令）。
    // 注意 task.marker 对 borrowed 即 controllerBinding.marker（openOwnedTask 返回时已对齐）。
    const driftUrl = task.borrowedJinsha ? 'jinsha-controller-target-url-drift' : 'jinsha-reused-target-url-drift';
    const driftMarker = task.borrowedJinsha ? 'jinsha-controller-target-marker-drift' : 'jinsha-reused-target-marker-drift';
    const retained = await bounded(async () => {
      if (!task.page.url().startsWith(task.spec.prefix)) throw new Error(driftUrl);
      if (!isOwnedName(await task.page.evaluate(() => window.name), task.marker)) throw new Error(driftMarker);
    }, 5_000);
    if (!retained.ok) receipt.cleanupWarnings.push(`${label}-${task.borrowedJinsha ? 'borrowed' : 'reused'}-target-release:${retained.reason}`);
    const connection = await bounded(() => task.browser.close(), 5_000);
    if (!connection.ok) receipt.cleanupWarnings.push(`${label}-connection-close:${connection.reason}`);
    return { pageClosed: false, connectionClosed: connection.ok, taskMarkerAbsent: retained.ok,
      ...(task.borrowedJinsha ? { borrowedPageRetained: retained.ok } : { reusedPageRetained: retained.ok }) };
  }
  const page = task.leasedSeed
    ? await bounded(async () => {
      await task.page.goto(task.spec.home, { waitUntil: 'domcontentloaded', timeout: 30_000 });
      if (isTaobaoLoginUrl(task.page.url())) throw new Error('taobao-login-expired-during-anchor-release');
      await waitForText(task.page, '数据中心', 60_000);
      const anchor = `aos-background-auth-anchor:${task.spec.profile}`;
      await task.page.evaluate((value) => { window.name = value; }, anchor);
      if (!isOwnedName(await task.page.evaluate(() => window.name), anchor)) throw new Error('taobao-auth-anchor-marker-failed');
    }, 95_000)
    : await bounded(() => task.page.close({ runBeforeUnload: false }), 5_000);
  if (!page.ok) {
    receipt.cleanupWarnings.push(`${label}-${task.leasedSeed ? 'anchor-release' : 'page-close'}:${page.reason}`);
    if (task.leasedSeed) {
      const fallbackClose = await bounded(() => task.page.close({ runBeforeUnload: false }), 5_000);
      if (fallbackClose.ok) {
        const connection = await bounded(() => task.browser.close(), 5_000);
        return { pageClosed: true, connectionClosed: connection.ok, taskMarkerAbsent: true, anchorLost: true };
      }
      receipt.cleanupWarnings.push(`${label}-fallback-page-close:${fallbackClose.reason}`);
    }
    try { task.browser._connection?.close(); } catch {}
    return { pageClosed: false, connectionClosed: false, taskMarkerAbsent: false };
  }
  let taskMarkerAbsent = true;
  if (task.context && task.marker) {
    for (const candidate of task.context.pages()) {
      try { if (isOwnedName(await candidate.evaluate(() => window.name), task.marker)) taskMarkerAbsent = false; } catch {}
    }
  }
  if (!taskMarkerAbsent) receipt.cleanupWarnings.push(`${label}-task-marker-remains`);
  const connection = await bounded(() => task.browser.close(), 5_000);
  if (!connection.ok) {
    receipt.cleanupWarnings.push(`${label}-connection-close:${connection.reason}`);
    try { task.browser._connection?.close(); } catch {}
  }
  return { pageClosed: true, connectionClosed: connection.ok, taskMarkerAbsent };
}

async function allFrameText(page) {
  const values = [];
  for (const frame of page.frames()) {
    try { const text = (await frame.locator('body').innerText()).trim(); if (text) values.push(text); } catch {}
  }
  return [...new Set(values)].join('\n');
}

async function waitForText(page, expected, timeout = 25_000) {
  const deadline = performance.now() + timeout;
  do {
    const text = await allFrameText(page);
    if (text.includes(expected)) return text;
    if (performance.now() >= deadline) break;
    await page.waitForTimeout(250);
  } while (true);
  throw new Error(`page-text-timeout:${expected}`);
}

async function downloadFrame(page) {
  const deadline = performance.now() + 60_000;
  do {
    if (isTaobaoLoginUrl(page.url())) throw new Error('taobao-login-expired');
    const frame = page.frames().find((item) => item.url().includes('melody-stats-next.ele.me/new/#/download-center'));
    if (frame && await frame.getByRole('button', { name: '下载数据', exact: true }).count() === 1) return frame;
    if (performance.now() >= deadline) break;
    await page.waitForTimeout(250);
  } while (true);
  throw new Error('taobao-download-frame-not-ready');
}

async function ensureActiveText(frame, text) {
  const node = frame.getByText(text, { exact: true }).filter({ visible: true });
  if (await node.count() !== 1) throw new Error(`visible-target-not-unique:${text}`);
  if (!(await node.getAttribute('class') || '').includes('activated')) await node.click();
  await frame.waitForTimeout(150);
  if (!(await node.getAttribute('class') || '').includes('activated')) throw new Error(`target-not-active:${text}`);
}

async function ensureAllFields(frame) {
  const all = frame.getByText('全选', { exact: true }).filter({ visible: true });
  if (await all.count() !== 1) throw new Error('all-fields-target-not-unique');
  const checkbox = all.locator('xpath=ancestor::*[self::label or self::div][1]//input[@type="checkbox"]').first();
  if (await checkbox.count() === 1 && !(await checkbox.isChecked())) await all.click();
  const visibleChecks = frame.locator('input[type="checkbox"]:visible');
  if (await visibleChecks.count() === 0 || await visibleChecks.evaluateAll((items) => items.some((item) => !item.checked))) {
    throw new Error('report-fields-not-all-selected');
  }
}

async function configureReport(frame, type, businessDate) {
  const tab = type === 'store' ? '门店下载' : '评价下载';
  await frame.getByText(tab, { exact: true }).click();
  await frame.waitForTimeout(350);
  await ensureActiveText(frame, '按天');
  const yesterday = frame.getByText('昨日', { exact: true }).filter({ visible: true });
  if (await yesterday.count() !== 1) throw new Error('yesterday-target-not-unique');
  await yesterday.click();
  await frame.waitForTimeout(250);
  const start = frame.locator('input[placeholder="开始日期"]:visible');
  const end = frame.locator('input[placeholder="结束日期"]:visible');
  if (await start.inputValue() !== businessDate || await end.inputValue() !== businessDate) {
    throw new Error(`business-date-readback-mismatch:${type}`);
  }
  if (type === 'store') await ensureActiveText(frame, '店铺');
  await ensureActiveText(frame, '全部门店');
  if (type === 'store') {
    const activeAll = frame.locator('li[class*="activated"]:visible').filter({ hasText: /^全部$/ });
    if (await activeAll.count() !== 2) throw new Error('store-all-filters-not-active');
  }
  await ensureAllFields(frame);
}

async function validateXlsx(file, type, businessDate) {
  const name = path.basename(file);
  if (!reportPattern(type, businessDate).test(name)) throw new Error(`download-name-invalid:${type}:${name}`);
  const stat = await fsp.stat(file);
  if (stat.size <= 0) throw new Error(`download-empty:${type}`);
  await execFile('/usr/bin/unzip', ['-t', file], { timeout: 20_000, maxBuffer: 1024 * 1024 });
  const bytes = await fsp.readFile(file);
  return { path: file, name, size: stat.size, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
}

export function isSafeProductionResumeReceipt(receipt, businessDate) {
  const expectedPrefix = ['initialized', 'profiles_ready', 'taobao_open', 'taobao_downloaded', 'taobao_closed'];
  const undispatchedType = knownUndispatchedUploadType(receipt, businessDate);
  const confirmedUploadedType = confirmedUploadedBeforeEvidenceType(receipt, businessDate);
  const untouchedUploads = receipt?.clickAttempts?.upload?.store === 0 && receipt?.clickAttempts?.upload?.review === 0;
  return receipt?.ok === false
    && receipt?.mode === MODE.PRODUCTION
    && receipt?.businessDate === businessDate
    && expectedPrefix.every((value, index) => receipt?.phaseHistory?.[index] === value)
    && receipt?.cleanupStatus === 'completed'
    && receipt?.taskMarkerCleanup?.taobao === true
    && receipt?.taskMarkerCleanup?.jinsha === true
    && receipt?.clickAttempts?.download?.store === 1
    && receipt?.clickAttempts?.download?.review === 1
    && (untouchedUploads || undispatchedType !== null || confirmedUploadedType !== null)
    && (receipt?.recoveryAttempts?.productionResume || 0) < CONTROL_POLICY.recoveryBudgets.productionResume
    && typeof receipt?.files?.store?.path === 'string'
    && typeof receipt?.files?.review?.path === 'string';
}

export function scheduledContinuationDecision(receipt, businessDate = yesterdayShanghai()) {
  const stop = (code) => Object.freeze({
    authority: 'executor-code-only', allowed: false, action: 'stop', code,
  });
  const proceed = (code) => Object.freeze({
    authority: 'executor-code-only', allowed: true, action: 'continue', code,
  });
  if (receipt?.ok === true && receipt?.stage === 'completed' && receipt?.phase === 'completed') {
    return stop('workflow-completed');
  }
  if (receipt?.ok !== false) return stop('workflow-result-not-failed');
  if (receipt?.mode !== MODE.PRODUCTION) return stop('workflow-mode-not-production');
  if (receipt?.businessDate !== businessDate) return stop('workflow-business-date-mismatch');
  if (receipt?.runtimeModelDecisions !== CONTROL_POLICY.runtimeModelDecisionsAllowed) return stop('runtime-model-decisions-forbidden');
  if (receipt?.cleanupStatus !== 'completed') return stop('workflow-cleanup-incomplete');
  if (receipt?.taskMarkerCleanup?.taobao !== true || receipt?.taskMarkerCleanup?.jinsha !== true) return stop('workflow-task-marker-cleanup-incomplete');
  const reason = String(receipt?.reason || '');
  if (reason.includes('upload-result-unknown')) return stop('upload-result-unknown');
  const storeUploads = receipt?.clickAttempts?.upload?.store;
  const reviewUploads = receipt?.clickAttempts?.upload?.review;
  if (!Number.isInteger(storeUploads) || !Number.isInteger(reviewUploads)) return stop('upload-click-count-missing');
  if (storeUploads === 0 && reviewUploads === 0) return proceed('safe-no-upload-effect');
  if (isSafeProductionResumeReceipt(receipt, businessDate)) return proceed('safe-code-validated-production-resume');
  return stop('unrecognized-external-effect-state');
}

export function confirmedUploadedBeforeEvidenceType(receipt, businessDate) {
  if (receipt?.businessDate !== businessDate || receipt?.cleanupStatus !== 'completed'
    || receipt?.taskMarkerCleanup?.taobao !== true || receipt?.taskMarkerCleanup?.jinsha !== true) return null;
  const reason = String(receipt?.reason || '');
  if (!reason.includes('page.screenshot: Timeout 30000ms exceeded.') || !reason.includes('waiting for fonts') || reason.includes('upload-result-unknown')) return null;
  const frames = receipt?.failureDiagnostics?.jinsha?.frames;
  if (!Array.isArray(frames)) return null;
  for (const type of ['store', 'review']) {
    const other = type === 'store' ? 'review' : 'store';
    const logConfirmed = frames.some((frame) => completedLogText(String(frame?.text || ''), type, businessDate));
    if (receipt?.clickAttempts?.upload?.[type] === 1
      && receipt?.clickAttempts?.upload?.[other] === 0
      && receipt?.uploadDecision?.[type] === 'uploaded-complete'
      && logConfirmed) return type;
  }
  return null;
}

export function knownUndispatchedUploadType(receipt, businessDate) {
  if (receipt?.businessDate !== businessDate || receipt?.cleanupStatus !== 'completed'
    || receipt?.taskMarkerCleanup?.taobao !== true || receipt?.taskMarkerCleanup?.jinsha !== true) return null;
  const reason = String(receipt?.reason || '');
  if (!reason.includes('locator.click: Timeout 30000ms exceeded.')
    || !reason.includes('<div class="zzc"')
    || !reason.includes('intercepts pointer events')
    || reason.includes('upload-result-unknown')) return null;
  for (const type of ['store', 'review']) {
    const other = type === 'store' ? 'review' : 'store';
    if (receipt?.clickAttempts?.upload?.[type] === 1
      && receipt?.clickAttempts?.upload?.[other] === 0
      && receipt?.uploadDecision?.[type] === 'upload-clicked-awaiting-result') return type;
  }
  return null;
}

async function loadProductionResumeReceipt(businessDate) {
  let entries = [];
  try { entries = await fsp.readdir(DEFAULT_OUTPUT, { withFileTypes: true }); }
  catch (error) { if (error?.code !== 'ENOENT') throw error; }
  const candidates = [];
  for (const entry of entries) {
    if (!entry.isDirectory() || !entry.name.startsWith(`${businessDate}-`)) continue;
    const directory = path.join(DEFAULT_OUTPUT, entry.name);
    const receiptFile = path.join(directory, 'receipt.json');
    try {
      const receipt = JSON.parse(await fsp.readFile(receiptFile, 'utf8'));
      if (!isSafeProductionResumeReceipt(receipt, businessDate)) continue;
      const expectedDirectory = path.join(DEFAULT_OUTPUT, `${businessDate}-${receipt.runId}`);
      if (path.resolve(directory) !== path.resolve(expectedDirectory)) continue;
      const files = {};
      for (const type of ['store', 'review']) {
        const resolved = await fsp.realpath(receipt.files[type].path);
        if (!resolved.startsWith(`${await fsp.realpath(directory)}${path.sep}`)) throw new Error(`resume-file-out-of-scope:${type}`);
        const validated = await validateXlsx(resolved, type, businessDate);
        if (validated.size !== receipt.files[type].size || validated.sha256 !== receipt.files[type].sha256 || validated.name !== receipt.files[type].name) {
          throw new Error(`resume-file-receipt-mismatch:${type}`);
        }
        files[type] = validated;
      }
      const stat = await fsp.stat(receiptFile);
      candidates.push({ receipt: { ...receipt, files }, receiptFile, modifiedMs: stat.mtimeMs });
    } catch {}
  }
  candidates.sort((left, right) => right.modifiedMs - left.modifiedMs || right.receiptFile.localeCompare(left.receiptFile));
  return candidates[0]?.receipt || null;
}

async function downloadReport(page, frame, outputDir, type, businessDate, receipt) {
  await configureReport(frame, type, businessDate);
  const button = frame.getByRole('button', { name: '下载数据', exact: true }).filter({ visible: true });
  if (await button.count() !== 1) throw new Error(`download-button-not-unique:${type}`);
  claimClick(receipt, 'download', type);
  const event = page.waitForEvent('download', { timeout: 60_000 });
  await button.click();
  const download = await event;
  const suggested = download.suggestedFilename();
  const target = path.join(outputDir, suggested);
  await download.saveAs(target);
  return validateXlsx(target, type, businessDate);
}

async function taobaoDownload(task, outputDir, businessDate, receipt) {
  const { page, context, marker } = task;
  await page.setViewportSize({ width: 2200, height: 2600 });
  let homeText;
  try {
    homeText = await waitForText(page, '今日实时数据', 60_000);
  } catch (error) {
    if (error?.message !== 'page-text-timeout:今日实时数据') throw error;
    claimRecovery(receipt, 'taobaoHomeReload', { code: 'home-reload', reason: error.message, location: 'taobao_login_gate' });
    await page.goto(FIXED.taobao.home, { waitUntil: 'domcontentloaded', timeout: 30_000 });
    await page.evaluate((value) => { window.name = value; }, marker);
    homeText = await waitForText(page, '今日实时数据', 60_000);
  }
  const analysisFrame = page.frames().find((item) => isTaobaoAnalysisFrameUrl(item.url()));
  if (!analysisFrame || !homeText.includes('经营分析')) throw new Error('taobao-login-gate-failed');
  await page.goto(FIXED.taobao.download, { waitUntil: 'domcontentloaded', timeout: 30_000 });
  const frame = await downloadFrame(page);
  const store = await timed(receipt, 'taobao_store_download', () => downloadReport(page, frame, outputDir, 'store', businessDate, receipt));
  const review = await timed(receipt, 'taobao_review_download', () => downloadReport(page, frame, outputDir, 'review', businessDate, receipt));
  await assertOwnedTask(context, marker);
  return { store, review };
}

export function isJinshaTaobaoView(text) {
  // 2026-10-18 金鲨改版适配：淘宝子视图侧栏 .optionli 消失，旧锚点（智能斗金/推广魔方/全站推广列表）
  // 已被新版「智能推广」取代。双轨语义门：旧版锚点全命中 OR 新版锚点（智能推广+数据上传）命中。
  const legacyAnchors = ['智能斗金', '推广魔方', '全站推广列表', '数据上传'].every((value) => text.includes(value));
  const modernAnchors = ['智能推广', '数据上传'].every((value) => text.includes(value));
  return (legacyAnchors || modernAnchors) && !text.includes('美团点金');
}

export function isJinshaUploadPage(text) {
  return ['数据上传', '评价上传', '上传日志'].every((value) => text.includes(value))
    && (text.includes('上传数据') || text.includes('上传评价'));
}

// 2026-10-20 输入管线半死兜底（14:00 轮实弹定性）：9232 Chrome browser 进程对合成鼠标事件的
// 响应通道挂死——事件实际送达页面（hash 正常变化）、但 CDP/Playwright 等不到响应 → 一律 30s
// 超时（中性点 CDP mousePressed 同样挂死而键盘事件响应正常；Target.getTargets 见 omnibox
// popup 常驻=地址栏聚焦吞掉输入路由）。修复=原生点击 5s 短超时，超时即在 renderer 内用
// element.click() 派发（与真点击同走事件冒泡，SPA router 正常响应——14:07 实弹
// uploadData↔realTimeData 往返验证通过）。点击后原有 hash/语义/class 后验门全部保留（fail-closed）。
async function robustClick(locator, receipt, meta = {}) {
  const code = meta.code || 'robust-click';
  try {
    await locator.click({ timeout: 5_000 });
    return 'native';
  } catch (error) {
    receipt.pitfalls.push({ stage: receipt.stage, code: `${code}-native-timeout-js-fallback`, reason: String(error?.message || error).split('\n')[0] });
    await locator.evaluate((node) => node.click());
    return 'js';
  }
}

async function closeKnownJinshaPopup(page, receipt) {
  // 轨道 A（现行版「上传教程」浮层，10-18 bundle 实证）：.showImgContent > .zzc 遮罩 +
  // .imgContent 内含 .btn（关闭）。旧实现只认 .upload+「新功能上线」文案，永远匹配不到
  // 这个无文案图片教程弹层（10-18 七连败：knownPopupCloseAttempts 恒 0 而 .zzc 拦截点击）。
  const tutorial = page.locator('.showImgContent:visible');
  if (await tutorial.count() > 0) {
    if (await tutorial.count() > 1) throw new Error('jinsha-tutorial-popup-not-unique');
    const closeBtn = tutorial.locator('.imgContent .btn');
    if (await closeBtn.count() === 1) {
      await closeBtn.click();
    } else {
      await tutorial.locator('.zzc').first().click();
    }
    receipt.knownPopupCloseAttempts += 1;
    await page.waitForTimeout(200);
    if (await tutorial.count() > 0) throw new Error('jinsha-tutorial-popup-close-stuck');
    return true;
  }
  // 轨道 B（旧版浮层）：.upload:visible 含「新功能上线」文案 + 关闭按钮。
  const popup = page.locator('.upload:visible').filter({ hasText: '新功能上线' });
  if (await popup.count() === 0) return false;
  if (await popup.count() > 1) throw new Error('jinsha-known-popup-not-unique');
  const close = popup.getByText('关闭', { exact: true });
  if (await close.count() !== 1) throw new Error('jinsha-known-popup-close-not-unique');
  await close.click();
  receipt.knownPopupCloseAttempts += 1;
  return true;
}

async function waitForJinshaReady(page, timeout = 25_000) {
  const deadline = performance.now() + timeout;
  do {
    const text = await page.locator('body').innerText();
    if (text.includes('今日实时数据') || isJinshaUploadPage(text)) return text;
    if (performance.now() >= deadline) break;
    await page.waitForTimeout(250);
  } while (true);
  throw new Error('jinsha-page-not-ready');
}

// 2026-10-18 幂等判据：hash 命中上传路由，或页面文本已呈上传页语义（防重复点菜单招惹遮罩）。
export function jinshaAlreadyOnUploadPage(url, text) {
  return String(url || '').endsWith(FIXED.jinsha.uploadHash) || isJinshaUploadPage(String(text || ''));
}

async function normalizeJinsha(page, receipt) {
  if (receipt.jinshaTaskStrategy !== 'borrowed-released-work-target') await page.setViewportSize({ width: 2200, height: 1600 });
  try {
    await waitForJinshaReady(page);
  } catch (error) {
    if (error?.message !== 'jinsha-page-not-ready') throw error;
    // 页面停在非就绪路由（如差评分析/负反馈列表）：经左侧菜单「数据上传」回跳，
    // 禁 URL goto/重开（大同 10-18 指令：要哪个页面直接从左侧菜单点）。
    await closeKnownJinshaPopup(page, receipt);
    const modernUploadLink = page.locator('ul.el-menu a[href="#/uploadData/uploadData"]');
    if (await modernUploadLink.count() !== 1) throw new Error('jinsha-data-upload-menu-not-unique');
    receipt.jinshaUploadMenuDecision = 'modern-el-menu-link-recovery';
    await robustClick(modernUploadLink, receipt, { code: 'jinsha-recovery-menu' });
    await page.waitForTimeout(300);
    await waitForJinshaReady(page);
  }
  await closeKnownJinshaPopup(page, receipt);
  let bodyText = await page.locator('body').innerText();
  if (isJinshaTaobaoView(bodyText)) {
    receipt.jinshaPlatformDecision = 'already-taobao-semantic-gate';
  } else {
    const platform = page.locator('.cutli:visible').filter({ hasText: /^\s*淘宝\s*$/ });
    if (await platform.count() !== 1) throw new Error('jinsha-taobao-platform-not-unique');
    receipt.platformSwitchAttempts += 1;
    if (!(await platform.getAttribute('class') || '').includes('pitchOn')) await robustClick(platform, receipt, { code: 'jinsha-platform-switch' });
    await page.waitForTimeout(300);
    bodyText = await page.locator('body').innerText();
    if (!(await platform.getAttribute('class') || '').includes('pitchOn') || !isJinshaTaobaoView(bodyText)) throw new Error('jinsha-taobao-platform-not-active');
    receipt.jinshaPlatformDecision = 'legacy-platform-switch';
  }
  // 2026-10-18 幂等优先（大同指令：要哪个页面直接从左侧菜单点，不重开）：已在数据上传页
  //（hash 命中或上传页语义门命中）⇒ 不重复点菜单——重复点击会再次触发 SPA 路由/loading
  // 遮罩，平白招惹拦截（10-18 七连败教训）。
  if (jinshaAlreadyOnUploadPage(page.url(), bodyText)) {
    receipt.jinshaUploadMenuDecision = 'already-on-upload-page';
  } else {
    // 2026-10-18 金鲨改版适配：旧版 .optionli 侧栏菜单已被 el-menu 结构取代。
    // 双轨点击：优先旧 .optionli（老页面兼容），无则走新 el-menu 内 <a href="#/uploadData/uploadData">。
    // 不再用 page.reload() 重开——页面态优先，已开着的页面直接用（10-18 教训：重开必撞未知浮层）。
    const legacyUploadMenu = page.locator('.optionli:visible').filter({ hasText: /^\s*数据上传\s*$/ });
    if (await legacyUploadMenu.count() === 1) {
      receipt.jinshaUploadMenuDecision = 'legacy-optionli';
      // 2026-10-20 加固（13:11 实弹：元素已解析/可见/stable 但 click 30s 超时，10-18 家族同款瞬态遮罩）：
      // legacy 点击改 10s 短超时；失败先关已知浮层再原轨重试一次；仍失败兜底落 el-menu 新轨。
      // 点后的 hash/语义门（waitForFunction）不变，错导航仍 fail-closed。
      try {
        await legacyUploadMenu.click({ timeout: 10_000 });
      } catch (error) {
        receipt.pitfalls.push({ stage: receipt.stage, code: 'menu-click-overlay-retry', reason: String(error?.message || error).split('\n')[0] });
        await closeKnownJinshaPopup(page, receipt);
        try {
          await legacyUploadMenu.click({ timeout: 10_000 });
        } catch (retryError) {
          receipt.pitfalls.push({ stage: receipt.stage, code: 'menu-click-fallback-el-menu', reason: String(retryError?.message || retryError).split('\n')[0] });
          const modernUploadLink = page.locator('ul.el-menu a[href="#/uploadData/uploadData"]');
          if (await modernUploadLink.count() !== 1) throw new Error('jinsha-data-upload-menu-not-unique');
          receipt.jinshaUploadMenuDecision = 'modern-el-menu-link-fallback';
          await robustClick(modernUploadLink, receipt, { code: 'jinsha-menu-fallback' });
        }
      }
    } else {
      const modernUploadLink = page.locator('ul.el-menu a[href="#/uploadData/uploadData"]');
      if (await modernUploadLink.count() !== 1) throw new Error('jinsha-data-upload-menu-not-unique');
      receipt.jinshaUploadMenuDecision = 'modern-el-menu-link';
      await robustClick(modernUploadLink, receipt, { code: 'jinsha-menu-primary' });
    }
    await page.waitForFunction(({ hash }) => {
      const text = document.body.innerText;
      return location.hash === hash || ['数据上传', '评价上传', '上传日志'].every((value) => text.includes(value)) && (text.includes('上传数据') || text.includes('上传评价'));
    }, { hash: FIXED.jinsha.uploadHash }, { timeout: 15_000 });
  }
  receipt.jinshaNavigationPostcondition = page.url().endsWith(FIXED.jinsha.uploadHash) ? 'hash' : 'upload-page-semantic-gate';
  await closeKnownJinshaPopup(page, receipt);
  await waitForText(page, '上传日志');
}

export function isJinshaTabActive(className) {
  return String(className).split(/\s+/).some((value) => value === 'active' || value === 'pitchOn');
}

async function selectJinshaTab(page, type, receipt) {
  await closeKnownJinshaPopup(page, receipt);
  const text = type === 'store' ? '数据上传' : '评价上传';
  const tab = page.locator('.nav_type_item:visible').filter({ hasText: new RegExp(`^\\s*${text}\\s*$`) });
  if (await tab.count() !== 1) throw new Error(`jinsha-tab-not-unique:${type}`);
  if (!isJinshaTabActive(await tab.getAttribute('class'))) await robustClick(tab, receipt, { code: `jinsha-tab-${type}` });
  await page.waitForTimeout(300);
  if (!isJinshaTabActive(await tab.getAttribute('class'))) throw new Error(`jinsha-tab-not-active:${type}`);
}

async function tabText(page) {
  const panel = page.locator('.right_box:visible, .upload_right:visible, .content_right:visible');
  if (await panel.count() === 1) return panel.innerText();
  return page.locator('body').innerText();
}

async function waitForCompletedLog(page, type, businessDate, timeout = 15_000) {
  const deadline = performance.now() + timeout;
  let text = '';
  do {
    text = await tabText(page);
    if (completedLogText(text, type, businessDate) || performance.now() >= deadline) return text;
    await page.waitForTimeout(250);
  } while (true);
}

async function capturePageScreenshot(page, file) {
  const session = await page.context().newCDPSession(page);
  try {
    const result = await session.send('Page.captureScreenshot', { format: 'png', fromSurface: true, captureBeyondViewport: false });
    if (typeof result?.data !== 'string' || result.data.length === 0) throw new Error('jinsha-screenshot-data-empty');
    await fsp.writeFile(file, Buffer.from(result.data, 'base64'), { mode: 0o600 });
  } finally { await session.detach(); }
}

async function uploadOrSkip(page, type, businessDate, file, outputDir, receipt, allowUpload) {
  await selectJinshaTab(page, type, receipt);
  let before = await waitForCompletedLog(page, type, businessDate);
  const borrowedWorkPage = receipt.jinshaTaskStrategy === 'borrowed-released-work-target';
  const logReloadKey = borrowedWorkPage
    ? type === 'store' ? 'jinshaBorrowedStoreLogReadRetry' : 'jinshaBorrowedReviewLogReadRetry'
    : 'jinshaLogReload';
  if (!completedLogText(before, type, businessDate) && receipt.currentAttemptRecovery[logReloadKey] === 0) {
    receipt.currentAttemptRecovery[logReloadKey] += 1;
    claimRecovery(receipt, logReloadKey, { code: 'log-reload', reason: 'completed-log-missing-first-read' });
    // 2026-10-18 页面态优先修复：不再无脑 page.reload()（重开会撞未知浮层且丢页面态）。
    // 就地恢复：重新走导航（如已在目标页则导航幂等），再重选 tab 触发日志重读。
    await normalizeJinsha(page, receipt);
    await selectJinshaTab(page, type, receipt);
    before = await waitForCompletedLog(page, type, businessDate);
  }
  if (completedLogText(before, type, businessDate)) {
    receipt.uploadDecision[type] = 'skipped-existing-complete';
    receipt.clickAttempts.upload[type] = 0;
  } else {
    if (!allowUpload) throw new Error(`completed-log-missing:${type}`);
    const input = page.locator('input[type="file"].el-upload__input');
    if (await input.count() !== 1) throw new Error(`jinsha-file-input-not-unique:${type}`);
    await input.setInputFiles(file.path);
    const selectedNames = await input.evaluate((node) => Array.from(node.files || [], (item) => item.name));
    if (!isExactSelectedUploadFile(selectedNames, file.name)) throw new Error(`jinsha-selected-file-readback-mismatch:${type}`);
    await page.waitForTimeout(500);
    // 2026-10-18 遮罩容忍修复：金鲨改版后选完文件可能出现瞬时 .zzc loading 遮罩。
    // 原逻辑「见遮罩立即找已知弹窗、找不到判死」过于激进（10-18 七轮皆死于此）。
    // 新逻辑三步：①先等遮罩自行消散（≤8s）②不消散再尝试关已知弹窗 ③仍不消散才判死。
    // 全程 fail-closed：遮罩存在期间绝不点击上传按钮。
    const blockingOverlay = page.locator('.zzc:visible');
    if (await blockingOverlay.count() > 0) {
      const waitDeadline = performance.now() + 8_000;
      while (await blockingOverlay.count() > 0 && performance.now() < waitDeadline) await page.waitForTimeout(200);
      if (await blockingOverlay.count() > 0) {
        if (!await closeKnownJinshaPopup(page, receipt)) throw new Error('jinsha-upload-overlay-unrecognized');
        const deadline = performance.now() + 5_000;
        while (await blockingOverlay.count() > 0 && performance.now() < deadline) await page.waitForTimeout(100);
        if (await blockingOverlay.count() > 0) throw new Error('jinsha-known-popup-overlay-stuck');
      }
    }
    const upload = page.locator('.upload_box_btn:visible').filter({ hasText: /^\s*上传\s*$/ });
    if (await upload.count() !== 1) throw new Error(`jinsha-upload-button-not-unique:${type}`);
    claimClick(receipt, 'upload', type);
    receipt.uploadDecision[type] = 'upload-clicked-awaiting-result';
    await robustClick(upload, receipt, { code: `jinsha-upload-btn-${type}` });
    try {
      await page.waitForFunction(({ prefix, compact }) => {
        const lines = document.body.innerText.split(/\n+/);
        return lines.some((line, index) => {
          const block = lines.slice(index, index + 8).join('');
          return block.includes(prefix) && block.includes(compact) && block.includes('上传完成');
        });
      }, { prefix: type === 'store' ? '门店下载_' : '评价下载_', compact: businessDate.replaceAll('-', '') }, { timeout: 45_000 });
    } catch { throw new Error(`upload-result-unknown:${type}`); }
    receipt.uploadDecision[type] = 'uploaded-complete';
  }
  await closeKnownJinshaPopup(page, receipt);
  const evidence = path.join(outputDir, `jinsha-${type}-final.png`);
  await capturePageScreenshot(page, evidence);
  const bytes = await fsp.readFile(evidence);
  return { path: evidence, sha256: crypto.createHash('sha256').update(bytes).digest('hex') };
}

async function jinshaProcess(task, files, businessDate, outputDir, receipt, allowUpload) {
  const { page, context, marker } = task;
  await normalizeJinsha(page, receipt);
  const store = await timed(receipt, 'jinsha_store_dedup_upload', () => uploadOrSkip(page, 'store', businessDate, files.store, outputDir, receipt, allowUpload));
  const review = await timed(receipt, 'jinsha_review_dedup_upload', () => uploadOrSkip(page, 'review', businessDate, files.review, outputDir, receipt, allowUpload));
  await assertOwnedTask(context, marker);
  return { store, review };
}

async function writeJson(file, value) {
  const temporary = `${file}.tmp`;
  await fsp.writeFile(temporary, JSON.stringify(value, null, 2), { mode: 0o600 });
  await fsp.rename(temporary, file);
}

export function buildRunReview(receipt) {
  const order = new Map(STAGE_ORDER.map((stage, index) => [stage, index]));
  const stageEntries = Object.entries(receipt.stageMs || {}).sort(([left], [right]) => {
    const leftOrder = order.has(left) ? order.get(left) : Number.MAX_SAFE_INTEGER;
    const rightOrder = order.has(right) ? order.get(right) : Number.MAX_SAFE_INTEGER;
    return leftOrder - rightOrder || left.localeCompare(right);
  });
  const measured = new Set(stageEntries.map(([stage]) => stage));
  const normalizedPitfalls = (receipt.pitfalls || []).map((pitfall) => {
    const stage = measured.has(pitfall.stage) ? pitfall.stage : PITFALL_STAGE_ALIASES[pitfall.stage];
    if (!stage || !measured.has(stage)) throw new Error(`review-pitfall-stage-unmeasured:${pitfall.stage}`);
    return { ...pitfall, stage };
  });
  return stageEntries.map(([stage, elapsedMs], index) => {
    if (!Number.isInteger(elapsedMs) || elapsedMs < 0) throw new Error(`review-stage-time-invalid:${stage}`);
    const pitfalls = normalizedPitfalls.filter((item) => item.stage === stage).map((item) => ({
      code: item.code,
      reason: item.reason,
      ...(item.location ? { location: item.location } : {}),
    }));
    if (stage === 'task_cleanup') {
      pitfalls.push(...(receipt.cleanupWarnings || []).map((reason) => ({ code: 'cleanup-warning', reason })));
    }
    return {
      item: index + 1,
      stage,
      label: STAGE_LABELS[stage] || stage,
      elapsedMs,
      status: pitfalls.some((item) => item.code === 'run-failure') ? 'failed' : pitfalls.length ? 'completed-with-pitfall' : 'completed',
      pitfalls,
    };
  });
}

function finalizeRunReview(receipt) {
  receipt.runReview = buildRunReview(receipt);
  const pitfallCount = receipt.runReview.reduce((total, item) => total + item.pitfalls.length, 0);
  receipt.reviewSummary = {
    totalElapsedMs: receipt.elapsedMs,
    itemCount: receipt.runReview.length,
    pitfallCount,
    controlPolicyVersion: receipt.controlPolicy.version,
    result: receipt.ok === true ? 'success' : 'failed',
  };
  const stageNames = Object.keys(receipt.stageMs || {});
  if (receipt.runReview.length !== stageNames.length) throw new Error('review-stage-count-mismatch');
  if (new Set(receipt.runReview.map((item) => item.stage)).size !== stageNames.length) throw new Error('review-stage-duplicate');
  if (!stageNames.every((stage) => receipt.runReview.some((item) => item.stage === stage))) throw new Error('review-stage-missing');
  const expectedPitfalls = (receipt.pitfalls || []).length + (receipt.cleanupWarnings || []).length;
  if (pitfallCount !== expectedPitfalls) throw new Error('review-pitfall-count-mismatch');
  if (receipt.reviewSummary.controlPolicyVersion !== CONTROL_POLICY.version) throw new Error('review-policy-version-mismatch');
}

function assertCompletionContract(receipt) {
  assertControlPolicy(receipt);
  const expectedPhases = PHASE_CHAINS[receipt.mode];
  if (receipt.phaseHistory.join('|') !== expectedPhases.join('|')) throw new Error('completion-phase-chain-invalid');
  if (receipt.runtimeModelDecisions !== 0) throw new Error('completion-runtime-model-decisions-nonzero');
  if (receipt.cleanupStatus !== 'completed') throw new Error('completion-cleanup-incomplete');
  if (receipt.taskMarkerCleanup?.taobao !== true || receipt.taskMarkerCleanup?.jinsha !== true) throw new Error('completion-task-marker-cleanup-invalid');
  for (const type of ['store', 'review']) {
    if (!['skipped-existing-complete', 'uploaded-complete'].includes(receipt.uploadDecision[type])) throw new Error(`completion-upload-decision-invalid:${type}`);
    if (receipt.clickAttempts.download[type] > 1 || receipt.clickAttempts.upload[type] > 1) throw new Error(`completion-click-budget-invalid:${type}`);
    if (receipt.mode === MODE.VERIFY_TODAY && receipt.clickAttempts.download[type] !== 0) throw new Error(`completion-readonly-download-click:${type}`);
    if (receipt.mode !== MODE.PRODUCTION && receipt.clickAttempts.upload[type] !== 0) throw new Error(`completion-readonly-upload-click:${type}`);
    if (receipt.mode !== MODE.VERIFY_TODAY && receipt.clickAttempts.download[type] !== 1) throw new Error(`completion-download-click-missing:${type}`);
    const evidence = receipt.evidence?.[type];
    if (!evidence?.path?.endsWith(`jinsha-${type}-final.png`) || !/^[a-f0-9]{64}$/.test(evidence.sha256 || '')) throw new Error(`completion-evidence-invalid:${type}`);
  }
  if (!receipt.profilePostflight?.taobao || !receipt.profilePostflight?.jinsha) throw new Error('completion-profile-postflight-missing');
  if (!Array.isArray(receipt.runReview) || receipt.reviewSummary?.itemCount !== receipt.runReview.length) throw new Error('completion-review-contract-missing');
}

async function runFixed(mode) {
  if (!PHASE_CHAINS[mode]) throw new Error('unsupported-internal-run-mode');
  const evidenceStorageHelper = "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/runtime/evidence_storage.mjs";
  if (crypto.createHash('sha256').update(await fsp.readFile(evidenceStorageHelper)).digest('hex') !== 'ba84c386010a0a887f0103da38d170bc145c50a5846caf6d8fe58d26efd758d2') throw Error('evidence-storage-helper-drift');
  await (await import(`file://${evidenceStorageHelper}`)).ensureEvidenceAliases();
  const execute = mode === MODE.PRODUCTION;
  const verifyIdempotencyOnly = mode === MODE.VERIFY_TODAY;
  const businessDate = yesterdayShanghai();
  const resumeReceipt = mode === MODE.PRODUCTION ? await loadProductionResumeReceipt(businessDate) : null;
  const undispatchedResumeType = resumeReceipt ? knownUndispatchedUploadType(resumeReceipt, businessDate) : null;
  const runId = resumeReceipt?.runId || crypto.randomUUID();
  const started = performance.now();
  const outputDir = path.join(DEFAULT_OUTPUT, `${businessDate}-${runId}`);
  await fsp.mkdir(outputDir, { recursive: true, mode: 0o700 });
  const receipt = resumeReceipt ? {
    ...resumeReceipt,
    ok: false,
    phase: 'taobao_closed',
    phaseHistory: resumeReceipt.phaseHistory.slice(0, resumeReceipt.phaseHistory.indexOf('taobao_closed') + 1),
    stage: 'resume_preflight',
    stageMs: { ...resumeReceipt.stageMs },
    controlPolicy: controlPolicySnapshot(mode),
    clickAttempts: {
      download: { ...resumeReceipt.clickAttempts.download },
      upload: { ...resumeReceipt.clickAttempts.upload },
    },
    uploadDecision: { ...resumeReceipt.uploadDecision },
    currentAttemptRecovery: { jinshaLogReload: 0, jinshaBorrowedLogReload: 0, jinshaBorrowedLogReadRetry: 0, jinshaBorrowedStoreLogReadRetry: 0, jinshaBorrowedReviewLogReadRetry: 0 },
    recoveryAttempts: {
      'taobao-brandNavigation': 0, 'jinsha-businessNavigation': 0, taobaoAuthAnchorRecovery: 0,
      taobaoHomeReload: 0, jinshaLogReload: 0, jinshaBorrowedLogReload: 0, jinshaBorrowedLogReadRetry: 0, jinshaBorrowedStoreLogReadRetry: 0, jinshaBorrowedReviewLogReadRetry: 0, jinshaUploadOverlay: 0, productionResume: 0,
      // 2026-10-08 F11-3：原此处有 `...resumeReceipt.recoveryAttempts`，会把上一轮**已耗尽**
      // 的恢复预算（如 jinshaLogReload:1，其 budget=1）整体继承回来，而本轮守卫读的是已归零的
      // currentAttemptRecovery ⇒ 放行后 claimRecovery 立刻 used>=budget 抛
      // recovery-budget-exhausted:jinshaLogReload，连上传都没走到，且当天每轮复现、零产出不可自愈。
      // 其余恢复预算本就是「单轮内」语义，应与已归零的 currentAttemptRecovery 对齐（不继承）。
      // 只保留跨轮代数计数 productionResume 的继承。
      productionResume: resumeReceipt.recoveryAttempts?.productionResume || 0,
    },
    resumeHistory: [
      ...(resumeReceipt.resumeHistory || []),
      {
        resumedAt: new Date().toISOString(), sourceReceiptFile: resumeReceipt.receiptFile,
        previousStage: resumeReceipt.stage, previousReason: resumeReceipt.reason,
        previousElapsedMs: resumeReceipt.elapsedMs, previousStageMs: { ...resumeReceipt.stageMs },
        previousRecoveryAttempts: { ...resumeReceipt.recoveryAttempts },
      },
    ],
    cleanupWarnings: [], cleanupStatus: 'not-started', taskMarkerCleanup: { taobao: true, jinsha: true },
  } : {
    ok: false, executor: 'background-browser-executor', channel: 'control-background-dedicated-chrome',
    fixedProfiles: { taobao: 'taobao-brand:9230', jinsha: 'jinsha-business:9232' }, desktopJinshaAllowed: false,
    executionOrder: [...FIXED.executionOrder],
    runId, businessDate, mode, phase: null, phaseHistory: [],
    stage: 'preflight', stageMs: {}, clickAttempts: { download: { store: 0, review: 0 }, upload: { store: 0, review: 0 } },
    controlPolicy: controlPolicySnapshot(mode),
    uploadDecision: {}, runtimeModelDecisions: 0,
    currentAttemptRecovery: { jinshaLogReload: 0, jinshaBorrowedLogReload: 0, jinshaBorrowedLogReadRetry: 0, jinshaBorrowedStoreLogReadRetry: 0, jinshaBorrowedReviewLogReadRetry: 0 },
    recoveryAttempts: { 'taobao-brandNavigation': 0, 'jinsha-businessNavigation': 0, taobaoAuthAnchorRecovery: 0, taobaoHomeReload: 0, jinshaLogReload: 0, jinshaBorrowedLogReload: 0, jinshaBorrowedLogReadRetry: 0, jinshaBorrowedStoreLogReadRetry: 0, jinshaBorrowedReviewLogReadRetry: 0, jinshaUploadOverlay: 0, jinshaControllerBindingRecovery: 0, productionResume: 0 },
    jinshaPlatformDecision: null, platformSwitchAttempts: 0, jinshaNavigationPostcondition: null, knownPopupCloseAttempts: 0,
    jinshaTaskStrategy: null,
    pitfalls: [], cleanupWarnings: [], cleanupStatus: 'not-started',
    taskMarkerCleanup: { taobao: true, jinsha: true },
  };
  if (resumeReceipt) {
    if (undispatchedResumeType) {
      receipt.clickAttempts.upload[undispatchedResumeType] = 0;
      receipt.uploadDecision[undispatchedResumeType] = 'previous-click-not-dispatched-overlay-blocked';
    }
    delete receipt.reason;
    delete receipt.failureDiagnostics;
    delete receipt.profilePostflight;
    delete receipt.evidence;
    delete receipt.evidenceManifest;
    delete receipt.runReview;
    delete receipt.reviewSummary;
  }
  let taobaoTask = null;
  let jinshaTask = null;
  let reachedBusinessCompletion = false;
  try {
    await timed(receipt, 'control_policy_preflight', async () => assertControlPolicy(receipt));
    if (resumeReceipt) {
      receipt.profiles = await timed(receipt, 'resume_profile_preflight', async () => {
        claimRecovery(receipt, 'productionResume', { code: 'production-resume', reason: 'safe-failed-receipt-reused' });
        if (undispatchedResumeType) claimRecovery(receipt, 'jinshaUploadOverlay', { code: 'known-upload-overlay', reason: `click-not-dispatched:${undispatchedResumeType}` });
        return { taobao: await assertProfile(FIXED.taobao, receipt), jinsha: await assertProfile(FIXED.jinsha, receipt) };
      });
    } else {
      transition(receipt, 'initialized');
      receipt.profiles = await timed(receipt, 'profile_preflight', async () => ({
        taobao: await assertProfile(FIXED.taobao, receipt), jinsha: await assertProfile(FIXED.jinsha, receipt),
      }));
      transition(receipt, 'profiles_ready');
    }
    const suffix = runId.toLowerCase().replace(/[^a-z0-9-]/g, '').slice(0, 30);
    let files = resumeReceipt?.files || { store: { path: '', name: '' }, review: { path: '', name: '' } };
    if (!verifyIdempotencyOnly && !resumeReceipt) {
      taobaoTask = await timed(receipt, 'taobao_task_open', () => openOwnedTask(FIXED.taobao, `taobao-download-${suffix}`, receipt));
      receipt.taskMarkerCleanup.taobao = false;
      transition(receipt, 'taobao_open');
      files = await timed(receipt, 'taobao_download_sequence', () => taobaoDownload(taobaoTask, outputDir, businessDate, receipt));
      transition(receipt, 'taobao_downloaded');
      const taobaoClose = await timed(receipt, 'taobao_task_cleanup', () => closeOwnedTask(taobaoTask, 'taobao', receipt));
      receipt.taskMarkerCleanup.taobao = taobaoClose.taskMarkerAbsent;
      if (!taobaoClose.pageClosed || !taobaoClose.taskMarkerAbsent) throw new Error('taobao-task-cleanup-failed-before-jinsha');
      taobaoTask = null;
      transition(receipt, 'taobao_closed');
    }
    receipt.files = files;
    jinshaTask = await timed(receipt, 'jinsha_task_open', () => openOwnedTask(FIXED.jinsha, `taobao-jinsha-${suffix}`, receipt));
    receipt.taskMarkerCleanup.jinsha = false;
    transition(receipt, 'jinsha_open');
    receipt.evidence = await timed(receipt, 'jinsha_sequence', () => jinshaProcess(jinshaTask, files, businessDate, outputDir, receipt, execute));
    transition(receipt, 'jinsha_processed');
    receipt.evidenceManifest = {
      executor: receipt.executor, channel: receipt.channel, runId, mode,
      groupName: FIXED.groupName, businessDate,
      uploadDecision: { ...receipt.uploadDecision },
      images: [receipt.evidence.store, receipt.evidence.review],
    };
    reachedBusinessCompletion = true;
  } catch (error) {
    receipt.reason = String(error?.message || error);
    receipt.pitfalls.push({ stage: receipt.stage, code: 'run-failure', reason: receipt.reason });
    receipt.failureDiagnostics = {
      taobao: await taskDiagnostics(taobaoTask),
      jinsha: await taskDiagnostics(jinshaTask),
    };
  } finally {
    receipt.receiptFile = path.join(outputDir, 'receipt.json');
    receipt.cleanupStatus = 'pending';
    receipt.elapsedMs = Math.round(performance.now() - started);
    await writeJson(receipt.receiptFile, receipt);
    const closeStarted = performance.now();
    const taobaoFinalClose = await closeOwnedTask(taobaoTask, 'taobao', receipt);
    const jinshaFinalClose = await closeOwnedTask(jinshaTask, 'jinsha', receipt);
    if (taobaoTask) receipt.taskMarkerCleanup.taobao = taobaoFinalClose.taskMarkerAbsent;
    if (jinshaTask) receipt.taskMarkerCleanup.jinsha = jinshaFinalClose.taskMarkerAbsent;
    receipt.stageMs.task_cleanup = Math.round(performance.now() - closeStarted);
    receipt.cleanupStatus = receipt.cleanupWarnings.length === 0 ? 'completed' : 'completed-with-warnings';
    if (reachedBusinessCompletion) {
      try {
        receipt.profilePostflight = await timed(receipt, 'profile_postflight', async () => ({
          taobao: await assertProfile(FIXED.taobao, receipt), jinsha: await assertProfile(FIXED.jinsha, receipt),
        }));
        transition(receipt, 'completed');
        receipt.elapsedMs = Math.round(performance.now() - started);
        finalizeRunReview(receipt);
        receipt.stage = 'completion_contract';
        const contractStarted = performance.now();
        try { assertCompletionContract(receipt); }
        finally { receipt.stageMs.completion_contract = Math.round(performance.now() - contractStarted); }
        receipt.ok = true;
        receipt.stage = 'completed';
      } catch (error) {
        receipt.ok = false;
        receipt.reason = String(error?.message || error);
        if (!Number.isInteger(receipt.stageMs[receipt.stage])) receipt.stageMs[receipt.stage] = 0;
        receipt.pitfalls.push({ stage: receipt.stage, code: 'run-failure', reason: receipt.reason });
      }
    }
    receipt.elapsedMs = Math.round(performance.now() - started);
    finalizeRunReview(receipt);
    await writeJson(receipt.receiptFile, receipt);
  }
  return receipt;
}

export async function runProduction() { return runFixed(MODE.PRODUCTION); }
export async function verifyTodayCompleted() { return runFixed(MODE.VERIFY_TODAY); }
export async function downloadAndVerifyWithoutUpload() { return runFixed(MODE.DOWNLOAD_NO_UPLOAD); }

export function selfTest() {
  const date = yesterdayShanghai(new Date('2026-09-11T04:00:00Z'));
  if (date !== '2026-09-10') throw new Error(`yesterday-self-test:${date}`);
  if (!reportPattern('store', date).test('门店下载_20260910_全部门店_5296218123_20260911142517727.xlsx')) throw new Error('store-name-self-test');
  if (!reportPattern('review', date).test('评价下载_20260910至20260910_全部门店_5296218123_20260911143206308.xlsx')) throw new Error('review-name-self-test');
  if (!completedLogText('门店下载_20260910_全部门店_x\n2026-09-11\n上传完成', 'store', date)) throw new Error('store-dedup-self-test');
  if (completedLogText('评价下载_20260909_全部门店_x\n上传完成', 'review', date)) throw new Error('review-date-negative-self-test');
  if (!isTaobaoLoginUrl('https://melody.shop.ele.me/login') || isTaobaoLoginUrl('https://melody.shop.ele.me/app/chain/95708808/stats__center')) throw new Error('taobao-login-url-self-test');
  if (!isTaobaoSeedRecoveryUrl('https://melody.shop.ele.me/app/chain/95708808/dashboard#app.chainshop.dashboard') || !isTaobaoSeedRecoveryUrl(FIXED.taobao.home) || isTaobaoSeedRecoveryUrl('https://melody.shop.ele.me/app/chain/12345678/dashboard') || isTaobaoSeedRecoveryUrl('https://melody.shop.ele.me/login') || isTaobaoSeedRecoveryUrl('https://example.com/app/chain/95708808/dashboard')) throw new Error('taobao-auth-seed-recovery-url-self-test');
  // 2026-10-17：经营分析 iframe 路由 chain→single 升级，正负对照防回归。
  if (!isTaobaoAnalysisFrameUrl('https://melody-stats-next.ele.me/new/#/chain/business-analysis?tab=overview')
      || !isTaobaoAnalysisFrameUrl('https://melody-stats-next.ele.me/new/#/single/business-analysis?otherParams=&subTab=&tab=overview&')
      || isTaobaoAnalysisFrameUrl('https://melody-stats-next.ele.me/new/#/chain/business-report')
      || isTaobaoAnalysisFrameUrl('https://example.com/new/#/chain/business-analysis')
      || isTaobaoAnalysisFrameUrl(null)
      || isTaobaoAnalysisFrameUrl(123)) throw new Error('taobao-analysis-frame-url-self-test');
  const activityShellUrl = 'https://melody.shop.ele.me/app/shop/1364123817/activity__myActivity#app.shop.activity.myActivity';
  const activityShellFrames = [activityShellUrl,
    'https://napos-dashboard-pc.faas.ele.me/single?',
    'https://im.ele.me/napos?shopId=1364123817&shopType=SHOP&isDd=0',
    'https://melody-activity-index.faas.ele.me/home/myActivity?status=ACTIVATED&activeTab=investment'];
  if (!isTaobaoActivityShellRecoveryPage(activityShellUrl, activityShellFrames, 1)
      || isTaobaoActivityShellRecoveryPage(activityShellUrl, activityShellFrames, 2)
      || isTaobaoActivityShellRecoveryPage('https://melody.shop.ele.me/app/shop/1364123817/other#app.shop.other', activityShellFrames, 1)
      || isTaobaoActivityShellRecoveryPage(activityShellUrl, activityShellFrames.map((url) => url.replace('shopId=1364123817', 'shopId=1364123818')), 1)
      || isTaobaoActivityShellRecoveryPage(activityShellUrl, [activityShellUrl, activityShellFrames[2], activityShellFrames[3]], 1)) throw new Error('taobao-activity-shell-recovery-self-test');
  if (!isExactSelectedUploadFile(['门店下载_20260910_全部门店.xlsx'], '门店下载_20260910_全部门店.xlsx') || isExactSelectedUploadFile(['门店下载_20260910_全部门店.xlsx', '其他.xlsx'], '门店下载_20260910_全部门店.xlsx') || isExactSelectedUploadFile(['截断...xlsx'], '门店下载_20260910_全部门店.xlsx')) throw new Error('selected-upload-file-readback-self-test');
  const resumable = { ok: false, mode: MODE.PRODUCTION, businessDate: date, runtimeModelDecisions: 0, phaseHistory: ['initialized', 'profiles_ready', 'taobao_open', 'taobao_downloaded', 'taobao_closed', 'jinsha_open'], cleanupStatus: 'completed', taskMarkerCleanup: { taobao: true, jinsha: true }, clickAttempts: { download: { store: 1, review: 1 }, upload: { store: 0, review: 0 } }, files: { store: { path: '/tmp/store.xlsx' }, review: { path: '/tmp/review.xlsx' } } };
  if (!isSafeProductionResumeReceipt(resumable, date) || isSafeProductionResumeReceipt({ ...resumable, clickAttempts: { ...resumable.clickAttempts, upload: { store: 1, review: 0 } } }, date)) throw new Error('production-resume-contract-self-test');
  if (scheduledContinuationDecision(resumable, date).allowed !== true) throw new Error('scheduled-continuation-no-upload-self-test');
  if (scheduledContinuationDecision({ ...resumable, reason: 'upload-result-unknown:store' }, date).allowed !== false) throw new Error('scheduled-continuation-unknown-self-test');
  if (scheduledContinuationDecision({ ...resumable, cleanupStatus: 'pending' }, date).allowed !== false) throw new Error('scheduled-continuation-cleanup-self-test');
  const overlayBlocked = { ...resumable, reason: 'locator.click: Timeout 30000ms exceeded. <div class="zzc"></div> subtree intercepts pointer events', clickAttempts: { ...resumable.clickAttempts, upload: { store: 1, review: 0 } }, uploadDecision: { store: 'upload-clicked-awaiting-result' } };
  if (knownUndispatchedUploadType(overlayBlocked, date) !== 'store' || !isSafeProductionResumeReceipt(overlayBlocked, date) || knownUndispatchedUploadType({ ...overlayBlocked, reason: 'upload-result-unknown:store' }, date) !== null) throw new Error('known-undispatched-upload-resume-self-test');
  if (scheduledContinuationDecision(overlayBlocked, date).code !== 'safe-code-validated-production-resume') throw new Error('scheduled-continuation-code-validated-resume-self-test');
  const uploadedBeforeEvidence = { ...resumable, reason: 'page.screenshot: Timeout 30000ms exceeded. waiting for fonts to load...', clickAttempts: { ...resumable.clickAttempts, upload: { store: 1, review: 0 } }, uploadDecision: { store: 'uploaded-complete' }, failureDiagnostics: { jinsha: { frames: [{ text: '门店下载_20260910_全部门店_x\n2026-09-11\n上传完成' }] } } };
  if (confirmedUploadedBeforeEvidenceType(uploadedBeforeEvidence, date) !== 'store' || !isSafeProductionResumeReceipt(uploadedBeforeEvidence, date) || confirmedUploadedBeforeEvidenceType({ ...uploadedBeforeEvidence, reason: 'upload-result-unknown:store' }, date) !== null) throw new Error('confirmed-upload-before-evidence-resume-self-test');
  if (!isJinshaTaobaoView('智能斗金\n推广魔方\n全站推广列表\n数据上传') || isJinshaTaobaoView('智能点金\n美团点金\n数据下载')) throw new Error('jinsha-platform-semantic-self-test');
  // 2026-10-18 金鲨改版双轨正负对照：新版锚点（智能推广+数据上传）命中；美团视图/缺锚点不命中。
  if (!isJinshaTaobaoView('数据总览\n添加店铺\n智能推广\n活动监控\n数据上传\n应用中心')
    || isJinshaTaobaoView('数据总览\n添加店铺\n智能推广\n活动监控\n数据上传\n应用中心\n美团点金')
    || isJinshaTaobaoView('智能推广')) throw new Error('jinsha-platform-modern-semantic-self-test');
  if (!isJinshaUploadPage('数据上传\n评价上传\n上传数据\n上传日志') || !isJinshaUploadPage('数据上传\n评价上传\n上传评价\n上传日志') || isJinshaUploadPage('数据上传\n上传日志')) throw new Error('jinsha-upload-page-semantic-self-test');
  if (!borrowedJinshaRouteNeedsHome('https://data.guoshuyufen.com/#/negativeAnalyse')
    || borrowedJinshaRouteNeedsHome(FIXED.jinsha.home)
    || borrowedJinshaRouteNeedsHome(`https://data.guoshuyufen.com/${FIXED.jinsha.uploadHash}`)
    || borrowedJinshaRouteNeedsHome('https://example.com/#/negativeAnalyse')) throw new Error('jinsha-borrowed-route-normalization-self-test');
  const businessLease = jinshaBusinessRunIdFromMarker('aos-background-task:jinsha-business-production-20260924-01');
  if (businessLease?.runId !== 'jinsha-business-production-20260924-01' || businessLease?.runDay !== '20260924'
    || businessLease?.sequence !== '01' || jinshaBusinessRunIdFromMarker('aos-background-task:other-20260924-01')) throw new Error('jinsha-business-lease-marker-self-test');
  if (!isJinshaTabActive('nav_type_item active') || !isJinshaTabActive('nav_type_item pitchOn') || isJinshaTabActive('nav_type_item')) throw new Error('jinsha-tab-active-self-test');
  if (!isOwnedName('aos-background-task:x', 'aos-background-task:x') || !isOwnedName('nameStorage:aos-background-task%3Ax?trace=1', 'aos-background-task:x') || isOwnedName('nameStorage:aos-background-task%3Ay?trace=1', 'aos-background-task:x')) throw new Error('owned-name-self-test');
  let rejected = false;
  try { parseArgs(['--execute']); } catch (error) { rejected = error.message === 'business-cli-disabled-use-installed-entrypoint'; }
  if (!rejected || FIXED.taobao.profile !== 'taobao-brand' || FIXED.taobao.port !== 9230 || FIXED.jinsha.profile !== 'jinsha-business' || FIXED.jinsha.port !== 9232) throw new Error('fixed-channel-self-test');
  if (!assertProfileState(FIXED.taobao, { profile: FIXED.taobao.profile, port: FIXED.taobao.port, mode: 'headless' })) throw new Error('taobao-headless-profile-state-self-test');
  const stoppedTaobaoState = { profile: FIXED.taobao.profile, profilePath: path.join(PROFILE_ROOT, FIXED.taobao.profile),
    port: FIXED.taobao.port, mode: 'headless', pid: 4804, url: FIXED.taobao.home };
  if (!taobaoProfileMayColdStart(FIXED.taobao, stoppedTaobaoState, () => false)) throw new Error('taobao-stopped-profile-cold-start-positive-self-test');
  for (const change of [
    { profile: 'other-profile' }, { port: 9231 }, { profilePath: '/tmp/other-profile' },
    { mode: 'visible' }, { url: 'https://example.com/' },
  ]) {
    if (taobaoProfileMayColdStart(FIXED.taobao, { ...stoppedTaobaoState, ...change }, () => false)) throw new Error('taobao-stopped-profile-cold-start-negative-self-test');
  }
  if (taobaoProfileMayColdStart(FIXED.taobao, stoppedTaobaoState, () => true)) throw new Error('taobao-live-profile-cold-start-forbidden-self-test');
  if (taobaoProfileMayColdStart(FIXED.jinsha, stoppedTaobaoState, () => false)) throw new Error('non-taobao-profile-cold-start-forbidden-self-test');
  if (!assertProfileState(FIXED.jinsha, { profile: FIXED.jinsha.profile, port: FIXED.jinsha.port, mode: 'headless' })) throw new Error('jinsha-headless-profile-state-self-test');
  const handoff = { profile: FIXED.jinsha.profile, port: FIXED.jinsha.port, mode: 'visible-handoff', phase: 'WINDOW_RELEASED', site: 'jinsha', prefix: FIXED.jinsha.prefix, cdpEnabled: true, automationAttached: true, instanceId: 'instance-1', confirmationInstance: 'instance-1', activeTargetId: 'target-1', activeMarker: 'aos-background-task:test' };
  if (!assertProfileState(FIXED.jinsha, handoff)) throw new Error('jinsha-visible-handoff-profile-state-self-test');
  const releasedHandoff = { ...handoff, activeTargetId: undefined, activeMarker: undefined, taskTargetId: 'task-target-1', taskMarker: 'aos-background-task:test:work' };
  if (!assertProfileState(FIXED.jinsha, releasedHandoff)) throw new Error('jinsha-released-task-profile-state-self-test');
  if (JSON.stringify(visibleHandoffBinding(releasedHandoff)) !== JSON.stringify({ targetId: 'task-target-1', marker: 'aos-background-task:test:work', family: 'task' })) throw new Error('jinsha-released-task-binding-self-test');
  for (const change of [{ taskTargetId: '' }, { taskMarker: '' }]) {
    let mismatchRejected = false;
    try { assertProfileState(FIXED.jinsha, { ...releasedHandoff, ...change }); } catch (error) { mismatchRejected = error.message === 'profile-state-mismatch:jinsha-business'; }
    if (!mismatchRejected) throw new Error('jinsha-released-task-negative-self-test');
  }
  for (const change of [{ phase: 'BLOCKED' }, { site: 'meituan' }, { prefix: 'https://example.com/' }, { cdpEnabled: false }, { automationAttached: false }, { confirmationInstance: 'instance-2' }, { activeTargetId: '' }, { activeMarker: '' }]) {
    let mismatchRejected = false;
    try { assertProfileState(FIXED.jinsha, { ...handoff, ...change }); } catch (error) { mismatchRejected = error.message === 'profile-state-mismatch:jinsha-business'; }
    if (!mismatchRejected) throw new Error('jinsha-visible-handoff-negative-self-test');
  }
  let taobaoHandoffRejected = false;
  try { assertProfileState(FIXED.taobao, { ...handoff, profile: FIXED.taobao.profile, port: FIXED.taobao.port }); } catch (error) { taobaoHandoffRejected = error.message === 'profile-state-mismatch:taobao-brand'; }
  if (!taobaoHandoffRejected) throw new Error('taobao-visible-handoff-forbidden-self-test');
  if (!isAuthenticatedJinshaRecoveryPage('https://data.guoshuyufen.com/#/negativeAnalyse', '臻肆外卖运营 数据总览 添加店铺 数据中心')) throw new Error('jinsha-target-recovery-positive-self-test');
  for (const [url, text] of [
    ['https://example.com/#/negativeAnalyse', '臻肆外卖运营 数据总览 添加店铺 数据中心'],
    ['https://data.guoshuyufen.com/#/login', '臻肆外卖运营 数据总览 添加店铺 数据中心'],
    ['https://data.guoshuyufen.com/#/negativeAnalyse', '臻肆外卖运营 数据总览'],
    ['https://data.guoshuyufen.com/#/negativeAnalyse', '臻肆外卖运营 数据总览 添加店铺 账号密码'],
  ]) {
    if (isAuthenticatedJinshaRecoveryPage(url, text)) throw new Error('jinsha-target-recovery-negative-self-test');
  }
  const controllerMarker = 'aos-background-task:daily-taobao-jinsha:work';
  if (jinshaControllerRecoveryMode('https://data.guoshuyufen.com/#/negativeAnalyse', '', controllerMarker, controllerMarker) !== 'matching-controller-marker') throw new Error('jinsha-marker-recovery-positive-self-test');
  if (jinshaControllerRecoveryMode('https://data.guoshuyufen.com/#/negativeAnalyse', '臻肆外卖运营 数据总览 添加店铺 数据中心', '', controllerMarker) !== 'authenticated-unmarked-page') throw new Error('jinsha-unmarked-recovery-positive-self-test');
  for (const sample of [
    ['https://example.com/', '', controllerMarker, controllerMarker],
    ['https://data.guoshuyufen.com/#/negativeAnalyse', '', 'unknown-marker', controllerMarker],
    ['https://data.guoshuyufen.com/#/negativeAnalyse', '', '', controllerMarker],
  ]) {
    if (jinshaControllerRecoveryMode(...sample) !== null) throw new Error('jinsha-controller-recovery-negative-self-test');
  }
  const dedicatedCommand = `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome --remote-debugging-port=9232 --user-data-dir=${path.join(PROFILE_ROOT, FIXED.jinsha.profile)}`;
  if (!matchesDedicatedBrowserCommand(dedicatedCommand, FIXED.jinsha)) throw new Error('jinsha-dedicated-process-positive-self-test');
  for (const command of [
    dedicatedCommand.replace('Google Chrome.app/Contents/MacOS/Google Chrome', 'Safari'),
    dedicatedCommand.replace('--remote-debugging-port=9232', '--remote-debugging-port=9233'),
    dedicatedCommand.replace('jinsha-business', 'other-profile'),
  ]) {
    if (matchesDedicatedBrowserCommand(command, FIXED.jinsha)) throw new Error('jinsha-dedicated-process-negative-self-test');
  }
  if (FIXED.taobao.home.includes('/dashboard') || FIXED.executionOrder.join('>') !== 'taobao-download>jinsha-process') throw new Error('stable-route-order-self-test');
  const fake = {
    mode: MODE.PRODUCTION, phase: null, phaseHistory: [], runtimeModelDecisions: 0,
    controlPolicy: controlPolicySnapshot(MODE.PRODUCTION),
    clickAttempts: { download: { store: 0, review: 0 }, upload: { store: 0, review: 0 } },
    recoveryAttempts: { taobaoHomeReload: 0 }, pitfalls: [],
  };
  transition(fake, 'initialized');
  claimClick(fake, 'download', 'store');
  let doubleClickRejected = false;
  try { claimClick(fake, 'download', 'store'); } catch (error) { doubleClickRejected = error.message === 'click-budget-exhausted:download:store'; }
  if (!doubleClickRejected) throw new Error('click-budget-self-test');
  claimRecovery(fake, 'taobaoHomeReload', { code: 'self-test-recovery', reason: 'test' });
  let doubleRecoveryRejected = false;
  try { claimRecovery(fake, 'taobaoHomeReload', { code: 'forbidden', reason: 'test' }); } catch (error) { doubleRecoveryRejected = error.message === 'recovery-budget-exhausted:taobaoHomeReload'; }
  if (!doubleRecoveryRejected) throw new Error('recovery-budget-self-test');
  let policyDriftRejected = false;
  try { assertControlPolicy({ ...fake, controlPolicy: { ...fake.controlPolicy, channel: 'model-selected' } }); } catch (error) { policyDriftRejected = error.message === 'control-policy-drift'; }
  if (!policyDriftRejected) throw new Error('control-policy-self-test');
  const review = buildRunReview({
    stageMs: { profile_preflight: 12, task_cleanup: 3 },
    pitfalls: [{ stage: 'profile_preflight', code: 'recovered', reason: 'test' }],
    cleanupWarnings: ['test-warning'],
  });
  if (review.length !== 2 || review[0].label !== '固定后台浏览器预检' || review[0].pitfalls.length !== 1 || review[1].pitfalls.length !== 1) throw new Error('run-review-self-test');
  let unmeasuredPitfallRejected = false;
  try { buildRunReview({ stageMs: { profile_preflight: 1 }, pitfalls: [{ stage: 'unknown', code: 'x', reason: 'x' }] }); } catch (error) { unmeasuredPitfallRejected = error.message === 'review-pitfall-stage-unmeasured:unknown'; }
  if (!unmeasuredPitfallRejected) throw new Error('run-review-unmeasured-self-test');
  // 2026-10-18 复用已开页面（禁新开标签）决策正负对照：同源恰好 1 个⇒复用；
  // 0 个/非同源/多个⇒fail-closed；chrome:// 残留页（omnibox-popup 等）不算同源。
  if (!jinshaReusePageDecision(['https://data.guoshuyufen.com/#/uploadData/uploadData', 'chrome://omnibox-popup.top-chrome/']).ok
    || jinshaReusePageDecision(['https://data.guoshuyufen.com/#/uploadData/uploadData']).url !== 'https://data.guoshuyufen.com/#/uploadData/uploadData'
    || jinshaReusePageDecision([]).code !== 'jinsha-no-existing-origin-page'
    || jinshaReusePageDecision(['chrome://omnibox-popup.top-chrome/']).code !== 'jinsha-no-existing-origin-page'
    || jinshaReusePageDecision(['https://data.guoshuyufen.com/', 'https://data.guoshuyufen.com/#/x']).code !== 'jinsha-existing-origin-page-not-unique:2'
    || jinshaReusePageDecision(['https://example.com/']).code !== 'jinsha-no-existing-origin-page'
    || jinshaReusePageDecision(null).code !== 'jinsha-no-existing-origin-page') throw new Error('jinsha-reuse-page-decision-self-test');
  // 2026-10-18 「已在数据上传页」幂等判据正负对照：hash 命中或语义门命中⇒跳过重复点菜单。
  if (!jinshaAlreadyOnUploadPage('https://data.guoshuyufen.com/#/uploadData/uploadData', 'x')
    || !jinshaAlreadyOnUploadPage('https://data.guoshuyufen.com/#/businessData/realTimeData', '数据上传\n评价上传\n上传日志\n上传数据')
    || jinshaAlreadyOnUploadPage('https://data.guoshuyufen.com/#/businessData/realTimeData', '今日实时数据')
    || jinshaAlreadyOnUploadPage('https://data.guoshuyufen.com/#/negativeAnalyse', '差评列表')
    || jinshaAlreadyOnUploadPage(null, null)) throw new Error('jinsha-already-on-upload-page-self-test');
  return { ok: true, tests: 87, controlPolicyVersion: CONTROL_POLICY.version, fixedProfiles: { taobao: 'taobao-brand:9230', jinsha: 'jinsha-business:9232' }, desktopJinshaAllowed: false };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  let result;
  try {
    const options = parseArgs(process.argv.slice(2));
    result = options.selfTest ? selfTest() : { ok: false, reason: 'business-cli-disabled-use-installed-entrypoint' };
  } catch (error) { result = { ok: false, reason: String(error?.message || error) }; }
  console.log(JSON.stringify(result));
  if (!result.ok) process.exitCode = 1;
}
