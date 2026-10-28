import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'skills/wechat-messaging/scripts'))
import native_ui_post as original
import native_image_copy_candidate as C
from native_image_copy_hook import submitted_image_observations
from test_native_image_copy_candidate import Driver, picture


class HookTests(unittest.TestCase):
    def setUp(self):
        self.source = picture('red')
        self.driver = Driver(self.source)
        self.row = list(self.driver.state['rowPath'])
        self.task = {'taskId': 'original-task', 'stage': 'send', 'owner': {'pid': 1},
                     'expectedPresentation': 'inline-image', 'request': {'groupName': '精确群'},
                     'item': {'type': 'image', 'sha256': C.sha(self.source), 'size': len(self.source)}}
        self.task['binding'] = C.sha(json.dumps(self.task, sort_keys=True, ensure_ascii=False).encode())
        self.live = Mock()
        self.factory = Mock(return_value=self.driver)
        self.wait = Mock(side_effect=original.NativeImageObservationPending(
            'native-ui-inline-image-not-exposed', self.row))
    def invoke(self):
        return submitted_image_observations(self.task, 'original-folder', 20, self.live,
            original_wait=self.wait, pending_type=original.NativeImageObservationPending,
            native=None, queue='original-queue', owner_check=lambda _: True,
            driver_factory=self.factory)
    def test_existing_structure_success_does_not_copy(self):
        self.wait = Mock(return_value=[{'original': True}, {'original': True}])
        self.assertEqual(self.invoke(), [{'original': True}, {'original': True}])
        self.factory.assert_not_called()
    def test_pending_original_row_can_produce_two_exact_pixel_frames(self):
        frames = self.invoke()
        self.assertEqual(len(frames), 2)
        self.assertEqual(self.driver.calls, 2)
        self.assertTrue(all(f['messagePath'] == self.row for f in frames))
    def test_new_tail_row_after_original_wait_cannot_be_rebound(self):
        self.driver.state['rowPath'][-1] += 1
        with self.assertRaisesRegex(RuntimeError, 'row-changed'):
            self.invoke()
        self.assertEqual(self.driver.calls, 0)
    def test_other_observation_failures_never_copy(self):
        for reason in ('native-ui-no-new-message-row', 'native-ui-target-or-draft-mismatch',
                       'native-ui-image-row-changed-during-readback', 'owner-gone'):
            self.wait = Mock(side_effect=RuntimeError(reason))
            with self.assertRaisesRegex(RuntimeError, reason):
                self.invoke()
        self.factory.assert_not_called()
    def test_unrecognized_pending_reason_does_not_copy(self):
        self.wait = Mock(side_effect=original.NativeImageObservationPending('different-pending', self.row))
        with self.assertRaisesRegex(RuntimeError, 'different-pending'):
            self.invoke()
        self.factory.assert_not_called()
    def test_owner_loss_after_observation_stops_before_driver(self):
        self.live.side_effect = RuntimeError('owner-ended')
        with self.assertRaisesRegex(RuntimeError, 'owner-ended'):
            self.invoke()
        self.factory.assert_not_called()
    def test_real_original_wait_pending_enters_same_row_hook(self):
        clock = [0.0]
        def pause(seconds):
            clock[0] += seconds
        pending = original.NativeImageObservationPending('native-ui-inline-image-not-exposed', self.row)
        self.wait = lambda task, count, live: original.wait_image_observations(
            task, count, live, wait_seconds=1)
        with patch.object(original, 'media_observation', side_effect=pending), \
             patch.object(original.time, 'monotonic', side_effect=lambda: clock[0]), \
             patch.object(original.time, 'sleep', side_effect=pause), \
             patch.object(original, 'execute') as ui:
            frames = self.invoke()
        self.assertEqual(len(frames), 2)
        self.assertEqual(clock[0], 1)
        ui.assert_not_called()
    def test_original_send_media_single_submit_and_original_response_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / self.task['taskId']
            folder.mkdir()
            image = root / 'original.png'
            image.write_bytes(self.source)
            task = dict(self.task, lifetime='owner-process')
            task['item'] = dict(task['item'], path=str(image), name=image.name)
            task.pop('binding')
            task['binding'] = C.sha(json.dumps(task, sort_keys=True, ensure_ascii=False).encode())
            (folder / 'task.json').write_text(json.dumps(task))
            selectors = root / 'selectors.json'
            selectors.write_text(json.dumps({'anchors': {
                'conversationTitle': {'path': [0, 27, 5], 'expected': {'role': 'AXTextField'}},
                'composer': {'path': [0, 27, 9, 0, 5, 0],
                             'expected': {'role': 'AXTextArea', 'description': '文本输入区'}}}}))
            def ui(actions=(), **kwargs):
                if kwargs.get('root_path') == [6, 1, 2]:
                    return {'nodes': [{'value': str(image)}]}
                if kwargs.get('root_path') == [6, 0, 2, 0]:
                    return {'nodes': [{'role': 'AXTextField', 'value': image.name}]}
                return {'nodes': []}
            anchors = [('conversationTitle', '精确群'), ('composer', ''),
                       ('conversationTitle', '精确群'), ('composer', '\ufffc')]
            def anchor(name):
                expected, value = anchors.pop(0)
                self.assertEqual(name, expected)
                return {}, {'value': value}
            def hook(t, baseline, live):
                self.assertEqual(t, task)
                self.assertTrue((folder / 'send-intent.json').is_file())
                return submitted_image_observations(t, folder, baseline, live,
                    original_wait=self.wait, pending_type=original.NativeImageObservationPending,
                    native=None, queue=root, owner_check=lambda _: True,
                    driver_factory=self.factory)
            with patch.object(original, 'QUEUE', root), \
                 patch.object(original, 'SELECTORS', selectors), \
                 patch.object(original, 'owner_active', return_value=True), \
                 patch.object(original, 'read_anchor', side_effect=anchor), \
                 patch.object(original, 'read_anchors', return_value=({}, {
                     'conversationTitle': {'value': '精确群'}, 'composer': {'value': ''}})), \
                 patch.object(original, 'message_rows', return_value=[None] * 20), \
                 patch.object(original, 'wait_media_selector', return_value=([6], [6, 0, 11])), \
                 patch.object(original, 'execute', side_effect=ui) as actions, \
                 patch.object(original, 'wait_image_observations', side_effect=hook), \
                 patch.object(original.subprocess, 'run'):
                reply = original.send_media(folder)
            self.assertEqual(reply['result']['status'], 'verified')
            self.assertEqual(reply['result']['sendAttempts'], 1)
            self.assertEqual(self.driver.calls, 2)
            submits = [a for call in actions.call_args_list for a in
                       (call.args[0] if call.args else [])
                       if a.get('key') == 'return' and a.get('expected', {}).get('role') == 'AXTextArea']
            self.assertEqual(len(submits), 1)
            self.assertEqual(json.loads((folder / 'response.json').read_text()), reply)
            checked = original.validate_response(task, reply)
            self.assertEqual(checked['verificationLevel'], 'wecom-ui-tree-image')


if __name__ == '__main__':
    unittest.main()
