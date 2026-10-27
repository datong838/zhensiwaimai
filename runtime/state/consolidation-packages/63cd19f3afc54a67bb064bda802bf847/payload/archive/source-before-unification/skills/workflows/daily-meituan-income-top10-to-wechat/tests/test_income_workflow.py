import contextlib
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
spec=importlib.util.spec_from_file_location('mei_income',Path(__file__).resolve().parents[1]/'scripts/income_workflow.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
from registered_ui_routes import meituan_income_allowed,top10_label_allowed
class Adapter:
    def __init__(self,unknown=False,ready=True):self.sends=[];self.unknown=unknown;self.ready=ready
    def session(self,r):return contextlib.nullcontext()
    def preflight(self,r,o):return {'ok':self.ready,'resolvedGroup':w.GROUP,'inputEmpty':True,'verificationLevel':'wecom-ui-tree-target'}
    def send_one(self,r,i,*args):self.sends.append(i['type']);return {'status':'unknown' if self.unknown and i['type']=='image' else 'verified','sendAttempts':1}
class Tests(unittest.TestCase):
    def setUp(self):
        self.t=tempfile.TemporaryDirectory();self.addCleanup(self.t.cleanup);self.root=Path(self.t.name)
        for p in [patch.object(w,'STATE',self.root/'state'),patch.object(w,'integrity'),patch.object(w,'day_now',return_value='2026-10-26')]:p.start();self.addCleanup(p.stop)
        self.capture=Mock(side_effect=self.collect)
    def collect(self,folder):
        folder.mkdir(parents=True);f=folder/'source.png';f.write_bytes(b'fixture');return {'ok':True,'file':str(f),'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'collectedAt':'2026-10-26T08:00:00Z','dataDate':'2026-10-25','browserPort':9233}
    def test_caption_image_order_and_verified_no_repeat(self):
        a=Adapter();self.assertTrue(w.run(execute=True,collect=self.capture,adapter=a)['ok']);w.run(execute=True,collect=self.capture,adapter=a)
        self.assertEqual(a.sends,['text','image']);self.assertEqual(self.capture.call_count,1)
    def test_image_unknown_preserved_no_repeated_caption_or_image(self):
        a=Adapter(unknown=True);self.assertFalse(w.run(execute=True,collect=self.capture,adapter=a)['ok']);w.run(execute=True,collect=self.capture,adapter=a)
        self.assertEqual(a.sends,['text','image']);self.assertEqual(self.capture.call_count,1)
    def test_preflight_zero_resume_frozen(self):
        a=Adapter(ready=False);w.run(execute=True,collect=self.capture,adapter=a);a.ready=True;w.run(execute=True,collect=self.capture,adapter=a)
        self.assertEqual(a.sends,['text','image']);self.assertEqual(self.capture.call_count,1)
    def test_wrong_data_date_rejected(self):
        with self.assertRaisesRegex(ValueError,'source-date'):w.run(execute=True,collect=lambda f:self.collect(f)|{'dataDate':'2026-10-24'},adapter=Adapter())
    def test_route_is_exact_two_items(self):
        day='2026-10-26';f=self.root/'skills/workflows/daily-meituan-income-top10-to-wechat/.runtime/days'/day/'2026-10-25-美团外卖门店收入top10.png';f.parent.mkdir(parents=True);f.write_bytes(b'fixture')
        text='美团外卖门店收入top10';label={'itemId':'meituan-income-label','type':'text','text':text,'sha256':hashlib.sha256(text.encode()).hexdigest()};image={'itemId':'meituan-income-top10','type':'image','path':str(f),'name':f.name,'size':7,'sha256':hashlib.sha256(f.read_bytes()).hexdigest()}
        r={'groupName':w.GROUP,'context':{'workflowId':w.FLOW,'eventId':day+'-meituan-income-top10','accountAlias':'main-wechat','channel':'desktop'},'items':[label,image]}
        self.assertTrue(meituan_income_allowed(r,root=self.root,day=day))
        for bad in [r|{'items':[image,label]},r|{'items':[label|{'text':'其他'},image]},r|{'items':[label,image|{'sha256':'bad'}]},r|{'groupName':'wrong'}]:self.assertFalse(meituan_income_allowed(bad,root=self.root,day=day))
    def test_taobao_label_fixed_scope(self):
        r={'groupName':w.GROUP,'context':{'workflowId':'top10-income-label','eventId':'2026-10-25-taobao-income-top10-label','accountAlias':'main-wechat','channel':'desktop'},'items':[{'itemId':'taobao-income-label','type':'text','text':'淘宝闪购门店收入top10'}]}
        self.assertTrue(top10_label_allowed(r,day='2026-10-25'));self.assertFalse(top10_label_allowed(r,day='2026-10-26'))
if __name__=='__main__':unittest.main()
