import sys, unittest, copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wecom_ui_queue import enabled, validate_response
class QueueTests(unittest.TestCase):
 def setUp(self):
  self.task={'taskId':'one','binding':'bound','stage':'send','request':{'groupName':'target'},'item':{'sha256':'abc','type':'image'}}
  self.result={'status':'verified','sendAttempts':1,'resolvedGroup':'target','sha256':'abc','observations':[{'groupName':'target','inputEmpty':True,'newMessageVisible':True} for _ in range(2)]}
 def reply(self,result=None): return {'taskId':'one','binding':'bound','result':result or self.result}
 def test_valid(self): self.assertEqual(validate_response(self.task,self.reply())['verificationLevel'],'wecom-ui-tree-image')
 def test_wrong_binding(self):
  for key in ['taskId','binding']:
   r=self.reply();r[key]='wrong'
   with self.assertRaises(ValueError):validate_response(self.task,r)
 def test_bad_evidence(self):
  for change in [{'sendAttempts':2},{'sha256':'bad'},{'resolvedGroup':'other'},{'observations':[]},{'observations':[{'groupName':'target','inputEmpty':False,'newMessageVisible':True}]*2}]:
   with self.assertRaises(ValueError):validate_response(self.task,self.reply(self.result|change))
 def test_preflight(self):
  task=self.task|{'stage':'preflight'}
  self.assertTrue(validate_response(task,self.reply({'ok':True,'resolvedGroup':'target','inputEmpty':True}))['ok'])
  with self.assertRaises(ValueError):validate_response(task,self.reply({'ok':True,'resolvedGroup':'target','inputEmpty':False}))
 def test_scope(self):
  self.assertTrue(enabled({'context':{'workflowId':'negative-reviews-summary'}}))
  self.assertFalse(enabled({'context':{'workflowId':'merchants'}}))
class EmptyNoticeQueueTests(unittest.TestCase):
 def test_only_fixed_empty_notice_is_enabled(self):
  r={'groupName':'电销+直播攻坚组','context':{'workflowId':'merchants','eventId':'/state/empty-202610241400.json'},'items':[{'type':'text','text':'当前无新增意向商家'}]}
  self.assertTrue(enabled(r))
  self.assertFalse(enabled(r|{'groupName':'其他群'}))
  self.assertFalse(enabled(r|{'items':[{'type':'text','text':'商家信息'}]}))
  self.assertFalse(enabled(r|{'context':{'workflowId':'merchants','eventId':'merchant.json'}}))
 def test_text_requires_exact_two_frame_hash(self):
  task={'taskId':'a','binding':'b','stage':'send','request':{'groupName':'g'},'item':{'type':'text','sha256':'hash'}}
  result={'resolvedGroup':'g','status':'verified','sendAttempts':1,'sha256':'hash','observations':[{'groupName':'g','inputEmpty':True,'newMessageVisible':True,'visibleTextSha256':'hash'}]*2}
  reply={'taskId':'a','binding':'b','result':result};self.assertEqual(validate_response(task,reply)['verificationLevel'],'wecom-ui-tree-text')
  result['observations']=[{'groupName':'g','inputEmpty':True,'newMessageVisible':True}]*2
  with self.assertRaises(ValueError):validate_response(task,reply)
class AdapterTests(unittest.TestCase):
 def test_ui_preflight_uses_queue_only(self):
  from unittest.mock import patch
  from wecom_adapter import WeComAdapter
  request={'groupName':'target','context':{'workflowId':'negative-reviews-summary'}}
  with patch('wecom_ui_queue.exchange',return_value={'ok':True,'resolvedGroup':'target','inputEmpty':True}) as queued, patch.object(WeComAdapter,'_run_sender',side_effect=AssertionError('legacy sender invoked')):
   self.assertTrue(WeComAdapter().preflight(request,'unused')['ok']);queued.assert_called_once()
if __name__=='__main__':unittest.main()
