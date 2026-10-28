import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from native_image_content_driver import CopyDriver


class CopyErrorDetail(unittest.TestCase):
    def test_ui_error_retains_bounded_detail_without_retry_or_clipboard_read(self):
        for stderr in ('execution error: candidate-visible-copy-unavailable (-2700)',
                       b'bad-ui-path', '', 'x' * 3000):
            with self.subTest(stderr=str(stderr)[:40]), tempfile.TemporaryDirectory() as folder:
                queue = Path(folder)
                target = queue / 'original'
                target.mkdir()
                task = {'taskId': 'original', 'stage': 'send', 'lifetime': 'owner-process',
                        'owner': {'pid': 77}, 'request': {'groupName': 'exact-group'},
                        'item': {'type': 'image', 'sha256': 'a' * 64}}
                task['binding'] = hashlib.sha256(json.dumps(task, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                for name, value in [('task.json', task), ('claim.json', {'worker': 'native-system-ui-post'}),
                                    ('send-intent.json', {'taskId': 'original', 'binding': task['binding'],
                                      'sha256': 'a' * 64, 'backend': 'system-events-ui-tree'})]:
                    (target / name).write_text(json.dumps(value))
                calls = []
                def runner(*args, **kwargs):
                    calls.append((args, kwargs))
                    raise subprocess.CalledProcessError(1, ['osascript'], stderr=stderr)
                driver = CopyDriver(target, task, queue=queue, native=None,
                                    owner_check=lambda _: True, worker_pid=77, runner=runner)
                driver.paths = {'messagesPath': [0], 'titlePath': [1], 'composerPath': [2]}
                driver.seed_count = 5
                with self.assertRaisesRegex(RuntimeError, 'candidate-copy-ui-failed:exit=1:stderr=') as caught:
                    driver.copy_image([0, 1], 'exact-group')
                self.assertLessEqual(len(str(caught.exception)), 1050)
                self.assertFalse(driver.copy_confirmed)
                self.assertEqual(len(calls), 1)
                self.assertIsNone(driver._pasteboard)
                self.assertTrue(calls[0][1]['check'])


if __name__ == '__main__':
    unittest.main()
