import fs from "node:fs/promises";
import path from "node:path";
import { assembleHybridInspection } from "./assemble_hybrid_inspection.mjs";

export const MEITUAN_ROW_CONTRACTS = Object.freeze({
  7: [["reviews", "商家是否回复"], ["reviews", "回复率"], ["reviews", "5 分钟回复率"]],
  8: [["reviews", "同行差评分析"]],
  9: [["reviews", "自动回复是否启用"], ["reviews", "自动回复规则或模板"]],
  13: [["activities", "满减档位"], ["activities", "折扣规则"]],
  14: [["products", "商品参加的活动"], ["activities", "适用门店和商品"]],
  15: [["products", "商品 ID 和完整名称"], ["products", "招牌、推荐、热销等后台标记"]],
  16: [["products", "原价、活动价、预计到手价"], ["products", "商品销量或销量排行"]],
  17: [["products", "招牌、推荐、热销等后台标记"]],
  18: [["store-profile", "品牌或资质状态", "堂食、连锁、品牌等平台标签", "门头图、Logo、环境图"]],
  19: [["store-profile", "营业时间"]],
  20: [["store-profile", "预订设置"]],
  24: [["delivery", "平均出餐时长", "P50、P90 出餐时长"]],
  27: [["activities", "店外投放券"]],
  28: [["activities", "下单返券"]],
  29: [["activities", "集点或复购活动"]],
  30: [["activities", "报名、审核和执行状态"]],
  31: [["products", "分类 ID、名称、描述、排序和启用状态"], ["products", "分类商品数量"]],
  32: [["products", "分类 ID、名称、描述、排序和启用状态"]],
  33: [["delivery", "配送面积", "配送半径", "配送区域"]],
  34: [["delivery", "全城送状态"]],
  35: [["delivery", "配送模式", "平台配送或自配送"]],
  36: [["products", "商品 ID 和完整名称"]],
  37: [["products", "商品描述"]],
  42: [["activities", "商家承担金额"], ["activities", "平台承担金额"], ["activities", "配送补贴"]],
  43: [["promotion", "账户余额"], ["promotion", "当前出价"]],
});

function text(value) { return String(value ?? "").trim(); }
function receiptObject(value) { return Array.isArray(value) ? value[0] : value; }
function sameStore(store, receipt) { return ["platform", "city", "storeName"].every((key) => text(store[key]) === text(receipt[key])) && text(store.storeId) === text(receipt.storeId) && text(store.address) === text(receipt.address); }
function shanghaiDate(value) {
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) throw new Error("meituan-receipt-observed-at-invalid");
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Shanghai", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
}

export function mapMeituanBackendFacts(input) {
  const store = input?.store ?? {};
  for (const key of ["platform", "city", "rosterStoreName", "storeName", "storeId", "address", "inspectionDate"]) if (!text(store[key])) throw new Error(`store-field-required:${key}`);
  if (store.platform !== "美团外卖") throw new Error(`meituan-platform-required:${store.platform}`);
  const receipts = new Map();
  for (const raw of input.receipts ?? []) {
    const receipt = receiptObject(raw);
    if (!receipt?.module || receipts.has(receipt.module)) throw new Error(`meituan-receipt-module-invalid:${receipt?.module}`);
    if (!sameStore(store, receipt)) throw new Error(`meituan-receipt-store-mismatch:${receipt.module}`);
    receipts.set(receipt.module, receipt);
  }
  const facts = [];
  const usedRows = new Set();
  for (const candidate of input.candidates ?? []) {
    const row = Number(candidate.row);
    const groups = MEITUAN_ROW_CONTRACTS[row];
    if (!groups) throw new Error(`meituan-row-contract-missing:${candidate.row}`);
    if (usedRows.has(row)) throw new Error(`duplicate-fact-row:${row}`);
    usedRows.add(row);
    const used = [];
    for (const group of groups) {
      const [module, ...allowedFields] = group;
      const receipt = receipts.get(module);
      if (!receipt || receipt.status !== "available") throw new Error(`meituan-row-receipt-not-available:${row}:${module}`);
      const matched = allowedFields.find((fieldName) => receipt.fields?.[fieldName]?.value !== null && receipt.fields?.[fieldName]?.value !== undefined && text(receipt.fields[fieldName].value));
      if (!matched) throw new Error(`meituan-row-field-missing:${row}:${module}:${allowedFields.join("|")}`);
      used.push({ module, field: matched, rawName: text(receipt.fields[matched].rawName), value: receipt.fields[matched].value });
    }
    const observedAt = used.map((item) => receipts.get(item.module).observedAt).sort().at(-1);
    facts.push({
      ...store,
      row,
      sourceType: "meituan_backend",
      observedDate: shanghaiDate(observedAt),
      sourceRef: `meituan:${store.storeId}:${row}:${text(observedAt)}`,
      finding: text(candidate.finding),
      recommendation: text(candidate.recommendation),
      fieldRefs: used,
    });
  }
  assembleHybridInspection({ store, facts });
  return { store, facts };
}

export async function mapMeituanBackendFactsFile({ inputPath, outputPath }) {
  const result = mapMeituanBackendFacts(JSON.parse(await fs.readFile(inputPath, "utf8")));
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  return { outputPath, facts: result.facts.length, rows: result.facts.map((fact) => fact.row) };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) throw new Error("usage: map_meituan_backend_facts.mjs <input.json> <facts.json>");
  console.log(JSON.stringify(await mapMeituanBackendFactsFile({ inputPath, outputPath }), null, 2));
}
