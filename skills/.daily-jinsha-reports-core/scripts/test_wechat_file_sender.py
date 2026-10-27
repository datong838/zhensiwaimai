import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch
import wechat_file_sender as sender


class SenderTests(unittest.TestCase):
    def test_stable_picker_target_waits_for_drawer_animation(self):
        d=Mock();d.app_current.return_value={"package":"com.android.documentsui"}
        target=Mock();target.exists.return_value=True;target.count=1
        a={"left":10,"right":100,"top":20,"bottom":80}
        b={**a,"left":20}
        type(target).info=__import__('unittest.mock',fromlist=['PropertyMock']).PropertyMock(
            side_effect=[{"bounds":a},{"bounds":b},{"bounds":b}])
        with patch.object(sender.time,'sleep'):
            sender.click_stable_picker_node(d,target,'下载内容')
        target.click.assert_called_once()

    def test_duplicate_picker_target_rejected(self):
        d=Mock();d.app_current.return_value={"package":"com.android.documentsui"}
        target=Mock();target.exists.return_value=True;target.count=2
        with self.assertRaisesRegex(sender.StopRun,'picker-target-not-unique'):
            sender.click_stable_picker_node(d,target,'下载内容')
        target.click.assert_not_called()

    def test_missing_picker_target_rejected_without_scroll(self):
        d=Mock();target=Mock();target.exists.return_value=False
        d.app_current.return_value={"package":"com.android.documentsui"}
        with patch.object(sender.time,'monotonic',side_effect=[0,1,6]),patch.object(sender.time,'sleep'):
            with self.assertRaisesRegex(sender.StopRun,'page-not-ready:picker-target'):
                sender.click_stable_picker_node(d,target,'下载内容')
        target.click.assert_not_called();d.swipe.assert_not_called()

    def test_folder_click_does_not_scroll_back_to_top(self):
        d=Mock()
        with patch.object(sender,'click_stable_picker_node') as click,patch.object(sender,'current_picker_folder',return_value=True):
            sender.open_picker_folder(d,'zhensi_reports')
        click.assert_called_once();d.return_value.scroll.toBeginning.assert_not_called()

    def test_folder_transition_requires_directory_evidence(self):
        with patch.object(sender,'click_stable_picker_node'),patch.object(sender,'current_picker_folder',return_value=False),patch.object(sender.time,'monotonic',side_effect=[0,1,6]),patch.object(sender.time,'sleep'):
            with self.assertRaisesRegex(sender.StopRun,'folder-transition'):
                sender.open_picker_folder(Mock(),'zhensi_reports')

    def test_current_report_folder_skips_root_navigation(self):
        d=Mock();d.app_current.return_value={"package":"com.android.documentsui"};d.return_value.exists=False
        with patch.object(sender,'current_picker_folder',return_value=True),patch.object(sender,'choose_visible_report_file',return_value={"name":"x"}):
            r=sender.choose_system_file(d,self.item)
        self.assertEqual(r['navigationRoute'],'current-report-folder');d.return_value.click.assert_not_called()

    def test_current_downloads_enters_visible_report_folder_directly(self):
        roots=Mock();roots.exists=False
        node=Mock();node.exists=True
        d=Mock(side_effect=lambda **kw:roots if kw.get('resourceId','').endswith('roots_list') else node)
        d.app_current.return_value={"package":"com.android.documentsui"}
        with patch.object(sender,'current_picker_folder',return_value=False),patch.object(sender,'open_picker_folder') as open_folder,patch.object(sender,'choose_visible_report_file',return_value={}):
            r=sender.choose_system_file(d,self.item)
        self.assertEqual(r['navigationRoute'],'current-downloads/report-folder')
        open_folder.assert_called_once_with(d,'zhensi_reports');roots.child.assert_not_called();node.click.assert_not_called()

    def test_other_root_uses_downloads_shortcut_not_internal_storage(self):
        roots=Mock();roots.exists=True;roots.wait.return_value=True;roots.wait_gone.return_value=True
        header=Mock();header.wait.return_value=True
        d=Mock(side_effect=lambda **kw:roots if kw.get('resourceId','').endswith('roots_list') else header)
        d.app_current.return_value={"package":"com.android.documentsui"}
        with patch.object(sender,'current_picker_folder',return_value=False),patch.object(sender,'click_stable_picker_node') as click,patch.object(sender,'open_picker_folder') as folder,patch.object(sender,'choose_visible_report_file',return_value={}):
            r=sender.choose_system_file(d,self.item)
        roots.child.assert_called_once_with(resourceId='android:id/title',text='下载内容')
        click.assert_called_once_with(d,roots.child.return_value,'下载内容')
        folder.assert_called_once_with(d,'zhensi_reports')
        self.assertEqual(r['navigationRoute'],'downloads-shortcut/report-folder')

    def test_expired_efficiency_target_does_not_stop_contract_check(self):
        # 不接设备：证明超时后仍进入文件校验，而非触发整轮硬停止。
        with tempfile.TemporaryDirectory() as work:
            args = sender.argparse.Namespace(group=sender.TARGET_GROUP,
                deadline_unix=1, build_receipt="unused.json", keep_work=False,
                send_receipt=str(Path(work) / "receipt.json"))
            with patch.object(sender, "load_build_receipt", side_effect=sender.StopRun("fixture-contract-stop")) as load:
                result = sender.run(args)
            load.assert_called_once()
            self.assertEqual(result["reason"], "fixture-contract-stop")
            self.assertEqual(result["efficiencyStatus"], "效率未达标")
            self.assertFalse(result["businessCompleted"])

    def test_same_device_dual_transport_prefers_usb(self):
        helpers = Mock()
        helpers.physical_devices.return_value = [{"serial": "runtime-address:5555"}, {"serial": "usb-device"}]
        helpers.adb.side_effect = ["physical-device", "HLK-AL00"] * 2
        with patch.object(sender, "DEVICE_ID_SHA256", sender.hashlib.sha256(b"physical-device").hexdigest()):
            serial, evidence = sender.select_verified_device(helpers)
        self.assertEqual(serial, "usb-device")
        self.assertEqual(evidence["verifiedEndpoints"], 2)
        self.assertEqual(evidence["transport"], "usb")
        self.assertNotIn("runtime-address", str(evidence))

    def test_unique_wireless_transport(self):
        helpers = Mock()
        helpers.physical_devices.return_value = [{"serial": "runtime-address:5555"}]
        helpers.adb.side_effect = ["physical-device", "HLK-AL00"]
        with patch.object(sender, "DEVICE_ID_SHA256", sender.hashlib.sha256(b"physical-device").hexdigest()):
            _, evidence = sender.select_verified_device(helpers)
        self.assertEqual(evidence["transport"], "wireless")

    def test_second_physical_device_rejected(self):
        helpers = Mock()
        helpers.physical_devices.return_value = [{"serial": "usb-device"}, {"serial": "other-device"}]
        helpers.adb.side_effect = ["physical-device", "HLK-AL00", "other-device", "HLK-AL00"]
        with patch.object(sender, "DEVICE_ID_SHA256", sender.hashlib.sha256(b"physical-device").hexdigest()):
            with self.assertRaisesRegex(sender.StopRun, "identity-mismatch"):
                sender.select_verified_device(helpers)

    def test_no_device_rejected(self):
        helpers = Mock()
        helpers.physical_devices.return_value = []
        with self.assertRaisesRegex(sender.StopRun, "not-connected"):
            sender.select_verified_device(helpers)

    def test_wireless_identity_checked_not_endpoint(self):
        helpers = Mock()
        helpers.adb.side_effect = ["physical-device", "HLK-AL00"]
        with patch.object(sender, "DEVICE_ID_SHA256", sender.hashlib.sha256(b"physical-device").hexdigest()):
            result = sender.verify_physical_identity(helpers, "runtime-endpoint")
        self.assertEqual(result["model"], "HLK-AL00")
        self.assertNotIn("serial", result)

    def test_same_model_wrong_device_rejected(self):
        helpers = Mock()
        helpers.adb.side_effect = ["other-device", "HLK-AL00"]
        with self.assertRaisesRegex(sender.StopRun, "identity-mismatch"):
            sender.verify_physical_identity(helpers, "runtime-endpoint")

    def setUp(self):
        self.item = {"platform": "meituan", "name": "美团全部_2026-09-02至2026-09-02.xlsx",
                     "size": 121115, "sha256": "unit-test-hash"}
        self.entries = [
            {"text": "臻肆测试群（3）", "x": 500, "y": 130},
            {"text": "美团全部_2026-09-02", "x": 500, "y": 1800},
            {"text": "至2026-09-02.xlsx", "x": 500, "y": 1860},
            {"text": "118.3 KB", "x": 350, "y": 1920},
        ]

    def test_wrapped_full_filename(self):
        self.assertTrue(sender.bubble_matches(self.entries, self.item))

    def test_excel_icon_between_filename_lines(self):
        self.entries.append({"text": "X", "x": 844, "y": 1830, "w": 31})
        self.assertTrue(sender.bubble_matches(self.entries, self.item))
        self.entries[1]["text"] = "美团全部_2026-09-01"
        self.assertFalse(sender.bubble_matches(self.entries, self.item))

    def test_non_icon_x_not_discarded(self):
        self.entries.append({"text": "X", "x": 500, "y": 1830, "w": 31})
        self.assertFalse(sender.bubble_matches(self.entries, self.item))

    def test_stable_send_waits_for_animation(self):
        def frame(y):
            return [{"text":"已选中1个文件","x":500,"y":y},
                {"text":"发送","x":960,"y":y},
                {"text":self.item['name'],"x":500,"y":y+100},
                {"text":"118.3KB","x":350,"y":y+160}]
        with patch.object(sender,'screenshot_entries',side_effect=[(Path('a'),frame(950)),(Path('b'),frame(675)),(Path('c'),frame(675))]) as scan, patch.object(sender.time,'sleep'):
            shot, _, button=sender.stable_selected_send(Mock(),None,Path('/tmp'),self.item)
        self.assertEqual(scan.call_count,3)
        self.assertEqual(button['y'],675)
        self.assertEqual(shot,Path('c'))

    def test_selected_wrong_filename_rejected(self):
        entries=[{"text":"已选中1个文件","x":500,"y":600},{"text":"发送","x":960,"y":600},
            {"text":"wrong.xlsx","x":500,"y":800},{"text":"118.3KB","x":350,"y":900}]
        self.assertIsNone(sender.selected_send_signature(entries,self.item))

    def test_short_filename_extension_in_presend_gate(self):
        item={**self.item,'name':'淘宝0903测试3.xlsx'}
        entries=[{'text':'已选中1个文件','x':500,'y':600},{'text':'发送','x':960,'y':600},
            {'text':'淘宝0903测试3.xIsx','x':500,'y':800},{'text':'118.3KB','x':350,'y':900}]
        with tempfile.TemporaryDirectory() as directory:
            device=Mock();shot=Path(directory)/'shot.png'
            with patch.object(sender,'wait_screen',return_value=(shot,entries)), patch.object(sender,'stable_selected_send',return_value=(shot,entries,entries[1])):
                sender.prepare_selected_send(device,None,Path(directory),item,Path(directory)/'ledger.json')
            device.click.assert_called_once_with(960,600)

    def test_timed_call_records_success_and_failure(self):
        result={}
        self.assertEqual(sender.timed_call(result,'success',lambda:7),7)
        with self.assertRaises(ValueError):
            sender.timed_call(result,'failure',lambda:(_ for _ in ()).throw(ValueError('test')))
        self.assertEqual([n['ok'] for n in result['nodes']],[True,False])

    def test_notification_occlusion_restarts_stability_count(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger=Path(directory)/'ledger.json';shot=Path(directory)/'shot.png'
            sender.atomic_json(ledger,{'groupName':sender.TARGET_GROUP,'files':{self.item['sha256']:{'state':'in-flight'}}})
            device=Mock();device.app_current.return_value={'package':'com.tencent.mm'}
            frames=[(shot,self.entries),(shot,self.entries[1:]),(shot,self.entries),(shot,self.entries)]
            with patch.object(sender,'screenshot_entries',side_effect=frames) as scan, patch.object(sender.time,'sleep'):
                result=sender.verify_sent_file(device,None,Path(directory),self.item,ledger)
            self.assertEqual(scan.call_count,4);self.assertEqual(result['state'],'confirmed');device.click.assert_not_called()

    def test_upload_pending_waits_without_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger=Path(directory)/'ledger.json';shot=Path(directory)/'shot.png'
            sender.atomic_json(ledger,{'groupName':sender.TARGET_GROUP,'files':{self.item['sha256']:{'state':'in-flight'}}})
            pending=self.entries+[{'text':'上传中','x':700,'y':1950}]
            device=Mock();device.app_current.return_value={'package':'com.tencent.mm'}
            with patch.object(sender,'screenshot_entries',side_effect=[(shot,pending),(shot,self.entries),(shot,self.entries)]),patch.object(sender.time,'sleep'):
                result=sender.verify_sent_file(device,None,Path(directory),self.item,ledger)
            self.assertEqual(result['uploadPendingFrames'],1);device.click.assert_not_called()

    def test_main_wechat_chooser_selects_exact_main_instance(self):
        main=Mock();main.exists.return_value=True;main.count=1
        clone=Mock();clone.exists.return_value=True;clone.count=1
        device=Mock(side_effect=lambda **kw: main if kw.get('description')=='微信' else clone)
        device.app_current.side_effect=[{'activity':'HwChooserActivity'},
            {'package':'com.tencent.mm','activity':'LauncherUI','pid':123}]
        helpers=Mock();helpers.adb.return_value='u0_a128 123 com.tencent.mm\n'
        self.assertTrue(sender.resolve_main_wechat_chooser(device,helpers,'serial'))
        main.click.assert_called_once();clone.click.assert_not_called()

    def test_main_wechat_chooser_rejects_ambiguous_entry(self):
        main=Mock();main.exists.return_value=True;main.count=2
        clone=Mock();clone.exists.return_value=True;clone.count=1
        device=Mock(side_effect=lambda **kw: main if kw.get('description')=='微信' else clone)
        device.app_current.return_value={'activity':'HwChooserActivity'}
        with self.assertRaisesRegex(sender.StopRun,'identity-not-unique'):
            sender.resolve_main_wechat_chooser(device,Mock(),'serial')
        main.click.assert_not_called()

    def test_visible_target_stabilizes_without_whole_list(self):
        target=Mock();target.exists.return_value=True;target.count=1
        target.info={'bounds':{'left':216,'right':700,'top':600,'bottom':665}}
        device=Mock(return_value=target);device.app_current.return_value={'package':'com.android.documentsui'}
        device.window_size.return_value=(1080,2340)
        with patch.object(sender.time,'sleep'):
            found,bounds=sender.stable_visible_report_target(device,self.item)
        self.assertIs(found,target);self.assertEqual(bounds['top'],600)

    def test_delayed_exact_file_selects_without_unnecessary_scroll(self):
        folder=Mock();folder.exists=True
        toggle=Mock();toggle.exists=True;toggle.count=1;toggle.wait_gone.return_value=True
        target=Mock();target.exists.side_effect=[False,False,True,True];target.count=1;target.info={'bounds':{'top':600,'bottom':665,'left':216,'right':700}}
        listing=Mock();listing.exists=True;listing.scroll.forward.return_value=True
        listing.info={'scrollable':True}
        def find(**kw):
            if kw.get('resourceId')=='com.android.documentsui:id/sub_menu_list':return toggle
            if kw.get('text')=='zhensi_reports':return folder
            if kw.get('text')==self.item['name']:return target
            return listing
        device=Mock(side_effect=find)
        device.app_current.return_value={'package':'com.android.documentsui'}
        device.window_size.return_value=(1080,2340)
        with patch.object(sender, 'stable_report_rows', return_value=((self.item['name'],'bounds'),)):
            result=sender.choose_visible_report_file(device,self.item)
        toggle.click.assert_called_once();toggle.wait_gone.assert_called_once_with(timeout=5)
        listing.scroll.forward.assert_not_called();listing.scroll.toBeginning.assert_not_called()
        target.click.assert_called_once();self.assertEqual(result['name'],self.item['name'])

    def test_clipped_report_row_is_not_clickable(self):
        d=Mock();d.window_size.return_value=(1080,2340)
        self.assertFalse(sender.report_row_visible(d,{'left':216,'right':662,'top':72,'bottom':89}))
        self.assertFalse(sender.report_row_visible(d,{'left':216,'right':662,'top':2210,'bottom':2260}))
        self.assertTrue(sender.report_row_visible(d,{'left':216,'right':662,'top':600,'bottom':665}))

    def test_report_folder_required_before_scroll(self):
        folder=Mock();folder.exists=False;device=Mock(return_value=folder)
        with self.assertRaisesRegex(sender.StopRun,'report-folder-not-verified'):
            sender.choose_visible_report_file(device,self.item)

    def test_group_title_waits_without_navigation(self):
        merchant=Mock();merchant.unique_group_in_title.side_effect=[False,True]
        helpers=Mock()
        def poll(fn,predicate,timeout):
            self.assertEqual(timeout,8)
            first=fn()
            return first if predicate(first) else fn()
        helpers.poll.side_effect=poll;device=Mock()
        self.assertTrue(sender.wait_group_title(device,helpers,merchant,Path('/tmp'),sender.TARGET_GROUP))
        self.assertEqual(merchant.unique_group_in_title.call_count,2);device.click.assert_not_called()

    def test_nearby_group_rejected(self):
        self.entries[0]["text"] = "臻肆测试群副群（3）"
        self.assertFalse(sender.bubble_matches(self.entries, self.item))

    def test_wrong_date_rejected(self):
        self.entries[1]["text"] = "美团全部_2026-09-01"
        self.assertFalse(sender.bubble_matches(self.entries, self.item))

    def test_observed_extension_ocr_confusion(self):
        self.entries[2]["text"] = "至2026-09-02.xIsx"
        self.assertTrue(sender.bubble_matches(self.entries, self.item))

    def test_wrong_size_rejected(self):
        self.entries[-1]["text"] = "103.4KB"
        self.assertFalse(sender.bubble_matches(self.entries, self.item))

    def test_duplicate_group_rejected(self):
        self.entries.append(dict(self.entries[0]))
        self.assertFalse(sender.bubble_matches(self.entries, self.item))

    def test_confirmed_and_unknown_never_resend(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            device = Mock()
            for state in ("in-flight", "confirmed"):
                sender.atomic_json(path, {"groupName": sender.TARGET_GROUP,
                    "files": {self.item["sha256"]: {"state": state}}})
                with self.assertRaisesRegex(sender.StopRun, "already-attempted"):
                    sender.prepare_selected_send(device, None, Path(directory), self.item, path)
                device.click.assert_not_called()

    def test_wrong_ledger_group_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ledger.json"
            sender.atomic_json(path, {"groupName": "其他群", "files": {}})
            with self.assertRaisesRegex(sender.StopRun, "ledger-group-mismatch"):
                sender.load_delivery_ledger(path)


if __name__ == "__main__":
    unittest.main()
