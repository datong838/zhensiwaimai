import tempfile
import unittest
from argparse import Namespace
from pathlib import Path
from unittest import mock

import desktop_sender as sender


class DesktopSenderTests(unittest.TestCase):
    def test_ocr_plus_variant_requires_raw_ax_identity(self):
        group = "电销+直播攻坚组"
        hit = sender.wd.OcrHit(787, 60, 292, 36, .3, "电销＋直播攻坚组（17）")
        window = {"x": 24, "y": 52, "width": 1120, "height": 636}
        def title(text, y=69):
            return {"text": text, "x": 346, "y": y, "width": 300, "height": 21}
        cases = [
            ([title(group), title(group + "(17)")], True),
            ([title("电销＋直播攻坚组")], False),
            ([title(group + "临时群")], False),
            ([title(group), title(group, 95)], False),
            ([], False),
        ]
        for texts, accepted in cases:
            with self.subTest(texts=texts), \
                 mock.patch.object(sender.wd, "wechat_ax_state", return_value={"window": window, "texts": texts}), \
                 mock.patch.object(sender.wd, "click") as click:
                self.assertEqual(sender.wd.find_exact_headers([hit], group), [hit] if accepted else [])
                click.assert_not_called()

    def test_plus_visual_duplicate_and_wrong_characters_are_rejected(self):
        group = "电销+直播攻坚组"
        exact = sender.wd.OcrHit(787, 60, 292, 36, .9, group)
        variant = sender.wd.OcrHit(787, 90, 292, 36, .9, group.replace("+", "＋"))
        wrong = sender.wd.OcrHit(787, 60, 292, 36, .9, "电销＋直播攻坚组2")
        with mock.patch.object(sender.wd, "wechat_ax_state") as ax:
            self.assertEqual(sender.wd.find_exact_headers([exact, variant], group), [exact, variant])
            self.assertEqual(sender.wd.find_exact_headers([wrong], group), [])
            self.assertEqual(sender.wd.find_exact_headers([exact], group), [exact])
            ax.assert_not_called()

    def test_plus_compatibility_does_not_change_group_identity_or_search(self):
        group = "电销+直播攻坚组"
        variant = sender.wd.OcrHit(200, 180, 200, 30, .9, "电销＋直播攻坚组")
        self.assertFalse(sender.wd.exact_group_text(variant.text, group))
        self.assertEqual(sender.wd.find_exact_group_rows([variant], group), [])

    def test_core_group_search_ignores_decorative_suffix_but_keeps_uniqueness(self):
        core = "上海臻肆外卖运营-盯个盯-饭敢当"
        full = core + " 💰发财精英荟💰"
        heading = sender.wd.OcrHit(120, 150, 80, 20, .9, "群聊")
        result = sender.wd.OcrHit(220, 190, 360, 24, .9, full)
        history = sender.wd.OcrHit(120, 250, 80, 20, .9, "聊天记录")
        self.assertEqual(sender.wd.find_unique_core_group_rows([heading, result, history], full, core), [result])
        duplicate = sender.wd.OcrHit(220, 220, 360, 24, .9, full + "2")
        self.assertEqual(len(sender.wd.find_unique_core_group_rows([heading, result, duplicate, history], full, core)), 2)

    def test_core_group_search_accepts_unique_truncated_row_inside_group_section(self):
        core = "上海臻肆外卖运营-盯个盯-饭敢当"
        full = core + " 💰发财精英荟💰"
        heading = sender.wd.OcrHit(120, 150, 80, 20, .9, "最常使用")
        result = sender.wd.OcrHit(220, 190, 360, 24, .9, "上海臻肆外卖运营-盯个盯-…")
        history = sender.wd.OcrHit(120, 250, 80, 20, .9, "聊天记录")
        network = sender.wd.OcrHit(220, 300, 360, 24, .9, core)
        self.assertTrue(sender.wd.core_group_result_text(result.text, core))
        self.assertTrue(sender.wd.core_group_result_text("上海臻肆外卖运营-盯个盯⋯•Q ①", core))
        self.assertTrue(sender.wd.core_group_result_text("1上海臻肆外卖运营-盯个盯⋯•Q ①", core))
        self.assertFalse(sender.wd.core_group_result_text("上海臻肆…", core))
        self.assertEqual(sender.wd.find_unique_core_group_rows([heading, result, history, network], full, core), [result])

    def test_exact_header_accepts_ocr_money_bag_glyph_noise(self):
        group = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
        self.assertTrue(sender.wd.exact_group_text("上海臻肆外卖运营-盯个盯-饭敢当 ®发财精英荟®（81）〇", group))
        self.assertFalse(sender.wd.exact_group_text("上海臻肆外卖运营-盯个盯-饭敢当 ®发财精英荟®临时", group))

    def test_member_count_icon_suffix_is_bounded_and_ax_guarded(self):
        group = "电销+直播攻坚组"
        for text, expected in [
            ("电销＋直播攻坚组（17） >", True),
            ("电销+直播攻坚组(17) >", True),
            ("电销＋直播攻坚组 >", False),
            ("电销＋直播攻坚组（17） >>", False),
            ("电销＋直播攻坚组临时（17） >", False),
            ("电销＋直播攻坚组（17） 2", False),
        ]:
            hit = sender.wd.OcrHit(806, 58, 330, 41, .3, text)
            with self.subTest(text=text), \
                 mock.patch.object(sender.wd, "ax_confirms_raw_group_header", return_value=True) as ax:
                self.assertEqual(sender.wd.find_exact_headers([hit], group), [hit] if expected else [])
                self.assertEqual(ax.call_count, int(expected))
        with mock.patch.object(sender.wd, "ax_confirms_raw_group_header", return_value=False):
            hit = sender.wd.OcrHit(806, 58, 330, 41, .3, "电销＋直播攻坚组（17） >")
            self.assertEqual(sender.wd.find_exact_headers([hit], group), [])

    def test_plus_variant_ax_failure_cannot_pass_sender_verification(self):
        hit = sender.wd.OcrHit(787, 60, 292, 36, .3, "电销＋直播攻坚组（17）")
        with mock.patch.object(sender.wd, "ocr", return_value=[hit]), \
             mock.patch.object(sender.wd, "wechat_ax_state", side_effect=RuntimeError("wechat-ax-read-failed")):
            with self.assertRaisesRegex(RuntimeError, "wechat-ax-read-failed"):
                sender.verify_group(Path("unused.png"), "电销+直播攻坚组")

    def test_exact_group_is_bounded(self):
        group = "FEIBING NEO AI数字员工"
        self.assertTrue(sender.exact_group("FEIBING NEO Al数字员工（18）", group))
        self.assertFalse(sender.exact_group(group + "临时群", group))

    def test_login_gate(self):
        for text in ("为了你的账号安全，请重新登录", "进入微信", "切换账号"):
            with self.subTest(text=text):
                hit = sender.wd.OcrHit(1, 1, 1, 1, .9, text)
                self.assertTrue(sender.wd.login_blocked([hit]))

    def test_conversation_file_transfer_text_is_not_login_gate(self):
        hit = sender.wd.OcrHit(1, 1, 1, 1, .9, "仅传输文件")
        self.assertFalse(sender.wd.login_blocked([hit]))

    def test_exact_open_uses_composited_search_region(self):
        hit = sender.wd.OcrHit(100, 100, 20, 20, .9, "搜索")
        with mock.patch.object(sender.wd, "wechat_running", return_value=True), \
             mock.patch.object(sender.wd, "ensure_window_size") as resize, \
             mock.patch.object(sender.wd, "screen_scale", return_value=2.0), \
             mock.patch.object(sender.wd, "open_group_exact_ax_visible", return_value=None), \
             mock.patch.object(sender.wd, "screenshot") as shadow_capture, \
             mock.patch.object(sender.wd, "screenshot_main_region") as region_capture, \
             mock.patch.object(sender.wd, "screenshot_search_region") as search_capture, \
             mock.patch.object(sender.wd, "ocr", return_value=[hit]), \
             mock.patch.object(sender.wd, "open_group_exact", return_value=sender.wd.Receipt(ok=False, action="open-group", note="stopped")):
            receipt = sender.wd.open_group("不存在的群", Path("/tmp/wechat-test"), exact=True)
        region_capture.assert_not_called()
        search_capture.assert_called_once()
        shadow_capture.assert_not_called()
        self.assertEqual(receipt.note, "stopped")

    def test_exact_open_prefers_ax_visible_row_and_skips_screenshot(self):
        expected = sender.wd.Receipt(ok=True, action="open-group", group="目标群", header="目标群", note="ax-visible-exact-row")
        with mock.patch.object(sender.wd, "wechat_running", return_value=True), \
             mock.patch.object(sender.wd, "ensure_window_size") as resize, \
             mock.patch.object(sender.wd, "screen_scale", return_value=2.0), \
             mock.patch.object(sender.wd, "open_group_exact_ax_visible", return_value=expected), \
             mock.patch.object(sender.wd, "screenshot_main_region") as main_capture, \
             mock.patch.object(sender.wd, "screenshot_search_region") as search_capture:
            receipt = sender.wd.open_group("目标群", Path("/tmp/wechat-test"), exact=True)
        self.assertEqual(receipt.note, "ax-visible-exact-row")
        resize.assert_not_called()
        main_capture.assert_not_called()
        search_capture.assert_not_called()

    def test_ax_zero_header_after_unique_click_enters_exact_search_fallback(self):
        delayed = sender.wd.Receipt(ok=False, action="open-group", group="目标群",
                                    note="ax-exact-header-count:0")
        hit = sender.wd.OcrHit(100, 100, 20, 20, .9, "搜索")
        expected = sender.wd.Receipt(ok=True, action="open-group", group="目标群",
                                     header="目标群（18）", note="exact-group-section-text-row")
        with mock.patch.object(sender.wd, "wechat_running", return_value=True), \
             mock.patch.object(sender.wd, "ensure_window_size") as resize, \
             mock.patch.object(sender.wd, "screen_scale", return_value=2.0), \
             mock.patch.object(sender.wd, "open_group_exact_ax_visible", return_value=delayed), \
             mock.patch.object(sender.wd, "screenshot_search_region") as screenshot, \
             mock.patch.object(sender.wd, "ocr", return_value=[hit]), \
             mock.patch.object(sender.wd, "open_group_exact", return_value=expected) as exact:
            receipt = sender.wd.open_group("目标群", Path("/tmp/wechat-test"), exact=True)
        self.assertTrue(receipt.ok)
        self.assertEqual(receipt.header, "目标群（18）")
        resize.assert_called_once()
        screenshot.assert_called_once()
        exact.assert_called_once()

    def test_ambiguous_ax_header_does_not_enter_search_fallback(self):
        ambiguous = sender.wd.Receipt(ok=False, action="open-group", group="目标群",
                                      note="ax-exact-header-count:multiple")
        with mock.patch.object(sender.wd, "wechat_running", return_value=True), \
             mock.patch.object(sender.wd, "open_group_exact_ax_visible", return_value=ambiguous), \
             mock.patch.object(sender.wd, "ensure_window_size") as resize, \
             mock.patch.object(sender.wd, "screenshot_search_region") as screenshot:
            receipt = sender.wd.open_group("目标群", Path("/tmp/wechat-test"), exact=True)
        self.assertIs(receipt, ambiguous)
        resize.assert_not_called()
        screenshot.assert_not_called()

    def test_exact_search_keeps_top_group_candidate_and_excludes_network_query(self):
        group = "FEIBING NEO AI数字员工"
        top_candidate = sender.wd.OcrHit(400, 15, 300, 29, .9, group)
        history_heading = sender.wd.OcrHit(210, 101, 88, 26, 1.0, "聊天记录")
        history_mention = sender.wd.OcrHit(508, 210, 501, 23, .9,
                                           "还是说先发到 FEIBING NEO AI数字员工 临时群里")
        network_heading = sender.wd.OcrHit(283, 397, 130, 26, 1.0, "搜索网络结果")
        network_query = sender.wd.OcrHit(335, 454, 254, 23, .9, group)
        rows = sender.wd.find_exact_group_rows(
            [top_candidate, history_heading, history_mention, network_heading, network_query], group)
        self.assertEqual(rows, [top_candidate])

    def test_exact_search_does_not_treat_history_or_network_query_as_group(self):
        group = "FEIBING NEO AI数字员工"
        hits = [
            sender.wd.OcrHit(210, 101, 88, 26, 1.0, "聊天记录"),
            sender.wd.OcrHit(400, 171, 195, 29, .9, group),
            sender.wd.OcrHit(283, 397, 130, 26, 1.0, "搜索网络结果"),
            sender.wd.OcrHit(335, 454, 254, 23, .9, group),
        ]
        self.assertEqual(sender.wd.find_exact_group_rows(hits, group), [])

    def test_core_search_forces_search_even_when_target_is_current(self):
        expected = sender.wd.Receipt(ok=True, action="open-group", group="完整群名", header="完整群名", note="unique-core-search-and-exact-header")
        hit = sender.wd.OcrHit(100, 100, 20, 20, .9, "搜索")
        with mock.patch.object(sender.wd, "wechat_running", return_value=True), \
             mock.patch.object(sender.wd, "ensure_window_size"), \
             mock.patch.object(sender.wd, "screen_scale", return_value=2.0), \
             mock.patch.object(sender.wd, "open_group_exact_ax_visible") as ax, \
             mock.patch.object(sender.wd, "screenshot_search_region"), \
             mock.patch.object(sender.wd, "ocr", return_value=[hit]), \
             mock.patch.object(sender.wd, "open_group_exact", return_value=expected) as exact:
            receipt = sender.wd.open_group("完整群名", Path("/tmp/wechat-test"), exact=True, search_name="核心群名")
        self.assertTrue(receipt.ok);ax.assert_not_called();exact.assert_called_once()

    def test_ax_visible_row_requires_exact_first_line(self):
        group = "FEIBING NEO AI数字员工"
        before = {
            "window": {"x": 24, "y": 52, "width": 1120, "height": 638},
            "texts": [
                {"text": group + "\n已置顶\n消息", "x": 84, "y": 234, "width": 246, "height": 65}
            ],
        }
        after = {
            "window": before["window"],
            "texts": [{"text": group + " (18)", "x": 346, "y": 69, "width": 300, "height": 21}],
        }
        refreshed = {"window": before["window"], "texts": [before["texts"][0] | {"y": 300}]}
        with mock.patch.object(sender.wd, "wechat_ax_state", side_effect=[before, refreshed, after]), \
             mock.patch.object(sender.wd, "activate_wechat") as activate, \
             mock.patch.object(sender.wd, "click") as click, \
             mock.patch.object(sender.wd.time, "sleep"):
            receipt = sender.wd.open_group_exact_ax_visible(group)
        self.assertTrue(receipt.ok)
        self.assertEqual(receipt.note, "ax-visible-exact-row")
        activate.assert_called_once()
        click.assert_called_once_with(207.0, 332.5, activate=True, scale=1.0)

    def test_ax_row_lost_after_raise_must_not_use_old_coordinates(self):
        group = "目标群"
        window = {"x": 24, "y": 52, "width": 1120, "height": 638}
        row = {"text": group + "\n消息", "x": 84, "y": 234, "width": 246, "height": 65}
        for refreshed_rows in [[], [row, row | {"y": 300}]]:
            with mock.patch.object(sender.wd, "wechat_ax_state", side_effect=[
                {"window": window, "texts": [row]}, {"window": window, "texts": refreshed_rows}]), \
                 mock.patch.object(sender.wd, "activate_wechat"), mock.patch.object(sender.wd, "click") as click:
                result = sender.wd.open_group_exact_ax_visible(group)
            self.assertFalse(result.ok)
            click.assert_not_called()

    def test_ax_parent_and_child_header_at_same_position_count_once(self):
        group = "FEIBING NEO AI数字员工"
        state = {
            "window": {"x": 24, "y": 52, "width": 1120, "height": 638},
            "texts": [
                {"text": group + "(18)", "x": 346, "y": 69, "width": 640, "height": 21},
                {"text": group, "x": 346, "y": 69, "width": 162, "height": 21},
            ],
        }
        with mock.patch.object(sender.wd, "wechat_ax_state", return_value=state), \
             mock.patch.object(sender.wd, "click") as click:
            receipt = sender.wd.open_group_exact_ax_visible(group)
        self.assertTrue(receipt.ok)
        self.assertEqual(receipt.note, "ax-current-header")
        click.assert_not_called()

    def test_click_binary_forces_atomic_wechat_activation(self):
        source = (Path(sender.wd.__file__).parent / "cgevent_click.swift").read_text(encoding="utf-8")
        self.assertIn(".activateIgnoringOtherApps", source)
        self.assertNotIn("app.activate(options: [])", source)

    def test_window_bounds_binds_named_main_window(self):
        with mock.patch.object(sender.wd, "wechat_ax_application", return_value="app"), \
             mock.patch.object(sender.wd, "ax_main_window", return_value=("w", (1200.0, 820.0))), \
             mock.patch.object(sender.wd, "ax_position", return_value=(10.0, 20.0)):
            self.assertEqual(sender.wd.window_bounds(), (10.0, 20.0, 1200.0, 820.0))
        source = Path(sender.wd.__file__).read_text(encoding="utf-8")
        bounds = source.split("def window_bounds()", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("ax_main_window", bounds)
        self.assertIn("ax_position", bounds)
        self.assertNotIn("front window", bounds)
        guard = source.split("def ax_main_window(", 1)[1].split("\ndef ", 1)[0]
        self.assertIn('== "微信"', guard)
        self.assertIn("700", guard)
        self.assertIn("500", guard)
        self.assertIn("wechat-main-window-count-not-one", guard)

    def test_undersized_single_named_window_is_recovered_before_main_window_gate(self):
        source = (Path(sender.wd.__file__).read_text(encoding="utf-8"))
        activate = source.split("def activate_wechat() -> None:", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("ensure_window_size()", activate)
        self.assertIn("window_geometry_script", source)
        self.assertIn("wechat-main-window-size-readback-mismatch", source)
        self.assertIn("set size of w to", sender.wd.window_geometry_script((24, 24), (1000, 700)))
        self.assertIn("ax_main_window", activate)
        self.assertIn("wechat-main-window-count-not-one", source)

    def test_main_region_capture_is_window_bound_and_shadowless(self):
        with mock.patch.object(sender.wd, "wechat_window_id", return_value=123), \
             mock.patch.object(sender.wd, "capture_image_valid", return_value=True), \
             mock.patch.object(sender.wd, "run") as run:
            run.return_value.returncode = 0
            sender.wd.screenshot_main_region(Path("/tmp/wechat-main.png"))
        self.assertEqual(run.call_args.args[0], ["screencapture", "-x", "-o", "-l", "123", "/tmp/wechat-main.png"])

    def test_main_region_capture_falls_back_to_same_window_without_activation(self):
        failed = mock.Mock(returncode=1, stderr="could not create image from window")
        succeeded = mock.Mock(returncode=0, stdout='{"width":2240,"height":1276}', stderr="")
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(sender.wd, "wechat_window_id", return_value=6363), \
             mock.patch.object(sender.wd, "run", side_effect=[failed, succeeded]) as run, \
             mock.patch.object(sender.wd, "capture_image_valid", return_value=True), \
             mock.patch.object(sender.wd, "activate_wechat") as activate:
            path = Path(directory) / "wechat-main.png"
            path.write_bytes(b"placeholder")
            def create_fallback(command, *args, **kwargs):
                if command[0] == sender.wd.CONTROL_PYTHON:
                    path.write_bytes(b"png")
                    return succeeded
                return failed
            run.side_effect = create_fallback
            method = sender.wd.screenshot_main_region(path)
        self.assertEqual(method, "quartz-window-id")
        activate.assert_not_called()
        self.assertEqual(run.call_count, 2)

    def test_blank_window_captures_fail_closed_when_wechat_not_unobstructed(self):
        failed = mock.Mock(returncode=1, stderr="could not create image from window")
        quartz = mock.Mock(returncode=0, stdout='{"width":2240,"height":1276}', stderr="")
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(sender.wd, "wechat_window_id", return_value=6363), \
             mock.patch.object(sender.wd, "capture_image_valid", return_value=False), \
             mock.patch.object(sender.wd, "run", side_effect=[failed, quartz]) as run, \
             mock.patch.object(sender.wd, "activate_wechat"), \
             mock.patch.object(sender.wd, "wechat_window_unobstructed", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "wechat-window-capture-failed"):
                sender.wd.screenshot_main_region(Path(directory) / "wechat-main.png")
        self.assertEqual(run.call_count, 2)

    def test_main_region_region_fallback_requires_unobstructed_window(self):
        failed = mock.Mock(returncode=1, stderr="could not create image from window")
        quartz = mock.Mock(returncode=1, stdout="", stderr="quartz-window-capture-invalid")
        region = mock.Mock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(sender.wd, "wechat_window_id", return_value=6363), \
             mock.patch.object(sender.wd, "capture_image_valid", return_value=True), \
             mock.patch.object(sender.wd, "run", side_effect=[failed, quartz, region]) as run, \
             mock.patch.object(sender.wd, "wechat_window_unobstructed", return_value=True), \
             mock.patch.object(sender.wd, "wechat_menu_bar_frontmost", return_value=True), \
             mock.patch.object(sender.wd, "window_bounds", return_value=(24, 30, 1200, 820)), \
             mock.patch.object(sender.wd, "activate_wechat") as activate:
            target = Path(directory) / "wechat-main.png"
            method = sender.wd.screenshot_main_region(target)
        self.assertEqual(method, "screencapture-region-frontmost")
        activate.assert_not_called()
        self.assertEqual(run.call_args.args[0],
                         ["screencapture", "-x", "-R24,30,1200,820", str(target)])

    def test_main_region_discards_region_frame_if_post_capture_occlusion_changes(self):
        failed = mock.Mock(returncode=1, stderr="could not create image from window")
        quartz = mock.Mock(returncode=1, stdout="", stderr="quartz-window-capture-invalid")
        region = mock.Mock(returncode=0, stderr="")
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(sender.wd, "wechat_window_id", return_value=6363), \
             mock.patch.object(sender.wd, "capture_image_valid", return_value=True), \
             mock.patch.object(sender.wd, "run", side_effect=[failed, quartz, region]), \
             mock.patch.object(sender.wd, "wechat_window_unobstructed", side_effect=[True, True, False]), \
             mock.patch.object(sender.wd, "wechat_menu_bar_frontmost", return_value=True), \
             mock.patch.object(sender.wd, "window_bounds", return_value=(24, 30, 1200, 820)), \
             mock.patch.object(sender.wd, "activate_wechat"):
            target = Path(directory) / "wechat-main.png"
            with self.assertRaisesRegex(RuntimeError, "wechat-window-capture-failed"):
                sender.wd.screenshot_main_region(target)
            self.assertFalse(target.exists())


    def test_search_region_capture_includes_transient_popover(self):
        with mock.patch.object(sender.wd, "activate_wechat"), \
             mock.patch.object(sender.wd.time, "sleep"), \
             mock.patch.object(sender.wd, "wechat_window_id", return_value=6363), \
             mock.patch.object(sender.wd, "wechat_window_unobstructed", return_value=True), \
             mock.patch.object(sender.wd, "wechat_menu_bar_frontmost", return_value=True), \
             mock.patch.object(sender.wd, "window_bounds", return_value=(24, 30, 1200, 820)), \
             mock.patch.object(sender.wd, "run") as run:
            run.return_value.returncode = 0
            sender.wd.screenshot_search_region(Path("/tmp/wechat-search.png"))
        self.assertEqual(run.call_args.args[0], ["screencapture", "-x", "-R24,30,1200,820", "/tmp/wechat-search.png"])

    def test_search_region_discards_frame_if_window_becomes_obstructed(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(sender.wd, "activate_wechat"), \
             mock.patch.object(sender.wd.time, "sleep"), \
             mock.patch.object(sender.wd, "wechat_window_id", return_value=6363), \
             mock.patch.object(sender.wd, "wechat_window_unobstructed", side_effect=[True, False]), \
             mock.patch.object(sender.wd, "wechat_menu_bar_frontmost", return_value=True), \
             mock.patch.object(sender.wd, "window_bounds", return_value=(24, 30, 1200, 820)), \
             mock.patch.object(sender.wd, "run") as run:
            path = Path(directory) / "search.png"
            path.write_bytes(b"candidate")
            run.return_value.returncode = 0
            with self.assertRaisesRegex(RuntimeError, "wechat-search-region-contended"):
                sender.wd.screenshot_search_region(path)
            self.assertFalse(path.exists())

    def test_window_id_requires_exact_wechat_process_and_main_window_shape(self):
        source = Path(sender.wd.__file__).read_text(encoding="utf-8")
        self.assertIn("kCGWindowListOptionAll", source)
        self.assertIn("kCGWindowOwnerPID", source)
        self.assertIn("owner_pid == int(process_id)", source)
        self.assertIn("width >= 900", source)
        self.assertIn("height >= 560", source)

    def test_sender_uses_borderless_evidence_for_action_coordinates(self):
        source = Path(sender.__file__).read_text(encoding="utf-8")
        self.assertIn('wd.screenshot_main_region(before)', source)
        self.assertIn('wd.screenshot_main_region(prepared)', source)
        self.assertIn('wd.screenshot_main_region(shot)', source)
        self.assertIn('desktop-file-preview-not-prepared', source)

    def test_sender_reuses_shared_exact_header_locator(self):
        with tempfile.TemporaryDirectory() as directory, \
             mock.patch.object(sender.wd, "ocr", return_value=[]), \
             mock.patch.object(sender.wd, "find_exact_headers", return_value=[object()]) as locator:
            path = Path(directory) / "window.png"
            sender.verify_group(path, "FEIBING NEO AI数字员工")
        locator.assert_called_once()

    def test_sender_accepts_ax_only_after_group_section_preflight(self):
        group="上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
        opened={"note":"exact-group-section-text-row","group":group,"header":group}
        with mock.patch.object(sender.wd,"ocr",return_value=[]), \
             mock.patch.object(sender.wd,"find_exact_headers",return_value=[]), \
             mock.patch.object(sender.wd,"ax_confirms_raw_group_header",return_value=True) as ax:
            sender.verify_group(Path("unused.png"),group,opened)
        ax.assert_called_once_with(group)

    def test_sender_rejects_ax_without_group_section_preflight(self):
        group="目标群"
        with mock.patch.object(sender.wd,"ocr",return_value=[]), \
             mock.patch.object(sender.wd,"find_exact_headers",return_value=[]), \
             mock.patch.object(sender.wd,"ax_confirms_raw_group_header",return_value=True) as ax:
            with self.assertRaisesRegex(sender.StopRun,"desktop-group-title-not-unique:0"):
                sender.verify_group(Path("unused.png"),group,{"note":"ax-current-header","group":group,"header":group})
        ax.assert_not_called()

    def test_sender_activates_wechat_only_at_authorized_input_stage(self):
        source = Path(sender.__file__).read_text(encoding="utf-8")
        stage = source.index('result["stage"] = "verify_target_and_input"')
        activate = source.index("wd.activate_wechat()", stage)
        focus = source.index("focus_chat_input(); time.sleep(.3)", stage)
        self.assertLess(activate, focus)

    def test_all_sender_group_rechecks_bind_verified_preflight(self):
        source = Path(sender.__file__).read_text(encoding="utf-8")
        self.assertIn("verify_group(before, args.group, opened)",source)
        self.assertIn("verify_group(prepared, args.group, opened)",source)
        self.assertIn("verify_group(shot, args.group, opened)",source)
        self.assertNotIn("verify_group(prepared, args.group)\n",source)
        self.assertNotIn("verify_group(shot, args.group)\n",source)

    def test_image_post_send_uses_composer_band_and_ax_empty_readback(self):
        source = Path(sender.__file__).read_text(encoding="utf-8")
        self.assertIn("int(height * .82)", source)
        self.assertIn("input_cleared = chat_input_empty()", source)
        self.assertIn('result.setdefault("postSendInputCleared", [])', source)
        self.assertIn("input_delta < max(7500, int(prepared_delta * .65))", source)

    def test_chat_input_empty_has_bounded_focus_retry(self):
        with mock.patch.object(sender, "focus_chat_input", side_effect=[sender.StopRun("transient"), None]) as focus, \
             mock.patch.object(sender, "focused_text_value", return_value=""):
            self.assertTrue(sender.chat_input_empty())
        self.assertEqual(focus.call_count, 2)

    def test_normalize_empty_composer_clears_whitespace_only(self):
        with mock.patch.object(sender, "focused_text_value", side_effect=[" \n", ""]), \
             mock.patch.object(sender, "set_focused_text") as set_value, \
             mock.patch.object(sender.time, "sleep"):
            self.assertTrue(sender.normalize_empty_composer())
        set_value.assert_called_once_with("")

    def test_normalize_empty_composer_preserves_non_whitespace_draft(self):
        with mock.patch.object(sender, "focused_text_value", return_value="用户草稿"), \
             mock.patch.object(sender, "set_focused_text") as set_value:
            self.assertFalse(sender.normalize_empty_composer())
        set_value.assert_not_called()

    def test_send_review_covers_each_measured_stage(self):
        receipt = {
            "ok": True, "stage": "completed", "elapsedMs": 30,
            "stageMs": {"prepare_payload": 20, "locate_group": 10},
        }
        sender.finalize_send_review(receipt)
        self.assertEqual([row["stage"] for row in receipt["sendReview"]], ["locate_group", "prepare_payload"])
        self.assertEqual(receipt["reviewSummary"], {"totalElapsedMs": 30, "itemCount": 2, "pitfallCount": 0, "result": "success"})

    def test_send_review_binds_failure_to_active_stage(self):
        receipt = {
            "ok": False, "stage": "verify_target_and_input", "reason": "desktop-chat-input-not-empty",
            "elapsedMs": 12, "stageMs": {"locate_group": 5, "verify_target_and_input": 7},
        }
        sender.finalize_send_review(receipt)
        self.assertEqual(receipt["sendReview"][1]["status"], "failed")
        self.assertEqual(receipt["sendReview"][1]["pitfalls"][0]["reason"], "desktop-chat-input-not-empty")

    def test_unknown_result_is_persisted_after_attempt(self):
        source = Path(sender.__file__).read_text(encoding="utf-8")
        self.assertIn('result["state"] = "unknown"\n            atomic_write(marker, result)', source)
        self.assertIn('result["postSendFailureReason"] = str(exc)', source)
        self.assertIn('result["reason"] = "desktop-post-send-verification-unknown"', source)

    def test_chat_input_focus_is_ax_role_and_size_bounded(self):
        focused = object()
        with mock.patch.object(sender.wd, "ax_main_window", return_value=("w", (1200.0, 820.0))), \
             mock.patch.object(sender.wd, "ax_descendants", return_value=[focused]), \
             mock.patch.object(sender.wd, "ax_size", return_value=(900.0, 120.0)), \
             mock.patch.object(sender.wd, "ax_attribute",
                               side_effect=lambda ax, el, attr, default=None: {
                                   "AXRole": "AXTextArea",
                                   "AXFocusedUIElement": focused}.get(attr, default)), \
             mock.patch.object(sender, "_ax_set") as set_attr:
            sender.focus_chat_input()
        set_attr.assert_called_once()
        source = Path(sender.__file__).read_text(encoding="utf-8")
        self.assertIn("AXTextArea", source)
        self.assertIn("> 400", source)
        self.assertIn("> 40", source)
        self.assertIn('"desktop-chat-input-focus-failed"', source)

    def test_send_uses_unique_enabled_ax_button_center_not_keyboard_shortcut(self):
        button = object()
        with mock.patch.object(sender.wd, "ax_main_window", return_value=("w", (1200.0, 820.0))), \
             mock.patch.object(sender.wd, "ax_descendants", return_value=[button]), \
             mock.patch.object(sender.wd, "ax_attribute",
                               side_effect=lambda ax, el, attr, default=None: {
                                   "AXRole": "AXButton",
                                   "AXTitle": "发送",
                                   "AXEnabled": True}.get(attr, default)), \
             mock.patch.object(sender.wd, "ax_position", return_value=(60.0, 180.0)), \
             mock.patch.object(sender.wd, "ax_size", return_value=(80.0, 40.0)), \
             mock.patch.object(sender.wd, "click") as click:
            sender.press_send_button()
        click.assert_called_once_with(100.0, 200.0, activate=True, scale=1.0)
        source = Path(sender.__file__).read_text(encoding="utf-8")
        self.assertIn('!= "发送"', source)
        self.assertIn("kAXEnabledAttribute", source)
        self.assertNotIn('perform action "AXPress"', source)
        self.assertIn('"desktop-send-button-press-failed"', source)

    def test_all_payload_types_require_empty_composer_after_send(self):
        source = Path(sender.__file__).read_text(encoding="utf-8")
        self.assertNotIn('key("send")', source)
        self.assertIn("input_cleared\n                    and bool(probes)", source)
        self.assertIn('ok = input_cleared and all(file_preview_visible', source)

    def test_text_send_retained_composer_is_unknown_not_false_verified(self):
        text = "城市\n联系人，手机号\n商家\n地址"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            args = Namespace(
                output_dir=str(root / "evidence"), group="FEIBING NEO AI数字员工",
                payload_type="text", item=[text], execute=True, authorization="standing",
                ledger=str(root / "ledger"), marker_name=None,
            )
            opened = sender.wd.Receipt(ok=True, action="open-group", group=args.group)
            with mock.patch.object(sender.wd, "open_group", return_value=opened), \
                 mock.patch.object(sender.wd, "activate_wechat"), \
                 mock.patch.object(sender.wd, "screenshot_main_region"), \
                 mock.patch.object(sender.wd, "ocr", return_value=[]), \
                 mock.patch.object(sender, "verify_group"), \
                 mock.patch.object(sender, "image_size", return_value=(1200, 800)), \
                 mock.patch.object(sender, "focus_chat_input"), \
                 mock.patch.object(sender, "focused_text_value", side_effect=["", text]), \
                 mock.patch.object(sender, "set_focused_text"), \
                 mock.patch.object(sender, "set_text_clipboard"), \
                 mock.patch.object(sender, "changed_pixels", return_value=20000), \
                 mock.patch.object(sender, "chat_input_empty", side_effect=[False, False]), \
                 mock.patch.object(sender, "press_send_button") as button, \
                 mock.patch.object(sender, "key") as keyboard, \
                 mock.patch.object(sender.time, "sleep"):
                receipt = sender.send(args)
            self.assertFalse(receipt["ok"])
            self.assertEqual(receipt["reason"], "desktop-post-send-verification-unknown")
            self.assertEqual(receipt["state"], "unknown")
            self.assertEqual(receipt["sendAttempts"], 1)
            self.assertEqual(receipt["postSendInputCleared"], [False, False])
            self.assertNotIn("verified", receipt)
            button.assert_called_once()
            keyboard.assert_not_called()
            marker = next((root / "ledger").glob("*.json"))
            self.assertEqual(sender.json.loads(marker.read_text())["state"], "unknown")

    def test_file_clipboard_requires_public_file_urls(self):
        source = Path(sender.__file__).read_text(encoding="utf-8")
        self.assertIn("NSPasteboard.generalPasteboard()", source)
        self.assertIn("NSURL.fileURLWithPath_", source)
        self.assertIn('"public.file-url" not in list(item.types())', source)
        self.assertNotIn("set the clipboard to xs", source)

    def test_file_preview_prefix_is_stable_before_date_suffix(self):
        self.assertEqual(sender.file_preview_prefix("美团外卖日报_2026-09-09.xlsx"), "美团外卖日报")
        self.assertEqual(sender.file_preview_prefix("淘宝闪购日报_2026-09-09.xlsx"), "淘宝闪购日报")

    def test_truncated_file_preview_requires_head_tail_and_exact_display_size(self):
        name = "淘宝闪购差评申诉汇总-2026-09-21.xlsx"
        self.assertEqual(sender.file_preview_size(8890), "8.7K")
        self.assertTrue(sender.file_preview_visible(name, 8890, "淘宝闪购差评申...21.xlsx 8.7K"))
        self.assertFalse(sender.file_preview_visible(name, 8890, "淘宝闪购差评申...20.xlsx 8.7K"))
        self.assertFalse(sender.file_preview_visible(name, 8890, "淘宝闪购差评申...21.xlsx 8.6K"))
        self.assertFalse(sender.file_preview_visible(name, 8890, "淘宝闪购差评申"))

    def test_existing_prepared_file_requires_same_zero_attempt_receipt_and_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            payload = {"name": "日报.xlsx", "size": 1234, "sha256": "a" * 64}
            receipt = {
                "groupName": "目标群", "payloadIdentity": "identity", "sendAttempts": 0,
                "reason": "desktop-file-preview-not-prepared", "uncommittedPreviewCleanup": "failed",
                "payloads": [payload],
            }
            (out / "receipt.json").write_text(sender.json.dumps(receipt), encoding="utf-8")
            self.assertTrue(sender.prior_zero_attempt_prepared_matches(out, "identity", "目标群", [payload]))
            self.assertFalse(sender.prior_zero_attempt_prepared_matches(out, "identity", "目标群", [payload | {"sha256": "b" * 64}]))
            receipt["sendAttempts"] = 1
            (out / "receipt.json").write_text(sender.json.dumps(receipt), encoding="utf-8")
            self.assertFalse(sender.prior_zero_attempt_prepared_matches(out, "identity", "目标群", [payload]))

    def test_exact_group_locators_reject_prefix_and_other_suffixes(self):
        group = "FEIBING NEO AI数字员工"
        section = sender.wd.OcrHit(100, 50, 100, 20, .9, "最常使用")
        hit = sender.wd.OcrHit(300, 144, 100, 20, .9, "FEIBING NEO Al数字员工（18）")
        history = sender.wd.OcrHit(100, 242, 100, 20, .9, "聊天记录")
        self.assertTrue(sender.wd.exact_group_text(hit.text, group))
        self.assertEqual(sender.wd.find_exact_group_rows([section, hit, history], group), [hit])
        self.assertFalse(sender.wd.exact_group_text(group + "测试群", group))
        self.assertFalse(sender.wd.exact_group_text(group + "2", group))

    def test_decorated_group_row_requires_group_section_and_full_name(self):
        group = "上海臻肆外卖运营-盯个盯-饭敢当"
        network = sender.wd.OcrHit(370, 187, 400, 30, .5, "Q " + group)
        heading = sender.wd.OcrHit(190, 254, 49, 26, 1, "群聊")
        result = sender.wd.OcrHit(510, 348, 505, 33, .3, group + "….Q")
        history = sender.wd.OcrHit(213, 446, 94, 26, .5, "聊天记录")
        history_row = sender.wd.OcrHit(503, 564, 498, 29, .3, "我是" + group + " 发…")
        self.assertTrue(sender.wd.decorated_group_result_text(result.text, group))
        self.assertFalse(sender.wd.decorated_group_result_text(group[:-1] + "….Q", group))
        self.assertEqual(sender.wd.find_exact_group_rows([network, heading, result, history, history_row], group), [result])

    def test_decorated_group_rows_remain_ambiguous_when_duplicated(self):
        group = "上海臻肆外卖运营-盯个盯-饭敢当"
        heading = sender.wd.OcrHit(190, 254, 49, 26, 1, "群聊")
        first = sender.wd.OcrHit(510, 330, 505, 33, .3, group + "….Q")
        second = sender.wd.OcrHit(510, 380, 505, 33, .3, group + "...O")
        history = sender.wd.OcrHit(213, 446, 94, 26, .5, "聊天记录")
        self.assertEqual(sender.wd.find_exact_group_rows([heading, first, second, history], group), [first, second])

    def test_exact_group_locator_ignores_section_names_and_excludes_input_and_chat(self):
        group = "FEIBING NEO AI数字员工"
        heading = sender.wd.OcrHit(100, 110, 100, 20, .9, "任意新分组名称")
        result = sender.wd.OcrHit(300, 144, 100, 20, .9, group)
        query = sender.wd.OcrHit(250, 70, 300, 20, .9, group)
        chat = sender.wd.OcrHit(900, 640, 300, 20, .9, group)
        right_edge = sender.wd.OcrHit(1150, 300, 20, 20, .9, "消息")
        self.assertEqual(sender.wd.find_exact_group_rows([heading, result, query, chat, right_edge], group), [result])

    def test_open_exact_group_clicks_existing_unique_result_before_search_toggle(self):
        group = "FEIBING NEO AI数字员工"
        result = sender.wd.OcrHit(300, 144, 100, 20, .9, group)
        right_edge = sender.wd.OcrHit(1150, 300, 20, 20, .9, "消息")
        header = sender.wd.OcrHit(419, 28, 260, 24, .9, group + "（18）")
        with tempfile.TemporaryDirectory() as d, \
             mock.patch.object(sender.wd, "click_local") as click, \
             mock.patch.object(sender.wd, "screenshot_main_region"), \
             mock.patch.object(sender.wd, "ocr", return_value=[header, right_edge]), \
             mock.patch.object(sender.wd, "find_search_controls") as search, \
             mock.patch.object(sender.wd.time, "sleep"):
            receipt = sender.wd.open_group_exact(group, Path(d), Path(d) / "before.png", [result, right_edge], 2.0)
        self.assertTrue(receipt.ok)
        self.assertEqual(receipt.note, "existing-exact-result")
        click.assert_called_once_with(result.cx, result.cy, activate=False, scale=2.0)
        search.assert_not_called()

    def test_search_query_echo_is_separate_from_clickable_result(self):
        group = "FEIBING NEO AI数字员工"
        query = sender.wd.OcrHit(250, 70, 300, 20, .9, "Q " + group)
        result = sender.wd.OcrHit(300, 144, 100, 20, .9, group)
        self.assertEqual(sender.wd.find_search_query_echoes([query, result], group), [query])
        self.assertEqual(sender.wd.find_exact_group_rows([query, result], group), [result])

    def test_exact_header_locator_adapts_to_narrow_window(self):
        group = "FEIBING NEO AI数字员工"
        sidebar_same_name = sender.wd.OcrHit(180, 70, 220, 24, .9, group)
        header = sender.wd.OcrHit(419, 28, 260, 24, .9, group + "（18）")
        right_edge_marker = sender.wd.OcrHit(1150, 300, 20, 20, .9, "消息")
        self.assertEqual(
            sender.wd.find_exact_headers([sidebar_same_name, header, right_edge_marker], group),
            [header],
        )

    def test_exact_header_locator_adapts_to_wide_window(self):
        group = "FEIBING NEO AI数字员工"
        sidebar_same_name = sender.wd.OcrHit(400, 70, 260, 24, .9, group)
        header = sender.wd.OcrHit(835, 57, 300, 30, .9, group + "（18）")
        right_edge_marker = sender.wd.OcrHit(2140, 500, 20, 20, .9, "消息")
        message_same_name = sender.wd.OcrHit(1200, 500, 300, 30, .9, group)
        self.assertEqual(
            sender.wd.find_exact_headers(
                [sidebar_same_name, header, right_edge_marker, message_same_name], group
            ),
            [header],
        )

    def test_search_control_allows_only_short_icon_noise(self):
        good = sender.wd.OcrHit(300, 120, 80, 20, .9, "Q 搜索")
        bad = sender.wd.OcrHit(300, 120, 120, 20, .9, "聊天记录搜索")
        self.assertEqual(sender.wd.find_search_controls([good, bad]), [good])

    def test_payload_identity_is_stable_and_content_bound(self):
        first, payloads = sender.payload_identity("群", "text", ["正文"])
        second, _ = sender.payload_identity("群", "text", ["正文"])
        changed, _ = sender.payload_identity("群", "text", ["正文2"])
        self.assertEqual(first, second)
        self.assertNotEqual(first, changed)
        self.assertEqual(payloads[0]["text"], "正文")

    def test_attempt_claim_is_cross_channel_business_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory)
            sender.claim(ledger, "identity", {"channel": "desktop"})
            with self.assertRaises(sender.StopRun):
                sender.claim(ledger, "identity", {"channel": "desktop"})

    def test_file_identity_hashes_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.xlsx"
            path.write_bytes(b"one")
            first, _ = sender.payload_identity("群", "file", [str(path)])
            path.write_bytes(b"two")
            second, _ = sender.payload_identity("群", "file", [str(path)])
            self.assertNotEqual(first, second)

    def test_image_preview_threshold_allows_rendered_preview(self):
        self.assertEqual(sender.MIN_IMAGE_PREVIEW_PIXELS, 3000)
        self.assertGreater(sender.MIN_IMAGE_PREVIEW_RATIO, 0)

    def test_uncommitted_preview_is_cancelled_and_verified(self):
        result = {}
        with mock.patch.object(sender, "key") as key, \
             mock.patch.object(sender, "chat_input_empty", return_value=True), \
             mock.patch.object(sender.time, "sleep"):
            sender.cancel_uncommitted_preview(result)
        key.assert_called_once_with("Escape")
        self.assertEqual(result["uncommittedPreviewCleanup"], "attempted")
        self.assertTrue(result["uncommittedPreviewCleared"])


if __name__ == "__main__":
    unittest.main()

class SingleWindowAppleScriptTests(unittest.TestCase):
    def test_sender_scripts_bind_main_window_through_ax(self):
        source = Path(sender.__file__).read_text(encoding="utf-8")
        self.assertNotIn('tell application "System Events"', source)
        self.assertNotIn("osascript", source)
        self.assertGreaterEqual(source.count("wd.ax_main_window"), 2)
