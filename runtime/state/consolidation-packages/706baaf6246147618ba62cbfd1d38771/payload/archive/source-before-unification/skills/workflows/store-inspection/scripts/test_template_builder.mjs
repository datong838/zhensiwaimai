import assert from "node:assert/strict";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { buildInspectionResult, validateInspectionResult } from "./build_inspection_result.mjs";

const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), "store-inspection-template-test-"));
const inputPath = path.join(tempDir, "inspection.json");
const outputPath = path.join(tempDir, "result.xlsx");
const previewDir = path.join(tempDir, "preview");

await fs.writeFile(inputPath, JSON.stringify({
  platform: "测试平台",
  city: "上海市",
  rosterStoreName: "测试门店",
  storeName: "测试门店",
  inspectionDate: "2026-09-09",
  templateChecks: Array.from({ length: 44 }, (_, index) => ({
    row: index + 2,
    finding: `第${index + 2}行测试发现`,
    recommendation: `第${index + 2}行具体方案`,
    evidence: "测试证据.png",
  })),
}, null, 2));

const built = await buildInspectionResult({ inputPath, outputPath, previewDir });
const validated = await validateInspectionResult(outputPath);
assert.equal(built.checks, 44);
assert.equal(validated.checks, 44);
assert.equal(validated.sheet, "Sheet1");
const builtText = await fs.readFile(outputPath);
assert.ok(builtText.byteLength > 0);
const blankInputPath = path.join(tempDir, "blank-inspection.json");
const blankOutputPath = path.join(tempDir, "blank-result.xlsx");
await fs.writeFile(blankInputPath, JSON.stringify({
  platform: "测试平台",
  city: "上海市",
  rosterStoreName: "测试门店",
  storeName: "测试门店",
  inspectionDate: "2026-09-09",
  templateChecks: Array.from({ length: 44 }, (_, index) => ({
    row: index + 2,
    finding: index === 0 ? "" : `第${index + 2}行测试发现`,
    recommendation: index === 0 ? "" : `第${index + 2}行具体方案`,
    evidence: index === 0 ? "" : "测试证据.png",
  })),
}, null, 2));
await buildInspectionResult({ inputPath: blankInputPath, outputPath: blankOutputPath, previewDir });
await validateInspectionResult(blankOutputPath);
console.log(JSON.stringify({ ok: true, outputPath, checks: validated.checks }));
