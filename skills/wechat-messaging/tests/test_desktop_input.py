import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from contract import Rejected
from desktop_input import AX_MESSAGE_TIMEOUT_SECONDS,choose_main_window,is_chat_history_search_window,is_detached_chat_window,is_excel_preview_window,is_search_results_dialog,search_dialog_exact_row,set_ax_messaging_timeout


def node(role=None,title=None,value=None,subrole=None,children=None,position=None,size=None):
    return {'AXRole':role,'AXTitle':title,'AXValue':value,'AXSubrole':subrole,
            'AXChildren':children or [],'AXPosition':position,'AXSize':size}


def attr(element,key):
    return element.get(key)

def pair(element,key,kind):
    return element.get(key)


class SearchResultsDialogTests(unittest.TestCase):
    def test_ax_messaging_timeout_requires_supported_successful_api(self):
        with self.assertRaisesRegex(Rejected,'wechat-ax-timeout-api-unavailable'):
            set_ax_messaging_timeout({},object())
        with self.assertRaisesRegex(Rejected,'wechat-ax-timeout-configuration-failed'):
            set_ax_messaging_timeout(SimpleNamespace(AXUIElementSetMessagingTimeout=lambda *_:1),object())
        calls=[]
        set_ax_messaging_timeout(SimpleNamespace(AXUIElementSetMessagingTimeout=lambda element,seconds:calls.append(seconds) or 0),object())
        self.assertEqual(calls,[AX_MESSAGE_TIMEOUT_SECONDS])

    def test_main_window_selector_preserves_single_candidate_fast_path(self):
        only=node(title='微信')
        self.assertIs(choose_main_window([only],lambda _:None),only)

    def test_main_window_selector_uses_only_unique_ax_main(self):
        front={'AXTitle':'微信','main':True}; inactive={'AXTitle':'微信','main':False}
        self.assertIs(choose_main_window([inactive,front],lambda window:window['main']),front)

    def test_main_window_selector_rejects_missing_or_ambiguous_ax_main(self):
        for values in ((False,False),(True,True),(True,None),(False,None)):
            windows=[{'AXTitle':'微信','main':value} for value in values]
            with self.assertRaisesRegex(Rejected,'wechat-main-window-count-not-one'):
                choose_main_window(windows,lambda window:window['main'])

    def test_native_activation_recovers_one_undersized_named_window(self):
        source=(Path(__file__).resolve().parents[1]/'scripts'/'desktop_input.py').read_text(encoding='utf-8')
        self.assertIn("if not mains:",source)
        self.assertIn("if len(named)==1:",source)
        self.assertIn("from wechat_desktop import ensure_window_size",source)
        self.assertIn("return activate_wechat()",source)

    def dialog(self,texts,children=None,title=''):
        rows=[node(role='AXStaticText',title=text) for text in texts]
        listing=node(role='AXList',children=rows)
        return node(role='AXWindow',title=title,subrole='AXDialog',children=children or [listing])

    def test_accepts_exact_wechat_search_results_structure(self):
        window=self.dialog(['最常使用','电销+直播攻坚组','搜索网络结果'])
        self.assertTrue(is_search_results_dialog(window,SimpleNamespace(width=368,height=500),attr))

    def test_accepts_grouped_search_results_structure(self):
        window=self.dialog(['搜索网络结果','群聊','目标群','聊天记录'])
        self.assertTrue(is_search_results_dialog(window,SimpleNamespace(width=368,height=500),attr))

    def test_rejects_dialog_without_a_result_list(self):
        window=node(role='AXWindow',title='',subrole='AXDialog',children=[])
        self.assertFalse(is_search_results_dialog(window,SimpleNamespace(width=368,height=500),attr))

    def test_rejects_multiple_lists(self):
        one=node(role='AXList',children=[node(role='AXStaticText',title='最常使用')])
        two=node(role='AXList',children=[node(role='AXStaticText',title='搜索网络结果')])
        window=self.dialog([],children=[one,two])
        self.assertFalse(is_search_results_dialog(window,SimpleNamespace(width=368,height=500),attr))

    def test_rejects_oversized_dialog(self):
        window=self.dialog(['最常使用','搜索网络结果'])
        self.assertFalse(is_search_results_dialog(window,SimpleNamespace(width=900,height=700),attr))

    def native_dialog(self,local_rows,network_rows=None):
        rows=[node(role='AXStaticText',title='最常使用',position=(20,20),size=(100,20))]
        rows += [node(role='AXRow',children=[node(role='AXStaticText',title=text,position=(30,60+i*35),size=(180,24))])
                 for i,text in enumerate(local_rows)]
        rows.append(node(role='AXStaticText',title='搜索网络结果',position=(20,180),size=(130,20)))
        rows += [node(role='AXStaticText',title=text,position=(30,220+i*35),size=(180,24))
                 for i,text in enumerate(network_rows or [])]
        return self.dialog([],children=[node(role='AXList',children=rows)])

    def test_selects_unique_exact_local_result(self):
        window=self.native_dialog(['电销+直播攻坚组'],['电销+直播攻坚组'])
        row=search_dialog_exact_row(window,SimpleNamespace(width=368,height=500),attr,pair,'电销+直播攻坚组')
        self.assertEqual((row['x'],row['y']),(30,60))

    def test_selects_unique_exact_group_section_result(self):
        group='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
        rows=[node(role='AXStaticText',title='搜索网络结果',position=(20,10),size=(130,20)),
              node(role='AXStaticText',title='群聊',position=(20,50),size=(100,20)),
              node(role='AXRow',children=[node(role='AXStaticText',title=group,position=(30,90),size=(300,24))]),
              node(role='AXStaticText',title='聊天记录',position=(20,140),size=(100,20))]
        window=self.dialog([],children=[node(role='AXList',children=rows)])
        row=search_dialog_exact_row(window,SimpleNamespace(width=368,height=500),attr,pair,group)
        self.assertEqual((row['x'],row['y']),(30,90))

    def test_ignores_same_name_in_chat_history_when_most_used_is_unique(self):
        group='李老哈（品牌）💰臻肆外卖运营对接群'
        rows=[node(role='AXStaticText',title='最常使用',position=(20,95),size=(100,20)),
              node(role='AXRow',children=[node(role='AXStaticText',title=group,position=(30,127),size=(300,64))]),
              node(role='AXStaticText',title='聊天记录',position=(20,191),size=(100,20)),
              node(role='AXStaticText',title=group,position=(30,223),size=(300,88)),
              node(role='AXStaticText',title='搜索网络结果',position=(20,521),size=(130,20))]
        window=self.dialog([],children=[node(role='AXList',children=rows)])
        row=search_dialog_exact_row(window,SimpleNamespace(width=368,height=610),attr,pair,group)
        self.assertEqual((row['x'],row['y']),(30,127))

    def test_section_labels_are_not_required_for_unique_clickable_group_row(self):
        group='李老哈（品牌）💰臻肆外卖运营对接群'
        rows=[node(role='AXStaticText',title='本地结果',position=(20,20),size=(100,20)),
              node(role='AXRow',children=[node(role='AXStaticText',title=group,position=(30,60),size=(300,48))]),
              node(role='AXStaticText',title='其他结果',position=(20,140),size=(100,20))]
        window=self.dialog([],children=[node(role='AXList',children=rows)])
        row=search_dialog_exact_row(window,SimpleNamespace(width=368,height=500),attr,pair,group)
        self.assertEqual((row['x'],row['y']),(30,60))

    def test_duplicate_non_clickable_names_fail_closed(self):
        group='李老哈（品牌）💰臻肆外卖运营对接群'
        rows=[node(role='AXStaticText',title='展示一',position=(20,20),size=(100,20)),
              node(role='AXStaticText',title=group,position=(30,60),size=(300,48)),
              node(role='AXStaticText',title=group,position=(30,130),size=(300,48))]
        window=self.dialog([],children=[node(role='AXList',children=rows)])
        self.assertIsNone(search_dialog_exact_row(window,SimpleNamespace(width=368,height=500),attr,pair,group))

    def test_rejects_duplicate_or_network_only_result(self):
        size=SimpleNamespace(width=368,height=500)
        duplicate=self.native_dialog(['电销+直播攻坚组','电销+直播攻坚组'])
        network_only=self.native_dialog([],['电销+直播攻坚组'])
        self.assertIsNone(search_dialog_exact_row(duplicate,size,attr,pair,'电销+直播攻坚组'))
        self.assertIsNone(search_dialog_exact_row(network_only,size,attr,pair,'电销+直播攻坚组'))


