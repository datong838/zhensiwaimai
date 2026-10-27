#!/usr/bin/env node
// 金鲨岗封印校验器（posts/jinsha-post/scripts/verify_dependencies.mjs）
// 用法：node verify_dependencies.mjs  → 全部一致退出 0 并打印 {ok:true}；任一失配退出 1。
// 校验器自身不进清单（它就是标尺）；改动岗位任何被钉文件后，必须走受控流程重算 dependencies.json。
import crypto from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const SKILL_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const MANIFEST = path.join(SKILL_DIR, 'dependencies.json');

async function sha256(file) {
  return crypto.createHash('sha256').update(await fs.readFile(file)).digest('hex');
}

async function main() {
  const manifest = JSON.parse(await fs.readFile(MANIFEST, 'utf8'));
  const mismatches = [];
  for (const [file, expected] of Object.entries(manifest.files || {})) {
    const resolved = path.isAbsolute(file) ? file : path.join(SKILL_DIR, file);
    const actual = await sha256(resolved);
    if (actual !== expected) mismatches.push({file, expected, actual});
  }
  const result = {ok: mismatches.length === 0, status: mismatches.length === 0 ? 'clean' : 'drift', fileCount: Object.keys(manifest.files || {}).length, mismatches};
  console.log(JSON.stringify(result, null, 2));
  if (mismatches.length > 0) process.exitCode = 1;
}

main().catch(error => {
  console.error(JSON.stringify({ok: false, status: 'blocked', reason: String(error.message || error)}));
  process.exitCode = 1;
});
