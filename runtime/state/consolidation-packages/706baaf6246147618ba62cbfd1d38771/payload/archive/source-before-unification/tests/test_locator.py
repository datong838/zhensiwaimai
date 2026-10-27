"""纯逻辑单测：抽取器正则、混合定位降级（无需真机）。

用法：python -m tests.test_locator
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from extractors import (  # noqa
    extract_rating, extract_monthly_sales, extract_price,
    extract_eta, extract_promotions, build_shop_info,
)
from locator import find  # noqa  # 仅测试导入与降级返回 None


class TestExtractors(unittest.TestCase):
    def test_rating(self):
        self.assertEqual(extract_rating("评分4.8分 好评如潮"), 4.8)
        self.assertIsNone(extract_rating("无评分"))

    def test_monthly_sales(self):
        self.assertEqual(extract_monthly_sales("月售9999+"), "9999+")

    def test_price(self):
        self.assertEqual(extract_price("特价¥29.9 限时"), 29.9)

    def test_eta(self):
        self.assertEqual(extract_eta("预计30分钟达"), "30分钟达")
        self.assertIsNone(extract_eta("暂无时效"))

    def test_promotions(self):
        self.assertEqual(
            extract_promotions("百亿补贴 聚划算 满减", ["百亿补贴", "聚划算"]),
            ["百亿补贴", "聚划算"],
        )

    def test_build_shop_info(self):
        class B:
            def __init__(self, text, y=50):
                self.text = text
                self.y = y
        blocks = [B("老王烧烤(朝阳店)"), B("4.8分"), B("月售2000+"), B("配送¥5")]
        info = build_shop_info(blocks, "meituan", rank=1)
        self.assertEqual(info["platform"], "meituan")
        self.assertEqual(info["rating"], 4.8)
        self.assertEqual(info["shop_name"], "老王烧烤(朝阳店)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
