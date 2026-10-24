import sys,time,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from desktop_adapter import DesktopAdapter
class WaitTests(unittest.TestCase):
 def test_upload_then_complete_without_resend(self):
  a=DesktopAdapter.__new__(DesktopAdapter);a.wd=Mock();a.sender=Mock();a.sender.chat_input_empty.return_value=True
  a.verify_media=Mock(side_effect=[{'ok':False},{'ok':True}])
  with patch('desktop_adapter.time.sleep'):
   r=a.wait_media({'groupName':'测试'},{},Path('/tmp/test'),{},time.time()+10)
  self.assertTrue(r['ok']);self.assertEqual(a.wd.screenshot_main_region.call_count,2);a.sender._send_locked.assert_not_called()
 def test_expired_no_sampling(self):
  a=DesktopAdapter.__new__(DesktopAdapter);a.wd=Mock();a.verify_media=Mock(return_value={'ok':False})
  self.assertFalse(a.wait_media({}, {},Path('/tmp/test'),{},time.time()-1)['ok']);a.wd.screenshot_main_region.assert_not_called()

class CountTests(unittest.TestCase):
 def test_exact_card_size_and_no_prefix_match(self):
  from desktop_adapter import file_card_count
  from types import SimpleNamespace as H
  def hits(n,s):return [H(text=n,cx=700,cy=300),H(text=s,cx=660,cy=344)]
  self.assertEqual(file_card_count(hits('a.xIsx','1.0K'),'a.xlsx',1024,1000,1000),1)
  self.assertEqual(file_card_count(hits('aa.xlsx','1.0K'),'a.xlsx',1024,1000,1000),0)
  self.assertEqual(file_card_count(hits('a.xlsx','11.0K'),'a.xlsx',1024,1000,1000),0)
