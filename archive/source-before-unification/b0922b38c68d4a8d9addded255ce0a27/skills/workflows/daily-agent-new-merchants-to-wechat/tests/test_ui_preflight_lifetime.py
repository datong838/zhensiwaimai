import argparse
import sys
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import desktop_wechat_sender as sender

class LifetimeTests(unittest.TestCase):
 def check_path(self, owner):
  request={'context':{'deadlineAt':1}}
  bridge=types.SimpleNamespace(argparse=argparse,REGISTRY={'merchants':[None,None,None,'existing']},prepare=lambda args:(request,{}))
  adapter=Mock();adapter.owner_lifetime=owner;adapter.session.return_value=nullcontext();adapter.preflight.return_value={'ok':True}
  limit=Mock(return_value=nullcontext())
  with patch.dict(sys.modules,{'workflow_bridge':bridge,'executor':types.SimpleNamespace(deadline=limit),'wecom_adapter':types.SimpleNamespace(WeComAdapter=lambda:adapter)}):
   result=sender._windows_preflight_once('电销+直播攻坚组',Path('/tmp/unused'),None,None,None)
  self.assertEqual(result,{'ok':True})
  return limit
 def test_owner_ui_does_not_apply_expired_countdown(self):
  self.check_path(True).assert_not_called()
 def test_legacy_adapter_keeps_existing_behavior(self):
  self.check_path(False).assert_called_once_with(1)
if __name__=='__main__':unittest.main()
