import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

REPO=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('scoped_top10_maintenance',REPO/'runtime/maintain_top10_home_recovery_20261028.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class MaintenanceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);self.e=self.root/'evidence';(self.e/'originals').mkdir(parents=True);(self.e/'candidates').mkdir()
  self.originals={}
  for name in ['runtime/maintain_top10_home_recovery_20261028.py','runtime/tests/top10_home_recovery.test.mjs','runtime/tests/test_top10_home_recovery_maintenance.py']:
   p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((REPO/name).read_bytes())
  for role,(base,source,label,*_) in m.SPECS.items():
   src=self.root/base/source;src.parent.mkdir(parents=True,exist_ok=True);src.write_text('original-'+role)
   policy=self.root/base/'runtime-policy.json';entry={'path':str(src),'sha256':m.sha(src.read_bytes())} if role=='taobao' else m.sha(src.read_bytes())
   policy.write_text(json.dumps({'files':{label:entry},'authorization':'unchanged','port':9230 if role=='taobao' else 9233,'nested':{'metadata':'unchanged'}}))
   for p,name in [(src,role+'.mjs'),(policy,role+'-policy.json')]:
    (self.e/'originals'/name).write_bytes(p.read_bytes());self.originals[str(p.relative_to(self.root))]=p.read_bytes()
   (self.e/'candidates'/(role+'.mjs')).write_text('candidate-'+role)
  for key,value in [('ROOT',self.root),('EVIDENCE',self.e)]:
   p=patch.object(m,key,value);p.start();self.addCleanup(p.stop)
  p=patch.object(m,'original_bytes',side_effect=lambda relative:self.originals[relative]);p.start();self.addCleanup(p.stop)
  self.idle=patch.object(m,'assert_idle');self.idle.start();self.addCleanup(self.idle.stop)
  p=patch.object(m,'acquire_groups');p.start();self.addCleanup(p.stop)
  self.gates=patch.object(m,'run_gates',return_value={'originalGates':True});self.gate_mock=self.gates.start();self.addCleanup(self.gates.stop)
 def ready(self):
  m.prepare();m.write(self.e/'tests.json',{'passed':True,'binding':m.candidate_binding()})
 def assert_originals(self):
  for relative,data in self.originals.items():self.assertEqual((self.root/relative).read_bytes(),data)
 def test_prepare_rejects_source_drift(self):
  source,_=m.paths('taobao');source.write_text('different')
  with self.assertRaisesRegex(ValueError,'original-drift'):m.prepare()
 def test_prepare_rejects_unrelated_policy_change(self):
  _,policy=m.paths('meituan');v=m.read(policy);v['authorization']='different';m.write(policy,v)
  with self.assertRaisesRegex(ValueError,'original-drift'):m.prepare()
 def test_untested_candidate_rejected(self):
  self.ready();(self.e/'candidates/taobao.mjs').write_text('changed')
  with self.assertRaisesRegex(ValueError,'untested-candidate'):m.apply_reviewed()
  self.assert_originals()
 def test_stale_review_rejected(self):
  self.ready();v=m.read(self.e/'review.json');v['scope']['taobao']['candidate']='wrong';m.write(self.e/'review.json',v)
  with self.assertRaisesRegex(ValueError,'stale-review'):m.apply_reviewed()
  self.assert_originals()
 def test_live_steps_refuse_install(self):
  self.ready()
  with patch.object(m,'assert_idle',side_effect=ValueError('live-steps-busy')):
   with self.assertRaisesRegex(ValueError,'live-steps-busy'):m.apply_reviewed()
  self.assert_originals()
 def test_foreign_group_refuses_install(self):
  self.ready()
  with patch.object(m,'acquire_groups',side_effect=ValueError('original-group-busy')):
   with self.assertRaisesRegex(ValueError,'original-group-busy'):m.apply_reviewed()
  self.assert_originals()
 def test_failed_original_gate_restores_exact_four_originals(self):
  self.ready();self.gate_mock.side_effect=ValueError('original-runtime-gate-failed')
  with self.assertRaisesRegex(ValueError,'original-runtime-gate-failed'):m.apply_reviewed()
  self.assert_originals();self.assertEqual(m.read(self.e/'rollback.json')['unmatched'],[])
 def test_success_changes_only_two_sources_and_existing_pins(self):
  self.ready();result=m.apply_reviewed();self.assertTrue(result['installed']);self.assertEqual(len(result['changes']),4)
  for role in m.SPECS:
   src,policy=m.paths(role);self.assertEqual(src.read_bytes(),(self.e/'candidates'/(role+'.mjs')).read_bytes())
   value=m.read(policy);old=json.loads(self.originals[str(policy.relative_to(self.root))])
   self.assertEqual(set(value['files']),set(old['files']));self.assertEqual(m.pin(value,role),m.sha(src.read_bytes()))
   self.assertEqual({k:v for k,v in value.items() if k!='files'},{k:v for k,v in old.items() if k!='files'})

if __name__=='__main__':unittest.main()
