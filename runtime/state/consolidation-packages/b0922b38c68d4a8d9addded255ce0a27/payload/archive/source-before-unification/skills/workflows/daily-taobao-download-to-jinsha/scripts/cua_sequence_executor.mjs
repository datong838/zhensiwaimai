import { createCuaSkyAdapter } from "./cua_sky_adapter.mjs";
import { isMerchantMenuOnlyState, runDownloadExecutor } from "./download_executor.mjs";
import { loadTargetFromReceipt, runJinshaPrepareSequence } from "./jinsha_prepare_executor.mjs";
import { sendDesktopWechatEvidence } from "./desktop_wechat_evidence_sender.mjs";

function rejectLegacyExecution() {
  throw new Error('legacy-executor-disabled-use-installed-entrypoint');
}

export function isJinshaReadyState(state) {
  if (!state.includes("URL: data.guoshuyufen.com/#/") || state.includes("electron-quick-start")) return false;
  const uploadLinks = state.split("\n").filter((line) =>
    /^\s*\d+ link Description: 数据上传, Value: .*\/#\/uploadData\/uploadData$/.test(line));
  return uploadLinks.length === 1;
}

export function isTransientJinshaLifecycleError(error) {
  return /App quit|noWindowsAvailable|native pipe closed before response|timeoutReachedWindow/i.test(String(error));
}

export function jinshaTaobaoPlatformTextIndex(state) {
  if (isJinshaReadyState(state)) return null;
  const labels = ["外卖", "团购", "分账", "美团", "淘宝", "京东"];
  const nodes = state.split("\n").flatMap((line) => {
    const match = line.match(/^\s*(\d+) 文本 (外卖|团购|分账|美团|淘宝|京东)$/);
    return match ? [{ index: Number(match[1]), label: match[2] }] : [];
  });
  const matches = nodes.flatMap((node, offset) =>
    labels.every((label, delta) => nodes[offset + delta]?.label === label)
      ? [nodes[offset + 4].index]
      : []);
  return matches.length === 1 ? matches[0] : null;
}

export function isChromeFrontMerchantState(beforeRaise, afterRaise) {
  const merchant = (text) => text.includes("淘宝闪购商家版");
  const correctChain = (text) => text.includes("melody.shop.ele.me/app/chain/95708808/");
  if (!merchant(beforeRaise) || !correctChain(beforeRaise) || !merchant(afterRaise)) return false;
  return correctChain(afterRaise) || isMerchantMenuOnlyState(afterRaise);
}

export async function runDailyTaobaoDownloadToJinsha({
  chromeApp,
  getChromeApp,
  jinshaApp,
  downloadDir,
  downloadReceipt = "/tmp/zhensi_daily_download/download_receipt.json",
  resumeStoreFile = null,
  resumeDownload = false,
  uploadMode = "stop-before-open",
  wechatSendAuthorized = false,
  wechatChannel = "mobile",
  wechatAuthorization = null,
  sendWechatEvidence = null,
} = {}) {
  rejectLegacyExecution();
  const started = performance.now();
  const result = {
    ok: false,
    executor: "daily-taobao-download-to-jinsha",
    stage: "preflight",
    stageMs: {},
    modelInterventionsDuringRun: 0,
  };
  if (!["mobile", "desktop"].includes(wechatChannel)) throw new Error("wechat-channel-invalid");
  const adapter = await createCuaSkyAdapter({ chromeApp, jinshaApp, getChromeApp });
  const timed = async (name, action) => {
    result.stage = name;
    const stageStarted = performance.now();
    try { return await action(); }
    finally { result.stageMs[name] = Math.round(performance.now() - stageStarted); }
  };
  try {
    const chromeFrontState = await timed("chrome_front_gate", async () => {
      let state = await adapter.get_app_state({ app: "com.google.Chrome", disableDiff: true });
      if (!/^\s*0 .*Secondary Actions: Raise/m.test(state.text)) throw new Error("chrome-window-root-unavailable");
      const beforeRaise = state.text;
      await adapter.perform_secondary_action({ app: "com.google.Chrome", element_index: 0, action: "Raise" });
      state = await adapter.get_app_state({ app: "com.google.Chrome", disableDiff: true });
      if (!isChromeFrontMerchantState(beforeRaise, state.text)) {
        throw new Error("chrome-front-merchant-gate-failed");
      }
      return state;
    });
    result.download = resumeDownload
      ? await timed("download_receipt_resume", async () => {
        const [store, review] = await Promise.all([
          loadTargetFromReceipt("store", downloadReceipt),
          loadTargetFromReceipt("review", downloadReceipt),
        ]);
        if (store.businessDate !== review.businessDate) throw new Error("download-receipt-date-mismatch");
        return { ok: true, resumed: true, businessDate: store.businessDate, store, review };
      })
      : await timed("download", () => runDownloadExecutor({
        sky: adapter,
        ...(downloadDir ? { downloadDir } : {}),
        receiptFile: downloadReceipt,
        resumeStoreFile,
        initialState: chromeFrontState,
      }));
    if (result.download.ok !== true) throw new Error(`download-failed:${result.download.stage}:${result.download.reason}`);
    const selectedWechatSender = wechatChannel === "desktop"
      ? (sendWechatEvidence || (manifest => sendDesktopWechatEvidence(manifest, { authorization: wechatAuthorization })))
      : sendWechatEvidence;
    result.jinsha = await timed("jinsha_prepare_sequence", () => runJinshaPrepareSequence({
      sky: adapter,
      ...(downloadReceipt ? { downloadReceipt } : {}),
      uploadMode,
      wechatSendAuthorized,
      sendWechatEvidence: selectedWechatSender,
      wechatChannel,
    }));
    if (result.jinsha.ok !== true) throw new Error("jinsha-prepare-sequence-failed");
    result.ok = true;
    result.stage = uploadMode === "dedup-upload" ? "uploads_completed_or_skipped" : "review_selected_before_open";
    result.finalState = result.jinsha.finalState;
    result.openClicked = result.jinsha.openClicked;
    result.uploadOccurred = result.jinsha.uploadOccurred;
  } catch (error) {
    result.reason = String(error?.message ?? error);
  } finally {
    result.elapsedMs = Math.round(performance.now() - started);
    result.controlMetrics = { ...adapter.metrics };
    await adapter.dispose();
  }
  return result;
}

export async function runDailyWithColdStartedJinsha({
  chromeApp,
  currentJinshaApp,
  getJinshaApp,
  ...options
} = {}) {
  rejectLegacyExecution();
  if (!chromeApp || !currentJinshaApp || typeof getJinshaApp !== "function") throw new Error("cold-start-bindings-required");
  const started = performance.now();
  let lifecycleRecoveryRaise = 0;
  let restartBoundarySeen = false;
  try {
    let current = await currentJinshaApp.getAXState({ emit: false, disableDiffing: true });
    if (current.includes("ID: open-panel")) {
      await currentJinshaApp.pressKey("Escape");
      current = await currentJinshaApp.getAXState({ emit: false, disableDiffing: true });
    }
    await currentJinshaApp.pressKey("super+q");
  } catch (error) {
    if (!isTransientJinshaLifecycleError(error)) throw error;
    if (isTransientJinshaLifecycleError(error)) restartBoundarySeen = true;
    if (/timeoutReachedWindow/.test(String(error))) {
      try {
        const rebound = await getJinshaApp();
        const reboundState = await rebound.getAXState({ emit: false, disableDiffing: true });
        if (!reboundState.includes("ID: open-panel")) {
          try {
            await rebound.performSecondaryAction(0, "Raise");
            lifecycleRecoveryRaise = 1;
            await rebound.getAXState({ emit: false, disableDiffing: true });
          } catch (raiseError) {
            if (!isTransientJinshaLifecycleError(raiseError)) throw raiseError;
          }
          try { await rebound.pressKey("super+q"); } catch (retryError) {
            if (!isTransientJinshaLifecycleError(retryError)) throw retryError;
            restartBoundarySeen = true;
          }
        }
      } catch (recoveryError) {
        if (!isTransientJinshaLifecycleError(recoveryError)) throw recoveryError;
        restartBoundarySeen = true;
      }
    }
  }
  let jinshaApp = null;
  let ready = false;
  let processWindowMs = null;
  let businessUrlMs = null;
  let taobaoViewReadyMs = null;
  let sidebarReadyMs = null;
  let platformSwitchAttempts = 0;
  const readyDeadline = performance.now() + 75_000;
  while (performance.now() < readyDeadline) {
    try {
      jinshaApp = await getJinshaApp();
      const state = await jinshaApp.getAXState({ emit: false, disableDiffing: true });
      if (!isJinshaReadyState(state)) restartBoundarySeen = true;
      if (processWindowMs == null && /^Window: /m.test(state)) processWindowMs = Math.round(performance.now() - started);
      if (businessUrlMs == null && state.includes("URL: data.guoshuyufen.com/#/") && !state.includes("electron-quick-start")) {
        businessUrlMs = Math.round(performance.now() - started);
      }
      const taobaoPlatformIndex = jinshaTaobaoPlatformTextIndex(state);
      if (!isJinshaReadyState(state) && platformSwitchAttempts === 0 && taobaoPlatformIndex != null) {
        platformSwitchAttempts += 1;
        await jinshaApp.click(taobaoPlatformIndex);
      }
      if (restartBoundarySeen && isJinshaReadyState(state)) {
        const confirmation = await jinshaApp.getAXState({ emit: false, disableDiffing: true });
        if (isJinshaReadyState(confirmation)) {
          ready = true;
          taobaoViewReadyMs = Math.round(performance.now() - started);
          sidebarReadyMs = Math.round(performance.now() - started);
          break;
        }
      }
    } catch (error) {
      if (!isTransientJinshaLifecycleError(error)) throw error;
      restartBoundarySeen = true;
    }
    if (performance.now() >= readyDeadline) break;
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  if (!ready || !jinshaApp) {
    throw new Error(`jinsha-cold-start-not-ready:process=${processWindowMs ?? "missing"}:url=${businessUrlMs ?? "missing"}:sidebar=${sidebarReadyMs ?? "missing"}`);
  }
  const coldStartMs = Math.round(performance.now() - started);
  const result = await runDailyTaobaoDownloadToJinsha({ chromeApp, jinshaApp, ...options });
  result.stageMs = {
    jinsha_process_window: processWindowMs,
    jinsha_business_url: businessUrlMs,
    jinsha_taobao_view_ready: taobaoViewReadyMs,
    jinsha_sidebar_ready: sidebarReadyMs,
    jinsha_cold_start: coldStartMs,
    ...result.stageMs,
  };
  result.elapsedMsWithColdStart = Math.round(performance.now() - started);
  result.jinshaLifecycle = "cold-started";
  result.jinshaLifecycleRecoveryRaise = lifecycleRecoveryRaise;
  result.jinshaPlatformSwitchAttempts = platformSwitchAttempts;
  return result;
}

// 唯一稳定生产/考核入口。调用者无需判断金鲨当前是否处于可复用状态。
export async function runStableDailyTaobaoDownloadToJinsha(options = {}) {
  rejectLegacyExecution();
  const result = await runDailyWithColdStartedJinsha(options);
  result.entrypoint = "stable-cold-start";
  return result;
}

// 每日 15:00 生产入口：上传决策完全由今日同类型、同业务日期完成记录决定。
export async function runScheduledDailyTaobaoDownloadToJinsha(options = {}) {
  rejectLegacyExecution();
  const result = await runStableDailyTaobaoDownloadToJinsha({ ...options, uploadMode: "dedup-upload" });
  result.entrypoint = "scheduled-dedup-upload";
  return result;
}

export function selfTestColdStartReadiness() {
  const ready = "0 application\n  1 link Description: 数据上传, Value: data.guoshuyufen.com/#/uploadData/uploadData\n  2 webarea URL: data.guoshuyufen.com/#/";
  const shellOnly = "0 webarea URL: data.guoshuyufen.com/#/";
  const duplicate = `${ready}\n  3 link Description: 数据上传, Value: data.guoshuyufen.com/#/uploadData/uploadData`;
  const meituanView = "0 application\n  9 文本 外卖\n  10 文本 团购\n  11 文本 分账\n  12 文本 美团\n  13 文本 淘宝\n  14 文本 京东\n  15 webarea URL: data.guoshuyufen.com/#/businessData/realTimeData\n  16 文本 美团\n  17 文本 淘宝";
  const ambiguousTaobao = `${meituanView}\n  20 文本 外卖\n  21 文本 团购\n  22 文本 分账\n  23 文本 美团\n  24 文本 淘宝\n  25 文本 京东`;
  const chromeBeforeRaise = 'Window: "淘宝闪购商家版", App: Google Chrome.\n0 标准窗口 Secondary Actions: Raise\n9 文本栏 (settable) Description: 地址和搜索栏, Value: melody.shop.ele.me/app/chain/95708808/downloadCenter#app.chainshop.downloadCenter';
  const chromeMenuAfterRaise = 'Window: "淘宝闪购商家版", App: Google Chrome.\n0 菜单 Secondary Actions: Cancel\n  1 商家首页\n  2 数据中心';
  if (!isJinshaReadyState(ready)) throw new Error("jinsha-ready-state-self-test-failed");
  if (isJinshaReadyState(shellOnly)) throw new Error("jinsha-shell-state-self-test-failed");
  if (isJinshaReadyState(duplicate)) throw new Error("jinsha-duplicate-upload-link-self-test-failed");
  if (typeof runStableDailyTaobaoDownloadToJinsha !== "function") throw new Error("stable-entrypoint-missing");
  if (typeof runScheduledDailyTaobaoDownloadToJinsha !== "function") throw new Error("scheduled-entrypoint-missing");
  if (!isTransientJinshaLifecycleError("Sky Computer Use native pipe closed before response")) throw new Error("jinsha-native-pipe-transient-self-test-failed");
  if (!isTransientJinshaLifecycleError("Computer Use server error -10005: timeoutReachedWindow")) throw new Error("jinsha-timeout-transient-self-test-failed");
  if (isTransientJinshaLifecycleError("jinsha-upload-page-link-missing")) throw new Error("jinsha-business-error-misclassified");
  if (jinshaTaobaoPlatformTextIndex(meituanView) !== 13) throw new Error("jinsha-taobao-platform-index-self-test-failed");
  if (jinshaTaobaoPlatformTextIndex(ambiguousTaobao) !== null) throw new Error("jinsha-taobao-platform-ambiguity-self-test-failed");
  if (jinshaTaobaoPlatformTextIndex(ready) !== null) throw new Error("jinsha-ready-platform-noop-self-test-failed");
  if (!isChromeFrontMerchantState(chromeBeforeRaise, chromeMenuAfterRaise)
    || isChromeFrontMerchantState(chromeBeforeRaise.replace("95708808", "95708809"), chromeMenuAfterRaise)
    || isChromeFrontMerchantState(chromeBeforeRaise, chromeMenuAfterRaise.replace("淘宝闪购商家版", "淘宝闪购服务商平台"))) throw new Error("chrome-front-continuity-self-test-failed");
  return { ok: true, tests: 12 };
}
