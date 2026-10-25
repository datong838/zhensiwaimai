import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import native_ui_post as post
class NativePostTests(unittest.TestCase):
 def test_same_group_preflight_does_not_navigate(self):
  with patch.object(post,'read_anchor',side_effect=[({}, {'value':'群'}),({}, {'value':''})]),patch.object(post,'execute') as ui:
   self.assertEqual(post.ensure_group('群'),'群');ui.assert_not_called()
 def test_existing_draft_prevents_any_group_switch(self):
  with patch.object(post,'read_anchor',side_effect=[({}, {'value':'旧群'}),({}, {'value':'草稿'})]),patch.object(post,'execute') as ui:
   with self.assertRaisesRegex(RuntimeError,'do-not-overwrite'):post.ensure_group('新群')
   ui.assert_not_called()
 def test_readback_dispatch_never_sends(self):
  with tempfile.TemporaryDirectory() as d:
   p,t=self.task(Path(d));t['stage']='readback';t.pop('binding');t['binding']=post.text_hash(json.dumps(t,sort_keys=True,ensure_ascii=False));(p/'task.json').write_text(json.dumps(t))
   with patch.object(post,'QUEUE',Path(d)),patch.object(post,'execute') as ui,patch.object(post,'send_text') as send:
    r=post.dispatch(p)
   self.assertEqual(r['result']['sendAttempts'],0);self.assertIn('unsupported',r['result']['reason']);ui.assert_not_called();send.assert_not_called()
 def test_latest_text_reads_real_new_row_and_normalizes_phone(self):
  actual='联系：[123456](tel:123456)';t={'item':{'sha256':post.text_hash('联系：123456')},'request':{'groupName':'群'}}
  with patch.object(post,'message_rows',return_value=[[0],[1]]),patch.object(post,'execute',return_value={'nodes':[{'role':'AXTextArea','value':actual}]}),patch.object(post,'read_anchor',side_effect=[({}, {'value':'群'}),({}, {'value':''})]):
   r=post.latest_text_observation(t,1)
  self.assertEqual(r['visibleText'],'联系：123456');self.assertEqual(r['messagePath'],[1])
 def test_latest_text_rejects_old_row(self):
  with patch.object(post,'message_rows',return_value=[[0]]),patch.object(post,'execute') as ui:
   with self.assertRaisesRegex(RuntimeError,'no-new-message-row'):post.latest_text_observation({},1)
   ui.assert_not_called()
 def test_media_existing_intent_is_readback_only(self):
  with tempfile.TemporaryDirectory() as d:
   p,t=self.task(Path(d));t['item']={'type':'image'};t.pop('binding');t['binding']=post.text_hash(json.dumps(t,sort_keys=True,ensure_ascii=False));(p/'task.json').write_text(json.dumps(t));(p/'send-intent.json').write_text('{}')
   with patch.object(post,'QUEUE',Path(d)),patch.object(post,'execute') as ui:
    with self.assertRaisesRegex(ValueError,'readback-only'):post.send_media(p)
    ui.assert_not_called()
 def test_image_without_real_image_role_is_not_verified(self):
  t={'item':{'type':'image'},'request':{'groupName':'群'}}
  with patch.object(post,'message_rows',return_value=[[0],[1]]),patch.object(post,'execute',return_value={'nodes':[{'role':'AXUnknown'}]}),patch.object(post,'read_anchor',side_effect=[({}, {'value':'群'}),({}, {'value':''})]):
   with self.assertRaisesRegex(RuntimeError,'image-not-exposed'):post.media_observation(t,1)
 def test_old_media_row_cannot_prove_new_delivery(self):
  with patch.object(post,'message_rows',return_value=[[0]]),patch.object(post,'execute') as ui:
   with self.assertRaisesRegex(RuntimeError,'no-new-message-row'):post.media_observation({},1)
   ui.assert_not_called()
 def task(self,root):
  p=root/'task';p.mkdir();text='当前无新增意向商家';t={'taskId':'task','stage':'send','request':{'groupName':'电销+直播攻坚组'},'item':{'type':'text','text':text,'sha256':post.text_hash(text)},'lifetime':'owner-process','owner':{}};t['binding']=post.text_hash(json.dumps(t,sort_keys=True,ensure_ascii=False));(p/'task.json').write_text(json.dumps(t));return p,t
 def test_existing_intent_never_calls_ui(self):
  with tempfile.TemporaryDirectory() as d:
   p,t=self.task(Path(d));(p/'send-intent.json').write_text('{}')
   with patch.object(post,'QUEUE',Path(d)),patch.object(post,'read_anchor') as ui:
    with self.assertRaisesRegex(ValueError,'existing-intent'):post.send_text(p)
    ui.assert_not_called()
 def test_stale_history_is_not_delivery(self):
  with patch.object(post,'read_anchor',side_effect=[({}, {'value':'群'}),({}, {'value':''})]),patch.object(post,'matching_texts',return_value=['旧消息']):
   with self.assertRaisesRegex(RuntimeError,'not-confirmed'):post.message_observation({'request':{'groupName':'群'}},1)
 def test_focus_failure_records_zero_and_never_return(self):
  with tempfile.TemporaryDirectory() as d:
   p,t=self.task(Path(d));calls=[]
   def ui(actions=(),**kw):
    calls.extend(actions)
    if any(a['type']=='paste' for a in actions):raise RuntimeError('native-ui-focus-mismatch')
    return {'nodes':[]}
   def anchor(n):return {},{'value':'电销+直播攻坚组' if n=='conversationTitle' else ''}
   with patch.object(post,'QUEUE',Path(d)),patch.object(post,'owner_active',return_value=True),patch.object(post,'read_anchor',side_effect=anchor),patch.object(post,'message_rows',return_value=[]),patch.object(post,'execute',side_effect=ui),patch.object(post.subprocess,'run'),patch.object(post,'validate_response'),patch.object(post.time,'sleep'):
    r=post.send_text(p)
   self.assertEqual(r['result']['sendAttempts'],0);self.assertEqual(r['result']['status'],'blocked');self.assertTrue((p/'send-intent.json').exists());self.assertFalse(any(a.get('key')=='return' for a in calls))
if __name__=='__main__':unittest.main()
