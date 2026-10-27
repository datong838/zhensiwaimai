import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import wechat_file_sender as s
from resume_flow import next_action, validate_binding, retryable


class ResumeTests(unittest.TestCase):
    def test_inflight_transition_mismatch_only_verifies(self):
        item={'platform':'taobao','name':'a.xlsx','sha256':'h'}
        ledger={'files':{'h':{'state':'in-flight'}}}
        def verify(*args): ledger['files']['h']['state']='confirmed'
        with tempfile.TemporaryDirectory() as folder:
            cp=Path(folder)/'cp.json';cp.write_text(json.dumps({'group':s.TARGET_GROUP,'hashes':{'taobao':'h'},'activeHash':'h','groupVerified':True,'events':[]}))
            with patch.object(s,'load_delivery_ledger',side_effect=lambda:ledger),patch.object(s,'observe_file_page',side_effect=s.StopRun('selected-file-name-size-mismatch')),patch.object(s,'verify_sent_file',side_effect=verify) as checked,patch.object(s,'retry_proven_unsent') as retry,patch.object(s,'prepare_selected_send') as send:
                s.deliver_with_resume(Mock(),'serial',Mock(),Mock(),Path(folder),[item],{'sent':[],'sendAttempts':0},cp)
            checked.assert_called_once();retry.assert_not_called();send.assert_not_called()

    def test_collapsed_selection_expands_without_sending(self):
        d=Mock(); d.app_current.return_value={'package':'com.tencent.mm','activity':'FileSelectorUI'}
        entries=[{'text':'已选中1个文件','x':400,'y':2080,'w':280,'h':40}]
        with patch.object(s,'screenshot_entries',return_value=('shot',entries)),patch.object(s,'selected_send_signature',return_value=None):
            self.assertEqual(s.observe_file_page(d,Mock(),Path('/tmp'),{'name':'a.xlsx'}),'obscured')
        d.click.assert_called_once_with(75,2080)

    def test_local_frequent_group_not_network_result(self):
        local={'text':s.TARGET_GROUP+'(3)','y':460,'x':350}
        entries=[{'text':'最常使用','y':318},local,{'text':'搜索网络结果','y':620},{'text':s.TARGET_GROUP+'(3)','y':735}]
        self.assertEqual(s.local_group_candidate(entries),local)
        self.assertIsNone(s.local_group_candidate(entries+[dict(local)]))
        local['text'] += 'Q'
        self.assertEqual(s.local_group_candidate(entries),local)
        local['text'] += 'other'
        self.assertIsNone(s.local_group_candidate(entries))

    def test_folder_header_not_list_row(self):
        d=Mock()
        d.dump_hierarchy.return_value='<hierarchy><node text="zhensi_reports" resource-id="android:id/title" bounds="[20,400][500,500]"/></hierarchy>'
        self.assertFalse(s.current_picker_folder(d,'zhensi_reports'))
        d.dump_hierarchy.return_value='<hierarchy><node resource-id="com.android.documentsui:id/dropdown_breadcrumb"><node text="zhensi_reports" resource-id="android:id/title" bounds="[240,127][629,208]"/></node></hierarchy>'
        self.assertTrue(s.current_picker_folder(d,'zhensi_reports'))

    def test_delayed_exact_folder_waits_without_root_traversal(self):
        d=Mock(); target=Mock();d.return_value=target
        d.app_current.return_value={'package':'com.android.documentsui'}
        target.exists.side_effect=[False,True,True];target.count=1
        target.info={'bounds':{'left':20,'right':500,'top':400,'bottom':500}}
        with patch.object(s.time,'sleep'),patch.object(s,'current_picker_folder',return_value=True):
            s.open_picker_folder(d,'zhensi_reports')
        d.swipe.assert_not_called();target.scroll.toBeginning.assert_not_called();target.click.assert_called_once()

    def test_router_current_pages_and_ledger(self):
        for page, action in [('group','panel'),('file_selector','select'),('picker','choose'),('selected','send'),('home','locate'),('obscured','wait')]:
            self.assertEqual(next_action(None,page,True),action)
            self.assertEqual(next_action('in-flight',page,True),'verify')
            self.assertEqual(next_action('confirmed',page,False),'done')

    def test_unbound_picker_or_sheet_never_sent(self):
        for page in ['picker','selected','file_selector']:
            with self.assertRaisesRegex(RuntimeError,'unbound'):
                next_action(None,page,False)

    def test_changed_hash_or_group_rejected(self):
        saved={'group':'g','hashes':{'m':'h'}}
        validate_binding(saved,'g',{'m':'h'})
        for group, hashes in [('other',{'m':'h'}),('g',{'m':'wrong'})]:
            with self.assertRaisesRegex(RuntimeError,'binding'):
                validate_binding(saved,group,hashes)

    def test_only_transient_failure_retried(self):
        self.assertTrue(retryable('transient-page-obscured'))
        self.assertTrue(retryable('report-list-not-stable'))
        for reason in ['selected-file-name-size-mismatch','checkpoint-binding-mismatch','physical-device-identity-mismatch']:
            self.assertFalse(retryable(reason))

    def test_list_waits_for_rows_and_two_identical_frames(self):
        def xml(bounds=None):
            row='' if bounds is None else f'<node resource-id="android:id/title" text="a.xlsx" bounds="{bounds}"/>'
            return '<hierarchy><node text="zhensi_reports"/>'+row+'</hierarchy>'
        d=Mock();d.app_current.return_value={'package':'com.android.documentsui'}
        d.dump_hierarchy.side_effect=[xml(),xml('moving'),xml('stable'),xml('stable')]
        with patch.object(s.time,'sleep'):
            self.assertEqual(s.stable_report_rows(d),(('a.xlsx','stable'),))
        self.assertEqual(d.dump_hierarchy.call_count,4)

    def test_obscured_then_resume_current_picker_no_restart(self):
        item={'platform':'meituan','sha256':'hash','name':'a.xlsx'}
        ledger={'files':{}}
        result={'sent':[],'sendAttempts':0}
        with tempfile.TemporaryDirectory() as folder:
            cp=Path(folder)/'flow.json'
            cp.write_text(json.dumps({'group':s.TARGET_GROUP,'hashes':{'meituan':'hash'},'activeHash':'hash','groupVerified':True,'events':[]}))
            def send(*args):ledger['files']['hash']={'state':'in-flight'}
            def verify(*args):ledger['files']['hash']={'state':'confirmed'}
            with patch.object(s,'load_delivery_ledger',side_effect=lambda:ledger),patch.object(s,'observe_file_page',side_effect=['obscured','picker','selected','group']),patch.object(s,'choose_system_file') as choose,patch.object(s,'prepare_selected_send',side_effect=send) as send_mock,patch.object(s,'verify_sent_file',side_effect=verify),patch.object(s.time,'sleep'),patch.object(s,'open_file_panel') as panel:
                s.deliver_with_resume(Mock(),'runtime',Mock(),Mock(),Path(folder),[item],result,cp)
            choose.assert_called_once();send_mock.assert_called_once();panel.assert_not_called()
            saved=json.loads(cp.read_text());self.assertTrue(saved['businessCompleted'])
            self.assertEqual(saved['events'][0]['retry'],1)
            self.assertEqual(result['sendAttempts'],1)

    def test_confirmed_skips_observation_and_send(self):
        item={'platform':'meituan','sha256':'h','name':'a.xlsx'}
        with tempfile.TemporaryDirectory() as folder,patch.object(s,'load_delivery_ledger',return_value={'files':{'h':{'state':'confirmed'}}}),patch.object(s,'observe_file_page') as observe:
            result={'sent':[],'sendAttempts':0}
            s.deliver_with_resume(Mock(),'runtime',Mock(),Mock(),Path(folder),[item],result,Path(folder)/'cp.json')
            observe.assert_not_called();self.assertEqual(result['sendAttempts'],0)

    def test_missed_send_max_one_recovery(self):
        with patch.object(s,'load_delivery_ledger',return_value={'files':{'h':{'state':'in-flight','filePickerSendClicks':2}}}),patch.object(s,'stable_selected_send') as stable:
            with self.assertRaisesRegex(s.StopRun,'send-recovery'):
                s.retry_proven_unsent(Mock(),Mock(),Path('/tmp'),{'sha256':'h'},True)
            stable.assert_not_called()


if __name__=='__main__':unittest.main()
