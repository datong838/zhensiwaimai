import { createRequire } from 'node:module';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const folder = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(folder, '../../..');
const result = [];
for (const base of ['skills/workflows/store-inspection', 'skills/workflows/store-inspection/scripts']) {
  const require = createRequire(path.join(root, base, 'dependency-check.cjs'));
  for (const name of ['sharp', '@oai/artifact-tool']) {
    const resolved = fs.realpathSync(require.resolve(name));
    if (!resolved.startsWith(root + '/vendor/node_modules/')) throw Error('external-library-resolution');
    result.push({ base, name, resolved });
  }
}
const require = createRequire(path.join(root, 'skills/workflows/store-inspection/scripts/dependency-check.cjs'));
const sharp = require('sharp');
if (process.platform !== 'darwin' || process.arch !== 'arm64') throw Error('native-platform-unverified');
const receipt = { ok: true, platform: process.platform, arch: process.arch,
  sharp: sharp.versions.sharp, vips: sharp.versions.vips, resolution: result, productionActions: 0 };
fs.writeFileSync(path.join(folder, 'resolution.json'), JSON.stringify(receipt, null, 2) + '\n');
console.log(JSON.stringify(receipt));
