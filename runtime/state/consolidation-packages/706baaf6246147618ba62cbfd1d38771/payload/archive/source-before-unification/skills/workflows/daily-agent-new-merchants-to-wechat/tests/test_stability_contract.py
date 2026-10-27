import sys,unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import structured_merchant_collector as c
import wechat_sender_executor as s
import desktop_wechat_sender as desktop
import workflow_executor as workflow
import executor_integrity as integrity
def fixture_manifest():
 # Temporary test candidate only; never refresh the live sealed acceptance.
 manifest=json.loads(integrity.MANIFEST_PATH.read_text())
 for label,path in integrity.RUNTIME_FILES.items():
  manifest['files'][label]={'path':str(path),'sha256':integrity.sha256(path)}
 return manifest

class StabilityTests(unittest.TestCase):
 def test_sealed_executor_integrity_passes(self):
  manifest=fixture_manifest()
  manifest['status']='SEALED'
  with tempfile.TemporaryDirectory() as d:
   candidate=Path(d)/'executor-lock.json';candidate.write_text(json.dumps(manifest))
   receipt=integrity.verify(candidate)
  self.assertTrue(receipt['ok'])
  self.assertEqual(receipt['status'],'SEALED')
  self.assertEqual(receipt['fileCount'],len(integrity.RUNTIME_FILES))
  self.assertEqual(receipt['runtimeModelDecisions'],0)
 def test_normal_entry_rejects_unsealed_manifest(self):
  manifest=fixture_manifest()
  manifest['status']='UNSEALED_ACCEPTANCE'
  with tempfile.TemporaryDirectory() as d:
   candidate=Path(d)/'executor-lock.json';candidate.write_text(json.dumps(manifest))
   with self.assertRaisesRegex(integrity.IntegrityError,'not-sealed'):
    integrity.verify(candidate)
 def test_unsealed_acceptance_requires_exact_authorization(self):
  manifest=fixture_manifest()
  manifest['status']='UNSEALED_ACCEPTANCE'
  manifest['unsealedAcceptance']={'authorization':'approved','expiresAt':'2999-01-01T00:00:00+08:00'}
  with tempfile.TemporaryDirectory() as d:
   candidate=Path(d)/'executor-lock.json';candidate.write_text(json.dumps(manifest))
   with patch.object(integrity,'_validate_code_maintenance'):
    with self.assertRaisesRegex(integrity.IntegrityError,'authorization-mismatch'):
     integrity.verify_unsealed_acceptance('wrong',candidate)
    self.assertEqual(integrity.verify_unsealed_acceptance('approved',candidate)['status'],'UNSEALED_ACCEPTANCE')
 def test_sealed_executor_integrity_rejects_changed_file(self):
  manifest=fixture_manifest()
  manifest['status']='SEALED'
  manifest['files']['workflow_executor']['sha256']='0'*64
  with tempfile.TemporaryDirectory() as d:
   changed=Path(d)/'executor-lock.json';changed.write_text(json.dumps(manifest))
   with self.assertRaisesRegex(integrity.IntegrityError,'digest-mismatch:workflow_executor'):
    integrity.verify(changed)
 def test_sealed_executor_integrity_rejects_changed_acceptance_receipt(self):
  manifest=fixture_manifest()
  manifest['status']='SEALED'
  manifest['acceptance']['receiptSha256']='0'*64
  with tempfile.TemporaryDirectory() as d:
   changed=Path(d)/'executor-lock.json';changed.write_text(json.dumps(manifest))
   with self.assertRaisesRegex(integrity.IntegrityError,'acceptance-receipt-digest-mismatch'):
    integrity.verify(changed)
 def test_sealed_executor_integrity_rejects_changed_maintenance_receipt(self):
  manifest=fixture_manifest()
  manifest['status']='SEALED'
  manifest['maintenanceAcceptance']['receiptSha256']='0'*64
  with tempfile.TemporaryDirectory() as d:
   changed=Path(d)/'executor-lock.json';changed.write_text(json.dumps(manifest))
   with self.assertRaisesRegex(integrity.IntegrityError,'maintenance-receipt-digest-mismatch'):
    integrity.verify(changed)
 def test_workflow_integrity_precedes_wechat_and_collection(self):
  args=workflow.build_parser().parse_args(['--standing-authorization','a','--output-dir','/tmp/x'])
  with tempfile.TemporaryDirectory() as d,patch.object(s,'STATE_DIR',Path(d)),patch.object(args,'output_dir',str(Path(d)/'run')), \
       patch.object(integrity,'verify',side_effect=integrity.IntegrityError('sealed-drift')), \
       patch.object(desktop,'preflight') as preflight,patch.object(c,'collect') as collect:
   receipt=workflow.execute(args)
  self.assertFalse(receipt['ok'])
  self.assertEqual(receipt['stage'],'executor_integrity')
  preflight.assert_not_called();collect.assert_not_called()
 def test_default_channel_is_desktop(self):
  args=workflow.build_parser().parse_args(['--standing-authorization','a','--output-dir','/tmp/x'])
  self.assertEqual(args.wechat_channel,'desktop')
 def test_default_desktop_contention_budget_is_bounded(self):
  self.assertEqual(desktop.DEFAULT_CONTENTION_WAIT_SECONDS,60.0)
  self.assertEqual(desktop.DEFAULT_CONTENTION_POLL_SECONDS,5.0)
 def test_desktop_preflight_requires_exact_shared_locator(self):
  receipt={'ok':True,'action':'open-group','group':s.TEST_GROUP,'header':s.TEST_GROUP+'（18）','note':None}
  with tempfile.TemporaryDirectory() as d,patch.object(desktop,'_windows_preflight_once',return_value=receipt):
   self.assertTrue(desktop.preflight(s.TEST_GROUP,Path(d),wait_seconds=0)['ok'])
 def test_desktop_preflight_retries_transient_contention(self):
  values=iter([{'ok':False,'reason':'exact-group-result-count:0','sendAttempts':0,'hardGate':False},
               {'ok':True,'action':'open-group','group':s.TEST_GROUP,'sendAttempts':0,'hardGate':False}])
  with tempfile.TemporaryDirectory() as d,patch.object(desktop,'_windows_preflight_once',side_effect=lambda group,out,*a,**kwargs:next(values)),patch.object(desktop.time,'sleep'):
   receipt=desktop.preflight(s.TEST_GROUP,Path(d),wait_seconds=10,poll_seconds=1)
  self.assertEqual(receipt['contentionRetries'],1)
  self.assertEqual(receipt['contentionWaitMs'],1000)
  self.assertEqual(receipt['contentionEvents'][0]['reason'],'exact-group-result-count:0')
 def test_desktop_preflight_login_gate_does_not_retry(self):
  run=unittest.mock.Mock(return_value={'ok':False,'reason':'blocked-login','sendAttempts':0,'hardGate':True})
  with tempfile.TemporaryDirectory() as d,patch.object(desktop,'_windows_preflight_once',run):
   with self.assertRaises(s.StopRun):desktop.preflight(s.TEST_GROUP,Path(d),wait_seconds=10,poll_seconds=0)
  self.assertEqual(run.call_count,1)
 def test_desktop_preflight_window_capture_failure_does_not_retry(self):
  run=unittest.mock.Mock(return_value={'ok':False,'reason':'wechat-window-capture-failed','sendAttempts':0,'hardGate':True})
  with tempfile.TemporaryDirectory() as d,patch.object(desktop,'_windows_preflight_once',run):
   with self.assertRaisesRegex(s.StopRun,'wechat-window-capture-failed'):
    desktop.preflight(s.TEST_GROUP,Path(d),wait_seconds=10,poll_seconds=0)
  self.assertEqual(run.call_count,1)
 def test_unknown_send_is_never_retried(self):
  calls=[]
  def attempted():
   calls.append(1);return {'ok':False,'reason':'desktop-post-send-verification-unknown','sendAttempts':1}
  with tempfile.TemporaryDirectory() as d:
   receipt=desktop._wait_before_send(attempted,phase='send-before-attempt',output_dir=Path(d),wait_seconds=10,poll_seconds=0)
  self.assertEqual(len(calls),1)
  self.assertEqual(receipt['sendAttempts'],1)
  self.assertEqual(receipt['contentionWaitMs'],0)
 def delivery_fixture(self):
  import hashlib
  text='城市\n联系人\n商家\n地址';h=hashlib.sha256(text.encode()).hexdigest()
  item={'merchantId':'1','text':text,'sha256':h,'merchantName':'商家'}
  proof={'ok':True,'bubblePositions':[[1,2],[1,2]],'copyMenuCount':1,'composerEmpty':True,'copiedTextSha256':h}
  receipt={'ok':True,'verified':True,'state':'verified','sendAttempts':1,'physicalSendAttempts':1,
   'groupName':s.PRODUCTION_GROUP,'payloads':[{'text':text,'sha256':h}], 'copyReadback':proof,'postSendInputCleared':[True,True]}
  return item,receipt
 def test_unknown_send_delegates_readonly_common_reconcile(self):
  item,base=self.delivery_fixture();base['reconciledWithoutSend']=True
  with tempfile.TemporaryDirectory() as tmp:
   marker=Path(tmp)/'attempt.json';marker.write_text('{}')
   with patch.object(desktop.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout=json.dumps(base))) as run:
    result=desktop._reconcile_unknown(marker,s.PRODUCTION_GROUP,item,Path(tmp)/'evidence')
   command=run.call_args.args[0]
   self.assertIn('--reconcile',command);self.assertNotIn('--execute',command)
   self.assertIn('merchants',command);self.assertTrue(result['verified'])
 def test_common_reconcile_failure_cannot_be_committed(self):
  item,_=self.delivery_fixture()
  with tempfile.TemporaryDirectory() as tmp:
   marker=Path(tmp)/'attempt.json';marker.write_text('{}')
   with patch.object(desktop.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='{"ok":false,"verified":false}')):
    result=desktop._reconcile_unknown(marker,s.PRODUCTION_GROUP,item,Path(tmp)/'evidence')
   self.assertFalse(result['verified']);self.assertEqual(marker.read_text(),'{}')
 def test_common_success_requires_strong_copy_before_commit(self):
  item,base=self.delivery_fixture()
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);marker=root/'attempt.json'
   with patch.object(desktop,'_copy_exact_bubble') as readback:
    receipt=desktop._copy_verify_successful_send(marker,s.PRODUCTION_GROUP,item,root/'evidence',base)
   readback.assert_not_called();self.assertTrue(receipt['verified'])
   self.assertEqual(json.loads(marker.read_text())['messageSha256'],item['sha256'])
   base['copyReadback']['copiedTextSha256']='wrong'
   with self.assertRaisesRegex(RuntimeError,'delivery-evidence-incomplete'):
    desktop._copy_verify_successful_send(marker,s.PRODUCTION_GROUP,item,root/'evidence',base)
 def test_payload_anchor_accepts_split_long_name_with_two_exact_lines(self):
  hits=[SimpleNamespace(text='城市',cx=900,cy=500),SimpleNamespace(text='联系人',cx=920,cy=540),
        SimpleNamespace(text='很长商家名称上半段',cx=930,cy=580),SimpleNamespace(text='地址',cx=940,cy=620)]
  anchor=desktop._payload_bubble_anchor(hits,'城市\n联系人\n很长商家名称上半段下半段\n地址',1200,900)
  self.assertTrue(anchor['ok'])
  self.assertEqual(anchor['matchedLineIndexes'],[0,1,3])
 def test_payload_anchor_selects_latest_cluster_for_common_newness_check(self):
  one=[SimpleNamespace(text='城市',cx=900,cy=500)]
  self.assertTrue(desktop._payload_bubble_anchor(one,'城市\n联系人\n商家\n地址',1200,900)['ok'])
  duplicate=[SimpleNamespace(text='城市',cx=900,cy=300),SimpleNamespace(text='联系人',cx=920,cy=340),
             SimpleNamespace(text='城市',cx=900,cy=600),SimpleNamespace(text='联系人',cx=920,cy=640)]
  anchor=desktop._payload_bubble_anchor(duplicate,'城市\n联系人\n商家\n地址',1200,900)
  self.assertTrue(anchor['ok']);self.assertTrue(all(p[1]>=600 for p in anchor['linePositions'].values()))
 def test_payload_anchor_retries_same_frame_without_ui_action(self):
  sparse=[SimpleNamespace(text='无关文字',cx=900,cy=500)]
  full=[SimpleNamespace(text='城市',cx=900,cy=500),SimpleNamespace(text='联系人',cx=920,cy=540)]
  wd=SimpleNamespace(ocr=unittest.mock.Mock(side_effect=[sparse,full]),
                     find_exact_headers=lambda hits,group:[object()])
  with patch.object(desktop.time,'sleep'):
   anchor=desktop._read_unique_payload_anchor(wd,Path('/unchanged.png'),'群','城市\n联系人\n商家\n地址',1200,900)
  self.assertTrue(anchor['ok'])
  self.assertEqual(anchor['ocrAttempts'],2)
  self.assertEqual(wd.ocr.call_count,2)
 def test_payload_anchor_accepts_ax_header_when_ocr_header_is_zero(self):
  hits=[SimpleNamespace(text='城市',cx=900,cy=500)]
  wd=SimpleNamespace(ocr=unittest.mock.Mock(return_value=hits),find_exact_headers=lambda hits,group:[])
  anchor=desktop._read_unique_payload_anchor(
   wd,Path('/unchanged.png'),'群','城市\n联系人\n商家\n地址',1200,900,ax_header_confirmed=True)
  self.assertTrue(anchor['ok']);self.assertEqual(anchor['headerCount'],0)
  self.assertTrue(anchor['headerVerifiedByAX']);self.assertEqual(wd.ocr.call_count,1)
 def test_copy_readback_rejects_stale_clipboard(self):
  class Device:
   clipboard='expected'
   def set_clipboard(self,text,**kwargs):self.clipboard=text
  d=Device()
  h=SimpleNamespace(adb=lambda *a:None,screenshot=lambda *a:Path('image.png'),poll=lambda fn,pred,timeout:fn())
  with patch.object(Path,'is_file',return_value=True),patch.object(s.subprocess,'run',return_value=SimpleNamespace(stdout='400,1600\n')):
   with self.assertRaises(s.StopRun):s.copy_exact_text(d,'device',h,Path('.'),'expected',(200,1900))
  self.assertTrue(d.clipboard.startswith('verify-'))
 def test_ocr_middle_dot_not_chinese_substitution(self):
  self.assertEqual(s.normalize('店·凉面'),s.normalize('店•凉面'))
  self.assertEqual(s.normalize('店·米线'),s.normalize('店⋅米线'))
  self.assertNotEqual(s.normalize('甲店'),s.normalize('乙店'))
 def test_english_group_ocr_i_l_is_strictly_bounded(self):
  group='FEIBING NEO AI数字员工'
  self.assertTrue(s.exact_target_group_title('FEIBING NEO Al数字员工（18）',group))
  self.assertTrue(s.exact_target_group_title('FEIBING NEO AI数字员工',group))
  self.assertFalse(s.exact_target_group_title('FEIBING NEO Al数字员工 临时群',group))
  self.assertFalse(s.exact_target_group_title('FEIBING NEO A数字员工（18）',group))
 def test_search_input_is_not_group_title(self):
  group='FEIBING NEO AI数字员工'
  entries=[{'text':group,'y':163},{'text':'群聊','y':318},{'text':group+'(18)','y':452}]
  self.assertEqual(s.group_title_matches(entries,group),[])
 def test_current_search_sections_bound_unique_group(self):
  group='FEIBING NEO AI数字员工'
  entries=[{'text':'群聊','y':318},{'text':'FEIBING NEO Al数字员工（18）','y':452},
           {'text':'创建新的群聊','y':595},{'text':'聊天记录','y':792},
           {'text':'有人提到 FEIBING NEO AI数字员工','y':1000}]
  self.assertEqual(len(s.group_search_candidates(entries,group)),1)
 def test_stable_same_time(self):
  rows=[{'merchantId':'2','recommendTime':'2026-09-04 10:00:00'},{'merchantId':'1','recommendTime':'2026-09-04 10:00:00'}]
  self.assertEqual([x['merchantId'] for x in c.incremental(rows,{'recommendTime':'2026-09-03 00:00:00'},'2026-09-04')],['2','1'])
