import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import runtime_contract as contract
import workflow_executor as workflow
import desktop_wechat_sender as desktop
import wechat_sender_executor as sender
import executor_integrity as integrity
import structured_merchant_collector as collector

DAY = datetime(2026, 10, 28, 8, 30, tzinfo=ZoneInfo('Asia/Shanghai'))
OLD = DAY - timedelta(days=1)


class CrossdayDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.group = sender.PRODUCTION_GROUP
        self.items = []
        for i in (1, 2):
            text = f'city ; contact ; shop{i} ; address'
            self.items.append({'merchantId': str(12345670+i), 'merchantName': f'shop{i}',
                'recommendTime': f'2026-10-27 10:00:0{i}', 'tableOrder': i,
                'text': text, 'sha256': hashlib.sha256(text.encode()).hexdigest()})
        self.base = {'schemaVersion': 1, 'groupName': self.group, 'verified': True,
            'merchantId': '12345000', 'recommendTime': '2026-10-26 08:00:00', 'tableOrder': 0}
        for name, value in [('STATE_DIR', self.root), ('HISTORY_FILE', self.root/'history.jsonl')]:
            p = patch.object(sender, name, value); p.start(); self.addCleanup(p.stop)
        p = patch.object(contract, '_dispatch_now', return_value=DAY); p.start(); self.addCleanup(p.stop)
        sender.cursor_file(self.group).write_text(json.dumps(self.base))
        sender.HISTORY_FILE.write_text('')
        self.path = self.root/'collection.json'
        self.collection = self.source(self.items, DAY, self.path)

    def source(self, items, now, path):
        value = {'ok': True, 'executor': 'merchant-collector', 'groupName': self.group,
                 'businessDate': now.strftime('%Y-%m-%d'), 'cursor': self.base,
                 'messages': copy.deepcopy(items)}
        path.write_text(json.dumps(value))
        return value

    def marker_path(self, item, group=None):
        return self.root/'send-attempts'/(sender.send_identity(group or self.group, item)+'.json')

    def unknown(self, item, old=True, group=None):
        group = group or self.group
        if old:
            path = self.root/(item['merchantId']+'-old-source.json')
            source = self.source([item], OLD, path)
            contract.record_dispatch_origin(sender, group, item, source, path, now=OLD)
        marker = {'state': 'unknown', 'verified': False, 'groupName': group,
                  'sendAttempts': 1, 'physicalSendAttempts': 1, 'payloadType': 'text',
                  'payloads': [{'text': item['text'], 'sha256': item['sha256']}],
                  'merchantId': item['merchantId'], 'messageSha256': item['sha256']}
        path = self.marker_path(item, group); path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(marker))
        return path

    def plan(self, register=True):
        return contract.day_dispatch(sender, self.group, self.collection, self.path, register=register)

    def test_old_unknown_is_durable_without_changing_marker_cursor_or_history(self):
        marker = self.unknown(self.items[0]); original = marker.read_bytes()
        cursor = sender.cursor_file(self.group).read_bytes()
        plan = self.plan()
        self.assertEqual(plan['eligibleIdentities'], [sender.send_identity(self.group, self.items[1])])
        self.assertEqual(len(plan['historicalDeferred']), 1)
        self.assertEqual(marker.read_bytes(), original)
        self.assertEqual(sender.cursor_file(self.group).read_bytes(), cursor)
        self.assertEqual(sender.HISTORY_FILE.read_text(), '')
        self.assertTrue(Path(plan['historicalDeferred'][0]['recordPath']).is_file())
        self.assertTrue(contract.validate_day_dispatch(sender,self.group,self.collection,self.path,plan))

    def test_recommendation_date_alone_is_not_old_attempt_proof(self):
        self.unknown(self.items[0], old=False)
        plan = self.plan()
        self.assertEqual(len(plan['eligibleIdentities']), 2)
        self.assertEqual(plan['historicalDeferred'], [])

    def test_latest_current_preparation_overrides_old_identical_byte_observation(self):
        item=self.items[0]
        contract.record_dispatch_origin(sender,self.group,item,self.collection,self.path)
        marker=self.unknown(item,old=False)
        identity=sender.send_identity(self.group,item)
        (self.root/'attempt-observations-v1.json').write_text(json.dumps({'schemaVersion':1,'entries':{
            identity:[{'markerSha256':hashlib.sha256(marker.read_bytes()).hexdigest(),
                       'groupName':self.group,'firstObservedAt':OLD.isoformat()}]}}))
        self.assertEqual(self.plan()['historicalDeferred'], [])

    def test_legacy_exact_bytes_observed_on_old_day_can_be_deferred(self):
        self.unknown(self.items[0],old=False)
        old_path=self.root/'observed-old.json';old=self.source(self.items,OLD,old_path)
        contract.day_dispatch(sender,self.group,old,old_path,register=True,now=OLD)
        self.assertEqual(len(self.plan()['historicalDeferred']),1)

    def test_unknown_origin_cannot_be_overwritten(self):
        self.unknown(self.items[0])
        with self.assertRaisesRegex(RuntimeError,'existing-attempt'):
            contract.record_dispatch_origin(sender,self.group,self.items[0],self.collection,self.path)

    def test_marker_change_and_forged_partition_are_rejected(self):
        marker=self.unknown(self.items[0]);plan=self.plan()
        bad=copy.deepcopy(plan);bad['eligibleIdentities']=[]
        with self.assertRaises(RuntimeError):
            contract.validate_day_dispatch(sender,self.group,self.collection,self.path,bad)
        data=json.loads(marker.read_text());data['reason']='changed';marker.write_text(json.dumps(data))
        with self.assertRaises(RuntimeError):
            contract.validate_day_dispatch(sender,self.group,self.collection,self.path,plan)

    def test_registration_failure_stops_before_any_send(self):
        self.unknown(self.items[0])
        original=sender.atomic_write_json
        def write(path,value):
            if 'historical-pending' in Path(path).parts:raise OSError('disk-full')
            return original(path,value)
        with patch.object(sender,'atomic_write_json',side_effect=write),patch.object(desktop.subprocess,'run') as run:
            with self.assertRaises(OSError):self.plan()
        run.assert_not_called()

    def test_reused_pending_record_does_not_depend_on_daily_table_position(self):
        self.unknown(self.items[0]);self.plan()
        self.collection['messages'][0]['tableOrder']=99
        self.path.write_text(json.dumps(self.collection))
        self.assertEqual(len(self.plan()['historicalDeferred']),1)

    def test_old_payload_conflict_is_kept_without_sending_replacement(self):
        self.unknown(self.items[0])
        item=self.collection['messages'][0];item['text']='changed ; contact ; shop ; address'
        item['sha256']=hashlib.sha256(item['text'].encode()).hexdigest();self.path.write_text(json.dumps(self.collection))
        plan=self.plan();self.assertTrue(plan['historicalDeferred'][0]['payloadConflict'])
        self.assertEqual(len(plan['eligibleIdentities']),1)

    def test_wrong_group_does_not_become_historical_permission(self):
        path=self.unknown(self.items[0]);data=json.loads(path.read_text());data['groupName']='wrong';path.write_text(json.dumps(data))
        with self.assertRaisesRegex(RuntimeError,'group-mismatch'):self.plan()

    def test_changed_source_is_rejected(self):
        self.path.write_text('{}')
        with self.assertRaisesRegex(RuntimeError,'source-binding'):self.plan()

    def test_future_origin_is_not_historical(self):
        item=self.items[0];future=self.root/'future.json';source=self.source([item],DAY+timedelta(days=1),future)
        contract.record_dispatch_origin(sender,self.group,item,source,future,now=DAY+timedelta(days=1))
        self.unknown(item,old=False)
        self.assertEqual(self.plan()['historicalDeferred'],[])

    def test_only_old_items_allow_original_empty_slot_notice_and_keep_cursor(self):
        self.unknown(self.items[0]);self.collection=self.source([self.items[0]],DAY,self.path);plan=self.plan()
        argv=workflow.empty_notice_arguments(self.collection,self.group,now=DAY,dispatch_plan=plan,collection_path=self.path)
        self.assertIn('empty-202610280830.json',argv)
        result=contract.audit_final(sender,self.group,self.collection,'desktop',dispatch_plan=plan,collection_path=self.path)
        self.assertTrue(result['verified']);self.assertEqual(result['checkedDeliveries'],0)
        self.assertEqual(json.loads(sender.cursor_file(self.group).read_text()),self.base)
        with patch.object(sender,'audit_collection'),patch.object(desktop.subprocess,'run') as run:
            delivery=desktop.run(self.path,self.group,contract.PRODUCTION_AUTHORIZATION,self.root/'out',dispatch_plan=plan)
        run.assert_not_called();self.assertTrue(delivery['ok'])

    def test_empty_notice_rejects_current_items_and_unregistered_historical_claim(self):
        self.unknown(self.items[0]);plan=self.plan()
        with self.assertRaises(RuntimeError):
            workflow.empty_notice_arguments(self.collection,self.group,now=DAY,dispatch_plan=plan,collection_path=self.path)
        with self.assertRaises(RuntimeError):workflow.empty_notice_arguments(self.collection,self.group,now=DAY)

    def test_original_current_send_path_is_used_once_and_only_then_advances_cursor(self):
        old_marker=self.unknown(self.items[0]);old_bytes=old_marker.read_bytes();plan=self.plan();item=self.items[1]
        def publish(*args,**kwargs):
            origin=json.loads((self.root/'dispatch-origins'/(sender.send_identity(self.group,item)+'.json')).read_text())
            self.assertEqual(origin['preparations'][-1]['businessDate'],'2026-10-28')
            receipt={'ok':True,'verified':True,'state':'verified','groupName':self.group,
                     'sendAttempts':1,'physicalSendAttempts':1,'merchantId':item['merchantId'],
                     'messageSha256':item['sha256'],'payloads':[{'text':item['text'],'sha256':item['sha256']}],
                     'postSendInputCleared':[True,True],'copyReadback':{'ok':True,'composerEmpty':True,
                     'copyMenuCount':1,'bubblePositions':[[1,2],[1,2]],'copiedTextSha256':item['sha256']}}
            self.marker_path(item).write_text(json.dumps(receipt))
            return SimpleNamespace(returncode=0,stdout=json.dumps(receipt))
        with patch.object(sender,'audit_collection'),patch.object(desktop.subprocess,'run',side_effect=publish) as run, \
                patch.object(desktop,'_copy_verify_successful_send',side_effect=lambda marker,group,item,out,receipt:receipt):
            result=desktop.run(self.path,self.group,contract.PRODUCTION_AUTHORIZATION,self.root/'out',dispatch_plan=plan)
        self.assertTrue(result['ok'],result);self.assertEqual(run.call_count,1)
        self.assertEqual(old_marker.read_bytes(),old_bytes)
        self.assertEqual(json.loads(sender.cursor_file(self.group).read_text())['merchantId'],item['merchantId'])
        self.assertEqual(len(sender.HISTORY_FILE.read_text().splitlines()),1)
        self.assertTrue(contract.audit_final(sender,self.group,self.collection,'desktop',dispatch_plan=plan,collection_path=self.path)['verified'])

    def test_same_day_unknown_still_reconciles_only_and_cannot_send_later_item(self):
        self.unknown(self.items[0],old=False);plan=self.plan()
        with patch.object(sender,'audit_collection'),patch.object(desktop,'_reconcile_unknown',return_value={'ok':False,'reason':'not-visible'}) as reconcile, \
                patch.object(desktop.subprocess,'run') as send:
            result=desktop.run(self.path,self.group,contract.PRODUCTION_AUTHORIZATION,self.root/'out',
                               reconciliation_only=True,dispatch_plan=plan)
        self.assertFalse(result['ok']);reconcile.assert_called_once();send.assert_not_called()
        self.assertEqual(sender.HISTORY_FILE.read_text(),'')

    def test_multiple_old_items_preserve_order_of_multiple_current_items(self):
        for item in self.items:self.unknown(item)
        more=[]
        for n in (3,4):
            item=copy.deepcopy(self.items[0]);item.update(merchantId=str(12345670+n),tableOrder=n)
            item['text']=f'city ; contact ; shop{n} ; address'
            item['sha256']=hashlib.sha256(item['text'].encode()).hexdigest();more.append(item)
        self.collection=self.source(self.items+more,DAY,self.path)
        plan=self.plan();self.assertEqual(len(plan['historicalDeferred']),2)
        self.assertEqual(plan['eligibleIdentities'],[sender.send_identity(self.group,x) for x in more])

    def test_attempt_count_null_is_preserved_when_old_attempt_is_deferred(self):
        path=self.unknown(self.items[0]);v=json.loads(path.read_text())
        v.update(state='attempted',sendAttempts=None,physicalSendAttempts=None);path.write_text(json.dumps(v))
        raw=path.read_bytes();self.assertEqual(len(self.plan()['historicalDeferred']),1)
        self.assertEqual(path.read_bytes(),raw)

    def test_origin_parent_symlink_cannot_escape_state_root(self):
        with tempfile.TemporaryDirectory() as other:
            (self.root/'dispatch-origins').symlink_to(other,target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError,'symlink-or-escape'):
                contract.record_dispatch_origin(sender,self.group,self.items[0],self.collection,self.path)
            self.assertEqual(list(Path(other).iterdir()),[])

    def test_historical_only_plan_does_not_authorize_cursor_jump(self):
        self.unknown(self.items[0]);self.collection=self.source([self.items[0]],DAY,self.path);plan=self.plan()
        sender.cursor_file(self.group).write_text(json.dumps(self.base|{'merchantId':'changed'}))
        with self.assertRaisesRegex(RuntimeError,'noop-cursor-changed'):
            contract.audit_final(sender,self.group,self.collection,'desktop',dispatch_plan=plan,collection_path=self.path)

    def test_non_text_marker_does_not_become_historical_text_permission(self):
        path=self.unknown(self.items[0]);v=json.loads(path.read_text());v['payloadType']='image';path.write_text(json.dumps(v))
        with self.assertRaisesRegex(RuntimeError,'payload-kind'):self.plan()

    def test_attempt_cannot_predate_the_recommendation_identity(self):
        item=self.items[0];item['recommendTime']='2026-10-28 07:00:00'
        self.unknown(item);self.collection=self.source(self.items,DAY,self.path)
        with self.assertRaisesRegex(RuntimeError,'recommendation-after-old-attempt'):self.plan()

    def test_original_workflow_preflights_current_item_and_commits_only_current_delivery(self):
        now=datetime.now(ZoneInfo('Asia/Shanghai'));old=now-timedelta(days=1)
        first,second=copy.deepcopy(self.items)
        self.base['recommendTime']=old.strftime('%Y-%m-%d')+' 08:00:00'
        sender.cursor_file(self.group).write_text(json.dumps(self.base))
        for n,(item,stamp) in enumerate(((first,old),(second,now)),2):
            item.update(recommendTime=stamp.strftime('%Y-%m-%d')+' 10:00:00',tableOrder=n,
                        detailVerified=True,status='待处理')
        old_path=self.root/'prior-source.json';prior=self.source([first],old,old_path)
        contract.record_dispatch_origin(sender,self.group,first,prior,old_path,now=old)
        old_marker=self.unknown(first,old=False);old_bytes=old_marker.read_bytes()
        collection=self.source([first,second],now,self.path)
        collection.update(createdAt=now.isoformat(),dateFilterVerified=True,paginationComplete=True,
            ascending=True,detailsVerified=True,filterStartDate=old.strftime('%Y-%m-%d'),
            filterEndDate=now.strftime('%Y-%m-%d'),
            dateFilter=old.strftime('%Y-%m-%d')+'..'+now.strftime('%Y-%m-%d'),
            totalRows=3,pendingRows=3,targetCount=2,selectionAudit={'totalRows':3,'pendingRows':3,
            'excludedAtOrBeforeCursor':1,'excludedAfterCursorNotPending':0,'targetCount':2,
            'rows':[self.base|{'status':'待处理'},first,second]})
        self.path.write_text(json.dumps(collection));sender.audit_collection(collection)
        def publish(*args,**kwargs):
            self.assertIn(second['text'],args[0]);self.assertNotIn(first['text'],args[0])
            receipt={'ok':True,'verified':True,'state':'verified','groupName':self.group,
                'sendAttempts':1,'physicalSendAttempts':1,'merchantId':second['merchantId'],
                'messageSha256':second['sha256'],'payloads':[{'text':second['text'],'sha256':second['sha256']}],
                'postSendInputCleared':[True,True],'copyReadback':{'ok':True,'composerEmpty':True,
                'copyMenuCount':1,'bubblePositions':[[1,2],[1,2]],'copiedTextSha256':second['sha256']}}
            self.marker_path(second).write_text(json.dumps(receipt))
            return SimpleNamespace(returncode=0,stdout=json.dumps(receipt))
        args=workflow.build_parser().parse_args(['--standing-authorization',contract.PRODUCTION_AUTHORIZATION,
                                               '--output-dir',str(self.root/'workflow')])
        with patch.object(contract,'_dispatch_now',return_value=now), \
                patch.object(integrity,'verify_for_run',return_value={'ok':True,'status':'SEALED'}), \
                patch.object(contract,'offline_selftest',return_value={'ok':True}), \
                patch.object(collector,'collect',return_value=collection), \
                patch.object(desktop,'preflight',return_value={'ok':True}) as preflight, \
                patch.object(desktop.subprocess,'run',side_effect=publish) as send, \
                patch.object(desktop,'_copy_verify_successful_send',side_effect=lambda marker,group,item,out,receipt:receipt):
            result=workflow.execute(args)
        self.assertTrue(result['ok'],result)
        preflight.assert_called_once();send.assert_called_once()
        self.assertEqual(preflight.call_args.kwargs['pending_item']['merchantId'],second['merchantId'])
        self.assertEqual(len(result['dayDispatch']['historicalDeferred']),1)
        self.assertEqual(result['finalCursor']['merchantId'],second['merchantId'])
        self.assertEqual(old_marker.read_bytes(),old_bytes)

    def test_attempt_appearing_before_send_blocks_and_preserves_unknown_count(self):
        self.collection=self.source([self.items[0]],DAY,self.path);plan=self.plan()
        validate=contract.validate_day_dispatch;calls=[]
        def racing(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:
                path=self.unknown(self.items[0],old=False);data=json.loads(path.read_text())
                data.update(sendAttempts=None,physicalSendAttempts=None);path.write_text(json.dumps(data))
            return validate(*args,**kwargs)
        with patch.object(sender,'audit_collection'),patch.object(contract,'validate_day_dispatch',side_effect=racing), \
                patch.object(desktop.subprocess,'run') as send:
            result=desktop.run(self.path,self.group,contract.PRODUCTION_AUTHORIZATION,self.root/'out',dispatch_plan=plan)
        self.assertFalse(result['ok']);send.assert_not_called()
        self.assertIsNone(result['desktop']['sendAttempts'])
        self.assertEqual(sender.HISTORY_FILE.read_text(),'')

    def test_internal_review_keeps_historical_unknown_separate_from_current_completion(self):
        self.unknown(self.items[0]);plan=self.plan()
        review=contract.build_review({'runId':'synthetic','ok':True,'elapsedMs':1,'dayDispatch':plan,'wechat':{}})
        self.assertEqual(review['historicalDeferred'],plan['historicalDeferred'])
        self.assertIn('历史待核',contract.render_review(review))
        self.assertEqual(review['sent'],0)


if __name__=='__main__':unittest.main()
