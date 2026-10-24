import unittest,copy,json,hashlib
from reconcile_ui_post_verified import validate
class EvidenceTests(unittest.TestCase):
 def setUp(self):
  text='当前无新增意向商家';sha=hashlib.sha256(text.encode()).hexdigest();item={'itemId':'0','type':'text','text':text,'sha256':sha}
  self.t={'taskId':'test','stage':'send','item':item,'deadlineAt':30,'request':{'groupName':'电销+直播攻坚组','items':[item],'context':{'workflowId':'merchants','eventId':'/ledger/empty-202610241500.json'}}}
  self.t['binding']=hashlib.sha256(json.dumps(self.t,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
  self.i={'taskId':'test','binding':self.t['binding'],'sha256':sha,'groupName':'电销+直播攻坚组','sendAttempts':1,'createdAt':10}
  self.r={'taskId':'test','binding':self.t['binding'],'result':{'status':'verified','sendAttempts':1,'resolvedGroup':'电销+直播攻坚组','sha256':sha,'observations':[{'groupName':'电销+直播攻坚组','inputEmpty':True,'newMessageVisible':True,'visibleTextSha256':sha,'observedAt':x} for x in (20,25)]}}
 def test_valid(self):self.assertEqual(validate(self.t,self.r,self.i)['status'],'verified')
 def test_rejections(self):
  for target,key,value in [('intent','sendAttempts',0),('intent','binding','wrong'),('reply','resolvedGroup','wrong'),('frame','visibleTextSha256','wrong'),('frame','inputEmpty',False),('frame','observedAt',31)]:
   with self.subTest(target=target,key=key):
    i=copy.deepcopy(self.i);r=copy.deepcopy(self.r)
    obj=i if target=='intent' else r['result'] if target=='reply' else r['result']['observations'][0];obj[key]=value
    with self.assertRaises(ValueError):validate(self.t,r,i)
 def test_tampered_task(self):
  t=copy.deepcopy(self.t);t['request']['context']['workflowId']='other'
  with self.assertRaises(ValueError):validate(t,self.r,self.i)
class LateReadOnlyFrameTests(EvidenceTests):
 def test_second_readonly_frame_may_follow_deadline(self):
  self.r['result']['observations'][1]['observedAt']=40
  self.assertEqual(validate(self.t,self.r,self.i)['status'],'verified')
 def test_second_frame_budget_exceeded(self):
  self.r['result']['observations'][1]['observedAt']=151
  with self.assertRaises(ValueError):validate(self.t,self.r,self.i)
if __name__=='__main__':unittest.main()
