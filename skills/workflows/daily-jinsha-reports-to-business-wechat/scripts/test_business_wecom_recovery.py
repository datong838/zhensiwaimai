import sys
import tempfile
import time
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from business_wecom_recovery import eligible

class RecoveryGuards(unittest.TestCase):
 def test_only_sent_prefix_and_never_dispatched_suffix(self):
  request={'items':[{'itemId':'0','type':'file','sha256':'a'},{'itemId':'1','type':'file','sha256':'b'}]}
  first={'status':'unknown','sha256':'a','sendAttempts':1,'claimedAt':time.time(),
         'reason':'wecom-tail-unconfirmed','transport':{'sent':True,'receipt':{'result':'sent-tail-unconfirmed'}}}
  journal={'0':first};read=lambda p:journal.get(p.parent.name)
  key=lambda r,i:i['itemId'];p=Path('/fixture')
  prior={'bridgeVersion':1,'state':'unknown'}
  self.assertTrue(eligible(prior,request,p,key,read))
  journal['1']={'status':'unknown'}
  self.assertFalse(eligible(prior,request,p,key,read))
  journal.pop('1');first['transport']['sent']=False
  self.assertFalse(eligible(prior,request,p,key,read))
  first['transport']['sent']=True;first['sha256']='different'
  self.assertFalse(eligible(prior,request,p,key,read))
 def test_verified_prefix_requires_recorded_resume_flag(self):
  request={'items':[{'itemId':'0','type':'file','sha256':'a'},{'itemId':'1','type':'file','sha256':'b'}]}
  prior={'bridgeVersion':1,'state':'partial'}
  read=lambda p:{'status':'verified','sha256':'a','verificationLevel':'file-name-size-ui'} if p.parent.name=='0' else None
  key=lambda r,i:i['itemId']
  self.assertFalse(eligible(prior,request,Path('/fixture'),key,read))
  self.assertTrue(eligible(prior|{'resumeUnattempted':True},request,Path('/fixture'),key,read))
 def test_sent_suffix_is_reconciled_without_allowing_another_send(self):
  request={'items':[{'itemId':'0','type':'file','sha256':'a'},{'itemId':'1','type':'file','sha256':'b'}]}
  journal={'0':{'status':'verified','sha256':'a','verificationLevel':'file-name-size-ui'},
           '1':{'status':'unknown','sha256':'b','sendAttempts':1,'transport':{'sent':True}}}
  read=lambda p:journal.get(p.parent.name)
  key=lambda r,i:i['itemId']
  prior={'bridgeVersion':1,'state':'partial'}
  self.assertTrue(eligible(prior,request,Path('/fixture'),key,read))
  journal['1']['transport']['sent']=None
  self.assertFalse(eligible(prior,request,Path('/fixture'),key,read))
if __name__=='__main__':unittest.main()
