import sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import desktop_wechat_sender as d
class ScrollRaise(unittest.TestCase):
 def test_raise_precedes_scroll(self):
  events=[];control=Mock();control.activate_wechat.side_effect=lambda:events.append('raise')
  def run(*args,**kw):
   events.append('scroll');return Mock(returncode=0,stdout='{"ok":true}')
  with patch.object(d,'_load_desktop_control',return_value=control),patch.object(d.subprocess,'run',side_effect=run),patch.object(d.time,'sleep'):
   self.assertTrue(d._scroll_latest_messages()['ok'])
  self.assertEqual(events,['raise','scroll'])
 def test_failed_raise_cannot_scroll(self):
  control=Mock();control.activate_wechat.side_effect=RuntimeError('main-window-not-unique')
  with patch.object(d,'_load_desktop_control',return_value=control),patch.object(d.subprocess,'run') as run:
   with self.assertRaisesRegex(RuntimeError,'main-window-not-unique'):d._scroll_latest_messages()
   run.assert_not_called()

class AxPruning(unittest.TestCase):
 def test_message_subtree_never_read(self):
  import types,json
  app=Mock();app.processIdentifier.return_value=1
  fake_appkit=types.SimpleNamespace(NSRunningApplication=types.SimpleNamespace(runningApplicationsWithBundleIdentifier_=lambda _: [app]))
  attrs={('app','windows'):['main'],('main','title'):'微信',('main','children'):['header','messages','composer'],('header','role'):'AXStaticText',('header','value'):'group',('messages','role'):'AXList',('messages','title'):'消息',('composer','role'):'AXTextArea',('composer','value'):'',('composer','size'):'size'}
  calls=[]
  def read(node,key,_):
   calls.append((node,key));return 0,attrs.get((node,key))
  fake_as=types.SimpleNamespace(AXUIElementCreateApplication=lambda _: 'app',AXUIElementCopyAttributeValue=read,AXValueGetValue=lambda *a:(True,types.SimpleNamespace(width=700,height=100)),kAXWindowsAttribute='windows',kAXTitleAttribute='title',kAXRoleAttribute='role',kAXValueAttribute='value',kAXSizeAttribute='size',kAXChildrenAttribute='children',kAXValueCGSizeType='sizekind')
  def run(argv,**kwargs):
   from contextlib import redirect_stdout
   from io import StringIO
   output=StringIO()
   with patch.dict(sys.modules,{'AppKit':fake_appkit,'ApplicationServices':fake_as}),patch.object(sys,'argv',['-c','group']),redirect_stdout(output):exec(argv[2],{})
   return Mock(returncode=0,stdout=output.getvalue())
  with patch.object(d.subprocess,'run',side_effect=run):self.assertTrue(d._ax_chat_state('group')['ok'])
  self.assertNotIn(('messages','value'),calls);self.assertNotIn(('messages','children'),calls)

class PassiveSecondFrame(unittest.TestCase):
 def test_second_frame_never_reopens_or_scrolls_and_drift_rejected(self):
  import tempfile
  from PIL import Image
  wd=Mock();wd.open_group.return_value=Mock(ok=True)
  wd.screenshot_main_region.side_effect=lambda p:Image.new('RGB',(1120,636),'white').save(p)
  frames=[{'ok':True,'headerCount':1,'linePositions':{'0':[500,300]}},{'ok':True,'headerCount':1,'linePositions':{'0':[500,320]}}]
  with tempfile.TemporaryDirectory() as tmp,patch.object(d,'_load_desktop_control',return_value=wd),patch.object(d,'_scroll_latest_messages',return_value={'ok':True}) as scroll,patch.object(d,'_ax_chat_state',return_value={'ok':True}),patch.object(d,'_read_unique_payload_anchor',side_effect=frames),patch.object(d.subprocess,'run') as external:
   result=d._copy_exact_bubble('group',{'text':'line'},Path(tmp))
   self.assertEqual(result['reason'],'desktop-reconcile-bubble-not-stable');self.assertEqual(wd.open_group.call_count,1);self.assertEqual(scroll.call_count,4);external.assert_not_called()
