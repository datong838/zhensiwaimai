import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import maintain_store_inspection_dependencies as module


class LocalLibraries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'runtime/state/live_steps').mkdir(parents=True)
        packages = []
        for name in module.REQUIRED:
            folder = self.root / 'vendor/node_modules' / name
            folder.mkdir(parents=True)
            data = json.dumps({'name': name}).encode()
            (folder / 'package.json').write_bytes(data)
            packages.append({'name': name, 'relativeRoot': str(folder.relative_to(self.root)),
                             'files': [{'path': 'package.json', 'sha256': hashlib.sha256(data).hexdigest()}]})
        (self.root / 'runtime/node-libraries.lock.json').write_text(json.dumps({'packages': packages}))
        (self.root / 'runtime/skills_manifest.json').write_text(json.dumps({'skills': [
            {'name': n, 'enabled': False} for n in module.PAUSED]}))
        for name in module.LINKS:
            p = self.root / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.symlink_to(module.OLD)

    def test_readonly_does_not_switch(self):
        result = module.maintain(self.root)
        self.assertFalse(result['ok'])
        self.assertTrue(all(p == module.OLD for p in result['before'].values()))

    def test_apply_and_idempotent(self):
        self.assertTrue(module.maintain(self.root, apply=True)['ok'])
        self.assertTrue(module.maintain(self.root, apply=True)['ok'])
        for name in module.LINKS:
            self.assertFalse((self.root / name).readlink().is_absolute())

    def test_new_host_missing_links(self):
        for name in module.LINKS:
            (self.root / name).unlink()
        self.assertTrue(module.maintain(self.root, apply=True)['ok'])

    def test_library_drift_rejects_without_switch(self):
        (self.root / 'vendor/node_modules/sharp/package.json').write_text('changed')
        with self.assertRaisesRegex(ValueError, 'sha-drift'):
            module.maintain(self.root, apply=True)
        self.assertEqual((self.root / module.LINKS[0]).readlink(), Path(module.OLD))

    def test_foreign_link_and_real_directory_rejected(self):
        p = self.root / module.LINKS[0]
        p.unlink(); p.symlink_to('/foreign/unavailable')
        with self.assertRaisesRegex(ValueError, 'foreign-link'):
            module.maintain(self.root, apply=True)
        p.unlink(); p.mkdir()
        with self.assertRaisesRegex(ValueError, 'real-directory'):
            module.maintain(self.root, apply=True)

    def test_busy_or_enabled_rejected(self):
        busy = self.root / 'runtime/state/live_steps/live.json'
        busy.touch()
        with self.assertRaisesRegex(ValueError, 'director-busy'):
            module.maintain(self.root, apply=True)
        busy.unlink()
        (self.root / 'runtime/skills_manifest.json').write_text('{"skills":[]}')
        with self.assertRaisesRegex(ValueError, 'remain-disabled'):
            module.maintain(self.root, apply=True)

    def test_partial_apply_failure_rolls_back(self):
        original = module.os.replace
        def replace(src, dest):
            if str(dest).endswith('/scripts/node_modules'):
                raise OSError('injected replace failure')
            return original(src, dest)
        with patch.object(module.os, 'replace', side_effect=replace):
            with self.assertRaisesRegex(OSError, 'injected'):
                module.maintain(self.root, apply=True)
        for name in module.LINKS:
            self.assertEqual((self.root / name).readlink(), Path(module.OLD))


if __name__ == '__main__':
    unittest.main()