def test_missing_today_cursor_degrades_to_watermark(self):
 # 2026-10-22 契约变更（cursor-watermark 修复）：游标行被运营处理后移出「待处理」队列是常态，
 # matches=0 必须降级为「严格晚于游标推荐时间」的时间水位，不得阻塞当天全部增量。
 rows=[{'merchantId':'2','recommendTime':'2026-09-04 09:00:00'},{'merchantId':'3','recommendTime':'2026-09-04 11:00:00'}]
 got=c.incremental(rows,{'merchantId':'1','recommendTime':'2026-09-04 10:00:00'},'2026-09-04')
 self.assertEqual([x['merchantId'] for x in got],['3'])
def test_duplicate_cursor_row_still_stops(self):
 # 行身份不唯一（同 merchantId+recommendTime 多行）仍必须硬失败，防重复外发。
 rows=[{'merchantId':'1','recommendTime':'2026-09-04 10:00:00'},{'merchantId':'1','recommendTime':'2026-09-04 10:00:00'}]
 with self.assertRaises(c.UIError):c.incremental(rows,{'merchantId':'1','recommendTime':'2026-09-04 10:00:00'},'2026-09-04')
 def test_cursor_group_verified(self):
  self.assertFalse(c.valid_cursor({'verified':True,'groupName':'wrong'},s.TEST_GROUP))
 def test_claim_no_second_send(self):
  with tempfile.TemporaryDirectory() as d,patch.object(s,'STATE_DIR',Path(d)):
   item={'merchantId':'1','recommendTime':'2026-09-04 10:00:00','sha256':'hash'}
   s.claim_send(s.TEST_GROUP,item)
   with self.assertRaises(s.StopRun):s.claim_send(s.TEST_GROUP,item)
 def test_claim_group_isolation(self):
  item={'merchantId':'1','recommendTime':'2026-09-04 10:00:00'}
  self.assertNotEqual(s.send_identity('a',item),s.send_identity('b',item))
 def test_old_receipt_rejected(self):
  with self.assertRaises(s.StopRun):s.audit_collection({'businessDate':'2000-01-01'})
 def test_evidence_required(self):
  with self.assertRaises(s.StopRun):s.audit_collection({'businessDate':c.today()})
 def test_history_recovers_commit_gap(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);r={'verified':True,'groupName':s.TEST_GROUP,'merchantId':'1','recommendTime':'2026-09-04 10:00:00','tableOrder':1}
   (p/'send-history.jsonl').write_text(json.dumps(r)+'\n')
   self.assertEqual(c.cursor_state(p/'cursor.test.json',s.TEST_GROUP),(r,'verified-history'))
