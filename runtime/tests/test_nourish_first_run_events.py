import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
source=ROOT/'skills/workflows/daily-new-stores-not-nourished-ops-to-wechat/scripts/nourish_workflow.py'
if os.environ.get('NOURISH_EVENTS_TEST_ORIGINAL')=='1':
    source=ROOT/'runtime/state/nourish-first-run-events-20261028/original-workflow.py'
spec=importlib.util.spec_from_file_location('nourish_events_preflight',source)
flow=importlib.util.module_from_spec(spec);spec.loader.exec_module(flow)

class NourishEventsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.events=self.root/'events'
        stack=contextlib.ExitStack();self.addCleanup(stack.close)
        stack.enter_context(patch.object(flow,'EVENTS',self.events))
        stack.enter_context(patch.object(flow,'RUNS',self.root/'runs'))
        stack.enter_context(patch.object(flow,'arm_state',return_value={'armed':True}))
        stack.enter_context(patch.object(sys,'argv',['nourish_daily.py','--execute']))
        def collect(run):
            self.assertTrue(self.events.is_dir(),'fixed event directory missing before first collection')
            return {}
        self.collect=stack.enter_context(patch.object(flow,'collect',side_effect=collect))
        stack.enter_context(patch.object(flow,'build_report',return_value={'rows':0,'path':None}))
    def test_fresh_main_initializes_before_collect(self):
        with contextlib.redirect_stdout(io.StringIO()):flow.main()
        self.collect.assert_called_once();self.assertTrue(self.events.is_dir())
    def test_existing_markers_preserved(self):
        self.events.mkdir()
        originals={}
        for state in ('verified','unknown'):
            p=self.events/(state+'.json');p.write_text(json.dumps({'state':state,'event':'original'}));originals[p]=p.read_bytes()
        with contextlib.redirect_stdout(io.StringIO()):flow.main()
        for p,value in originals.items():self.assertEqual(p.read_bytes(),value)
    def test_invalid_directory_does_not_collect(self):
        self.events.write_text('preserved')
        with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(OSError):flow.main()
        self.collect.assert_not_called();self.assertEqual(self.events.read_text(),'preserved')
    def test_deliver_still_refuses_missing_directory(self):
        file=self.root/'report.xlsx';file.write_bytes(b'fixture-report')
        with patch.dict(sys.modules,{'wecom_adapter':None}):result=flow.deliver({'path':str(file),'rows':1},self.root,'2026-10-28')
        self.assertEqual(result['status'],'blocked');self.assertEqual(result['reason'],'canonical-nourish-ledger-unavailable')
        self.assertEqual(result['sendAttempts'],0);self.assertFalse(self.events.exists())

if __name__=='__main__':unittest.main()
