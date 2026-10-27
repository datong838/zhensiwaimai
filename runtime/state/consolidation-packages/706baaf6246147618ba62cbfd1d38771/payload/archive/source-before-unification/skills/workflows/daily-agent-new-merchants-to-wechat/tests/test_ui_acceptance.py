import unittest,sys,copy,hashlib
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from executor_integrity import _validate_acceptance,IntegrityError
class UIAcceptance(unittest.TestCase):
 def setUp(self):
  sha=hashlib.sha256('example'.encode()).hexdigest();self.meta={'merchantId':'123','messageSha256':sha}
  evidence={'method':'wecom-ui-tree-text','resolvedGroup':'电销+直播攻坚组','sha256':sha,'observations':[{'groupName':'电销+直播攻坚组','inputEmpty':True,'newMessageVisible':True,'visibleTextSha256':sha} for _ in range(2)]}
  self.r={'ok':True,'verified':True,'state':'verified','groupName':'电销+直播攻坚组','merchantId':'123','messageSha256':sha,'physicalSendAttempts':1,'sendAttempts':1,'runtimeModelDecisions':0,'payloads':[{'text':'example','sha256':sha}],'postSendInputCleared':[True,True],'commonReceipt':{'status':'verified','items':[{'status':'verified','sendAttempts':1,'verificationLevel':'wecom-ui-tree-text','evidence':evidence}]}}
 def test_complete(self):_validate_acceptance(self.r,self.meta)
 def test_reject_bad_binding(self):
  for k,v in [('groupName','other'),('merchantId','wrong'),('messageSha256','wrong'),('sendAttempts',2),('physicalSendAttempts',0),('postSendInputCleared',[True,False])]:
   with self.subTest(k=k):
    r=copy.deepcopy(self.r);r[k]=v
    with self.assertRaises(IntegrityError):_validate_acceptance(r,self.meta)
 def test_reject_bad_frames(self):
  for k,v in [('inputEmpty',False),('visibleTextSha256','wrong'),('newMessageVisible',False)]:
   r=copy.deepcopy(self.r);r['commonReceipt']['items'][0]['evidence']['observations'][1][k]=v
   with self.assertRaises(IntegrityError):_validate_acceptance(r,self.meta)
 def test_old_missing_evidence_stays_blocked(self):
  r=copy.deepcopy(self.r);r.pop('commonReceipt')
  with self.assertRaises(IntegrityError):_validate_acceptance(r,self.meta)
if __name__=='__main__':unittest.main()
