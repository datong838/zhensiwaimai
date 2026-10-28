"""Verify or restore only the paused inspection workflow's local library links."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parent.parent
OLD = '/Users/ddt/.codex-runtimes/codex-primary-runtime/dependencies/node/node_modules'
LINKS = ['skills/workflows/store-inspection/node_modules',
         'skills/workflows/store-inspection/scripts/node_modules']
PAUSED = {'store-inspection', 'daily-store-metrics-rotation-to-wechat', 'coupon-issue-task-flow'}
REQUIRED = {'sharp', '@img/colour', 'detect-libc', 'semver',
            '@img/sharp-darwin-arm64', '@img/sharp-libvips-darwin-arm64', '@oai/artifact-tool'}


def verify_libraries(root):
    lock = json.loads((root / 'runtime/node-libraries.lock.json').read_text())
    packages = {p['name']: p for p in lock['packages']}
    if not REQUIRED <= packages.keys():
        raise ValueError('inspection-library-lock-incomplete')
    for name in REQUIRED:
        package = packages[name]
        folder = root / 'vendor/node_modules' / name
        if package['relativeRoot'] != str(folder.relative_to(root)) or folder.is_symlink():
            raise ValueError('inspection-library-root-invalid:' + name)
        actual = {str(p.relative_to(folder)) for p in folder.rglob('*') if p.is_file()}
        if any(p.is_symlink() for p in folder.rglob('*')):
            raise ValueError('inspection-library-symlink:' + name)
        if actual != {f['path'] for f in package['files']}:
            raise ValueError('inspection-library-file-set-drift:' + name)
        for entry in package['files']:
            path = folder / entry['path']
            if not path.resolve().is_relative_to(folder.resolve()):
                raise ValueError('inspection-library-path-escape')
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry['sha256']:
                raise ValueError('inspection-library-sha-drift:' + name)
    return sorted(REQUIRED)


def maintain(root=ROOT, *, apply=False):
    root = root.resolve()
    verified = verify_libraries(root)
    links = [root / name for name in LINKS]
    target = root / 'vendor/node_modules'
    before = {}
    for link in links:
        if not link.parent.resolve().is_relative_to(root):
            raise ValueError('inspection-link-parent-escape')
        old = os.readlink(link) if link.is_symlink() else None
        if link.exists() and not link.is_symlink():
            raise ValueError('inspection-link-is-real-directory')
        if old is not None and old != OLD and link.resolve() != target.resolve():
            raise ValueError('inspection-foreign-link')
        before[str(link.relative_to(root))] = old
    if apply:
        manifest = json.loads((root / 'runtime/skills_manifest.json').read_text())
        paused = [s for s in manifest['skills'] if s['name'] in PAUSED]
        if len(paused) != len(PAUSED) or any(s.get('enabled') is not False for s in paused):
            raise ValueError('inspection-workflows-must-remain-disabled')
        if any((root / 'runtime/state/live_steps').iterdir()):
            raise ValueError('original-director-busy')
        changed = []
        try:
            for link in links:
                old = before[str(link.relative_to(root))]
                if (link.exists() and not link.is_symlink()) or (os.readlink(link) if link.is_symlink() else None) != old:
                    raise ValueError('inspection-link-changed-during-review')
                if link.is_symlink() and link.resolve() == target.resolve():
                    continue
                temporary = link.with_name('.inspection-library-' + uuid.uuid4().hex)
                try:
                    temporary.symlink_to(os.path.relpath(target, link.parent))
                    os.replace(temporary, link)
                finally:
                    temporary.unlink(missing_ok=True)
                changed.append((link, old))
        except BaseException:
            for link, old in reversed(changed):
                if link.is_symlink() and link.resolve() == target.resolve():
                    if old is None:
                        link.unlink()
                    else:
                        temporary = link.with_name('.inspection-rollback-' + uuid.uuid4().hex)
                        temporary.symlink_to(old)
                        os.replace(temporary, link)
            raise
    return {'ok': all(p.is_symlink() and p.resolve() == target.resolve() for p in links),
            'apply': apply, 'before': before, 'verifiedLibraries': verified,
            'productionActions': 0, 'workflowEnablementChanged': False,
            'scope': 'library bytes and two module links; not native-platform or production acceptance'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(maintain(apply=args.apply), ensure_ascii=False))
