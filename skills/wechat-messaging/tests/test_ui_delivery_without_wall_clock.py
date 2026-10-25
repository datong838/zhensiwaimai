import unittest,tempfile,time
from pathlib import Path
from unittest.mock import patch
from test_runtime import sample,grant,Fake
from contract import normalize
from executor import deliver
class OwnerFake(Fake):owner_lifetime=True
class UIWithoutWallClockTests(unittest.TestCase):
 def expired(self):
  raw=sample();raw['context']['deadlineAt']=time.time()-10
  r=normalize(raw);g=grant(r);g['expiresAt']=time.time()-5
  return r,g
 def test_owner_ui_completes_despite_old_wall_clock(self):
  r,g=self.expired();a=OwnerFake()
  with tempfile.TemporaryDirectory() as td,patch('executor.deadline',side_effect=AssertionError('timer-must-not-run')):
   result=deliver(r,g,Path(td),a)
  self.assertEqual(result['status'],'verified');self.assertEqual(a.sent,['one'])
 def test_non_ui_still_enforces_existing_grant_expiry(self):
  r,g=self.expired();a=Fake()
  with tempfile.TemporaryDirectory() as td:result=deliver(r,g,Path(td),a)
  self.assertEqual(result['status'],'blocked');self.assertEqual(a.sent,[])
 def test_owner_mode_does_not_accept_wrong_group(self):
  r,g=self.expired();g['groupName']='wrong';a=OwnerFake()
  with tempfile.TemporaryDirectory() as td:result=deliver(r,g,Path(td),a)
  self.assertEqual(result['status'],'blocked');self.assertEqual(a.sent,[])
 def test_owner_mode_preserves_dedup(self):
  r,g=self.expired();a=OwnerFake()
  with tempfile.TemporaryDirectory() as td:
   deliver(r,g,Path(td),a);deliver(r,g,Path(td),a)
  self.assertEqual(a.sent,['one'])
if __name__=='__main__':unittest.main()
