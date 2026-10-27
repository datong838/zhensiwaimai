import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import mobile_helpers as h,mobile_text as t
from mobile_adapter import MobileAdapter
class MobileTests(unittest.TestCase):
 def test_exact_group(self):
  self.assertTrue(t.exact_target_group_title('臻肆测试群(3)','臻肆测试群'))
  self.assertTrue(t.exact_target_group_title('臻肆测试群(3)C','臻肆测试群'))
  self.assertTrue(t.exact_target_group_title('臻肆测试群(3)Q>','臻肆测试群'))
  for wrong in ['臻肆测试群2','臻肆测试群备份','臻肆测试群(3)其他']:
   self.assertFalse(t.exact_target_group_title(wrong,'臻肆测试群'))
 def test_main_task_not_clone(self):
  self.assertTrue(h.is_main_wechat_foreground({'package':'com.tencent.mm'},'mResumedActivity: u0 com.tencent.mm/.ui.LauncherUI'))
  self.assertFalse(h.is_main_wechat_foreground({'package':'com.tencent.mm'},'mResumedActivity: u128 com.tencent.mm/.ui.LauncherUI'))
 def test_claim_not_reusable(self):
  with tempfile.TemporaryDirectory() as d:
   item={'_work':d,'sha256':'abc'}
   t.claim_send('测试',item)
   with self.assertRaises(FileExistsError):t.claim_send('测试',item)
 def test_failure_after_claim_is_unknown(self):
  with tempfile.TemporaryDirectory() as d:
   a=MobileAdapter('test-device');a.main=Mock(side_effect=RuntimeError('focus-lost'))
   self.assertEqual(a.send_one({}, {},Path(d),{},0)['status'],'blocked')
   (Path(d)/'attempt.json').write_text('{}')
   r=a.send_one({}, {},Path(d),{},0)
   self.assertEqual((r['status'],r['sendAttempts']),('unknown',1))

 def test_wrong_page_never_gallery(self):
  self.assertFalse(h.gallery_ready([{'text':'发红包'},{'text':'发送'}]))
  self.assertTrue(h.gallery_ready([{'text':'原图'},{'text':'预览'},{'text':'发送'}]))

 def test_outgoing_bubble_count(self):
  from PIL import Image,ImageDraw
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'frame.png';im=Image.new('RGB',(1080,2340),'white');draw=ImageDraw.Draw(im)
   draw.rectangle((300,1000,900,1120),fill=(150,235,100));im.save(p)
   self.assertEqual(t.newest_bubble(p,count=True),1)
   draw.rectangle((300,1500,900,1620),fill=(150,235,100));im.save(p)
   self.assertEqual(t.newest_bubble(p,count=True),2)
 def test_file_label_blocks_foreign_app(self):
  import mobile_files
  device=Mock();device.app_current.return_value={'package':'com.tencent.wework'}
  with self.assertRaisesRegex(ValueError,'foreground-lost'):
   mobile_files.click_label(device,Mock(),Path('/tmp/unused'),'文件','test')
  device.assert_not_called()

 def test_notification_detection(self):
  self.assertTrue(h.notification_visible([{'text':'企业微信 刚刚','y':158}]))
  self.assertFalse(h.notification_visible([{'text':'企业微信 刚刚','y':600}]))
  self.assertFalse(h.notification_visible([{'text':'臻肆测试群(3)','y':138}]))
