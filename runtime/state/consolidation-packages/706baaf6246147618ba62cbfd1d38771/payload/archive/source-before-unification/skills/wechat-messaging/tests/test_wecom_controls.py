import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import wecom_desktop_sender as sender


class ControlTraversalTests(unittest.TestCase):
    def test_file_name_and_size_are_paired_only_inside_same_message_row(self):
        trees={'window':['table'],'table':['row1','row2'],'row1':['row1','clock1','name1','size1'],
               'row2':['row2','name2','size2']}
        values={'clock1':'上午 9:19','name1':'美团外卖日报_2026-10-23.xlsx','size1':'130K',
                'name2':'淘宝闪购日报_2026-10-23.xlsx','size2':'110K'}
        def ax(node,attr):
            if attr=='AXRole':return ('AXTable' if node=='table' else 'AXRow' if node.startswith('row') else 'AXStaticText',0)
            if attr=='AXChildren':return (trees.get(node,[]),0)
            return (values.get(node) if attr=='AXValue' else None,0)
        with patch.object(sender,'main_window',return_value='window'), \
             patch.object(sender,'_win_x',return_value=0), \
             patch.object(sender,'iter_tree',side_effect=lambda node:iter(trees[node])), \
             patch.object(sender,'ax',side_effect=ax), \
             patch.object(sender,'ax_pos',return_value=(400,100)), \
             patch.object(sender,'ax_size',return_value=(800,400)):
            cards=sender.visible_file_cards()
            from datetime import datetime, timezone, timedelta
            stamp=datetime(2026,10,24,9,21,tzinfo=timezone(timedelta(hours=8))).timestamp()
            self.assertEqual(sender.visible_file_cards(stamp),cards)
            self.assertEqual(sender.visible_file_cards(stamp+3600),[])
        self.assertEqual(cards,['美团外卖日报_2026-10-23.xlsx 130K',
                                '淘宝闪购日报_2026-10-23.xlsx 110K'])

    def test_file_card_needs_full_name_and_matching_size(self):
        item={'name':'淘宝闪购日报_2026-10-23.xlsx','size':113110}
        self.assertTrue(sender.file_card_matches(item,item['name']+' 110K'))
        self.assertFalse(sender.file_card_matches(item,'淘宝闪购日报_2026-10-22.xlsx 110K'))
        self.assertFalse(sender.file_card_matches(item,item['name']+' 212K'))
        self.assertFalse(sender.file_card_matches(item,item['name'][:20]+'… 110K'))

    def test_closed_file_sheet_focus_is_reacquired_once_before_send(self):
        box={'el':'fresh-editor','pos':(400,600),'size':(800,100)}
        with patch.object(sender,'wecom_is_frontmost',return_value=True), \
             patch.object(sender,'current_conversation_title',return_value='业务群'), \
             patch.object(sender,'locate_input_box',return_value=box), \
             patch.object(sender,'assert_focus_on',side_effect=[False,True]), \
             patch.object(sender,'click_checked') as click, \
             patch.object(sender.time,'sleep'),patch.object(sender,'press_enter') as send:
            self.assertEqual(sender.restore_media_input_focus('业务群'),box)
            click.assert_called_once_with(960.0,670.0,'input_box',(400,600))
            send.assert_not_called()
        with patch.object(sender,'wecom_is_frontmost',return_value=True), \
             patch.object(sender,'current_conversation_title',return_value='其他群'), \
             patch.object(sender,'click_checked') as click:
            self.assertIsNone(sender.restore_media_input_focus('业务群'))
            click.assert_not_called()

    def test_office_original_button_center_and_actual_sheet_disappearance(self):
        def ax(node,attr):
            return ('AXButton',0) if attr=='AXRole' else ('使用原文件',0)
        with patch.object(sender,'_find_ax_sheet',side_effect=['sheet',None]), \
             patch.object(sender,'iter_tree',return_value=iter(['button'])), \
             patch.object(sender,'ax',side_effect=ax), \
             patch.object(sender,'ax_pos',return_value=(500,600)), \
             patch.object(sender,'ax_size',return_value=(120,30)), \
             patch.object(sender,'click_checked') as click:
            self.assertEqual(sender._resolve_file_sheet(),'use-original-file-clicked')
            click.assert_called_once_with(560.0,615.0,'file_sheet',(500,600))
        with patch.object(sender,'_find_ax_sheet',return_value='sheet'), \
             patch.object(sender,'iter_tree',return_value=iter(['button'])), \
             patch.object(sender,'ax',side_effect=ax), \
             patch.object(sender,'ax_pos',return_value=(500,600)), \
             patch.object(sender,'ax_size',return_value=(120,30)), \
             patch.object(sender,'click_checked') as click,patch.object(sender.time,'sleep'):
            self.assertEqual(sender._resolve_file_sheet(),'sheet-still-open')
            click.assert_called_once()

    def test_return_is_once_and_requires_real_foreground(self):
        with patch.object(sender, 'wecom_is_frontmost', return_value=False), \
                patch.object(sender, 'press_key') as press:
            with self.assertRaisesRegex(RuntimeError, 'not-frontmost'):
                sender.press_enter()
            press.assert_not_called()
        with patch.object(sender, 'wecom_is_frontmost', return_value=True), \
                patch.object(sender, 'ensure_clean_modifiers') as clear, \
                patch.object(sender, 'press_key') as press:
            sender.press_enter()
            clear.assert_called_once()
            press.assert_called_once_with(36, 0)

    def test_zero_key_flags_are_explicit(self):
        with patch.object(sender.Quartz, 'CGEventCreateKeyboardEvent', side_effect=['down', 'up']), \
                patch.object(sender.Quartz, 'CGEventSetFlags') as flags, \
                patch.object(sender.Quartz, 'CGEventPost'), \
                patch.object(sender.time, 'sleep'):
            sender.press_key(36, 0)
            self.assertEqual([c.args for c in flags.call_args_list], [('down', 0), ('up', 0)])
    def test_similar_group_prefix_is_not_identity(self):
        self.assertTrue(sender._title_matches_group('电销+直播攻坚组', '电销+直播攻坚组'))
        self.assertFalse(sender._title_matches_group('电销+直播攻坚组二群', '电销+直播攻坚组'))
        self.assertFalse(sender._title_matches_group('电销+直播', '电销+直播攻坚组'))
    def test_virtual_tables_are_pruned_but_real_controls_remain(self):
        roles = {'root': 'AXWindow', 'group': 'AXGroup', 'messages': 'AXTable',
                 'fake-editor': 'AXTextArea', 'editor': 'AXTextArea', 'search': 'AXTextField'}
        children = {'root': ['group'], 'group': ['search', 'messages', 'editor'],
                    'messages': ['fake-editor']}
        visited = []

        def ax(node, attr):
            visited.append((node, attr))
            return (roles.get(node), 0) if attr == 'AXRole' else (children.get(node, []), 0)

        with patch.object(sender, 'ax', side_effect=ax):
            controls = list(sender.iter_controls('root'))
        self.assertEqual(controls, ['root', 'group', 'search', 'editor'])
        self.assertNotIn(('messages', 'AXChildren'), visited)
        self.assertFalse(any(n == 'fake-editor' for n, _ in visited))

    def test_unknown_role_does_not_hide_children(self):
        def ax(node, attr):
            if attr == 'AXRole':
                return (None, -1) if node == 'root' else ('AXTextField', 0)
            return (['search'] if node == 'root' else [], 0)
        with patch.object(sender, 'ax', side_effect=ax):
            self.assertEqual(list(sender.iter_controls('root')), ['root', 'search'])

    def test_readiness_stops_after_one_hundred_nodes(self):
        seen = []
        def nodes(_):
            for i in range(20000):
                seen.append(i)
                yield i
        with patch.object(sender, 'iter_tree', side_effect=nodes):
            self.assertEqual(sender._tree_nodes('root'), 100)
        self.assertEqual(len(seen), 100)

    def test_paste_preview_must_be_new_relative_to_before(self):
        before = {('BOX', (300, 600), (800, 80))}
        after = before | {('AXUnknown', (300, 600), (136, 69))}
        with patch.object(sender, 'locate_input_box', return_value={}), \
                patch.object(sender, 'input_subtree_sig', return_value=after):
            self.assertTrue(sender.paste_verify(before, 'image', (136, 69))[0])
            self.assertFalse(sender.paste_verify(after, 'image', (136, 69))[0])

    def test_small_preview_requires_source_aspect_and_uniqueness(self):
        before = {('BOX', (300, 600), (800, 80))}
        after = before | {('AXUnknown', (569, 599), (56, 45))}
        with patch.object(sender, 'locate_input_box', return_value={}), \
                patch.object(sender, 'input_subtree_sig', return_value=after):
            self.assertTrue(sender.paste_verify(before, 'image', (2240, 1760))[0])
            self.assertFalse(sender.paste_verify(before, 'image', (300, 30))[0])

    def test_media_caller_uses_saved_before_paste_signature(self):
        # Regression at the actual call site: computing a fresh after-signature
        # as the baseline erases every pasted preview before validation.
        import inspect
        source = inspect.getsource(sender.cmd_send_media)
        self.assertIn('paste_verify(sig_before, kind, source_size)', source)
        self.assertNotIn('paste_verify(input_subtree_sig(', source)


if __name__ == '__main__':
    unittest.main()
