import copy
import math
from pathlib import Path
import sys
import tempfile
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wecom_ui_queue import preflight_enabled,enabled,exchange

class LegacyPreflightTests(unittest.TestCase):
    def request(self):return {'groupName':'上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰','context':{'searchGroupName':None,'deadlineAt':time.time()+120}}
    def test_original_readonly_request(self):
        r=self.request();self.assertTrue(preflight_enabled(r));self.assertFalse(enabled(r))
    def test_bad_scope(self):
        for mutation in [lambda r:r.update(groupName='其他群'),lambda r:r.update(items=[]),lambda r:r['context'].update(workflowId='top10'),lambda r:r['context'].update(searchGroupName='其他')]:
            r=self.request();mutation(r);self.assertFalse(preflight_enabled(r))
    def test_bad_deadline(self):
        for value in [0,-1,float('inf'),float('nan'),True,'later']:
            r=self.request();r['context']['deadlineAt']=value;self.assertFalse(preflight_enabled(r))
    def test_original_owner_lifecycle_does_not_use_remaining_seconds(self):
        for value in [time.time()-1,time.time()+600]:
            r=self.request();r['context']['deadlineAt']=value;self.assertTrue(preflight_enabled(r))
    def test_send_and_readback_do_not_enqueue(self):
        with tempfile.TemporaryDirectory() as tmp:
            for stage in ['send','readback']:
                with self.assertRaisesRegex(ValueError,'not-enabled'):exchange(stage,self.request(),queue=Path(tmp))
            self.assertEqual(list(Path(tmp).iterdir()),[])
if __name__=='__main__':unittest.main()
