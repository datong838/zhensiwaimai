import contextlib
import tempfile
import unittest
from pathlib import Path
import workflow_executor as w

class Adapter:
    def __init__(self,status='verified',ready=True):self.status=status;self.ready=ready;self.sends=0
    def session(self,request):return contextlib.nullcontext()
    def preflight(self,request,output):return {'ok':self.ready,'resolvedGroup':w.CANONICAL_TARGET_GROUP,'inputEmpty':True,'verificationLevel':'wecom-ui-tree-target'}
    def send_one(self,request,item,*args):
        assert item['text']=='淘宝闪购门店收入top10'
        self.sends+=1;return {'status':self.status,'sendAttempts':1}
class IncomeLabelTests(unittest.TestCase):
    def check(self,status):
        with tempfile.TemporaryDirectory() as t:
            a=Adapter(status);kwargs={'adapter':a,'label_dir':Path(t)/'labels'}
            w.send_income_label('2026-10-25',Path(t),**kwargs)
            result=w.send_income_label('2026-10-25',Path(t),**kwargs)
            self.assertEqual(a.sends,1);self.assertEqual(result['sendAttempts'],0)
    def test_verified_not_repeated(self):self.check('verified')
    def test_unknown_not_repeated(self):self.check('unknown')
    def test_zero_send_preflight_can_resume_same_caption(self):
        with tempfile.TemporaryDirectory() as t:
            a=Adapter(ready=False);kwargs={'adapter':a,'label_dir':Path(t)/'labels'}
            self.assertEqual(w.send_income_label('2026-10-25',Path(t),**kwargs)['sendAttempts'],0)
            a.ready=True;w.send_income_label('2026-10-25',Path(t),**kwargs);self.assertEqual(a.sends,1)
if __name__=='__main__':unittest.main()
