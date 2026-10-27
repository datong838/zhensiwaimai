import datetime
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wecom_ui_queue import user_no_resend_today,enabled
class UserNoResendTests(unittest.TestCase):
    def test_exact_day_and_workflow_only(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);day=datetime.datetime(2026,10,24,19,30)
            data={'date':'2026-10-24','source':'explicit-user-instruction','noMoreSendsToday':True,'workflows':['daily-new-stores-opening-to-wechat','daily-store-task-completion-ops']}
            (root/'user-no-resend-20261024-opening-taskrate.json').write_text(json.dumps(data))
            for workflow in data['workflows']:self.assertTrue(user_no_resend_today(workflow,now=day,state=root))
            self.assertFalse(user_no_resend_today('merchants',now=day,state=root))
            self.assertFalse(user_no_resend_today(data['workflows'][0],now=day+datetime.timedelta(days=1),state=root))
    def test_guard_precedes_supplement_authorization(self):
        with patch('wecom_ui_queue.user_no_resend_today',return_value=True):
            self.assertFalse(enabled({'context':{'workflowId':'daily-new-stores-opening-to-wechat','supplementAuthorization':'old'}}))
if __name__=='__main__':unittest.main()
