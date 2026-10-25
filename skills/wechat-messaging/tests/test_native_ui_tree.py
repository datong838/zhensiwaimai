import json
import sys
import unittest
import tempfile
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import native_ui_tree as ui

class NativeTreeTests(unittest.TestCase):
    def test_only_explicit_zero_action_rejection_is_safe_to_classify_zero(self):
        output={'actionRejected':True,'results':[],'error':'changed'}
        with patch.object(ui.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(output))):
            with self.assertRaises(ui.NativeUIActionRejected):ui.execute(max_depth=0)
        output['results']=[{'type':'key','ok':True}]
        with patch.object(ui.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(output))):
            with self.assertRaises(RuntimeError) as failure:ui.execute(max_depth=0)
        self.assertNotIsInstance(failure.exception,ui.NativeUIActionRejected)

    def test_context_guard_cannot_contain_actions(self):
        action={'type':'key','key':'return','path':[0],'expected':{'role':'AXTextArea'},
                'guards':[{'type':'click','path':[0],'expected':{'role':'AXTextField'}}]}
        with patch.object(ui.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'context-guard-invalid'):ui.execute([action])
        run.assert_not_called()

    def test_batch_read_is_one_exact_read_only_call(self):
        anchors=json.loads(ui.SELECTORS.read_text())['anchors']
        names=('conversationTitle','composer')
        nodes=[dict(anchors[n]['expected'],path=anchors[n]['path'],value='') for n in names]
        with patch.object(ui,'execute',return_value={'nodes':nodes}) as run:
            _, result=ui.read_anchors(*names)
        self.assertEqual(set(result),set(names))
        run.assert_called_once_with(root_paths=[anchors[n]['path'] for n in names],max_depth=0)

    def test_batch_missing_anchor_is_not_old_proof(self):
        with patch.object(ui,'execute',return_value={'nodes':[]}),patch.object(ui,'refresh_chat_cache') as refresh:
            with self.assertRaisesRegex(RuntimeError,'anchor-changed:batch'):
                ui.read_anchors('conversationTitle','composer')
        refresh.assert_called_once()

    def test_batch_rejects_actions_and_deep_scan_before_ui(self):
        with patch.object(ui.subprocess,'run') as run:
            with self.assertRaisesRegex(ValueError,'read-only'):
                ui.execute([{'type':'activate'}],root_paths=[[0]],max_depth=0)
            with self.assertRaisesRegex(ValueError,'read-only'):
                ui.execute(root_paths=[[0]],max_depth=1)
        run.assert_not_called()

    def test_local_cache_refresh_validates_unique_container(self):
        with tempfile.TemporaryDirectory() as d:
            selectors=Path(d)/'selectors.json'
            selectors.write_text(json.dumps({'anchors':{'conversationTitle':{'path':[0,23,5],'expected':{'role':'AXTextField'}},'composer':{'path':[0,23,9,0,2,0],'expected':{'role':'AXTextArea'}}}}))
            def observe(*,root_path,max_depth):
                if root_path==[0]:return {'nodes':[{'path':[0,25],'role':'AXSplitGroup'}]}
                if root_path==[0,25]:return {'nodes':[{'path':[0,25,i],'role':r} for i,r in [(1,'AXTextField'),(5,'AXTextField'),(9,'AXSplitGroup')]]}
                return {'nodes':[{'role':'AXTextArea' if root_path[-1]==0 else 'AXTextField'}]}
            with patch.object(ui,'SELECTORS',selectors),patch.object(ui,'execute',side_effect=observe) as run:
                ui.refresh_chat_cache()
            self.assertEqual(json.loads(selectors.read_text())['anchors']['composer']['path'],[0,25,9,0,2,0])
            self.assertTrue(all(c.kwargs['max_depth']<=1 for c in run.call_args_list))
    def test_reject_modifier_before_any_ui_execution(self):
        with patch.object(ui.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError,'modifier-not-allowed'):
                ui.execute([{'type':'click','path':[0],'expected':{'role':'AXCell'},'modifier':'control'}])
            run.assert_not_called()
    def test_reject_literal_key_before_any_ui_execution(self):
        with patch.object(ui.subprocess, 'run') as run:
            with self.assertRaisesRegex(ValueError,'key-not-allowed'):
                ui.execute([{'type':'key','path':[0],'expected':{'role':'AXTextField'},'key':'control'}])
            run.assert_not_called()
    def test_no_raw_keydown_or_keyup_backend(self):
        source=ui.SCRIPT.read_text()
        self.assertNotIn('se.keyDown(',source)
        self.assertNotIn('se.keyUp(',source)

    def test_reject_coordinate_action_before_any_execution(self):
        with patch.object(ui.subprocess, 'run') as run:
            with self.assertRaises(ValueError): ui.execute([{'type':'screenshot'}])
            run.assert_not_called()
    def test_reject_unbound_click(self):
        with patch.object(ui.subprocess, 'run') as run:
            with self.assertRaises(ValueError): ui.execute([{'type':'click','path':[0]}])
            run.assert_not_called()
    def test_cached_anchor_reads_only_exact_path(self):
        anchor=json.loads(ui.SELECTORS.read_text())['anchors']['composer']
        with patch.object(ui,'execute',return_value={'nodes':[dict(anchor['expected'], value='')]}) as run:
            ui.read_anchor('composer')
            run.assert_called_once_with(root_path=anchor['path'],max_depth=0)
    def test_stale_anchor_is_not_clicked(self):
        with patch.object(ui,'execute',return_value={'nodes':[{'role':'AXButton'}]}):
            with self.assertRaisesRegex(RuntimeError,'anchor-changed'): ui.read_anchor('composer')
    def test_native_backend_has_no_capture_or_injection_api(self):
        source=ui.SCRIPT.read_text()
        for forbidden in ['CGEvent','Quartz','getScreenshot','getState(', 'AXValue=','AXValue =']:
            self.assertNotIn(forbidden,source)
        self.assertIn("windows.byName('企业微信')",source)
        self.assertNotIn('keyDown(',source)
        self.assertNotIn('keyUp(',source)

if __name__=='__main__': unittest.main()
