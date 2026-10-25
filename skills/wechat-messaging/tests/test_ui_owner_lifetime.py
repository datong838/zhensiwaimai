import sys,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import wecom_ui_queue as q
class OwnerLifetimeTests(unittest.TestCase):
 def test_expired_wall_clock_does_not_stop_live_original_owner(self):
  with tempfile.TemporaryDirectory() as td:
   original=q.atomic_json
   def write(path,value):
    original(path,value)
    if path.name=='task.json':
     self.assertIsNone(value['deadlineAt']);self.assertEqual(value['lifetime'],'owner-process')
     original(path.parent/'response.json',{'taskId':value['taskId'],'binding':value['binding'],'result':{'ok':True,'resolvedGroup':'g','inputEmpty':True}})
   with patch.object(q,'preflight_enabled',return_value=True),patch.object(q,'process_identity',return_value='stable-start'),patch.object(q,'atomic_json',side_effect=write):
    result=q.exchange('preflight',{'groupName':'g','context':{'deadlineAt':0}},queue=Path(td),owner_lifetime=True)
   self.assertTrue(result['ok'])
 def test_pid_reuse_or_exit_stops_owner(self):
  owner={'pid':1,'parentPid':2,'identity':'old','parentIdentity':'old'}
  with patch.object(q,'process_identity',return_value='new'):self.assertIs(q.owner_active(owner),False)
  with patch.object(q,'process_identity',return_value=None):self.assertIs(q.owner_active(owner),False)
 def test_probe_failure_is_not_process_exit(self):
  owner={'pid':1,'parentPid':2,'identity':'old','parentIdentity':'old'}
  with patch.object(q,'process_identity',side_effect=RuntimeError('temporary')):self.assertIsNone(q.owner_active(owner))
 def test_parent_exit_stops_orphan(self):
  owner={'pid':1,'parentPid':2,'identity':'live','parentIdentity':'parent'}
  with patch.object(q,'process_identity',side_effect=lambda pid:'live' if pid==1 else None):self.assertIs(q.owner_active(owner),False)
if __name__=='__main__':unittest.main()
