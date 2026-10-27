import unittest,sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import wecom_desktop_sender as s
class TargetWrite(unittest.TestCase):
 def test_wrong_group_has_no_input_or_cleanup(self):
  with patch.object(s,'current_conversation_title',return_value='运营群'),patch.object(s,'press_key') as keys,patch.object(s,'type_text') as typing,patch.object(s,'locate_input_box') as locate:
   ok,reason=s.write_input('商家通知',expected_group='电销+直播攻坚组')
  self.assertFalse(ok);self.assertEqual(reason,'wrong-conversation-before-write');keys.assert_not_called();typing.assert_not_called();locate.assert_not_called()
 def test_target_changes_after_focus_no_typing(self):
  box={'el':'input','pos':(0,600),'size':(800,100)}
  with patch.object(s,'current_conversation_title',side_effect=['电销+直播攻坚组','运营群']),patch.object(s,'wecom_is_frontmost',return_value=True),patch.object(s,'locate_input_box',return_value=box),patch.object(s,'click_checked'),patch.object(s,'assert_focus_on',return_value=True),patch.object(s.time,'sleep'),patch.object(s,'press_key') as keys,patch.object(s,'type_text') as typing:
   ok,reason=s.write_input('商家通知',expected_group='电销+直播攻坚组')
  self.assertFalse(ok);self.assertEqual(reason,'wrong-conversation-before-type');keys.assert_not_called();typing.assert_not_called()
if __name__=='__main__':unittest.main()