class ChatHistorySearchWindowTests(unittest.TestCase):
    def window(self, *, title='搜索聊天记录', enter_count=1, list_count=2, input_count=1):
        children=[]
        children += [node(role='AXList') for _ in range(list_count)]
        children += [node(role='AXTextField') for _ in range(input_count)]
        children += [node(role='AXButton',title='进入聊天') for _ in range(enter_count)]
        return node(role='AXWindow',title=title,children=children)

    def test_accepts_exact_bounded_chat_history_search_window(self):
        self.assertTrue(is_chat_history_search_window(
            self.window(),SimpleNamespace(width=720,height=640),attr))

    def test_rejects_missing_required_structure(self):
        self.assertFalse(is_chat_history_search_window(
            self.window(list_count=1),SimpleNamespace(width=720,height=640),attr))

    def test_rejects_other_title_or_size(self):
        self.assertFalse(is_chat_history_search_window(
            self.window(title='聊天记录'),SimpleNamespace(width=720,height=640),attr))
        self.assertFalse(is_chat_history_search_window(
            self.window(),SimpleNamespace(width=900,height=800),attr))

    def test_rejects_ambiguous_enter_chat_buttons(self):
        self.assertFalse(is_chat_history_search_window(
            self.window(enter_count=2),SimpleNamespace(width=720,height=640),attr))


