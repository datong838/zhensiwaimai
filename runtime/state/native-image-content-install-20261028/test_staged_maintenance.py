import datetime,hashlib,importlib.util,json,pathlib,tempfile,unittest
from unittest.mock import Mock
BASE=pathlib.Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('staged_copy_maintenance',BASE/'stage/scripts/dependency_maintenance.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
AUTH='user-20261028-native-image-content-copy'
class Tests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=pathlib.Path(self.temp.name)
  keys=[M.SELF_KEY,M.HEARTBEAT_RECOVERY_KEY,M.DESKTOP_ADAPTER_KEY,M.POLICY_REGISTRATION_KEY,M.EGRESS_POLICY_KEY]
  files={}
  for key in keys:
   p=self.root/key;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('original-fixture');files[key]=M.sha256(p)
  for key,digest in M.MAINTENANCE_AUTHORIZATIONS[AUTH]['allowedAfterSha256'].items():
   p=self.root/key;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((BASE/'stage'/key).read_bytes());self.assertEqual(M.sha256(p),digest)
  self.manifest=self.root/'dependencies.json';self.manifest.write_text(json.dumps({'schemaVersion':1,'files':files}));self.before=self.manifest.read_bytes()
  self.command=Mock(return_value={'ok':True,'testCount':459})
 def prepare(self):
  return M.prepare(AUTH,(datetime.datetime.now().astimezone()+datetime.timedelta(hours=1)).isoformat(),self.root/'result',manifest_path=self.manifest,root=self.root,run_command=self.command)
 def test_exact_new_files_registered_only_by_original_maintenance(self):
  result=self.prepare();self.assertTrue(result['ok'],result);self.assertEqual(result['sendAttempts'],0)
  self.assertEqual({c['path'] for c in result['changes']},set(M.MAINTENANCE_AUTHORIZATIONS[AUTH]['allowedAfterSha256']))
  self.assertEqual(M.inspect(self.manifest,self.root)['status'],'clean')
 def test_modified_candidate_rejected_before_tests_or_write(self):
  (self.root/'scripts/native_image_content.py').write_text('tampered')
  result=self.prepare();self.assertFalse(result['ok']);self.assertIn('unreviewed',str(result));self.command.assert_not_called();self.assertEqual(self.manifest.read_bytes(),self.before)
 def test_unrelated_registered_drift_rejected(self):
  (self.root/M.EGRESS_POLICY_KEY).write_text('unrelated drift')
  result=self.prepare();self.assertFalse(result['ok']);self.command.assert_not_called();self.assertEqual(self.manifest.read_bytes(),self.before)
 def test_ordinary_inspect_does_not_silently_register_new_modules(self):
  _,manifest=M._read_manifest(self.manifest);candidate,changes=M._candidate(manifest,self.root)
  self.assertNotIn('scripts/native_image_content.py',candidate['files']);self.assertEqual(changes,[])
if __name__=='__main__':unittest.main(verbosity=2)
