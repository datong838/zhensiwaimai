import unittest
from unittest.mock import patch
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import wecom_desktop_sender as s
class TallPreview(unittest.TestCase):
 def check(self,sizes,source=(514,1114)):
  sig={('AXUnknown',(float(i),601.),size) for i,size in enumerate(sizes)}
  with patch.object(s,'locate_input_box',return_value={}),patch.object(s,'input_subtree_sig',return_value=sig):return s.paste_verify(set(),'image',source)[0]
 def test_real_tall(self):self.assertTrue(self.check([(20.301615798922796,45.)]))
 def test_landscape(self):self.assertTrue(self.check([(120.,60.)],(1000,500)))
 def test_too_small(self):self.assertFalse(self.check([(9.,20.)]))
 def test_wrong_ratio(self):self.assertFalse(self.check([(100.,45.)]))
 def test_multiple(self):self.assertFalse(self.check([(20.3,45.),(20.3,45.)]))
 def test_empty(self):self.assertFalse(self.check([]))
if __name__=='__main__':unittest.main()
