import sys,unittest,hashlib,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from runtime_contract import verify_delivery
class UiProofTests(unittest.TestCase):
 def setUp(self):
  text='城市：示例市  ；  店铺：测试店';sha=hashlib.sha256(text.encode()).hexdigest();self.item={'merchantId':'123','text':text,'sha256':sha};self.group='电销+直播攻坚组'
  self.receipt={'ok':True,'verified':True,'state':'verified','groupName':self.group,'sendAttempts':1,'physicalSendAttempts':1,'merchantId':'123','messageSha256':sha,'payloads':[{'text':text,'sha256':sha}],'uiPostReadback':{'method':'wecom-ui-tree-text','resolvedGroup':self.group,'sha256':sha,'observations':[{'groupName':self.group,'inputEmpty':True,'newMessageVisible':True,'visibleTextSha256':sha} for _ in range(2)]}}
 def test_bound_readback(self):self.assertTrue(verify_delivery(self.receipt,self.group,self.item)['ok'])
 def test_wrong_target_text_and_partial_evidence_rejected(self):
  for key,value in [('groupName','其他群'),('sendAttempts',2),('messageSha256','bad')]:
   with self.assertRaises(RuntimeError):verify_delivery(self.receipt|{key:value},self.group,self.item)
  for field,value in [('visibleTextSha256','other'),('inputEmpty',False),('groupName','other')]:
   r=copy.deepcopy(self.receipt);r['uiPostReadback']['observations'][1][field]=value
   with self.assertRaises(RuntimeError):verify_delivery(r,self.group,self.item)
if __name__=='__main__':unittest.main()