class SelectionAuditCursorTests(unittest.TestCase):
 # 2026-10-22：本文件上方自 183 行嵌套类之后存在缩进层级问题，部分 1 空格缩进的用例
 # 实际落在方法局部作用域、不会被 unittest 采集（文件内 37 个 def test_ / 仅 27 个加载）。
 # 新增用例统一挂在本顶层类下，确保真的被执行。
 def _receipt(self,rows,audit,cursor,messages):
  from datetime import datetime,timezone
  d=c.today()
  return {'businessDate':d,'dateFilterVerified':True,'paginationComplete':True,'ascending':True,
          'detailsVerified':True,
          'createdAt':datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%f')[:-3]+'Z',
          'filterStartDate':d,'filterEndDate':d,'dateFilter':f'{d}..{d}',
          'messages':messages,'totalRows':len(rows),'pendingRows':sum(r['status']=='待处理' for r in rows),
          'targetCount':len(messages),'selectionAudit':audit,'cursor':cursor}
 def test_audit_degrades_when_cursor_time_refreshed(self):
  # 游标商家再次提交意向，平台把 recommendTime 从 10:00:00 刷到 14:00:00 ⇒ 二元组在表内不存在。
  # 审计必须与采集器同步降级为时间水位（不阻塞、不重发），而不是抛 cursor-not-unique。
  d=c.today()
  rows=[{'merchantId':'111111','recommendTime':f'{d} 09:00:00','status':'待处理'},
        {'merchantId':'222222','recommendTime':f'{d} 14:00:00','status':'完成'},
        {'merchantId':'333333','recommendTime':f'{d} 15:00:00','status':'待处理'}]
  audit={'rows':rows,'totalRows':3,'pendingRows':2,'excludedAtOrBeforeCursor':1,
         'excludedAfterCursorNotPending':1,'targetCount':1}
  messages=[{'merchantId':'333333','recommendTime':f'{d} 15:00:00','tableOrder':3,
             'status':'待处理','detailVerified':True}]
  s.audit_collection(self._receipt(rows,audit,{'merchantId':'222222','recommendTime':f'{d} 10:00:00'},messages))
 def test_audit_rejects_refreshed_cursor_merchant_as_target(self):
  # 同一商家时间被刷新且仍「待处理」时，绝不能再进目标集（防重复外发）。
  d=c.today()
  rows=[{'merchantId':'111111','recommendTime':f'{d} 09:00:00','status':'待处理'},
        {'merchantId':'222222','recommendTime':f'{d} 14:00:00','status':'待处理'}]
  audit={'rows':rows,'totalRows':2,'pendingRows':2,'excludedAtOrBeforeCursor':1,
         'excludedAfterCursorNotPending':0,'targetCount':1}
  messages=[{'merchantId':'222222','recommendTime':f'{d} 14:00:00','tableOrder':2,
             'status':'待处理','detailVerified':True}]
  with self.assertRaisesRegex(s.StopRun,'cursor-merchant-retargeted'):
   s.audit_collection(self._receipt(rows,audit,{'merchantId':'222222','recommendTime':f'{d} 10:00:00'},messages))
if __name__=='__main__':unittest.main()
