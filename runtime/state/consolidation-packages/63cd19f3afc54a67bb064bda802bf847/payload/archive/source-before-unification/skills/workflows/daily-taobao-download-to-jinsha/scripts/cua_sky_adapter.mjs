import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

export async function createCuaSkyAdapter({ chromeApp, jinshaApp, getChromeApp, workRoot = os.tmpdir() } = {}) {
  if (!chromeApp || !jinshaApp) throw new Error("cua-app-bindings-required");
  const screenshotDir = await fs.mkdtemp(path.join(workRoot, "zhensi-cua-state-"));
  let screenshotIndex = 0;
  const metrics = { raiseCount: 0, chromeRebindCount: 0 };
  let chromeBinding = chromeApp;
  const resolve = (app) => app === "com.google.Chrome" ? chromeBinding : jinshaApp;
  const adapter = {
    metrics,
    async refresh_app_binding({ app } = {}) {
      if (app !== "com.google.Chrome" || typeof getChromeApp !== "function") return false;
      chromeBinding = await getChromeApp();
      metrics.chromeRebindCount += 1;
      return true;
    },
    async get_app_state({ app, disableDiff = true } = {}) {
      const target = resolve(app);
      const text = await target.getAXState({ emit: false, disableDiffing: disableDiff });
      return { text };
    },
    async get_screenshot_state({ app, disableDiff = true } = {}) {
      const target = resolve(app);
      const [text, screenshot] = await Promise.all([
        target.getAXState({ emit: false, disableDiffing: disableDiff }),
        target.getScreenshot({ emit: false }),
      ]);
      const file = path.join(screenshotDir, `${String(screenshotIndex++).padStart(4, "0")}.png`);
      await fs.writeFile(file, screenshot, { mode: 0o600 });
      return { text, screenshot: { url: pathToFileURL(file).href } };
    },
    async click({ app, element_index: elementIndex, x, y } = {}) {
      const target = resolve(app);
      if (Number.isFinite(elementIndex)) return target.click(elementIndex);
      if (Number.isFinite(x) && Number.isFinite(y)) return target.click([x, y]);
      throw new Error("cua-click-target-required");
    },
    async press_key({ app, key } = {}) { return resolve(app).pressKey(key); },
    async scroll({ app, element_index: elementIndex, x, y, direction, pages } = {}) {
      const target = Number.isFinite(elementIndex) ? elementIndex : [x, y];
      return resolve(app).scroll(target, direction, pages);
    },
    async set_value({ app, element_index: elementIndex, value } = {}) {
      return resolve(app).setValue(elementIndex, value);
    },
    async perform_secondary_action({ app, element_index: elementIndex, action } = {}) {
      if (action === "Raise") metrics.raiseCount += 1;
      return resolve(app).performSecondaryAction(elementIndex, action);
    },
    async dispose() { await fs.rm(screenshotDir, { recursive: true, force: true }); },
  };
  return adapter;
}

export async function selfTestCuaSkyAdapter() {
  const calls = [];
  const fake = {
    async getAXStateAndScreenshot() { calls.push("state"); return { state: "ok", screenshot: new Uint8Array([1, 2, 3]) }; },
    async getAXState() { calls.push("ax"); return "ok"; },
    async getScreenshot() { calls.push("screenshot"); return new Uint8Array([1, 2, 3]); },
    async click(target) { calls.push(["click", target]); },
    async pressKey(key) { calls.push(["key", key]); },
    async scroll(target, direction, pages) { calls.push(["scroll", target, direction, pages]); },
    async setValue(target, value) { calls.push(["value", target, value]); },
    async performSecondaryAction(target, action) { calls.push(["secondary", target, action]); },
  };
  const adapter = await createCuaSkyAdapter({ chromeApp: fake, jinshaApp: fake, getChromeApp: async () => fake });
  const state = await adapter.get_app_state({ app: "com.google.Chrome" });
  await adapter.click({ app: "com.google.Chrome", element_index: 7 });
  await adapter.click({ app: "jinsha", x: 10, y: 20 });
  await adapter.press_key({ app: "jinsha", key: "Escape" });
  await adapter.scroll({ app: "com.google.Chrome", element_index: 9, direction: "down", pages: 1 });
  await adapter.set_value({ app: "jinsha", element_index: 4, value: "x" });
  await adapter.perform_secondary_action({ app: "jinsha", element_index: 0, action: "Raise" });
  await adapter.refresh_app_binding({ app: "com.google.Chrome" });
  await adapter.dispose();
  const fallback = { ...fake, async getAXStateAndScreenshot() { return { state: "fallback" }; } };
  const fallbackAdapter = await createCuaSkyAdapter({ chromeApp: fallback, jinshaApp: fallback });
  const fallbackState = await fallbackAdapter.get_app_state({ app: "com.google.Chrome" });
  const screenshotState = await fallbackAdapter.get_screenshot_state({ app: "com.google.Chrome" });
  await fallbackAdapter.dispose();
  if (state.text !== "ok" || state.screenshot || calls.length !== 10 || fallbackState.text !== "ok" || fallbackState.screenshot || screenshotState.text !== "ok" || !screenshotState.screenshot?.url || adapter.metrics.raiseCount !== 1 || adapter.metrics.chromeRebindCount !== 1) throw new Error("cua-adapter-self-test-failed");
  return { ok: true, tests: 11 };
}
