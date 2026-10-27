import sys, unittest
from tempfile import TemporaryDirectory
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from desktop_headers import DesktopHeaders
from desktop_adapter import DesktopAdapter

class HeaderTests(unittest.TestCase):
    def setUp(self):
        self.base=Mock()
        self.base.find_exact_headers.return_value=[]
        self.base.find_exact_group_rows.return_value=[]
        self.base.ax_confirms_raw_group_header.return_value=True
        self.proxy=DesktopHeaders(self.base)
    def hit(self,text):return NS(text=text,cx=757,cy=55,w=231,h=33)
    def test_icon_requires_exact_ax(self):
        hit=self.hit('臻肆测试群（3）C')
        self.assertEqual(self.proxy.find_exact_headers([hit],'臻肆测试群'),[hit])
        self.base.ax_confirms_raw_group_header.return_value=False
        self.assertEqual(self.proxy.find_exact_headers([hit],'臻肆测试群'),[])
    def test_no_loose_suffix_or_group_match(self):
        for s in ['臻肆测试群〇','臻肆测试群（3）其他','臻肆测试群2（3）〇','臻肆测试群（3）〇〇']:
            self.assertEqual(self.proxy.find_exact_headers([self.hit(s)],'臻肆测试群'),[])
    def test_ambiguity_rejected(self):
        self.assertEqual(self.proxy.find_exact_headers([self.hit('臻肆测试群（3）〇')]*2,'臻肆测试群'),[])
    def test_original_match_preserved(self):
        original=[self.hit('臻肆测试群（3）')]
        self.base.find_exact_headers.return_value=original
        self.assertEqual(self.proxy.find_exact_headers(original,'臻肆测试群'),original)
        self.base.ax_confirms_raw_group_header.assert_not_called()
    def test_native_search_fallback_only_after_exact_ocr_miss(self):
        from unittest.mock import patch
        receipt=NS(ok=False,note='exact-group-result-count:0',artifacts=['search.png'])
        verified=NS(ok=True,note='ax-current-header',artifacts=[])
        self.base.open_group.return_value=receipt
        self.base.open_group_exact_ax_visible.return_value=verified
        with patch('desktop_input.open_exact_search_result',return_value=True) as native:
            result=self.proxy.open_group('电销+直播攻坚组','out',exact=True)
        self.assertIs(result,verified)
        self.assertEqual(result.note,'ax-native-search-result')
        self.assertEqual(result.artifacts,['search.png'])
        native.assert_called_once()

    def test_visible_exact_local_result_preempts_legacy_ax_poll(self):
        verified=NS(ok=True,note='ocr-exact-local-result-raw-ax-header',artifacts=[])
        self.proxy._open_unique_exact_local_result=Mock(return_value=verified)
        result=self.proxy.open_group('电销+直播攻坚组','out',exact=True)
        self.assertIs(result,verified)
        self.base.open_group.assert_not_called()

    def test_unique_exact_local_result_requires_raw_ax_header(self):
        adapter=DesktopHeaders(Mock())
        adapter.base.ocr.return_value=[
            NS(text='最常使用',cx=100,cy=80,h=20),
            NS(text='电销＋直播攻坚组Q',cx=200,cy=140,h=24),
            NS(text='六 搜索网络结果',cx=100,cy=210,h=20),
        ]
        adapter.base.screen_scale.return_value=1
        verified=NS(ok=True,note='ax-current-header',header='电销+直播攻坚组',artifacts=[])
        adapter.base.open_group_exact_ax_visible.return_value=verified
        with TemporaryDirectory() as directory:
            result=adapter._open_unique_exact_local_result('电销+直播攻坚组',Path(directory))
        self.assertIs(result,verified)
        self.assertEqual(result.note,'ocr-exact-local-result-raw-ax-header')
        adapter.base.click_local.assert_called_once()

    def test_unique_exact_local_result_rejects_unverified_header(self):
        adapter=DesktopHeaders(Mock())
        adapter.base.ocr.return_value=[
            NS(text='最常使用',cx=100,cy=80,h=20),
            NS(text='电销＋直播攻坚组Q',cx=200,cy=140,h=24),
            NS(text='六 搜索网络结果',cx=100,cy=210,h=20),
        ]
        adapter.base.screen_scale.return_value=1
        adapter.base.open_group_exact_ax_visible.return_value=NS(ok=False,note='ax-mismatch',artifacts=[])
        with TemporaryDirectory() as directory:
            result=adapter._open_unique_exact_local_result('电销+直播攻坚组',Path(directory))
        self.assertIsNone(result)

    def test_unique_search_result_clicks_without_display_text_or_ax_title_gate(self):
        from tempfile import TemporaryDirectory
        adapter=DesktopHeaders(Mock())
        core='上海臻肆外卖运营-盯个盯'
        group=core+' 💰发财精英荟💰'
        heading=NS(text='最常使用',cx=100,cy=100,h=20)
        target=NS(text='任何显示文字',cx=200,cy=180,h=20)
        history=NS(text='聊天记录',cx=100,cy=260,h=20)
        network=NS(text=core,cx=200,cy=340,h=20)
        adapter.base.ocr.return_value=[heading,target,history,network]
        adapter.base.screen_scale.return_value=1
        with TemporaryDirectory() as directory:
            result=adapter._open_unique_search_result(group,core,Path(directory))
        self.assertTrue(result.ok)
        self.assertEqual(result.note,'unique-search-result-clicked')
        self.assertEqual(adapter.base.click_local.call_args.args[:2],(200,180))

    def test_unique_search_rejects_multiple_local_candidates(self):
        from tempfile import TemporaryDirectory
        adapter=DesktopHeaders(Mock())
        core='上海臻肆外卖运营-盯个盯'
        adapter.base.ocr.return_value=[NS(text='最常使用',cx=100,cy=100,h=20),
            NS(text=core,cx=200,cy=160,h=20),NS(text=core+'-副本',cx=200,cy=200,h=20),
            NS(text='聊天记录',cx=100,cy=260,h=20)]
        with TemporaryDirectory() as directory:
            self.assertIsNone(adapter._open_unique_search_result(core+' 💰发财精英荟💰',core,Path(directory)))
        adapter.base.click_local.assert_not_called()

    def test_plus_variant_click_requires_raw_ax_header(self):
        from tempfile import TemporaryDirectory
        adapter=DesktopHeaders(Mock())
        hit=NS(text='电销＋直播攻坚组',cx=200,cy=180)
        adapter.base.ocr.return_value=[hit]
        adapter.base.screen_scale.return_value=1
        verified=NS(ok=True,artifacts=[])
        adapter._ax_visible_after_click=Mock(return_value=verified)
        with TemporaryDirectory() as directory:
            result=adapter._open_ocr_plus_variant('电销+直播攻坚组',Path(directory))
        self.assertIs(result,verified)
        adapter.base.click_local.assert_called_once()

    def test_ascii_ocr_plus_variant_uses_same_raw_ax_gate(self):
        from tempfile import TemporaryDirectory
        adapter=DesktopHeaders(Mock())
        hit=NS(text='电销+直播攻坚组',cx=200,cy=180)
        adapter.base.ocr.return_value=[hit]
        adapter.base.screen_scale.return_value=1
        verified=NS(ok=True,artifacts=[])
        adapter._ax_visible_after_click=Mock(return_value=verified)
        with TemporaryDirectory() as directory:
            result=adapter._open_ocr_plus_variant('电销+直播攻坚组',Path(directory))
        self.assertIs(result,verified)
        adapter.base.click_local.assert_called_once()

    def test_decorated_top_result_wins_over_lower_network_row(self):
        from tempfile import TemporaryDirectory
        adapter=DesktopHeaders(Mock())
        top=NS(text='电销＋直播攻坚组？',cx=200,cy=180,h=20)
        lower=NS(text='电销＋直播攻坚组',cx=200,cy=320,h=20)
        adapter.base.ocr.return_value=[top,lower]
        adapter.base.screen_scale.return_value=1
        verified=NS(ok=True,artifacts=[])
        adapter._ax_visible_after_click=Mock(return_value=verified)
        with TemporaryDirectory() as directory:
            result=adapter._open_ocr_plus_variant('电销+直播攻坚组',Path(directory))
        self.assertIs(result,verified)
        self.assertEqual(adapter.base.click_local.call_args.args[:2],(200,180))

    def test_current_exact_header_without_member_count_forces_search(self):
        group='上海臻肆外卖运营-盯个盯-饭敢当'
        receipt=NS(ok=True,note='ax-current-header',header=group,artifacts=[])
        search_receipt=NS(ok=True,note='exact-group-section-text-row',header=group,artifacts=[])
        header=self.hit(group)
        self.base.open_group.return_value=receipt
        self.base.exact_group_text.return_value=True
        self.base.ocr.return_value=[header,self.hit('搜索')]
        self.base.find_exact_headers.return_value=[header]
        self.base.screen_scale.return_value=2
        self.base.open_group_exact.return_value=search_receipt
        result=self.proxy.open_group(group,Path('/tmp/force-search'),exact=True)
        self.assertIs(result,search_receipt)
        self.base.ensure_window_size.assert_called_once()
        self.base.open_group_exact.assert_called_once()

    def test_current_header_with_member_count_keeps_fast_path(self):
        group='目标群'
        receipt=NS(ok=True,note='ax-current-header',header='目标群（8）',artifacts=[])
        self.base.open_group.return_value=receipt
        self.base.exact_group_text.return_value=True
        self.assertIs(self.proxy.open_group(group,Path('/tmp'),exact=True),receipt)
        self.base.open_group_exact.assert_not_called()
    def test_forced_search_uses_native_header_when_ocr_header_misses(self):
        group='目标群'
        current=NS(ok=True,note='ax-current-header',header=group,artifacts=[])
        missed=NS(ok=False,note='exact-group-header-count:0',artifacts=['after.png'])
        verified=NS(ok=True,note='ax-current-header',artifacts=[])
        self.base.open_group.return_value=current
        self.base.exact_group_text.return_value=True
        self.base.ocr.return_value=[]
        self.base.find_exact_headers.return_value=[]
        self.base.open_group_exact.return_value=missed
        self.base.open_group_exact_ax_visible.return_value=verified
        result=self.proxy.open_group(group,Path('/tmp'),exact=True)
        self.assertIs(result,verified)
        self.assertEqual(result.note,'exact-group-section-text-row')
    def test_native_search_does_not_bypass_other_failures(self):
        receipt=NS(ok=False,note='exact-group-result-count:2',artifacts=[])
        self.base.open_group.return_value=receipt
        self.assertIs(self.proxy.open_group('电销+直播攻坚组','out',exact=True),receipt)
        self.base.open_group_exact_ax_visible.assert_not_called()
    def test_native_header_finishes_verified_group_section_click(self):
        from unittest.mock import patch
        receipt=NS(ok=False,note='exact-group-header-count:0',artifacts=['after.png'])
        verified=NS(ok=True,note='ax-current-header',artifacts=[])
        self.base.open_group.return_value=receipt
        self.base.open_group_exact_ax_visible.return_value=verified
        with patch('desktop_input.open_exact_search_result',return_value=False):
            result=self.proxy.open_group('目标群','out',exact=True)
        self.assertIs(result,verified)
        self.assertEqual(result.note,'exact-group-section-text-row')
        self.assertEqual(result.artifacts,['after.png'])
    def test_native_search_geometry_precedes_ocr(self):
        self.base.window_bounds.return_value=(100,50,900,700)
        self.base.screen_scale.return_value=2
        self.base.OcrHit=NS
        row={'x':130,'y':90,'width':180,'height':24,'text':'电销+直播攻坚组'}
        from unittest.mock import patch
        with patch('desktop_input.exact_search_result',return_value=row):
            hits=self.proxy.find_exact_group_rows([],row['text'])
        self.assertEqual((hits[0].cx,hits[0].cy),(240,104))
        self.base.find_exact_group_rows.assert_not_called()
    def test_ocr_is_only_no_dialog_fallback(self):
        expected=[self.hit('电销+直播攻坚组')]
        self.base.find_exact_group_rows.return_value=expected
        from unittest.mock import patch
        with patch('desktop_input.exact_search_result',return_value=None):
            self.assertEqual(self.proxy.find_exact_group_rows([],expected[0].text),expected)

    def test_group_section_text_and_exact_header_proves_group_without_count(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.preflight_module=Mock()
        adapter.preflight_module.run_exact_group_preflight.return_value={
            'ok':True,'group':'上海臻肆外卖运营-盯个盯-饭敢当',
            'header':'上海臻肆外卖运营-盯个盯-饭敢当','note':'exact-group-section-text-row'}
        adapter.wd=Mock()
        adapter.wd.wechat_ax_state.return_value={'window':{'x':0,'y':0},'texts':[]}
        adapter.wd.exact_group_text.return_value=True
        result=adapter.preflight({'groupName':'上海臻肆外卖运营-盯个盯-饭敢当','context':{'deadlineAt':9999999999}},Path('/tmp'))
        self.assertTrue(result['groupTypeVerified'])
        self.assertEqual(result['groupTypeProof'],'unique-group-section-text-and-exact-header')

    def test_plain_same_header_without_group_section_proof_is_rejected(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.preflight_module=Mock()
        adapter.preflight_module.run_exact_group_preflight.return_value={
            'ok':True,'group':'目标群','header':'目标群','note':'ax-current-header'}
        adapter.wd=Mock()
        adapter.wd.wechat_ax_state.return_value={'window':{'x':0,'y':0},'texts':[]}
        adapter.wd.exact_group_text.return_value=True
        result=adapter.preflight({'groupName':'目标群','context':{'deadlineAt':9999999999}},Path('/tmp'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'],'group-type-not-proven')

    def test_current_verified_group_skips_search_and_open(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.wd=Mock();adapter.sender=Mock();adapter.preflight_module=Mock()
        adapter.wd.wechat_ax_state.return_value={
            'window':{'x':0,'y':0},'texts':[{'text':'臻肆测试群(3)','x':500,'y':30}]}
        adapter.sender.focused_text_value.return_value=''
        result=adapter.preflight({'groupName':'臻肆测试群','context':{'deadlineAt':9999999999}},Path('/tmp'))
        self.assertTrue(result['ok'])
        self.assertEqual(result['note'],'ax-current-group-fast-path')
        self.assertEqual(result['candidateStrategy'],'current-group-fast-path')
        self.assertTrue(result['composerVerifiedEmpty'])
        adapter.preflight_module.run_exact_group_preflight.assert_not_called()

    def test_unique_core_prefix_zero_result_does_not_repeat_same_search(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.current_group_preflight=Mock(return_value=None)
        adapter.wd=Mock();adapter.preflight_module=Mock()
        adapter.preflight_module.run_exact_group_preflight.return_value={
            'ok':False,'reason':'exact-group-result-count:0','sendAttempts':0}
        request={'groupName':'目标群','context':{'deadlineAt':9999999999,'searchGroupName':'唯一核心前缀'}}
        result=adapter.preflight(request,Path('/tmp'))
        self.assertEqual(result['candidateStrategy'],'unique-core-prefix-not-found')
        self.assertEqual(len(result['attempts']),1)
        adapter.preflight_module.run_exact_group_preflight.assert_called_once()

    def test_post_locate_header_retry_reuses_current_group_without_second_locate(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.current_group_preflight=Mock(side_effect=[None,{
            'ok':True,'group':'FEIBING NEO AI数字员工','header':'FEIBING NEO AI数字员工(18)',
            'note':'ax-current-group-fast-path','composerVerifiedEmpty':True,'sendAttempts':0}])
        adapter.wd=Mock()
        adapter.preflight_module=Mock()
        adapter.preflight_module.run_exact_group_preflight.return_value={
            'ok':False,'reason':'ax-exact-header-count:0','sendAttempts':0}
        result=adapter.preflight({'groupName':'FEIBING NEO AI数字员工','context':{'deadlineAt':9999999999}},Path('/tmp'))
        self.assertTrue(result['ok'])
        self.assertEqual(result['candidateStrategy'],'current-group-post-locate-fast-path')
        self.assertEqual(len(result['attempts']),1)
        adapter.preflight_module.run_exact_group_preflight.assert_called_once()

    def test_unique_search_result_reuses_clicked_group_without_title_lookup(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter._unique_search_group='目标群'
        adapter.sender=Mock()
        adapter.sender.focused_text_value.return_value=''
        fallback=Mock()
        result=adapter.sender_preflight({'groupName':'目标群'},fallback,'目标群',Path('/tmp'))
        self.assertTrue(result['ok'])
        self.assertEqual(result['groupTypeProof'],'unique-search-result')
        adapter.sender.focus_chat_input.assert_called_once()
        fallback.assert_not_called()

    def test_unique_search_result_keeps_existing_draft_protected(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter._unique_search_group='目标群'
        adapter.sender=Mock()
        adapter.sender.focused_text_value.return_value='已有草稿'
        result=adapter.sender_preflight({'groupName':'目标群'},Mock(),'目标群',Path('/tmp'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'],'current-group-composer-not-empty')
        self.assertEqual(result['sendAttempts'],0)

    def test_current_verified_group_accepts_real_window_title_below_100_pixels(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.wd=Mock();adapter.sender=Mock();adapter.preflight_module=Mock()
        adapter.wd.wechat_ax_state.return_value={'window':{'x':0,'y':0},'texts':[{'text':'电销+直播攻坚组(17)','x':500,'y':150}]}
        adapter.sender.focused_text_value.return_value=''
        result=adapter.preflight({'groupName':'电销+直播攻坚组','context':{'deadlineAt':9999999999}},Path('/tmp'))
        self.assertTrue(result['ok']); adapter.preflight_module.run_exact_group_preflight.assert_not_called()

    def test_current_verified_group_with_draft_fails_closed_without_search(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.wd=Mock();adapter.sender=Mock();adapter.preflight_module=Mock()
        adapter.wd.wechat_ax_state.return_value={
            'window':{'x':0,'y':0},'texts':[{'text':'臻肆测试群(3)','x':500,'y':30}]}
        adapter.sender.focused_text_value.return_value='保留草稿'
        result=adapter.preflight({'groupName':'臻肆测试群','context':{'deadlineAt':9999999999}},Path('/tmp'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['reason'],'current-group-composer-not-empty')
        adapter.preflight_module.run_exact_group_preflight.assert_not_called()

    def test_sender_inner_preflight_reuses_current_verified_group(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.wd=Mock();adapter.sender=Mock()
        adapter.wd.wechat_ax_state.return_value={
            'window':{'x':0,'y':0},'texts':[{'text':'臻肆测试群(3)','x':500,'y':30}]}
        adapter.sender.focused_text_value.return_value=''
        fallback=Mock()
        result=adapter.sender_preflight(
            {'groupName':'臻肆测试群'},fallback,'臻肆测试群',Path('/tmp'),acquire_lock=False)
        self.assertTrue(result['ok'])
        self.assertEqual(result['note'],'ax-current-group-fast-path')
        fallback.assert_not_called()

    def test_ax_current_group_can_cover_only_zero_ocr_title_hits(self):
        adapter=DesktopAdapter.__new__(DesktopAdapter)
        adapter.wd=Mock();adapter.wd.ax_confirms_raw_group_header.return_value=True
        request={'groupName':'李老哈（品牌）💰臻肆外卖运营对接群'}
        preflight={'note':'ax-current-group-fast-path','group':request['groupName'],
                   'groupTypeVerified':True}
        self.assertTrue(adapter.allow_ax_title_fallback(
            request,request['groupName'],preflight,RuntimeError('desktop-group-title-not-unique:0')))
        self.assertFalse(adapter.allow_ax_title_fallback(
            request,request['groupName'],preflight,RuntimeError('desktop-group-title-not-unique:1')))
        self.assertFalse(adapter.allow_ax_title_fallback(
            request,request['groupName'],{'note':'exact-group-section-text-row'},
            RuntimeError('desktop-group-title-not-unique:0')))

if __name__=='__main__':unittest.main()

class TransientTests(unittest.TestCase):
 def test_retry_read_only_then_success(self):
  base=Mock();base.ax_confirms_raw_group_header.side_effect=[RuntimeError('wechat-process-count-not-one'),True]
  self.assertTrue(DesktopHeaders(base).ax_confirms_raw_group_header('测试'))
  self.assertEqual(base.ax_confirms_raw_group_header.call_count,2)
 def test_repeated_or_other_error_not_accepted(self):
  base=Mock();base.ax_confirms_raw_group_header.side_effect=RuntimeError('wechat-process-count-not-one')
  with self.assertRaises(RuntimeError):DesktopHeaders(base).ax_confirms_raw_group_header('测试')
  self.assertEqual(base.ax_confirms_raw_group_header.call_count,3)
