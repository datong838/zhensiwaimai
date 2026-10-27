import sys,unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import desktop_input as d
class NativeWindows(unittest.TestCase):
 def test_nsarray_proxy_identity_stays_stable_after_materialization(self):
  class Window:
   def __init__(self,title,w,h):self.title=title;self.size=NS(width=w,height=h)
  class NSArray:
   def __iter__(self):return iter([Window('微信',1120,636),Window('图片和视频',300,200)])
  def attr(e,k,_):
   if k=='AXWindows':return 0,NSArray()
   if k=='AXTitle':return 0,e.title
   if k=='AXSize':return 0,e.size
   return 0,None
  ax=NS(AXUIElementCreateApplication=lambda _: 'app',AXUIElementCopyAttributeValue=attr,
    AXValueGetValue=lambda raw,*_: (True,raw),kAXValueCGSizeType=1,
    AXUIElementSetMessagingTimeout=Mock(return_value=0),kAXErrorSuccess=0,
    AXUIElementSetAttributeValue=Mock(),AXUIElementPerformAction=Mock())
  running=Mock()
  with patch.dict(sys.modules,{'AppKit':NS(NSApplicationActivateIgnoringOtherApps=1),'ApplicationServices':ax}),patch.object(d,'running_app',return_value=running),patch.object(d.time,'sleep'):
   d.activate_wechat()
  ax.AXUIElementPerformAction.assert_called_once()
  self.assertTrue(all(call.args[1]==d.AX_MESSAGE_TIMEOUT_SECONDS for call in ax.AXUIElementSetMessagingTimeout.call_args_list))

 def test_multiple_main_sized_windows_use_unique_native_ax_main(self):
  class Window:
   def __init__(self,title,w,h,main):self.title=title;self.size=NS(width=w,height=h);self.main=main
  selected=Window('微信',1120,636,True);inactive=Window('微信',1120,636,False)
  class NSArray:
   def __iter__(self):return iter([inactive,selected])
  def attr(e,k,_):
   if k=='AXWindows':return 0,NSArray()
   if k=='AXTitle':return 0,e.title
   if k=='AXSize':return 0,e.size
   if k=='AXMain':return 0,e.main
   return 0,None
  perform=Mock()
  ax=NS(AXUIElementCreateApplication=lambda _: 'app',AXUIElementCopyAttributeValue=attr,
    AXValueGetValue=lambda raw,*_: (True,raw),kAXValueCGSizeType=1,
    AXUIElementSetMessagingTimeout=Mock(return_value=0),kAXErrorSuccess=0,
    AXUIElementSetAttributeValue=Mock(),AXUIElementPerformAction=perform)
  running=Mock()
  with patch.dict(sys.modules,{'AppKit':NS(NSApplicationActivateIgnoringOtherApps=1),'ApplicationServices':ax}),patch.object(d,'running_app',return_value=running),patch.object(d.time,'sleep'):
   d.activate_wechat()
  self.assertIs(perform.call_args.args[0],selected)

if __name__=='__main__':unittest.main()
