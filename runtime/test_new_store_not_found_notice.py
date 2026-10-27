import importlib.util,json,sys,tempfile,types,unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT/'runtime'))
from business_coverage import assess_receipt
sys.path.insert(0,str(ROOT/'skills/wechat-messaging/scripts'))
from registered_ui_routes import allowed_direct
HIT={'channel':'淘宝','name':'海上三小姐·甜品·下午茶(河西店)','days':'1天'}
MODULES=[]
for kind in ['activity','decoration']:
 folder=ROOT/'skills/workflows'/f'daily-new-stores-{kind}-audit-to-wechat/scripts'
 sys.path.insert(0,str(folder))
 def load(name,path):
  spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
 flow=load(kind+'_workflow',folder/(kind+'_workflow.py'));sys.modules[kind+'_workflow']=flow
 daily=load(kind+'_daily',folder/(kind+'_daily.py'));MODULES.append((kind,flow,daily))

class NoticeTests(unittest.TestCase):
 def test_precise_message_and_record_note(self):
  for kind,flow,_ in MODULES:
   with self.subTest(kind=kind):
    r=flow.not_found_receipt(HIT,kind+'-collection-skipped:shop-not-found:未搜索到店铺')
    title='活动配置巡检' if kind=='activity' else '店铺装修巡检'
    self.assertEqual(flow.message(r,HIT['name']),f"{title}：{HIT['name']} 新店铺（开业1天）淘宝闪购商家版 查无此店铺")
    self.assertEqual(r['recordNote'],'店铺在主账号查不到未能检查');self.assertNotIn('shopId',r);self.assertNotIn('targetStatus',r)
    for field,value in [('account','other'),('shopName','other'),('days','4天'),('checkedAt','2020-01-01T00:00:00+08:00')]:
     with self.assertRaises((ValueError,KeyError)):flow.message(r|{field:value},HIT['name'])
 def test_timeout_busy_login_and_wrong_source_are_not_not_found(self):
  for kind,flow,_ in MODULES:
   for reason in ['shop-search-timeout','post-lease-busy','brand-login-required','shop-not-found:unknown']:
    with self.subTest(kind=kind,reason=reason),self.assertRaises(ValueError):flow.not_found_receipt(HIT,kind+'-collection-skipped:'+reason)
   with self.assertRaises(ValueError):flow.not_found_receipt(HIT|{'channel':'美团'},kind+'-collection-skipped:shop-not-found:未搜索到店铺')
 def test_original_delivery_verified_is_idempotent_and_unknown_not_resent(self):
  for kind,flow,_ in MODULES:
   for outcome in ['verified','unknown']:
    with self.subTest(kind=kind,outcome=outcome),tempfile.TemporaryDirectory() as td:
     calls=[]
     class Adapter:
      def session(self,r):return nullcontext()
      def preflight(self,r,p):return {'ok':True}
      def send_one(self,r,item,*args):calls.append((r,item));return {'status':outcome,'sendAttempts':1,'reason':'unconfirmed' if outcome=='unknown' else None}
     module=types.SimpleNamespace(WeComAdapter=Adapter,target_preflight_verified=lambda r,g:r['ok'])
     r=flow.not_found_receipt(HIT,kind+'-collection-skipped:shop-not-found:未搜索到店铺')
     with patch.dict(sys.modules,{'wecom_adapter':module}),patch.object(flow,'EVENTS',Path(td)),patch.object(flow,'arm_state',return_value={'armed':True},create=True):
      a=flow.deliver(r,Path(td)/'run1',HIT['name']);b=flow.deliver(r,Path(td)/'run2',HIT['name'])
     self.assertEqual(a['status'],outcome);self.assertEqual(b['status'],'already_verified' if outcome=='verified' else 'unknown');self.assertEqual(len(calls),1)
     self.assertEqual(calls[0][0]['groupName'],flow.GROUP);self.assertEqual(calls[0][1]['text'],flow.message(r,HIT['name']))
     request=calls[0][0];self.assertTrue(allowed_direct(request))
     for change in [{'groupName':'wrong'},{'context':request['context']|{'eventId':'2020-01-01-taobao-not-found-anything'}},{'items':[request['items'][0]|{'sha256':'0'*64}]},{'items':[request['items'][0]|{'text':request['items'][0]['text']+'其他'}]}]:self.assertFalse(allowed_direct(request|change))
 def test_original_daily_completes_only_after_notice_delivery(self):
  for kind,flow,daily in MODULES:
   for status in ['verified','unknown','ready']:
    with self.subTest(kind=kind,status=status),tempfile.TemporaryDirectory() as td:
     with patch.object(daily,'todays_source',return_value=(Path(td)/'collection.json',[HIT])),patch.object(flow,'RUNTIME',Path(td)),patch.object(flow,'collect',side_effect=RuntimeError(kind+'-collection-skipped:shop-not-found:未搜索到店铺')),patch.object(flow,'deliver',return_value={'status':status,'sendAttempts':1 if status!='ready' else 0}) as send,patch.object(daily,'reset_chain_seed',return_value={'status':'reset'}),patch.object(daily,'update_watchlist',return_value={},create=True):
      result=daily.run(execute=status!='ready')
     shop=result['shops'][0];self.assertEqual(shop['recordNote'],'店铺在主账号查不到未能检查')
     self.assertEqual(assess_receipt(result,result['day'])['complete'],status=='verified')
     self.assertEqual(send.call_count,0 if status=='ready' else 1)
if __name__=='__main__':unittest.main()
