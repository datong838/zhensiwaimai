import hashlib
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wecom_adapter import WeComAdapter
from workflow_bridge import REGISTRY

class ImageBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.image=self.root/'image.png';self.image.write_bytes(b'image fixture')
        self.item={'type':'image','path':str(self.image)}
        group,_,_,_,ledger=REGISTRY['negative-reviews-summary']
        self.request={'groupName':group,'context':{'workflowId':'negative-reviews-summary',
                      'eventId':str(ledger.resolve()/'test-only.json')},'items':[self.item]}
    def send(self,item):
        with patch('egress_policy.check',return_value={'allow':True}), patch('wecom_ui_queue.exchange',return_value={'status':'verified'}) as queued, patch('wecom_adapter.ui_tree_only_required',return_value=True), patch.object(WeComAdapter,'_run_sender',side_effect=AssertionError('legacy transport')):
            result=WeComAdapter()._send_one(self.request,item,self.root/'work',{},time.time()+100)
        return result,queued
    def test_binds_image_before_queue(self):
        result,queued=self.send(self.item)
        item=queued.call_args.args[2]
        self.assertEqual(item['sha256'],hashlib.sha256(self.image.read_bytes()).hexdigest())
        self.assertEqual(item['name'],'image.png');self.assertEqual(item['size'],13)
        self.assertEqual(result['status'],'verified')
    def test_conflicting_binding_never_transports(self):
        for change in [{'sha256':'wrong'},{'size':99},{'name':'other.png'}]:
            result,queued=self.send(self.item|change)
            self.assertEqual(result['status'],'blocked');self.assertEqual(result['sendAttempts'],0)
            queued.assert_not_called()
    def test_correct_existing_binding_is_preserved(self):
        item=self.item|{'name':self.image.name,'size':13,'sha256':hashlib.sha256(self.image.read_bytes()).hexdigest()}
        _,queued=self.send(item);self.assertEqual(queued.call_args.args[2],item)

if __name__=='__main__':unittest.main()
