import unittest,tempfile,sys,io,json
from pathlib import Path
from unittest.mock import patch
from contextlib import redirect_stdout
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import wecom_desktop_sender as s
class UITreePolicy(unittest.TestCase):
 def test_policy_scope(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'policy';self.assertFalse(s.ui_tree_only_blocks('send',p));p.write_text('{}')
   for cmd in ['send','send-file','send-image']:self.assertTrue(s.ui_tree_only_blocks(cmd,p))
   for cmd in ['frontmost','verify','verify-file','locate','calibrate']:self.assertFalse(s.ui_tree_only_blocks(cmd,p))
 def test_main_blocks_before_ui_even_dryrun(self):
  for cmd in ['send','send-file','send-image']:
   with patch.object(sys,'argv',['sender',cmd,'--dry-run']),patch.object(s,'ui_tree_only_blocks',return_value=True),patch.object(s,'activate_wecom') as activate,patch.object(s,'cmd_send') as send,patch.object(s,'cmd_send_media') as media,redirect_stdout(io.StringIO()) as out:
    self.assertEqual(s.main(),2)
   self.assertEqual(json.loads(out.getvalue())['sendAttempts'],0);activate.assert_not_called();send.assert_not_called();media.assert_not_called()
 def test_adapter_preflight_stops_before_activation(self):
  from wecom_adapter import WeComAdapter
  with tempfile.TemporaryDirectory() as t,patch.object(WeComAdapter,'_run_sender',side_effect=AssertionError('no UI subprocess')):
   out=Path(t)/'uncreated';result=WeComAdapter().preflight({'groupName':'电销+直播攻坚组'},out)
   self.assertEqual(result['sendAttempts'],0);self.assertEqual(result['reason'],'ui-tree-only-required');self.assertFalse(out.exists())
if __name__=='__main__':unittest.main()

class PortablePolicyTests(unittest.TestCase):
 def test_static_policy_without_runtime_flag(self):
  import wecom_adapter as adapter
  with tempfile.TemporaryDirectory() as t,patch.object(adapter,'ROOT',Path(t)):
   self.assertFalse(adapter.ui_tree_only_required())
   p=Path(t)/'skills/wechat-messaging/config/ui-execution-policy.json';p.parent.mkdir(parents=True);p.write_text('{}')
   self.assertTrue(adapter.ui_tree_only_required())
   with patch.object(adapter.WeComAdapter,'_run_sender',side_effect=AssertionError('no injected UI')):
    result=adapter.WeComAdapter().preflight({'groupName':'g'},Path(t)/'out')
    self.assertEqual(result['sendAttempts'],0)
