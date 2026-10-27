import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import morning_goal_acceptance as subject
class MorningScopeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.scope=Path(self.tmp.name)
  self.request={'groupName':subject.GROUP,'context':{'workflowId':subject.WORKFLOW,'eventId':'test'},'items':[{'type':'text','text':'__TEST__ one'}]}
  self.manifest={'request':self.request,'grant':{'groupName':subject.GROUP,'expiresAt':time.time()+600}}
  self.write();p=patch.object(subject,'SCOPE',self.scope);p.start();self.addCleanup(p.stop)
 def write(self):(self.scope/'manifest.json').write_text(json.dumps(self.manifest))
 def test_only_frozen_request(self):
  self.assertTrue(subject.request_enabled(self.request))
  for changes in [{'groupName':'上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰'},{'items':[]},{'context':{'workflowId':'merchants','eventId':'test'}}]:self.assertFalse(subject.request_enabled(self.request|changes))
 def test_expired_manifest_is_closed(self):
  self.manifest['grant']['expiresAt']=time.time()-1;self.write();self.assertFalse(subject.request_enabled(self.request))
 def test_changed_payload_is_closed(self):
  r=copy.deepcopy(self.request);r['items'][0]['text']='different';self.assertFalse(subject.request_enabled(r))
if __name__=='__main__':unittest.main()
