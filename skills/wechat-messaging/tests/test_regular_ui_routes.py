import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wecom_ui_queue import enabled
from wecom_adapter import WeComAdapter
GROUP='上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'
class RegularRoutes(unittest.TestCase):
    def setUp(self):
        guard=patch('wecom_ui_queue.user_no_resend_today',return_value=False)
        guard.start();self.addCleanup(guard.stop)
    def requests(self):
        return [dict(groupName=GROUP,context={'workflowId':'daily-new-stores-opening-to-wechat','eventId':'2026-10-25'},items=[{'itemId':'new-stores','type':'text','text':'new stores'}]),
                dict(groupName=GROUP,context={'workflowId':'daily-store-task-completion-ops','eventId':'2026-10-25-taobao-store-task-detail'},items=[{'itemId':'store-task-detail','type':'file','path':'detail.xlsx'},{'itemId':'store-task-stats','type':'image','path':'stats.png'}])]
    def test_exact_regular_requests(self):
        for request in self.requests(): self.assertTrue(enabled(request))
    def test_wrong_scope_is_rejected(self):
        for original in self.requests():
            for change in [{'groupName':'wrong'},{'items':[]},{'context':{'workflowId':'other'}},{'context':original['context']|{'eventId':'different'}}]:
                self.assertFalse(enabled(original|change))
            request=copy.deepcopy(original);request['items'][0]['type']='image'
            self.assertFalse(enabled(request))
    def test_stats_requires_both_distinct_original_items(self):
        request=self.requests()[1]
        self.assertFalse(enabled(request|{'items':[request['items'][0]]*2}))
        self.assertFalse(enabled(request|{'items':[request['items'][1]]}))
    def test_preflight_only_uses_ui_queue(self):
        for request in self.requests():
            with patch('wecom_ui_queue.exchange',return_value={'ok':True,'resolvedGroup':GROUP,'inputEmpty':True}) as queued, patch.object(WeComAdapter,'_run_sender',side_effect=AssertionError('legacy transport')):
                self.assertTrue(WeComAdapter().preflight(request,'unused')['ok']);queued.assert_called_once()
    def test_contract_is_not_enabled_before_multi_page_fix(self):
        self.assertFalse(enabled({'groupName':GROUP,'context':{'workflowId':'contract-termination-ops'},'items':[{'itemId':'contract-termination-p1','type':'image','path':'p1.png'}]}))

if __name__=='__main__':unittest.main()
