import fs from "node:fs/promises";
import path from "node:path";
import { assembleHybridInspection } from "./assemble_hybrid_inspection.mjs";

export const JINSHA_ROW_CONTRACTS = Object.freeze({
  5: [["multi-store", "店铺评分"]],
  6: [["multi-store", "店铺评分"]],
  10: [["negative-reviews", "差评数量"], ["negative-reviews", "差评主题"]],
  11: [["multi-store", "月售销量"], ["multi-store", "有效订单"]],
  12: [["historical", "周期有效订单"], ["historical", "上周期变化"]],
  13: [["activities", "满减档位"], ["activities", "活动时间"]],
  14: [["products", "招牌分类商品"], ["activities", "满减档位"]],
  15: [["products", "招牌分类商品"]],
  16: [["products", "商品价格带"]],
  17: [["products", "招牌分类商品"]],
  22: [["historical", "7天复购率"], ["historical", "30天复购率"], ["historical", "老客订单"]],
  31: [["products", "分类名称"], ["products", "分类数量"]],
  36: [["products", "商品完整名称"]],
  44: [["historical", "经营指标对比"], ["historical", "评价对比"]],
});

function text(value) { return String(value ?? "").trim(); }
function receiptObject(value) { return Array.isArray(value) ? value[0] : value; }
function sameStore(store, receipt) {
  return ["platform", "city", "storeName", "storeId"].every((key) => text(store[key]) === text(receipt[key]));
}
function shanghaiDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error("jinsha-receipt-observed-at-invalid");
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

export function mapJinshaFacts(input) {
  const store = input?.store ?? {};
  for (const key of ["platform", "city", "rosterStoreName", "storeName", "storeId", "inspectionDate"]) if (!text(store[key])) throw new Error(`store-field-required:${key}`);
  const receipts = new Map();
  for (const raw of input.receipts ?? []) {
    const receipt = receiptObject(raw);
    if (!receipt?.module || receipts.has(receipt.module)) throw new Error(`jinsha-receipt-module-invalid:${receipt?.module}`);
    if (!sameStore(store, receipt)) throw new Error(`jinsha-receipt-store-mismatch:${receipt.module}`);
    receipts.set(receipt.module, receipt);
  }
  const facts = [];
  const usedRows = new Set();
  for (const candidate of input.candidates ?? []) {
    const row = Number(candidate.row);
    const groups = JINSHA_ROW_CONTRACTS[row];
    if (!groups) throw new Error(`jinsha-row-contract-missing:${candidate.row}`);
    if (usedRows.has(row)) throw new Error(`duplicate-fact-row:${row}`);
    usedRows.add(row);
    const used = [];
    for (const group of groups) {
      const [module, ...allowedFields] = group;
      const receipt = receipts.get(module);
      if (!receipt || receipt.status !== "available") throw new Error(`jinsha-row-receipt-not-available:${row}:${module}`);
      const matched = allowedFields.find((fieldName) => receipt.fields?.[fieldName]?.value !== null && receipt.fields?.[fieldName]?.value !== undefined && text(receipt.fields[fieldName].value));
      if (!matched) throw new Error(`jinsha-row-field-missing:${row}:${module}:${allowedFields.join("|")}`);
      used.push({ module, field: matched, rawName: text(receipt.fields[matched].rawName), value: receipt.fields[matched].value });
    }
    const observedAt = used.map((item) => receipts.get(item.module).observedAt).sort().at(-1);
    facts.push({
      ...store,
      row,
      sourceType: "jinsha_report",
      observedDate: shanghaiDate(observedAt),
      sourceRef: `jinsha:${store.storeId}:${row}:${text(observedAt)}`,
      finding: text(candidate.finding),
      recommendation: text(candidate.recommendation),
      fieldRefs: used,
    });
  }
  assembleHybridInspection({ store, facts });
  return { store, facts };
}

export async function mapJinshaFactsFile({ inputPath, outputPath }) {
  const result = mapJinshaFacts(JSON.parse(await fs.readFile(inputPath, "utf8")));
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  return { outputPath, facts: result.facts.length, rows: result.facts.map((fact) => fact.row) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) throw new Error("usage: map_jinsha_facts.mjs <input.json> <facts.json>");
  console.log(JSON.stringify(await mapJinshaFactsFile({ inputPath, outputPath }), null, 2));
}
