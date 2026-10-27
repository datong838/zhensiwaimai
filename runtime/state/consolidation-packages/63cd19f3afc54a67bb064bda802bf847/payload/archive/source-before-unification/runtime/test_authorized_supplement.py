import contextlib
import hashlib
import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import authorized_supplement as subject

class FakeAdapter:
    def __init__(self, status='verified'):
        self.calls=0
        self.status=status
    def session(self, request): return contextlib.nullcontext()
    def preflight(self, request, work): return {'ok':True,'resolvedGroup':subject.GROUP}
    def send_one(self, *args):
        self.calls+=1
        return {'status':self.status,'sendAttempts':1}

class SupplementTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.run=self.root/'run';self.run.mkdir()
        self.file=self.root/'authorization.json';self.workflow='daily-new-stores-opening-to-wechat'
        self.grant={'groupName':subject.GROUP,'eventId':'authorized-event','runsRoot':str(self.root),
                    'journal':str(self.root/'journal.json'), 'item':{'itemId':'one','type':'text','text':'six stores',
                    'sha256':hashlib.sha256(b'six stores').hexdigest()}}
        self.data={'authorization':subject.AUTH,'acceptedPossibleDuplicate':True,'expiresAt':time.time()+600,
                   'grants':{self.workflow:self.grant}}
        self.save()
        self.p=patch.object(subject,'table',return_value=self.file);self.p.start();self.addCleanup(self.p.stop)
    def save(self): self.file.write_text(json.dumps(self.data))
    def test_verified_never_sends_twice(self):
        adapter=FakeAdapter()
        self.assertEqual(subject.deliver_once(self.workflow,self.run,adapter=adapter)['status'],'verified')
        self.assertEqual(subject.deliver_once(self.workflow,self.run,adapter=adapter)['status'],'already_verified')
        self.assertEqual(adapter.calls,1)
    def test_unknown_never_retries(self):
        adapter=FakeAdapter('unknown')
        subject.deliver_once(self.workflow,self.run,adapter=adapter)
        self.assertEqual(subject.deliver_once(self.workflow,self.run,adapter=adapter)['status'],'unknown')
        self.assertEqual(adapter.calls,1)
    def test_request_exact_binding(self):
        request={'groupName':subject.GROUP,'items':[self.grant['item']],
                 'context':{'workflowId':self.workflow,'eventId':self.grant['eventId'],'supplementAuthorization':subject.AUTH}}
        self.assertTrue(subject.request_enabled(request))
        request['groupName']='wrong';self.assertFalse(subject.request_enabled(request))
        request['groupName']=subject.GROUP;request['context']['workflowId']='meituan-customer-reply-daily'
        self.assertFalse(subject.request_enabled(request))
    def test_payload_drift_rejected(self):
        self.grant['item']['text']='changed';self.save()
        with self.assertRaisesRegex(ValueError,'drift'):subject.load_grant(self.workflow)
    def test_expiry_rejected(self):
        self.data['expiresAt']=time.time()-1;self.save()
        with self.assertRaises(ValueError):subject.load_grant(self.workflow)
    def test_outside_original_workflow_not_executed(self):
        self.assertIsNone(subject.deliver_once(self.workflow,self.root.parent,adapter=FakeAdapter()))

if __name__=='__main__':unittest.main()
