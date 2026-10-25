import copy,hashlib,json,unittest
from reconcile_feedback_ui_zero import check_zero_evidence,GROUP
class Tests(unittest.TestCase):
 def fixture(self):
  i={'itemId':'0','type':'file','path':'/source/a.xlsx','name':'a.xlsx','size':1,'sha256':'a'}
  t={'taskId':'id','stage':'send','request':{'groupName':GROUP,'context':{'workflowId':'negative-feedback-appeals'},'items':[i,dict(i,itemId='1',name='b.xlsx')]},'item':dict(i,path='/frozen/a.xlsx')}
  self.bind(t)
  return t,{'taskId':'id','binding':t['binding'],'result':{'resolvedGroup':GROUP,'status':'blocked','sendAttempts':0,'inputEmpty':True,'reason':'task-expired-before-consumption','intentExists':False,'actualSendActions':0}}
 def bind(self,t):t['binding']=hashlib.sha256(json.dumps({k:v for k,v in t.items() if k!='binding'},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
 def test_bound_zero(self):
  t,r=self.fixture();self.assertTrue(check_zero_evidence(t,r,claimed=False,intent=False))
 def test_claim_or_intent_rejected(self):
  for c,i in [(True,False),(False,True)]:
   t,r=self.fixture()
   with self.assertRaises(ValueError):check_zero_evidence(t,r,claimed=c,intent=i)
 def test_scope_and_item_rejected(self):
  for mutate in [lambda t:t['request'].update(groupName='wrong'),lambda t:t['item'].update(sha256='changed'),lambda t:t['request']['context'].update(workflowId='other'),lambda t:t['request']['items'][1].update(type='image')]:
   t,r=self.fixture();mutate(t);self.bind(t);r['binding']=t['binding']
   with self.assertRaises(ValueError):check_zero_evidence(t,r,claimed=False,intent=False)
 def test_evidence_rejected(self):
  for k,v in [('actualSendActions',1),('intentExists',True),('sendAttempts',1),('inputEmpty',False),('reason','unknown')]:
   t,r=self.fixture();r['result'][k]=v
   with self.assertRaises(ValueError):check_zero_evidence(t,r,claimed=False,intent=False)
 def test_binding_rejected(self):
  t,r=self.fixture();r['binding']='wrong'
  with self.assertRaises(ValueError):check_zero_evidence(t,r,claimed=False,intent=False)
if __name__=='__main__':unittest.main()
