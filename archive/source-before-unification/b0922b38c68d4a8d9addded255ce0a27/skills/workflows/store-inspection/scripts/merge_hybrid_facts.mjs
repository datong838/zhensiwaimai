import fs from "node:fs/promises";
import path from "node:path";

export function mergeHybridFacts(base, overrides) {
  if (!base?.store || !Array.isArray(base?.facts) || !Array.isArray(overrides?.facts)) throw new Error("hybrid-facts-input-invalid");
  const overrideRows = new Set();
  for (const fact of overrides.facts) {
    const row = Number(fact?.row);
    if (!Number.isInteger(row) || overrideRows.has(row)) throw new Error(`hybrid-override-row-invalid:${fact?.row}`);
    overrideRows.add(row);
  }
  return { store: base.store, facts: [...base.facts.filter((fact) => !overrideRows.has(Number(fact.row))), ...overrides.facts].sort((a, b) => Number(a.row) - Number(b.row)) };
}

export async function mergeHybridFactsFile({ basePath, overridesPath, outputPath }) {
  const base = JSON.parse(await fs.readFile(basePath, "utf8"));
  const overrides = JSON.parse(await fs.readFile(overridesPath, "utf8"));
  const result = mergeHybridFacts(base, overrides);
  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  await fs.writeFile(outputPath, `${JSON.stringify(result, null, 2)}\n`, "utf8");
  return { outputPath, facts: result.facts.length, overrideRows: overrides.facts.length };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const [, , basePath, overridesPath, outputPath] = process.argv;
  if (![basePath, overridesPath, outputPath].every(Boolean)) throw new Error("usage: merge_hybrid_facts.mjs <base.json> <overrides.json> <output.json>");
  console.log(JSON.stringify(await mergeHybridFactsFile({ basePath, overridesPath, outputPath }), null, 2));
}
