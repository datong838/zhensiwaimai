import sys,unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from workflow_executor import empty_notice_arguments
GROUP='电销+直播攻坚组'
class EmptyNoticeTests(unittest.TestCase):
 def args(self,t,**changes):
  c={'ok':True,'businessDate':'2026-10-24','messages':[]};c.update(changes)
  return empty_notice_arguments(c,GROUP,datetime.fromisoformat('2026-10-24T'+t).replace(tzinfo=ZoneInfo('Asia/Shanghai')))
 def test_slot_identity(self):
  a=self.args('08:30:00');b=self.args('08:59:59');c=self.args('09:00:00')
  self.assertEqual(a,b);self.assertNotEqual(a,c);self.assertIn('empty-202610240830.json',a);self.assertIn('当前无新增意向商家',a)
 def test_business_hours(self):
  for t in ['08:29:59','19:00:00','23:00:00']:
   with self.assertRaisesRegex(RuntimeError,'outside-business-hours'):self.args(t)
  self.assertIn('empty-202610241830.json',self.args('18:59:59'))
 def test_failure_and_nonempty_are_not_empty(self):
  for changes in [{'ok':False},{'messages':[{'merchantId':'1'}]},{'businessDate':'2026-10-23'}]:
   with self.assertRaises(RuntimeError):self.args('10:00:00',**changes)
if __name__=='__main__':unittest.main()
