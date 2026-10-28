import hashlib
import json
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
import business_delivery_facts as facts
from test_executed_image_acceptance import ExecutedImageAcceptanceTests


class StandingImagePolicyTests(unittest.TestCase):
    def setUp(self):
        self.f=ExecutedImageAcceptanceTests('test_acceptance_keeps_original_unknown_bytes')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.current_confirmation();self.f.accept_path.unlink()
        self.policy=self.f.root/'runtime/policies/submitted-image-business-policy.json'
        self.policy.parent.mkdir(parents=True)
        self.data={'source':'explicit-user-standing-instruction','recordedAt':'2026-10-28T20:00:00+08:00',
                   'userQuote':facts.SUBMITTED_IMAGE_POLICY_QUOTE,'businessCompleteOnBoundSingleSubmission':True,
                   'preserveTechnicalStatus':True,'noResend':True,'clientTechnicalDetails':False}
        self.save();self.advance(datetime(2026,10,29,20,tzinfo=ZoneInfo('Asia/Shanghai')))
    def save(self):self.policy.write_text(json.dumps(self.data,ensure_ascii=False))
    def advance(self,now):
        f=self.f;f.now=now;day=now.strftime('%Y-%m-%d');item=f.task['item']
        item['name']=day+'_合同解约申请_处理中_p1.png'
        f.task['request']['items']=[item];f.task['request']['context']['eventId']=day+'-contract'
        f.task.pop('binding',None)
        binding=hashlib.sha256(json.dumps(f.task,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        f.task['binding']=binding;f.dump('task.json',f.task)
        for name in ('response.json','send-intent.json'):
            value=json.loads((f.folder/name).read_text());value['binding']=binding
            if name=='send-intent.json':value['at']=now.replace(hour=9).timestamp()
            f.dump(name,value)
    def fact(self):return facts.read_fact(self.f.flow,self.f.now)
    def test_future_days_work_without_manual_confirmation_or_date_whitelist(self):
        for now in (datetime(2026,10,29,20,tzinfo=ZoneInfo('Asia/Shanghai')),
                    datetime(2026,11,5,20,tzinfo=ZoneInfo('Asia/Shanghai')),
                    datetime(2027,1,2,20,tzinfo=ZoneInfo('Asia/Shanghai'))):
            self.advance(now);before=self.f.hashes();value=self.fact()
            self.assertTrue(value['businessDelivered']);self.assertFalse(value['humanConfirmationRequired'])
            self.assertEqual(value['technicalStatusPreserved'],'unknown');self.assertEqual(value['newSendAttempts'],0)
            self.assertEqual(before,self.f.hashes())
    def test_next_day_requires_its_own_submission(self):
        self.f.now=self.f.now.replace(day=30);self.assertIsNone(self.fact())
    def test_policy_is_required_and_can_be_withdrawn(self):
        self.policy.unlink();self.assertIsNone(self.fact())
    def test_wrong_policy_quote_or_permission_flags_rejected(self):
        original=dict(self.data)
        for change in ({'userQuote':'wrong'},{'preserveTechnicalStatus':False},{'noResend':False},
                       {'clientTechnicalDetails':True},{'recordedAt':'2026-11-01T20:00:00+08:00'}):
            self.data=original|change;self.save();self.assertIsNone(self.fact())
    def test_no_submission_intent_is_not_business_completion(self):
        (self.f.folder/'send-intent.json').unlink();self.assertIsNone(self.fact())
    def test_zero_submission_and_boolean_attempt_count_rejected(self):
        for count in (0,True):
            value=json.loads((self.f.folder/'response.json').read_text());value['result']['sendAttempts']=count
            self.f.dump('response.json',value);self.assertIsNone(self.fact())
    def test_wrong_group_or_nonempty_input_rejected(self):
        for change in ({'resolvedGroup':'wrong'},{'inputEmpty':False}):
            value=json.loads((self.f.folder/'response.json').read_text());value['result'].update(change)
            self.f.dump('response.json',value);self.assertIsNone(self.fact())
    def test_changed_source_or_old_business_filename_rejected(self):
        self.f.task['item']['name']='2026-10-27_合同解约申请_处理中_p1.png'
        self.f.dump('task.json',self.f.task);self.assertIsNone(self.fact())
    def test_remote_three_flows_not_accepted_by_this_policy(self):
        for flow in ('daily-store-metrics-rotation-to-wechat','store-inspection','coupon-issue-task-flow'):
            self.assertIsNone(facts.read_fact(flow,self.f.now))
    def test_later_than_current_read_intent_rejected(self):
        value=json.loads((self.f.folder/'send-intent.json').read_text());value['at']=self.f.now.timestamp()+1
        self.f.dump('send-intent.json',value);self.assertIsNone(self.fact())
    def test_non_image_item_on_same_route_does_not_block_the_original_image(self):
        folder=self.f.folder.parent/'other-original-label';folder.mkdir()
        (folder/'send-intent.json').write_bytes((self.f.folder/'send-intent.json').read_bytes())
        (folder/'response.json').write_bytes((self.f.folder/'response.json').read_bytes())
        task=json.loads((self.f.folder/'task.json').read_text());task['item']={'type':'text','text':'original-label'}
        (folder/'task.json').write_text(json.dumps(task))
        self.assertTrue(self.fact()['businessDelivered'])
    def test_proven_zero_send_item_does_not_shadow_the_later_valid_submission(self):
        folder=self.f.folder.parent/'prior-zero-send';folder.mkdir()
        for name in ('task.json','send-intent.json'):(folder/name).write_bytes((self.f.folder/name).read_bytes())
        reply=json.loads((self.f.folder/'response.json').read_text());reply['result'].update(status='blocked',sendAttempts=0)
        (folder/'response.json').write_text(json.dumps(reply))
        self.assertTrue(self.fact()['businessDelivered'])
    def test_verified_original_keeps_verified_status_and_requires_both_observations(self):
        reply=json.loads((self.f.folder/'response.json').read_text())
        reply['result'].update(status='verified',sha256=self.f.task['item']['sha256'],observations=[{'groupName':facts.GROUP,'inputEmpty':True}]*2)
        self.f.dump('response.json',reply)
        self.assertEqual(self.fact()['technicalStatusPreserved'],'verified')
        reply['result']['observations']=reply['result']['observations'][:1];self.f.dump('response.json',reply)
        self.assertIsNone(self.fact())


if __name__=='__main__':unittest.main()
