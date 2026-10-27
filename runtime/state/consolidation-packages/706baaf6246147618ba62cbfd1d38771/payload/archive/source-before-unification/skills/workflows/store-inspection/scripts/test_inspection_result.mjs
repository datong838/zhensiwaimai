import assert from "node:assert/strict";
import { validateInspectionResult } from "./build_inspection_result.mjs";

const outputPath = process.argv[2];
assert.ok(outputPath, "usage: test_inspection_result.mjs <result.xlsx>");
const result = await validateInspectionResult(outputPath);
assert.equal(result.sheet, "Sheet1");
assert.equal(result.checks, 44);
console.log(JSON.stringify({ ok: true, ...result }));
