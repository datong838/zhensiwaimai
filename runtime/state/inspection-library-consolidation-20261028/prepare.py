"""One-off library preparation; does not alter the two inspection links."""
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
SOURCE = Path('/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/node_modules')
NAMES = ['sharp', '@img/colour', 'detect-libc', 'semver',
         '@img/sharp-darwin-arm64', '@img/sharp-libvips-darwin-arm64']


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


if (OUT / 'prepared.json').exists():
    raise SystemExit('already prepared; inspect original receipt before repeating')
old_lock = json.loads((ROOT / 'runtime/node-libraries.lock.json').read_text())
baseline = {}
for package in old_lock['packages']:
    for entry in package['files']:
        p = ROOT / package['relativeRoot'] / entry['path']
        if sha(p) != entry['sha256']:
            raise ValueError('original library drift')
        baseline[str(p.relative_to(ROOT))] = sha(p)
for name in ['runtime/skills_manifest.json', 'runtime/posts.json', 'runtime/state/control.json']:
    baseline[name] = sha(ROOT / name)
for name in ['store-inspection', 'daily-store-metrics-rotation-to-wechat', 'coupon-issue-task-flow']:
    base = ROOT / 'skills/workflows' / name
    for folder in ['runtime', 'state', '.runtime', 'data', 'docs']:
        for p in (base / folder).rglob('*'):
            if p.is_file() and not p.is_symlink():
                baseline[str(p.relative_to(ROOT))] = sha(p)
(OUT / 'original-node-libraries.lock.json').write_bytes((ROOT / 'runtime/node-libraries.lock.json').read_bytes())
(OUT / 'original-dependency-contract.json').write_bytes((ROOT / 'runtime/dependency-contract.json').read_bytes())
packages = []
for name in NAMES:
    source = SOURCE / name
    target = ROOT / 'vendor/node_modules' / name
    if target.exists() or target.is_symlink() or any(p.is_symlink() for p in source.rglob('*')):
        raise ValueError('unexpected destination or source symlink:' + name)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target)
    files = []
    for p in sorted(source.rglob('*')):
        if p.is_file():
            relative = p.relative_to(source)
            if sha(p) != sha(target / relative):
                raise ValueError('copy mismatch')
            files.append({'path': str(relative), 'sha256': sha(p)})
    if len(files) != sum(p.is_file() for p in target.rglob('*')):
        raise ValueError('copy file set mismatch')
    packages.append({'name': name, 'version': json.loads((source / 'package.json').read_text())['version'],
                     'relativeRoot': str(target.relative_to(ROOT)),
                     'bytes': sum(p.stat().st_size for p in target.rglob('*') if p.is_file()), 'files': files})
new_lock = old_lock | {'packages': old_lock['packages'] + packages}
(ROOT / 'runtime/node-libraries.lock.json').write_text(json.dumps(new_lock, indent=2) + '\n')
shadow = OUT / 'isolated-inspection'
shadow.mkdir()
shutil.copytree(ROOT / 'skills/workflows/store-inspection/scripts', shadow / 'scripts',
                ignore=shutil.ignore_patterns('node_modules', '__pycache__'))
(shadow / 'node_modules').symlink_to(ROOT / 'vendor/node_modules')
(shadow / 'runtime').mkdir()
template = ROOT / 'skills/workflows/store-inspection/runtime/门店自检表(框架+模板).xlsx'
shutil.copy2(template, shadow / 'runtime' / template.name)
receipt = {'copiedPackages': packages, 'originalFileSha256': baseline,
           'originalLinks': {str(p.relative_to(ROOT)): str(p.readlink()) for p in [
               ROOT / 'skills/workflows/store-inspection/node_modules',
               ROOT / 'skills/workflows/store-inspection/scripts/node_modules']},
           'platform': 'darwin-arm64', 'productionActions': 0}
(OUT / 'prepared.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'packages': len(packages), 'files': sum(len(p['files']) for p in packages),
                  'bytes': sum(p['bytes'] for p in packages), 'originalFilesProtected': len(baseline)}))
