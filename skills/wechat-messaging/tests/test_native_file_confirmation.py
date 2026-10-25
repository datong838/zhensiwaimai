import unittest
from unittest.mock import patch, Mock
from test_native_ui_post import post


class NativeFileConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.task = {'request': {'groupName':'test'}, 'item':{'name':'test.xlsx','type':'file'}}

    def test_selected_attachment_submits_once(self):
        with patch.object(post,'read_anchor',side_effect=[({},{'value':'test'}),({},{'value':'\ufffc'})]), \
             patch.object(post,'execute') as ui:
            post.confirm_selected_file(self.task,5,Mock())
        ui.assert_called_once()
        self.assertEqual(ui.call_args.args[0][0]['key'],'return')

    def test_already_sent_file_card_never_submits_again(self):
        with patch.object(post,'read_anchor',side_effect=[({},{'value':'test'}),({},{'value':''})]), \
             patch.object(post,'media_observation',return_value={}),patch.object(post,'execute') as ui:
            post.confirm_selected_file(self.task,5,Mock())
        ui.assert_not_called()

    def test_wrong_group_does_not_submit(self):
        with patch.object(post,'read_anchor',side_effect=[({},{'value':'wrong'}),({},{'value':'\ufffc'})]), \
             patch.object(post,'execute') as ui:
            with self.assertRaisesRegex(RuntimeError,'target-changed'):
                post.confirm_selected_file(self.task,5,Mock())
        ui.assert_not_called()

    def test_other_draft_does_not_submit(self):
        with patch.object(post,'read_anchor',side_effect=[({},{'value':'test'}),({},{'value':'other draft'})]), \
             patch.object(post,'execute') as ui:
            with self.assertRaisesRegex(RuntimeError,'file-draft-mismatch'):
                post.confirm_selected_file(self.task,5,Mock())
        ui.assert_not_called()


if __name__ == '__main__':unittest.main()
