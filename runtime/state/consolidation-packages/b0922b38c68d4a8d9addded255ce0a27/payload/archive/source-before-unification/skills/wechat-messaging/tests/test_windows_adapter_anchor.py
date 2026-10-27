import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import windows_adapter as w  # noqa: E402

NOTICE = (
    '--- 2026-09-29 差评申诉进度通知 ---\n'
    '李老哈·东北农家小院(海上海店)\n'
    '【美团】\n'
    '评价时间: 2026-09-29\n'
    '评价等级: 2星\n'
    '申诉结果：---申诉中---\n'
    '评价内容: 最难吃的炖白菜\n'
)
# 驱动的真实回读形态：换行被整体删除，其余原样保留。
FLATTENED = (
    '--- 2026-09-29 差评申诉进度通知 ---李老哈·东北农家小院(海上海店)【美团】'
    '评价时间: 2026-09-29评价等级: 2星申诉结果：---申诉中---评价内容: 最难吃的炖白菜'
)


class AnchorFlattening(unittest.TestCase):
    def test_multiline_anchor_matches_flattened_readback(self):
        # 2026-09-30 实测事故：通知已发出，却因换行表示差异被判 unknown。
        self.assertTrue(w._anchor_newness(['10:43', FLATTENED], NOTICE))

    def test_anchor_followed_only_by_timestamps_passes(self):
        self.assertTrue(w._anchor_newness(['10:43', FLATTENED, '11:28'], NOTICE))

    def test_anchor_not_trailing_still_fails(self):
        self.assertFalse(w._anchor_newness([FLATTENED, '又来了别的消息'], NOTICE))

    def test_wrong_anchor_still_fails(self):
        self.assertFalse(w._anchor_newness([FLATTENED], NOTICE.replace('最难吃的炖白菜', '别的评价')))

    def test_escaped_newline_inside_readback_still_matches(self):
        # 驱动条目也可能是结构化 dict，其字段里的**真实换行**会被 json.dumps 转义成
        # 两字符 '\n'（反斜杠+n）。压平必须能穿透这层转义后仍命中锚点。
        item = {'sender': '臻肆运营', 'content': NOTICE}
        self.assertTrue(w._anchor_newness([item], NOTICE))

    def test_escaped_carriage_return_inside_readback_still_matches(self):
        item = {'content': NOTICE.replace('\n', '\r\n')}
        self.assertTrue(w._anchor_newness([item], NOTICE))

    def test_literal_backslash_n_never_becomes_a_false_pass(self):
        # 已知边界且刻意保留：锚点是业务通知正文（不含反斜杠），故不做第二个字面
        # 反斜杠序列的归一化。若条目里真带字面 '\n'，只允许判 unknown（fail-closed），
        # 绝不允许越权判成 verified。
        literal = FLATTENED.replace('【美团】', '【美团】\\n')
        self.assertFalse(w._anchor_newness([literal], NOTICE))

    def test_empty_messages_fail_closed(self):
        self.assertFalse(w._anchor_newness([], NOTICE))

    def test_flatten_never_shortens_to_empty_for_real_text(self):
        self.assertEqual(w._flatten('a\r\nb\\nc'), 'abc')


class DriverSearchKey(unittest.TestCase):
    def test_truncates_at_first_non_bmp_and_keeps_prefix(self):
        full = '上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
        key = w._driver_search_key(full)
        self.assertEqual(key, '上海臻肆外卖运营-盯个盯-饭敢当')
        self.assertTrue(full.startswith(key))

    def test_plain_names_are_untouched(self):
        for name in ('FEIBING NEO AI数字员工', '臻肆测试群', '李老哈（品牌）'):
            self.assertEqual(w._driver_search_key(name), name)

    def test_brand_group_with_emoji_keeps_prefix(self):
        full = '李老哈（品牌）💰臻肆外卖运营对接群'
        self.assertEqual(w._driver_search_key(full), '李老哈（品牌）')
        self.assertTrue(full.startswith(w._driver_search_key(full)))

    def test_all_non_bmp_falls_back_instead_of_empty(self):
        self.assertEqual(w._driver_search_key('💰💰'), '💰💰')

    def test_empty_input_is_safe(self):
        self.assertEqual(w._driver_search_key(''), '')


if __name__ == '__main__':
    unittest.main()
