import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('decoration_errors',Path(__file__).resolve().parents[1]/'scripts/decoration_workflow.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)
class CollectorErrors(unittest.TestCase):
    def test_reason_is_not_lost_behind_long_stack(self):
        text=json.dumps({'reason':'shop-selection-not-settled:chain-domain','stack':'stack-tail'*100})
        self.assertEqual(subject.collector_failure_reason(text),'shop-selection-not-settled:chain-domain')
    def test_last_structured_error_and_fallback(self):
        self.assertEqual(subject.collector_failure_reason('{"reason":"first"}\n{"reason":"last"}'),'last')
        self.assertEqual(subject.collector_failure_reason('x'*300),'x'*250)
        self.assertEqual(subject.collector_failure_reason('[1,2]'),'[1,2]')
    def test_collect_remains_unknown_and_preserves_raw_evidence(self):
        text=json.dumps({'reason':'shop-selection-not-settled','stack':'tail'*200})
        with tempfile.TemporaryDirectory() as folder, patch.object(subject.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='',stderr=text)):
            root=Path(folder)
            with self.assertRaisesRegex(RuntimeError,'decoration-collection-unknown:shop-selection-not-settled'):subject.collect(root,'fixture')
            self.assertEqual((root/'collector.stderr.log').read_text(),text)
if __name__=='__main__':unittest.main()
