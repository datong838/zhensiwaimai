import concurrent.futures
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime'))
import post_group_lease as core
import run_all as director

if os.environ.get('GROUP_LEASE_TEST_ORIGINAL') == '1':
    # Compile the exact original source with its original runtime path, no execution.
    import types
    director = types.ModuleType('original_group_director')
    director.__file__ = str(ROOT / 'runtime/run_all.py')
    exec(compile((ROOT / 'runtime/state/director-group-lock-20261028/originals/run_all.py').read_text(),
                 director.__file__, 'exec'), director.__dict__)


class GroupLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.patch = patch.object(director, 'POST_GROUP_LOCK_DIR', self.directory)
        self.patch.start()
        self.path = self.directory / 'post.lock'

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def put(self, **overrides):
        value = {'group': 'post', 'runId': 'old', 'pid': os.getpid(),
                 'acquiredAt': '2000-01-01T00:00:00'}
        value.update(overrides)
        self.path.write_text(json.dumps(value))
        return self.path.read_bytes()

    def acquire(self, run='new'):
        return director.acquire_post_group_lock('post', run)

    def test_expired_live_owner_not_stolen(self):
        original = self.put()
        self.assertIsNone(self.acquire())
        self.assertEqual(self.path.read_bytes(), original)

    def test_fresh_dead_owner_recovered(self):
        self.put(pid=999999999, acquiredAt=director._now_iso())
        lease = self.acquire()
        self.assertIsNotNone(lease)
        self.assertTrue(json.loads(self.path.read_text())['recovered'])
        director.release_post_group_lock(lease)
        self.assertFalse(self.path.exists())

    def test_invalid_owner_and_bad_json_remain_busy(self):
        for content in ['{', '[]', '{}', json.dumps({'pid': True}),
                        json.dumps({'pid': '12'}), json.dumps({'pid': -1})]:
            with self.subTest(content=content):
                self.path.write_text(content)
                self.assertIsNone(self.acquire())
                self.assertEqual(self.path.read_text(), content)

    def test_permission_uncertain_owner_preserved(self):
        original = self.put(pid=23456789)
        with patch('os.kill', side_effect=PermissionError('uncertain')):
            self.assertIsNone(self.acquire())
        self.assertEqual(self.path.read_bytes(), original)

    def test_symlink_preserved(self):
        target = self.directory / 'original'
        target.write_text('{}')
        self.path.symlink_to(target)
        self.assertIsNone(self.acquire())
        self.assertTrue(self.path.is_symlink())
        self.assertEqual(target.read_text(), '{}')

    def test_same_run_not_reentrant(self):
        lease = self.acquire()
        self.assertIsNone(self.acquire())
        director.release_post_group_lock(lease)
        self.assertFalse(self.path.exists())

    def test_wrong_owner_cannot_release(self):
        lease = self.acquire()
        original = self.path.read_bytes()
        for field, value in [('pid', 999999999), ('runId', 'wrong'), ('group', 'wrong'),
                             ('acquiredAt', '2000-01-01T00:00:00'), ('leaseId', 'wrong')]:
            with self.subTest(field=field):
                self.path.write_bytes(original)
                director.release_post_group_lock({**lease, field: value})
                self.assertEqual(self.path.read_bytes(), original)
        director.release_post_group_lock(lease)

    def test_exact_foreign_owner_cannot_be_released(self):
        lease = self.acquire()
        foreign = {**lease, 'pid': 999999999}
        disk = {key: value for key, value in foreign.items() if key != 'path'}
        self.path.write_text(json.dumps(disk))
        original = self.path.read_bytes()
        director.release_post_group_lock(foreign)
        self.assertEqual(self.path.read_bytes(), original)

    def test_old_same_run_lease_cannot_release_new_lease(self):
        old = self.acquire()
        director.release_post_group_lock(old)
        new = self.acquire()
        director.release_post_group_lock(old)
        self.assertTrue(self.path.exists())
        director.release_post_group_lock(new)
        self.assertFalse(self.path.exists())

    def test_legacy_partial_release_cannot_remove(self):
        original = self.put()
        director.release_post_group_lock({'path': self.path, 'runId': 'old'})
        self.assertEqual(self.path.read_bytes(), original)

    def test_dead_owner_recovery_is_serialized(self):
        self.put(pid=999999999)
        # All child processes hold their winning lease until the parent releases them.
        script = '''import json,sys,os
sys.path.insert(0, sys.argv[1])
import run_all
from pathlib import Path
run_all.POST_GROUP_LOCK_DIR=Path(sys.argv[2])
x=run_all.acquire_post_group_lock('post','same')
print(json.dumps({'won':x is not None}),flush=True)
sys.stdin.readline()
if x: run_all.release_post_group_lock(x)
'''
        children = [subprocess.Popen([sys.executable, '-c', script, str(ROOT / 'runtime'),
                                      str(self.directory)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for _ in range(12)]
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
                results = list(pool.map(lambda p: json.loads(p.stdout.readline()), children))
            self.assertEqual(sum(item['won'] for item in results), 1)
        finally:
            for child in children:
                child.communicate('\n', timeout=10)
                self.assertEqual(child.returncode, 0)
        self.assertFalse(self.path.exists())

    def test_guard_process_death_releases_kernel_lock(self):
        script = '''import fcntl,os,sys
f=os.open(sys.argv[1],os.O_CREAT|os.O_RDWR,0o600)
fcntl.flock(f,fcntl.LOCK_EX)
print('held',flush=True)
sys.stdin.readline()
'''
        child = subprocess.Popen([sys.executable, '-c', script, str(self.path)+'.guard'],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'held')
            self.assertIsNone(self.acquire())
            child.kill()
            child.communicate(timeout=5)
            lease = self.acquire()
            self.assertIsNotNone(lease)
            director.release_post_group_lock(lease)
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate()

    def test_new_file_contract_is_complete_iso_owner(self):
        lease = self.acquire()
        value = json.loads(self.path.read_text())
        self.assertEqual(value['group'], 'post')
        self.assertEqual(value['pid'], os.getpid())
        self.assertEqual(value['runId'], 'new')
        self.assertIsInstance(value['acquiredAt'], str)
        self.assertGreater(len(value['leaseId']), 20)
        director.release_post_group_lock(lease)
        self.assertIsNone(director.release_post_group_lock(lease))


if __name__ == '__main__':
    unittest.main()
