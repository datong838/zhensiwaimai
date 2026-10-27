import hashlib,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import native_ui_post as post
class NativePostTests(unittest.TestCase):
 def test_final_submit_binds_exact_group_and_draft(self):
  action=post.composer_submit_action('完整目标群','完整正文')
  self.assertEqual(action['key'],'return');self.assertEqual(action['expected']['value'],'完整正文')
  self.assertEqual(action['guards'][0]['expected']['value'],'完整目标群')
  self.assertEqual(action['expected']['role'],'AXTextArea')
 def test_final_context_rejection_records_zero_without_a_second_submit(self):
  with tempfile.TemporaryDirectory() as d:
   p,t=self.task(Path(d));calls=[]
   def ui(actions=(),**kw):
    calls.extend(actions)
    if any(a.get('guards') for a in actions):raise post.NativeUIActionRejected('changed-after-paste')
    return {'nodes':[]}
   def anchor(n):return {},{'value':'电销+直播攻坚组' if n=='conversationTitle' else ''}
   with patch.object(post,'QUEUE',Path(d)),patch.object(post,'owner_active',return_value=True),patch.object(post,'read_anchor',side_effect=anchor),patch.object(post,'message_rows',return_value=[]),patch.object(post,'execute',side_effect=ui),patch.object(post.subprocess,'run'),patch.object(post,'validate_response'),patch.object(post.time,'sleep'):
    r=post.send_text(p)
   self.assertEqual(r['result']['sendAttempts'],0);self.assertEqual(r['result']['status'],'blocked')
   self.assertEqual(sum(a.get('key')=='return' for a in calls),1)
   self.assertTrue((p/'send-intent.json').exists())
 def test_preflight_reuses_exact_group_result_without_second_precheck(self):
  with tempfile.TemporaryDirectory() as d:
   p,t=self.task(Path(d));t['stage']='preflight';t.pop('binding');t['binding']=post.text_hash(json.dumps(t,sort_keys=True,ensure_ascii=False));(p/'task.json').write_text(json.dumps(t))
   with patch.object(post,'QUEUE',Path(d)),patch.object(post,'owner_active',return_value=True),patch.object(post,'ensure_group',return_value='电销+直播攻坚组') as locate,patch.object(post,'read_anchor',side_effect=AssertionError('repeated-precheck')):
    result=post.preflight(p)
   locate.assert_called_once();self.assertTrue(result['result']['ok'])
 def test_same_group_preflight_does_not_navigate(self):
  with patch.object(post,'read_anchor',side_effect=[({}, {'value':'群'}),({}, {'value':''})]),patch.object(post,'execute') as ui:
   self.assertEqual(post.ensure_group('群'),'群');ui.assert_not_called()
 def test_existing_draft_prevents_any_group_switch(self):
  with patch.object(post,'read_anchor',side_effect=[({}, {'value':'旧群'}),({}, {'value':'草稿'})]),patch.object(post,'execute') as ui:
   with self.assertRaisesRegex(RuntimeError,'do-not-overwrite'):post.ensure_group('新群')
   ui.assert_not_called()
 def test_search_batches_exact_control_focus_paste_and_guarded_return(self):
  def named(kind,name,**extra):return {'type':kind,'path':[1],'expected':{'role':'AXTextField'},**extra}
  with patch.object(post,'read_anchor',side_effect=[({}, {'value':'旧群'}),({}, {'value':''}),({}, {'value':''}),({}, {'value':'新群'}),({}, {'value':''})]),patch.object(post,'named_action',side_effect=named),patch.object(post,'execute') as ui,patch.object(post.subprocess,'run'):
   self.assertEqual(post.ensure_group('新群'),'新群')
  actions=ui.call_args_list[-1].args[0]
  self.assertEqual([a['type'] for a in actions],['click','key','paste','key'])
  self.assertEqual(actions[-1]['key'],'return');self.assertEqual(actions[-1]['expected']['value'],'新群')
 def test_readback_dispatch_never_sends(self):
  with tempfile.TemporaryDirectory() as d:
   p,t=self.task(Path(d));t['stage']='readback';t.pop('binding');t['binding']=post.text_hash(json.dumps(t,sort_keys=True,ensure_ascii=False));(p/'task.json').write_text(json.dumps(t))
   with patch.object(post,'QUEUE',Path(d)),patch.object(post,'execute') as ui,patch.object(post,'send_text') as send:
    r=post.dispatch(p)
   self.assertEqual(r['result']['sendAttempts'],0);self.assertIn('unsupported',r['result']['reason']);ui.assert_not_called();send.assert_not_called()
 def test_latest_text_reads_real_new_row_and_normalizes_phone(self):
  actual='联系：[123456](tel:123456)';t={'item':{'sha256':post.text_hash('联系：123456')},'request':{'groupName':'群'}}
  with patch.object(post,'message_rows',return_value=[[0],[1]]),patch.object(post,'execute',return_value={'nodes':[{'role':'AXTextArea','value':actual}]}),patch.object(post,'read_anchors',return_value=({}, {'conversationTitle':{'value':'群'},'composer':{'value':''}})):
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
  with patch.object(post,'message_rows',return_value=[[0],[1]]),patch.object(post,'execute',return_value={'nodes':[{'role':'AXUnknown'}]}),patch.object(post,'read_anchors',return_value=({}, {'conversationTitle':{'value':'群'},'composer':{'value':''}})):
   with self.assertRaisesRegex(RuntimeError,'image-not-exposed'):post.media_observation(t,1)
 def test_old_media_row_cannot_prove_new_delivery(self):
  with patch.object(post,'message_rows',return_value=[[0]]),patch.object(post,'execute') as ui:
   with self.assertRaisesRegex(RuntimeError,'no-new-message-row'):post.media_observation({},1)
   ui.assert_not_called()
 def observe_image(self,nodes,group='群',draft=''):
  task={'item':{'type':'image'},'request':{'groupName':'群'}}
  with patch.object(post,'message_rows',return_value=[[0],[1]]),patch.object(post,'execute',return_value={'nodes':nodes}),patch.object(post,'read_anchors',return_value=({}, {'conversationTitle':{'value':group},'composer':{'value':draft}})):
   return post.media_observation(task,1)
 def test_meeting_card_icon_is_not_inline_image_proof(self):
  nodes=[{'role':'AXImage','description':None},{'role':'AXTextArea','value':'会议主题'},
         {'role':'AXTextArea','value':'会议时间与会议号'},{'role':'AXStaticText','value':'腾讯会议'}]
  with self.assertRaisesRegex(RuntimeError,'image-not-exposed'):self.observe_image(nodes)
 def test_file_card_without_icon_description_is_not_inline_image_proof(self):
  with self.assertRaisesRegex(RuntimeError,'image-not-exposed'):
   self.observe_image([{'role':'AXImage'},{'role':'AXTextArea','value':'report.png'}])
 def test_existing_pure_image_structure_remains_accepted(self):
  result=self.observe_image([{'role':'AXButton','name':'发送者'},
                            {'role':'AXStaticText','value':'上午 9:00'},
                            {'role':'AXImage','description':None}])
  self.assertEqual(result['presentation'],'inline-image')
 def test_pure_image_still_rejects_wrong_group_and_existing_draft(self):
  for group,draft in [('其他群',''),('群','未发送内容')]:
   with self.subTest(group=group,draft=draft),self.assertRaisesRegex(RuntimeError,'target-or-draft-mismatch'):
    self.observe_image([{'role':'AXImage'}],group,draft)
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
 def test_typing_arrives_after_focus_does_not_paste_or_send(self):
  with tempfile.TemporaryDirectory() as d:
   p,t=self.task(Path(d));calls=[];reads={'composer':0}
   def anchor(name):
    if name=='composer':
     reads['composer']+=1;return {},{'value':'' if reads['composer']==1 else 'user typing'}
    return {},{'value':'电销+直播攻坚组'}
   def ui(actions=(),**kw):calls.extend(actions);return {'nodes':[]}
   with patch.object(post,'QUEUE',Path(d)),patch.object(post,'owner_active',return_value=True),patch.object(post,'read_anchor',side_effect=anchor),patch.object(post,'message_rows',return_value=[]),patch.object(post,'execute',side_effect=ui),patch.object(post.subprocess,'run') as clipboard,patch.object(post,'validate_response'),patch.object(post.time,'sleep'):
    r=post.send_text(p)
   self.assertEqual(r['result']['sendAttempts'],0);self.assertEqual(r['result']['status'],'blocked');clipboard.assert_not_called();self.assertFalse(any(a['type']=='paste' or a.get('key')=='return' for a in calls))
if __name__=='__main__':unittest.main()
