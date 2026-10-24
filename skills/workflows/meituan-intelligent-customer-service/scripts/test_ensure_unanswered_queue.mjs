import assert from "node:assert/strict";
import { runWithUnansweredQueue } from "./ensure_unanswered_queue.mjs";

function fakeDriver({ url = "https://waimaie.meituan.com/imworkbench/home#/im/page/workbench/reception", state, counts, failWait = false, ignoreClicks = false }) {
  const events = [];
  const current = structuredClone(state);
  return {
    events,
    async url() { return url; },
    async countExact(text) { events.push(`count:${text}`); return counts?.[text] ?? 1; },
    async clickExact(text) {
      events.push(`click:${text}`);
      if (!ignoreClicks && text === "全部顾客消息") current.activeMainTabs = [text];
      if (!ignoreClicks && text === "未回复") current.activeFilters = [text];
    },
    async waitForSelected(kind, text) {
      events.push(`wait:${kind}:${text}`);
      if (failWait) throw new Error("selection-timeout");
    },
    async readState() { events.push("read-state"); return structuredClone(current); },
  };
}

const success = fakeDriver({ state: { activeMainTabs: ["正在接待"], activeFilters: ["未读"] } });
assert.deepEqual(await runWithUnansweredQueue(success, async (_driver, receipt) => receipt), {
  ok: true, page: "imworkbench", mainTab: "全部顾客消息", filter: "未回复",
});
assert.deepEqual(success.events.filter((event) => event.startsWith("click:")), [
  "click:全部顾客消息", "click:未回复",
]);

await assert.rejects(
  runWithUnansweredQueue(fakeDriver({ url: "https://waimaie.meituan.com/", state: { activeMainTabs: [], activeFilters: [] } }), async () => {}),
  /not-isolated-meituan-workbench/,
);
await assert.rejects(
  runWithUnansweredQueue(fakeDriver({ state: { activeMainTabs: [], activeFilters: [] }, counts: { "全部顾客消息": 2 } }), async () => {}),
  /main-tab-target-not-unique/,
);
await assert.rejects(
  runWithUnansweredQueue(fakeDriver({ state: { activeMainTabs: ["正在接待"], activeFilters: ["未读"] }, failWait: true }), async () => {}),
  /selection-timeout/,
);
await assert.rejects(
  runWithUnansweredQueue(fakeDriver({ state: { activeMainTabs: ["正在接待"], activeFilters: ["未读"] }, ignoreClicks: true }), async () => {}),
  /main-tab-selection-not-verified/,
);
let scanned = false;
const callbackResult = await runWithUnansweredQueue(
  fakeDriver({ state: { activeMainTabs: ["正在接待"], activeFilters: ["未读"] } }),
  async (_driver, receipt) => { scanned = true; return receipt.filter; },
);
assert.equal(scanned, true);
assert.equal(callbackResult, "未回复");
scanned = false;
await assert.rejects(
  runWithUnansweredQueue(
    fakeDriver({ state: { activeMainTabs: ["正在接待"], activeFilters: ["未读"] }, ignoreClicks: true }),
    async () => { scanned = true; },
  ),
  /main-tab-selection-not-verified/,
);
assert.equal(scanned, false);

console.log("queue guard tests passed (7 cases)");
