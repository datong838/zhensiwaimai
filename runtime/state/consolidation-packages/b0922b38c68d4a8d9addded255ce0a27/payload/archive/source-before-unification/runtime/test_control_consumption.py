import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import run_all as subject

class ControlConsumptionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'control.json'
        p=patch.object(subject,'CONTROL_FILE',self.path);p.start();self.addCleanup(p.stop)
    def write(self,value):self.path.write_text(json.dumps(value))
    def test_preserves_immediate_and_other_fields(self):
        self.write({'force_run':['a'],'reset_circuit':'a','force_run_now':['b'],'note':'keep'})
        self.assertEqual(subject.pop_forced_runs(),(['a'],'a'))
        self.assertEqual(json.loads(self.path.read_text()),{'force_run_now':['b'],'note':'keep'})
        self.assertEqual(subject.pop_force_run_now(),['b'])
        self.assertEqual(json.loads(self.path.read_text()),{'note':'keep'})
    def test_only_immediate_is_untouched(self):
        self.write({'force_run_now':['b']});before=self.path.read_bytes()
        self.assertEqual(subject.pop_forced_runs(),([],None));self.assertEqual(self.path.read_bytes(),before)
    def test_consumes_once(self):
        self.write({'force_run':'a'})
        self.assertEqual(subject.pop_forced_runs(),(['a'],None));self.assertFalse(self.path.exists())
        self.assertEqual(subject.pop_forced_runs(),([],None))
    def test_bad_json_is_preserved(self):
        self.path.write_text('{')
        self.assertEqual(subject.pop_forced_runs(),([],None));self.assertEqual(self.path.read_text(),'{')
    def test_write_failure_does_not_dispatch(self):
        self.write({'force_run':['a'],'force_run_now':['b']})
        with patch.object(Path,'replace',side_effect=OSError('denied')):
            self.assertEqual(subject.pop_forced_runs(),([],None))
        self.assertEqual(json.loads(self.path.read_text())['force_run'],['a'])

if __name__=='__main__':unittest.main()
