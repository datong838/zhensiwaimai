"""仅临时fixture；不执行业务、不触碰真实state/intent。"""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import skill_runner as runner

BUDGETS = {
    'daily-top10-to-wechat-group': 600,
    'daily-meituan-income-top10-to-wechat': 900,
    'contract-termination-applications-screenshot': 1200,
    'daily-agent-new-merchants-to-wechat': 1200,
    'daily-new-stores-opening-to-wechat': 1200,
    'negative-feedback-list-appeals-0930': 600,
    'negative-feedback-list-appeals-1230': 1200,
    'daily-service-market-ranking-to-wechat': 900,
    'daily-negative-reviews': 2400,
}


def running(pid):
    result = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='],
                            capture_output=True, text=True, check=False)
    return result.returncode == 0 and bool(result.stdout.strip()) and not result.stdout.strip().startswith('Z')


class MorningBudgetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, value in [('REPO_ROOT', self.root), ('RUN_DIR_ROOT', self.root/'runs'),
                            ('LIVE_STEPS_DIR', self.root/'live')]:
            p = patch.object(runner, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.intent = self.root/'intent.json'
        self.original_intent = b'{"event":"fixture-original","status":"unknown"}\n'
        self.intent.write_bytes(self.original_intent)
        self.addCleanup(lambda: self.assertEqual(self.intent.read_bytes(), self.original_intent))

    def entry(self, program, timeout=1, steps=None):
        return {'name': 'offline-fixture', 'cwd': '.', 'timeout_seconds': timeout,
                'max_retries': 0, 'cooldown_seconds': 0,
                'steps': steps or [{'argv': [sys.executable, '-c', program]}]}

    def run_fixture(self, entry):
        return runner.run_skill(entry, history_dir=self.root/'history')

    def test_manifest_exact_nine_finite_budgets(self):
        manifest = json.loads((Path(__file__).parent/'skills_manifest.json').read_text())
        early = [x for x in manifest['skills'] if x.get('enabled') and x.get('earliest_hour', 99) <= 10]
        self.assertEqual({x['name'] for x in early}, set(BUDGETS))
        for entry in early:
            self.assertEqual(entry['timeout_seconds'], BUDGETS[entry['name']])
            self.assertEqual((entry['max_retries'], entry['cooldown_seconds']), (0, 0))
        self.assertEqual(sum(x['timeout_seconds']*len(x['steps']) for x in early), 11400)

    def test_timeout_cleans_ordinary_child_and_next_flow_succeeds(self):
        pidfile = self.root/'child.pid'
        script = ("import subprocess,sys,time; from pathlib import Path; "
                  "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                  f"Path({str(pidfile)!r}).write_text(str(p.pid)); time.sleep(60)")
        result = self.run_fixture(self.entry(script))
        child = int(pidfile.read_text())
        self.addCleanup(lambda: os.kill(child, signal.SIGKILL) if running(child) else None)
        self.assertEqual((result['status'], result['attempts']), ('FAILED', 1))
        self.assertLess(result['duration_seconds'], 5)
        self.assertFalse(running(child))
        self.assertEqual(list((self.root/'live').glob('*.json')), [])
        following = self.run_fixture(self.entry("print('fixture-following-success')"))
        self.assertEqual(following['status'], 'SUCCESS')

    def test_recoverable_failure_does_not_retry_or_sleep(self):
        calls = self.root/'calls'
        script = (f"from pathlib import Path; p=Path({str(calls)!r}); "
                  "p.write_text(p.read_text()+'x' if p.exists() else 'x'); "
                  "print('ECONNRESET fixture'); raise SystemExit(1)")
        clock = SimpleNamespace(time=time.time, strftime=time.strftime,
                                sleep=lambda _: self.fail('same-round-wait'))
        with patch.object(runner, 'time', clock):
            result = self.run_fixture(self.entry(script))
        self.assertEqual(result['category'], runner.CAT_RECOVERABLE)
        self.assertEqual(result['attempts'], 1)
        self.assertEqual(calls.read_text(), 'x')

    def test_each_step_receives_its_own_timeout(self):
        steps = [{'argv': [sys.executable, '-c', 'import time; time.sleep(.65)']} for _ in range(2)]
        result = self.run_fixture(self.entry('', timeout=1, steps=steps))
        self.assertEqual(result['status'], 'SUCCESS')
        self.assertGreater(result['duration_seconds'], 1)
        self.assertEqual(len(result['logs']), 2)

    def test_p0_ignored_term_child_is_killed_and_live_record_cleared(self):
        # P0回归：leader先响应TERM退出时，忽略TERM的孙进程仍须由原组KILL清理。
        pidfile = self.root/'resistant.pid'
        child_program = ('import signal,time; from pathlib import Path; '
                         'signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                         f'Path({str(pidfile)!r}).write_text(str(__import__("os").getpid())); '
                         'time.sleep(60)')
        parent_program = (f'import subprocess,sys,time; subprocess.Popen([sys.executable,"-c",{child_program!r}]); '
                          'time.sleep(60)')
        result = self.run_fixture(self.entry(parent_program))
        child = int(pidfile.read_text())
        try:
            self.assertEqual(result['status'], 'FAILED')
            self.assertFalse(running(child), '忽略TERM的孙进程不得残留')
            self.assertEqual(list((self.root/'live').glob('*.json')), [])
        finally:
            if running(child):
                os.kill(child, signal.SIGKILL)
        self.assertFalse(running(child))


if __name__ == '__main__':
    unittest.main()
