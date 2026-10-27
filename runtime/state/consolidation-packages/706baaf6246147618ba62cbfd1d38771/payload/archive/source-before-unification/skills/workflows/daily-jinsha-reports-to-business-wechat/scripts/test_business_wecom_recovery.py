import sys
import json
import hashlib
import copy
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[4]/'skills/wechat-messaging/scripts'))
from business_wecom_recovery import eligible, native_file_proof, native_unknown, verify_legacy_sent_file

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

class NativeReadbackGuards(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);source=self.root/'report.xlsx';source.write_bytes(b'x'*2048)
  self.item={'itemId':'0','type':'file','name':source.name,'path':str(source),'size':2048,'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
  self.request={'groupName':'运营群','context':{'workflowId':'jinsha-reports','eventId':'same-event','accountAlias':'main-wechat','channel':'desktop'},'items':[self.item]}
  self.claimed=time.time();self.queue=self.root/'queue';folder=self.queue/'original';folder.mkdir(parents=True)
  task={'taskId':'original','stage':'send','request':self.request,'item':self.item}
  task['binding']=hashlib.sha256(json.dumps(task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  self.task=task;self.taskfile=folder/'task.json';self.taskfile.write_text(json.dumps(task,ensure_ascii=False))
  self.intentfile=folder/'send-intent.json';self.intentfile.write_text(json.dumps({'taskId':'original','binding':task['binding'],'sha256':self.item['sha256'],'at':self.claimed}))
  selectors=self.root/'selectors.json';selectors.write_text(json.dumps({'anchors':{'messages':{'path':[0,1]}}}))
  self.group='运营群';self.draft='';self.nodes=[{'role':'AXRow','path':[0,1,0]}, {'path':[0,1,0,0],'value':'report.xlsx'}, {'path':[0,1,0,1],'value':'2K'}]
  self.calls=0;self.change_second=False
  def execute(*,root_path,max_depth):
   self.assertEqual(root_path,[0,1]);self.assertEqual(max_depth,4);self.calls+=1
   nodes=copy.deepcopy(self.nodes)
   if self.change_second and self.calls==2:
    for node in nodes:node['path'][2]=1
   return {'nodes':nodes}
  self.ui=SimpleNamespace(SELECTORS=selectors,execute=execute,read_anchors=lambda *args:(None,{'conversationTitle':{'value':self.group},'composer':{'value':self.draft}}))
 def proof(self):
  with patch('business_wecom_recovery.time.sleep'):
   return native_file_proof(self.request,self.item,self.claimed,queue=self.queue,ui=self.ui)
 def test_unique_two_frames_are_read_only(self):
  result=self.proof();self.assertEqual(result['result'],'verified');self.assertEqual(result['newSendAttempts'],0);self.assertEqual(len(result['frames']),2);self.assertTrue(result['readOnly']);self.assertFalse((self.queue/'original'/'response.json').exists())
 def test_missing_or_conflicting_original_intent(self):
  self.intentfile.unlink();self.assertEqual(self.proof()['result'],'not-verified')
  self.intentfile.write_text(json.dumps({'taskId':'original','binding':'wrong','sha256':self.item['sha256'],'at':self.claimed}));self.assertEqual(self.proof()['result'],'not-verified')
 def test_source_hash_and_stale_attempt_fail(self):
  Path(self.item['path']).write_bytes(b'y'*2048);self.assertEqual(self.proof()['result'],'not-verified')
  self.claimed-=7300;self.assertEqual(self.proof()['result'],'not-verified')
 def test_target_draft_size_and_ambiguous_cards_fail(self):
  self.group='其他群';self.assertEqual(self.proof()['result'],'not-verified');self.group='运营群'
  self.draft='用户草稿';self.assertEqual(self.proof()['result'],'not-verified');self.draft=''
  self.nodes[-1]['value']='4K';self.assertEqual(self.proof()['result'],'not-verified');self.nodes[-1]['value']='2K'
  duplicate=copy.deepcopy(self.nodes)
  for node in duplicate:node['path'][2]=1
  self.nodes+=duplicate;self.assertEqual(self.proof()['result'],'not-verified')
 def test_frame_changes_and_task_tampering_fail(self):
  self.change_second=True;self.assertEqual(self.proof()['result'],'not-verified');self.change_second=False
  self.task['item']['sha256']='different';self.taskfile.write_text(json.dumps(self.task));self.assertEqual(self.proof()['result'],'not-verified')
 def test_native_eligibility_remains_single_recent_attempt(self):
  prior={'status':'unknown','sendAttempts':1,'backend':'system-events-ui-tree','reason':'native-ui-file-card-not-confirmed','claimedAt':self.claimed}
  self.assertTrue(native_unknown(prior))
  for changes in ({'sendAttempts':0},{'claimedAt':'bad'},{'claimedAt':self.claimed-7300},{'backend':'other'},{'reason':'unrelated'}):self.assertFalse(native_unknown(prior|changes))
 def test_native_send_proof_never_calls_legacy_reader(self):
  def forbidden(*args):raise AssertionError('legacy-reader-called')
  adapter=SimpleNamespace(_run_sender=forbidden)
  for status in ('verified','unknown'):
   outcome={'status':status,'sendAttempts':1,'transport':{'sent':True},'verificationLevel':'wecom-ui-tree-file-name-size'}
   self.assertIs(verify_legacy_sent_file(adapter,self.request,self.item,outcome,self.claimed,native_mode=True),outcome)
if __name__=='__main__':unittest.main()
