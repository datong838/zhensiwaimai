import assert from "node:assert/strict";
import { normalizeRecords, storeKey } from "./build_weekly_roster.mjs";

const rows = normalizeRecords([
  { platform: "美团外卖", name: "A店", city: "上海市" },
  { platform: "美团外卖", name: "A店", city: "上海市" },
  { platform: "淘宝闪购", name: "A店", city: "上海市" },
]);
assert.equal(rows.length, 2);
assert.notEqual(storeKey(rows[0]), storeKey(rows[1]));
assert.throws(() => normalizeRecords([{ platform: "美团外卖", name: "", city: "上海市" }]));
console.log("weekly-roster-self-test:ok");
