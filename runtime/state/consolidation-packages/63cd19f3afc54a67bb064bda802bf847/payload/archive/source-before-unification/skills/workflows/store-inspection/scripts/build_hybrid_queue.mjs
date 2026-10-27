import fs from "node:fs/promises";
import path from "node:path";

const DEFAULT_DAILY_CAPACITIES = [160, 160, 160, 160, 160, 160, 40];
const MAX_BATCH_SIZE = 80;
const MAX_DAILY_CAPACITY = 160;

function text(value) { return String(value ?? "").trim(); }

export function storeKey(record) {
  return [record.platform, record.name, record.city].map(text).join("\u0000");
}

export function normalizeRecords(records) {
  const unique = new Map();
  for (const record of records ?? []) {
    const normalized = { platform: text(record.platform), name: text(record.name), city: text(record.city) };
    if (!normalized.platform || !normalized.name || !normalized.city) throw new Error(`invalid-roster-record:${JSON.stringify(record)}`);
    unique.set(storeKey(normalized), normalized);
  }
  return [...unique.values()].sort((left, right) => left.platform.localeCompare(right.platform, "zh-CN") || left.city.localeCompare(right.city, "zh-CN") || left.name.localeCompare(right.name, "zh-CN"));
}

function normalizeCapacities(capacities = DEFAULT_DAILY_CAPACITIES) {
  if (!Array.isArray(capacities) || !capacities.length) throw new Error("daily-capacities-required");
  return capacities.map((value, index) => {
    const capacity = Number(value);
    if (!Number.isInteger(capacity) || capacity < 1 || capacity > MAX_DAILY_CAPACITY) throw new Error(`invalid-daily-capacity:${index + 1}:${value}:max-${MAX_DAILY_CAPACITY}`);
    return capacity;
  });
}

export function buildHybridQueue({ week, records, dailyCapacities = DEFAULT_DAILY_CAPACITIES, batchSize = MAX_BATCH_SIZE }) {
  if (!text(week)) throw new Error("week-required");
  const normalized = normalizeRecords(records);
  const capacities = normalizeCapacities(dailyCapacities);
  const boundedBatchSize = Number(batchSize);
  if (!Number.isInteger(boundedBatchSize) || boundedBatchSize < 1 || boundedBatchSize > MAX_BATCH_SIZE) throw new Error(`invalid-batch-size:${batchSize}:max-${MAX_BATCH_SIZE}`);
  const totalCapacity = capacities.reduce((sum, value) => sum + value, 0);
  if (totalCapacity < normalized.length) throw new Error(`weekly-capacity-insufficient:${totalCapacity}:${normalized.length}`);
  let cursor = 0;
  const queue = [];
  const days = [];
  for (let day = 0; day < capacities.length && cursor < normalized.length; day += 1) {
    const start = cursor;
    const limit = Math.min(start + capacities[day], normalized.length);
    for (; cursor < limit; cursor += 1) {
      const record = normalized[cursor];
      queue.push({ ...record, key: storeKey(record), day: day + 1, batch: Math.floor((cursor - start) / boundedBatchSize) + 1, state: "BACKEND_FACTS_PENDING" });
    }
    days.push({ day: day + 1, capacity: capacities[day], assigned: limit - start });
  }
  return { week: text(week), batchSize: boundedBatchSize, dailyCapacities: capacities, totalStores: normalized.length, queue, days, compensationQueue: [] };
}

export async function buildHybridQueueFile({ inputPath, outputPath }) {
  const result = buildHybridQueue(JSON.parse(await fs.readFile(inputPath, "utf8")));
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  return { outputPath, totalStores: result.totalStores, days: result.days.length };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , inputPath, outputPath] = process.argv;
  if (!inputPath || !outputPath) throw new Error("usage: build_hybrid_queue.mjs <roster.json> <queue.json>");
  console.log(JSON.stringify(await buildHybridQueueFile({ inputPath, outputPath }), null, 2));
}
