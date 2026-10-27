import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wecom_ui_queue import validate_response
from wecom_adapter import WeComAdapter,target_preflight_verified
GROUP='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
class PreflightCompatibility(unittest.TestCase):
    def task(self):return {'taskId':'fixture','binding':'bound','stage':'preflight','request':{'groupName':GROUP}}
    def reply(self,**changes):return {'taskId':'fixture','binding':'bound','result':{'ok':True,'resolvedGroup':GROUP,'inputEmpty':True}|changes}
    def test_validated_ui_receipt_passes_original_target_contract(self):
        proof=validate_response(self.task(),self.reply())
        request={'groupName':GROUP,'context':{'workflowId':'daily-new-stores-activity-reminder','eventId':'2026-10-25-taobao-123-activity-reminder'},'items':[{'type':'text','itemId':'missing-activity','text':'fixture'}]}
        with patch('wecom_ui_queue.exchange',return_value=proof),patch.object(WeComAdapter,'_run_sender',side_effect=AssertionError('legacy transport')):
            actual=WeComAdapter().preflight(request,'unused')
        self.assertTrue(target_preflight_verified(actual,GROUP))
    def test_wrong_group_and_dirty_input_rejected(self):
        for changes in [{'resolvedGroup':'wrong'},{'inputEmpty':False},{'ok':False}]:
            with self.assertRaises(ValueError):validate_response(self.task(),self.reply(**changes))
        proof=validate_response(self.task(),self.reply())
        self.assertFalse(target_preflight_verified(proof,'wrong'))
        self.assertFalse(target_preflight_verified(proof|{'inputEmpty':False},GROUP))
    def test_wrong_binding_rejected(self):
        with self.assertRaises(ValueError):validate_response(self.task(),self.reply()|{'binding':'other'})
    def test_bare_ok_is_still_insufficient(self):
        self.assertFalse(target_preflight_verified({'ok':True,'resolvedGroup':GROUP,'inputEmpty':True},GROUP))
if __name__=='__main__':unittest.main()
