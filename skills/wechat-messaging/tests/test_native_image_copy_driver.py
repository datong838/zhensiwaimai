import json
import subprocess
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import native_image_content as C
from native_image_content_driver import CopyDriver


class Pasteboard:
    def __init__(self):
        self.count = 0
        self.reads = []
        self.images = {}
        self.race = False
    def clearContents(self):
        self.count += 1
        self.images.clear()
    def setString_forType_(self, value, kind):
        self.count += 1
        return True
    def changeCount(self):
        return self.count
    def dataForType_(self, kind):
        self.reads.append(kind)
        if self.race:
            self.count += 1
        return self.images.get(kind)


class DriverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.queue = Path(self.temp.name)
        self.folder = self.queue / 'original-task'
        self.folder.mkdir()
        self.task = {'taskId': 'original-task', 'stage': 'send', 'lifetime': 'owner-process',
                     'owner': {'pid': 1}, 'expectedPresentation': 'inline-image',
                     'item': {'type': 'image', 'sha256': 'a' * 64},
                     'request': {'groupName': '精确群'}}
        self.task['binding'] = C.sha(json.dumps(self.task, sort_keys=True, ensure_ascii=False).encode())
        self.write('task.json', self.task)
        self.write('claim.json', {'worker': 'native-system-ui-post'})
        self.intent = {'taskId': 'original-task', 'binding': self.task['binding'],
                       'sha256': 'a' * 64, 'backend': 'system-events-ui-tree'}
        self.write('send-intent.json', self.intent)
        self.pb = Pasteboard()
        self.active = True
        self.calls = 0
        def runner(args, **kwargs):
            self.calls += 1
            payload = json.loads(args[-1])
            self.pb.images['public.tiff'] = b'copied-image'
            self.pb.count += 1
            return SimpleNamespace(stdout=json.dumps({'backend': 'system-events-ui-tree',
                'copied': True, 'rowPath': payload['rowPath'], 'menuShortcut': 'C', 'menuModifiers': 0}))
        self.driver = CopyDriver(self.folder, self.task, queue=self.queue, native=None,
            owner_check=lambda _: self.active, pasteboard=self.pb, runner=runner, worker_pid=1)
        self.driver.paths = {'messagesPath': [0], 'titlePath': [1], 'composerPath': [2]}
    def write(self, name, value):
        (self.folder / name).write_text(json.dumps(value))
    def matches(self):
        return self.driver.intent_matches('original-task', self.task['binding'], 'a' * 64)
    def test_constructor_does_not_read_clipboard_or_ui(self):
        self.assertTrue(self.matches())
        self.assertEqual(self.pb.reads, [])
        self.assertEqual(self.calls, 0)
        self.assertEqual(self.pb.count, 0)
    def test_copy_error_retains_bounded_detail_without_retry_or_clipboard_read(self):
        for stderr in ('execution error: candidate-visible-copy-unavailable (-2700)',
                       b'bad-ui-path', '', 'x' * 3000):
            with self.subTest(stderr=str(stderr)[:40]):
                calls = []
                def fail(*args, **kwargs):
                    calls.append((args, kwargs))
                    raise subprocess.CalledProcessError(1, ['osascript'], stderr=stderr)
                self.driver.runner = fail
                self.driver.seed_count = 5
                with self.assertRaisesRegex(RuntimeError, 'candidate-copy-ui-failed:exit=1:stderr=') as caught:
                    self.driver.copy_image([0, 1], '精确群')
                self.assertLessEqual(len(str(caught.exception)), 1050)
                self.assertFalse(self.driver.copy_confirmed)
                self.assertEqual(len(calls), 1)
                self.assertTrue(calls[0][1]['check'])
                self.assertEqual(self.pb.reads, [])
                self.assertEqual(self.pb.count, 0)
    def test_original_intent_claim_task_and_owner_must_all_match(self):
        for field in ('taskId', 'binding', 'sha256', 'backend'):
            bad = dict(self.intent, **{field: 'wrong'})
            self.write('send-intent.json', bad)
            self.assertFalse(self.matches())
        self.write('send-intent.json', self.intent)
        self.active = False
        self.assertFalse(self.matches())
        self.active = True
        self.write('claim.json', {'worker': 'different-worker'})
        self.assertFalse(self.matches())
    def test_terminal_response_and_symlink_cannot_be_reused(self):
        self.write('response.json', {})
        self.assertFalse(self.matches())
        (self.folder / 'response.json').unlink()
        source = self.folder / 'send-intent.json'
        source.rename(self.folder / 'elsewhere.json')
        source.symlink_to(self.folder / 'elsewhere.json')
        self.assertFalse(self.matches())
    def test_no_clipboard_read_without_nonce_and_confirmed_copy(self):
        with self.assertRaisesRegex(RuntimeError, 'not-fresh'):
            self.driver.clipboard_image()
        self.driver.seed_nonce('zhensi-image-readback-test')
        with self.assertRaisesRegex(RuntimeError, 'not-fresh'):
            self.driver.clipboard_image()
        self.assertEqual(self.pb.reads, [])
    def test_only_fresh_allowlisted_image_read_once(self):
        before = self.driver.seed_nonce('zhensi-image-readback-test')
        self.assertEqual(self.pb.reads, [])
        self.driver.copy_image([0, 1], '精确群')
        result = self.driver.clipboard_image()
        self.assertEqual(result['data'], b'copied-image')
        self.assertGreater(result['changeCount'], before)
        self.assertEqual(self.pb.reads, ['public.png', 'public.tiff'])
        with self.assertRaisesRegex(RuntimeError, 'not-fresh'):
            self.driver.clipboard_image()
    def test_clipboard_race_during_read_is_rejected(self):
        self.driver.seed_nonce('zhensi-image-readback-test')
        self.driver.copy_image([0, 1], '精确群')
        self.pb.race = True
        with self.assertRaisesRegex(RuntimeError, 'changed-during-read'):
            self.driver.clipboard_image()
    def test_dead_owner_or_terminal_task_prevents_copy(self):
        self.driver.seed_nonce('zhensi-image-readback-test')
        self.write('response.json', {})
        with self.assertRaisesRegex(RuntimeError, 'intent-mismatch'):
            self.driver.copy_image([0, 1], '精确群')
        self.assertEqual(self.calls, 0)
    def test_snapshot_uses_shallow_original_anchors_and_rejectable_file_shape(self):
        selectors = self.queue / 'selectors.json'
        selectors.write_text(json.dumps({'anchors': {k: {'path': path} for k, path in
            [('conversationTitle', [1]), ('composer', [2]), ('messages', [0])]}}))
        calls = []
        def execute(**kwargs):
            calls.append(kwargs)
            if kwargs['root_path'] == [0]:
                return {'nodes': [{'path': [0, 1], 'role': 'AXRow'}]}
            return {'frontmost': True, 'nodes': [
                {'path': [0, 1, 0], 'role': 'AXCell'},
                {'path': [0, 1, 0, 0], 'role': 'AXTextField', 'value': '文件.xlsx'}]}
        self.driver.native = SimpleNamespace(SELECTORS=selectors, execute=execute,
            read_anchors=lambda *names: ({'frontmost': True}, {
                'conversationTitle': {'value': '精确群'}, 'composer': {'value': ''}}))
        state = self.driver.snapshot()
        self.assertTrue(state['fileCard'])
        self.assertEqual(state['rowPath'], [0, 1])
        self.assertEqual(state['cellRole'], 'AXCell')
        self.assertEqual(calls, [{'root_path': [0], 'max_depth': 1},
                                 {'root_path': [0, 1], 'max_depth': 3}])
    def test_original_task_changed_on_disk_rejects_without_ui(self):
        self.write('task.json', dict(self.task, stage='preflight'))
        with self.assertRaisesRegex(RuntimeError, 'intent-mismatch'):
            self.driver.snapshot()
        self.assertEqual(self.calls, 0)
    def test_other_process_cannot_borrow_even_live_original_owner(self):
        self.driver.worker_pid = 2
        self.assertFalse(self.matches())
        with self.assertRaisesRegex(RuntimeError, 'intent-mismatch'):
            self.driver.seed_nonce('zhensi-image-readback-test')
        self.assertEqual(self.pb.count, 0)


if __name__ == '__main__':
    unittest.main()
