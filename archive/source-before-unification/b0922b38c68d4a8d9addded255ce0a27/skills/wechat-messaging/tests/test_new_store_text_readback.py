import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from desktop_text_readback import _payload_bubble_anchor


class NewStoreTextReadbackTests(unittest.TestCase):
    def test_ocr_fullwidth_parentheses_only_locate_candidate(self):
        hit = SimpleNamespace(text="淘宝 伊戈塔可（雨花店）3天", cx=2133, cy=982)
        found = _payload_bubble_anchor([hit], "淘宝  伊戈塔可(雨花店)  3天", 2560, 1280)
        self.assertTrue(found["ok"])
        self.assertEqual((found["x"], found["y"]), (2133, 982))

    def test_other_store_does_not_match(self):
        hit = SimpleNamespace(text="淘宝 其他店（雨花店）3天", cx=2133, cy=982)
        self.assertFalse(_payload_bubble_anchor([hit], "淘宝  伊戈塔可(雨花店)  3天", 2560, 1280)["ok"])


if __name__ == "__main__":
    unittest.main()
