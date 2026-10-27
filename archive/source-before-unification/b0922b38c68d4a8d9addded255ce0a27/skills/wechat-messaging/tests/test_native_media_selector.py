import unittest
from unittest.mock import Mock, patch
from test_native_ui_post import post


class NativeMediaSelectorTests(unittest.TestCase):
    def test_waits_for_real_sheet_then_returns_semantic_button_path(self):
        states = [ {'nodes':[]},
                   {'nodes':[{'role':'AXSheet','description':'打开','path':[6]}]},
                   {'nodes':[{'role':'AXButton','name':'选取图片','path':[6,0,11]}]} ]
        with patch.object(post,'execute',side_effect=states),patch.object(post.time,'sleep'):
            self.assertEqual(post.wait_media_selector('选取图片',Mock()),([6],[6,0,11]))

    def test_opposite_selector_is_rejected(self):
        states = [{'nodes':[{'role':'AXSheet','description':'打开','path':[4]}]},
                  {'nodes':[{'role':'AXButton','name':'选取文件','path':[4,0,9]}]}]
        with patch.object(post,'execute',side_effect=states):
            with self.assertRaisesRegex(RuntimeError,'semantic-mismatch'):
                post.wait_media_selector('选取图片',Mock())

    def test_owner_exit_does_not_touch_ui(self):
        with patch.object(post,'execute') as ui:
            with self.assertRaisesRegex(RuntimeError,'owner-exited'):
                post.wait_media_selector('选取图片',Mock(side_effect=RuntimeError('owner-exited')))
        ui.assert_not_called()


if __name__=='__main__':unittest.main()