class ExcelPreviewWindowTests(unittest.TestCase):
    def preview(self,**changes):
        children=[node(role='AXButton',subrole=kind) for kind in
                  ('AXCloseButton','AXFullScreenButton','AXMinimizeButton')]
        data=dict(role='AXWindow',subrole='AXStandardWindow',
                  title='淘宝闪购差评申诉汇总-2026-09-22.xlsx',children=children)
        data.update(changes)
        return node(**data)

    def test_accepts_exact_inert_excel_preview(self):
        self.assertTrue(is_excel_preview_window(
            self.preview(),SimpleNamespace(width=1168,height=684),attr))

    def test_rejects_other_window_or_chat_controls(self):
        size=SimpleNamespace(width=1168,height=684)
        self.assertFalse(is_excel_preview_window(self.preview(title='其他.pdf'),size,attr))
        self.assertFalse(is_excel_preview_window(self.preview(subrole='AXDialog'),size,attr))
        self.assertFalse(is_excel_preview_window(self.preview(children=[
            node(role='AXTextArea'),node(role='AXButton',subrole='AXCloseButton'),
            node(role='AXButton',subrole='AXFullScreenButton'),
            node(role='AXButton',subrole='AXMinimizeButton')]),size,attr))
        self.assertFalse(is_excel_preview_window(
            self.preview(),SimpleNamespace(width=1700,height=684),attr))


class DetachedChatWindowTests(unittest.TestCase):
    def detached(self, *, title='电销+直播攻坚组', input_count=1, send_count=1):
        parts=[node(role='AXList',title='消息')]
        parts += [node(role='AXTextArea',title='输入') for _ in range(input_count)]
        parts += [node(role='AXButton',title='发送') for _ in range(send_count)]
        children=[node(role='AXStaticText'),node(role='AXSplitGroup',children=parts)]
        children += [node(role='AXButton',title=name) for name in
                     ('聊天记录','从手机导入聊天记录','语音通话','聊天信息','置顶')]
        children += [node(role='AXButton',subrole=kind) for kind in
                     ('AXCloseButton','AXFullScreenButton','AXMinimizeButton')]
        return node(role='AXWindow',subrole='AXStandardWindow',title=title,children=children)

    def test_accepts_one_structurally_complete_detached_chat(self):
        self.assertTrue(is_detached_chat_window(
            self.detached(),SimpleNamespace(width=598,height=640),attr))

    def test_rejects_main_title_missing_composer_or_oversize(self):
        size=SimpleNamespace(width=598,height=640)
        self.assertFalse(is_detached_chat_window(self.detached(title='微信'),size,attr))
        self.assertFalse(is_detached_chat_window(self.detached(input_count=0),size,attr))
        self.assertFalse(is_detached_chat_window(self.detached(send_count=2),size,attr))
        self.assertFalse(is_detached_chat_window(
            self.detached(),SimpleNamespace(width=1200,height=640),attr))


if __name__=='__main__':unittest.main()
