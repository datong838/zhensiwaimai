import os
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

from refresh_shop_pool import run_collector


class CollectorLifecycleTests(unittest.TestCase):
    def cleanup(self, pid):
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.exited.append(pid)

    def setUp(self):
        self.exited = []

    def test_success_reaps_before_cleanup_and_preserves_output(self):
        result = run_collector([sys.executable, '-c', "print('complete')"], 3, self.cleanup)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), 'complete')
        self.assertEqual(len(self.exited), 1)

    def test_timeout_reaps_real_child_before_cleanup(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            run_collector([sys.executable, '-c', 'import time; time.sleep(30)'], .1, self.cleanup)
        self.assertEqual(len(self.exited), 1)

    def test_failed_child_is_reaped_and_returncode_preserved(self):
        result = run_collector([sys.executable, '-c', 'import sys; sys.exit(7)'], 3, self.cleanup)
        self.assertEqual(result.returncode, 7)
        self.assertEqual(len(self.exited), 1)

    def test_cleanup_error_is_not_reported_as_collection_success(self):
        def failed_cleanup(pid):
            self.cleanup(pid)
            raise ValueError('cleanup-unconfirmed')
        with self.assertRaisesRegex(ValueError, 'cleanup-unconfirmed'):
            run_collector([sys.executable, '-c', 'pass'], 3, failed_cleanup)
        self.assertEqual(len(self.exited), 1)

    def test_real_node_timeout_releases_only_its_temporary_lease(self):
        node = os.environ.get('ZENSI_NODE') or shutil.which('node')
        self.assertTrue(node, 'Node is required for the collector integration test')
        run_id = 'monthly-roster-' + str(uuid.uuid4())
        helper = (Path(__file__).parent/'release_roster_lease.mjs').resolve().as_uri()
        with tempfile.TemporaryDirectory(prefix='roster-timeout-test-') as folder:
            lease = Path(folder)/'lease.json'
            script = "require('fs').writeFileSync(process.argv[1],JSON.stringify({runId:process.argv[2],pid:process.pid}));setInterval(()=>{},1000)"
            def cleanup(pid):
                self.cleanup(pid)
                self.assertTrue(lease.exists(), 'test child must have acquired its temporary lease')
                code = f"import {{releaseExitedRosterLease}} from {json.dumps(helper)}; console.log(JSON.stringify(await releaseExitedRosterLease(process.argv[1],Number(process.argv[2]),{{leasePath:process.argv[3]}})));"
                result = subprocess.run([node, '--input-type=module', '-e', code, run_id, str(pid), str(lease)],
                                        check=True, capture_output=True, text=True, timeout=3)
                self.assertTrue(json.loads(result.stdout)['released'])
            with self.assertRaises(subprocess.TimeoutExpired):
                run_collector([node, '-e', script, str(lease), run_id], .5, cleanup)
            self.assertFalse(lease.exists())
            self.assertEqual(len(self.exited), 1)


if __name__ == '__main__':
    unittest.main()
