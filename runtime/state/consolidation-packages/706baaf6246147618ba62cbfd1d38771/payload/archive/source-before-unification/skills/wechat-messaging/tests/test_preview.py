import sys,json,tempfile,unittest
from pathlib import Path
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from desktop_adapter import DesktopAdapter
from contract import Rejected

class PreviewTests(unittest.TestCase):
    def test_exact_zero_send_text_draft_is_reused_once_without_clearing(self):
        import hashlib
        text='city\ncontact\nmerchant\naddress'
        request={'groupName':'电销+直播攻坚组','items':[{'type':'text','text':text,
                 'sha256':hashlib.sha256(text.encode()).hexdigest()}],
                 'context':{'resumePreparedText':text,
                            'resumePreparedTextSha256':hashlib.sha256(text.encode()).hexdigest(),
                            'deadlineAt':9999999999}}
        a=DesktopAdapter.__new__(DesktopAdapter);a.sender=Mock();a.wd=Mock()
        a.wd.ax_confirms_raw_group_header.return_value=True
        a.sender.focused_text_value.return_value=text
        def send(_args):
            a.sender.normalize_empty_composer()
            a.sender.set_focused_text(text)
            return {'sendAttempts':0,'reason':'test-stop-before-attempt'}
        a.sender._send_locked.side_effect=send
        result=a.send_one(request,request['items'][0],Path('/tmp/no-such-preview'),
                           {'authorizationRef':'test-auth'},9999999999)
        self.assertEqual(result['status'],'blocked')
        a.sender._send_locked.assert_called_once()
        a.sender.set_focused_text.assert_not_called()
        a.sender.normalize_empty_composer.assert_not_called()

    def test_exact_zero_send_text_draft_mismatch_never_reaches_sender(self):
        import hashlib
        text='city\ncontact\nmerchant\naddress'
        request={'groupName':'电销+直播攻坚组','items':[{'type':'text','text':text,
                 'sha256':hashlib.sha256(text.encode()).hexdigest()}],
                 'context':{'resumePreparedText':text,
                            'resumePreparedTextSha256':hashlib.sha256(text.encode()).hexdigest(),
                            'deadlineAt':9999999999}}
        a=DesktopAdapter.__new__(DesktopAdapter);a.sender=Mock();a.wd=Mock()
        a.wd.ax_confirms_raw_group_header.return_value=True
        a.sender.focused_text_value.return_value='different draft'
        with self.assertRaisesRegex(Rejected,'zero-send-non-target-draft-clear-unverified'):
            a.send_one(request,request['items'][0],Path('/tmp/no-such-preview'),{},9999999999)
        a.sender.set_focused_text.assert_called_once_with('')
        a.sender._send_locked.assert_not_called()

    def test_exact_zero_send_non_target_draft_is_cleared_before_standard_fill(self):
        import hashlib
        text='city\ncontact\nmerchant\naddress'
        request={'groupName':'电销+直播攻坚组','items':[{'type':'text','text':text,
                 'sha256':hashlib.sha256(text.encode()).hexdigest()}],
                 'context':{'resumePreparedText':text,
                            'resumePreparedTextSha256':hashlib.sha256(text.encode()).hexdigest(),
                            'deadlineAt':9999999999}}
        a=DesktopAdapter.__new__(DesktopAdapter);a.sender=Mock();a.wd=Mock()
        a.wd.ax_confirms_raw_group_header.return_value=True
        a.sender.focused_text_value.side_effect=['other draft','','','','']
        def send(_args):
            self.assertTrue(a.sender.normalize_empty_composer())
            a.sender.set_focused_text(text)
            return {'sendAttempts':0,'reason':'test-stop-before-attempt'}
        a.sender._send_locked.side_effect=send
        result=a.send_one(request,request['items'][0],Path('/tmp/no-such-preview'),
                          {'authorizationRef':'test-auth'},9999999999)
        self.assertEqual(result['status'],'blocked')
        a.sender._send_locked.assert_called_once()
        self.assertEqual([call.args[0] for call in a.sender.set_focused_text.call_args_list],['',text])

    def test_exact_zero_send_empty_composer_is_filled_from_bound_payload(self):
        import hashlib
        text='city\ncontact\nmerchant\naddress'
        request={'groupName':'电销+直播攻坚组','items':[{'type':'text','text':text,
                 'sha256':hashlib.sha256(text.encode()).hexdigest()}],
                 'context':{'resumePreparedText':text,
                            'resumePreparedTextSha256':hashlib.sha256(text.encode()).hexdigest(),
                            'deadlineAt':9999999999}}
        a=DesktopAdapter.__new__(DesktopAdapter);a.sender=Mock();a.wd=Mock()
        a.wd.ax_confirms_raw_group_header.return_value=True
        a.sender.focused_text_value.return_value=''
        def send(_args):
            self.assertTrue(a.sender.normalize_empty_composer())
            a.sender.set_focused_text(text)
            return {'sendAttempts':0,'reason':'test-stop-before-attempt'}
        a.sender._send_locked.side_effect=send
        result=a.send_one(request,request['items'][0],Path('/tmp/no-such-preview'),
                          {'authorizationRef':'test-auth'},9999999999)
        self.assertEqual(result['status'],'blocked')
        a.sender._send_locked.assert_called_once()
        a.sender.set_focused_text.assert_called_once_with(text)

    def test_exact_own_preview_and_one_pixel_change(self):
        from PIL import Image
        for changed in (False,True):
            with tempfile.TemporaryDirectory() as d:
                p=Path(d);(p/'transport').mkdir()
                (p/'transport/receipt.json').write_text(json.dumps({'sendAttempts':0,'groupName':'测试','stage':'prepare_payload','payloads':[{'sha256':'abc'}]}))
                original=Image.new('RGB',(100,100),'white');original.save(p/'transport/prepared.png')
                current=original.copy()
                if changed:current.putpixel((50,85),(254,255,255))
                a=DesktopAdapter.__new__(DesktopAdapter);a.sender=Mock();a.wd=Mock()
                a.wd.ax_confirms_raw_group_header.return_value=True
                a.sender.focused_text_value.return_value='\ufffc'
                a.sender.chat_input_empty.return_value=True
                a.wd.screenshot_main_region.side_effect=lambda dest:current.save(dest)
                if changed:
                    with self.assertRaisesRegex(Rejected,'content-changed'):
                        a.cleanup_owned_preview({'groupName':'测试'},{'type':'file','sha256':'abc'},p)
                    a.sender.set_focused_text.assert_not_called()
                else:
                    a.cleanup_owned_preview({'groupName':'测试'},{'type':'file','sha256':'abc'},p)
                    a.sender.set_focused_text.assert_called_once_with('')
    def test_foreign_or_attempted_preview_not_cleared(self):
        for count,group in [(1,'测试'),(0,'其他')]:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d);(p/'transport').mkdir()
                (p/'transport/receipt.json').write_text(json.dumps({'sendAttempts':count,'groupName':group,'stage':'prepare_payload'}))
                a=DesktopAdapter.__new__(DesktopAdapter);a.sender=Mock();a.wd=Mock()
                a.cleanup_owned_preview({'groupName':'测试'},{'type':'file'},p)
                a.sender.set_focused_text.assert_not_called();a.wd.activate_wechat.assert_not_called()
    def test_changed_draft_or_group_rejected(self):
        for ax,value,reason in [(False,'\ufffc','group-mismatch'),(True,'用户草稿','composer-changed')]:
            with tempfile.TemporaryDirectory() as d:
                p=Path(d);(p/'transport').mkdir()
                (p/'transport/receipt.json').write_text(json.dumps({'sendAttempts':0,'groupName':'测试','stage':'prepare_payload','payloads':[{'sha256':'abc'}]}))
                a=DesktopAdapter.__new__(DesktopAdapter);a.sender=Mock();a.wd=Mock()
                a.wd.ax_confirms_raw_group_header.return_value=ax;a.sender.focused_text_value.return_value=value
                with self.assertRaisesRegex(Rejected,reason):a.cleanup_owned_preview({'groupName':'测试'},{'type':'file','sha256':'abc'},p)
                a.sender.set_focused_text.assert_not_called()

if __name__=='__main__':unittest.main()
