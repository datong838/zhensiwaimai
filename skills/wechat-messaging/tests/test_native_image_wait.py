import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_ui_post as post


class NativeImageWaitTests(unittest.TestCase):
    def setUp(self):
        self.clock = 0.0
        self.task = {'item': {'type': 'image'}, 'request': {'groupName': '完整群'}}
        self.row = [0, 1, 3]
        self.observed = {'messagePath': self.row, 'inputEmpty': True, 'groupName': '完整群'}

    def sleep(self, seconds):
        self.clock += seconds

    def wait(self, observations, live=None):
        with patch.object(post.time, 'monotonic', side_effect=lambda: self.clock), \
             patch.object(post.time, 'sleep', side_effect=self.sleep), \
             patch.object(post, 'media_observation', side_effect=observations) as observe, \
             patch.object(post, 'execute') as actions:
            result = post.wait_image_observations(self.task, 1, live or Mock(), wait_seconds=1)
            actions.assert_not_called()
            return result, observe

    def test_delayed_image_requires_two_observations_without_actions(self):
        pending = post.NativeImageObservationPending('native-ui-inline-image-not-exposed', self.row)
        result, observed = self.wait([pending, self.observed, self.observed])
        self.assertEqual(len(result), 2)
        self.assertEqual(observed.call_count, 3)
        self.assertEqual(observed.call_args.kwargs['expected_path'], self.row)

    def test_no_new_row_can_settle_then_bind_original_candidate(self):
        _, observed = self.wait([RuntimeError('native-ui-no-new-message-row'), self.observed, self.observed])
        self.assertEqual(observed.call_count, 3)

    def test_absent_content_remains_pending_at_bound(self):
        with self.assertRaisesRegex(RuntimeError, 'image-not-exposed'):
            self.wait(lambda *args, **kwargs: (_ for _ in ()).throw(
                post.NativeImageObservationPending('native-ui-inline-image-not-exposed', self.row)))
        self.assertLessEqual(self.clock, 1)

    def test_target_or_draft_drift_never_retries(self):
        for reason in ['native-ui-target-or-draft-mismatch', 'native-ui-image-row-changed-during-readback']:
            with self.assertRaisesRegex(RuntimeError, reason):
                self.wait([RuntimeError(reason)])
            self.assertEqual(self.clock, 0)

    def test_owner_failure_prevents_observation(self):
        live = Mock(side_effect=RuntimeError('owner-gone'))
        with self.assertRaisesRegex(RuntimeError, 'owner-gone'):
            self.wait([], live)

    def test_observations_must_be_consecutive(self):
        pending = post.NativeImageObservationPending('native-ui-inline-image-not-exposed', self.row)
        _, observed = self.wait([self.observed, pending, self.observed, self.observed])
        self.assertEqual(observed.call_count, 4)

    def test_changed_pending_candidate_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'image-row-changed'):
            self.wait([post.NativeImageObservationPending('pending', self.row),
                       post.NativeImageObservationPending('pending', [0, 1, 4])])

    def test_media_observation_rejects_row_drift_before_tree_read(self):
        with patch.object(post, 'message_rows', return_value=[[0], [2]]), patch.object(post, 'execute') as ui:
            with self.assertRaisesRegex(RuntimeError, 'image-row-changed'):
                post.media_observation(self.task, 1, expected_path=[1])
            ui.assert_not_called()
