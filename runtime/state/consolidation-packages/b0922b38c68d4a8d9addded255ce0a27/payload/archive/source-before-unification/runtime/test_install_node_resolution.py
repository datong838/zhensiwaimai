"""Exercise only installer resolution, before any plist or service mutation."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SOURCE = Path(__file__).with_name('install_daemon.sh')

class NodeResolutionTests(unittest.TestCase):
    def resolve(self, mode):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / 'project/runtime'
            runtime.mkdir(parents=True)
            venv = root / '.venvs/harmonyos3-phone-control/bin'
            venv.mkdir(parents=True)
            (venv / 'python').symlink_to(sys.executable)
            binaries = root / 'bin'
            binaries.mkdir()
            fallback = binaries / 'node'
            fallback.write_text('#!/bin/sh\nexit 0\n')
            fallback.chmod(0o700)
            selected = root / 'configured-node'
            if mode == 'valid':
                selected.write_text('#!/bin/sh\nexit 0\n')
                selected.chmod(0o700)
            elif mode == 'directory':
                selected.mkdir()
            manifest = {'interpreters': {'node': '' if mode == 'empty' else str(selected)}}
            (runtime / 'skills_manifest.json').write_text(json.dumps(manifest))
            # The real installer is not executed: retain its exact pre-mutation prefix.
            prefix = SOURCE.read_text().split('mkdir -p "$HOME/Library/LaunchAgents"', 1)[0]
            self.assertNotIn('launchctl bootout', prefix)
            script = runtime / 'resolve-only.sh'
            script.write_text(prefix + '\nprintf "%s" "$NODE_BIN"\n')
            result = subprocess.run(['/bin/sh', str(script)], env={**os.environ, 'HOME': str(root), 'PATH': str(binaries) + ':/usr/bin:/bin'}, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse((root / 'Library').exists())
            return result.stdout.strip(), str(selected if mode == 'valid' else fallback)

    def test_valid_config_keeps_priority(self): self.assertEqual(*self.resolve('valid'))
    def test_missing_config_falls_back(self): self.assertEqual(*self.resolve('missing'))
    def test_directory_config_falls_back(self): self.assertEqual(*self.resolve('directory'))
    def test_empty_config_falls_back(self): self.assertEqual(*self.resolve('empty'))

if __name__ == '__main__': unittest.main()
