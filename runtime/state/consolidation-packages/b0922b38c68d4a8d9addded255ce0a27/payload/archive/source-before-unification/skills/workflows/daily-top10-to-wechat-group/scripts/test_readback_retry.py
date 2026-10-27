import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import Mock, patch
import phone_executor as p

class ReadbackTests(unittest.TestCase):
    def exercise(self, scenario):
        clock=[0.0];clicks=[];receipt={};device=Mock()
        device.app_current.return_value={'package':'other' if scenario=='lost-focus' else 'com.tencent.mm'}
        device.click.side_effect=lambda *point: clicks.append(point)
        def entries(*_):
            viewer=(scenario=='first-success' and len(clicks)>=1) or (scenario=='retry-success' and len(clicks)>=2)
            return [] if viewer or scenario=='unknown-page' else [{'text':p.TARGET_GROUP,'y':100}]
        def verify(*_):
            good=scenario in ('first-success','retry-success')
            return {'ok':good,'distance':0.036 if good else 28,'matched':['门店','营业额'] if good else []}
        def sleep(seconds):clock[0]+=seconds
        error=None
        with ExitStack() as stack:
            for name,replacement in [('screenshot',lambda *_:Path('fixture.png')),('ocr_entries',entries),('verify_large_image',verify),('sha256_file',lambda *_:'fixture-hash'),('locate_chat_target',lambda *_:((200+len(clicks)*100,800),1.1))]:
                stack.enter_context(patch.object(p,name,side_effect=replacement))
            stack.enter_context(patch.object(p.time,'monotonic',side_effect=lambda:clock[0]))
            stack.enter_context(patch.object(p.time,'sleep',side_effect=sleep))
            try:p.open_and_verify_sent_image(device,Path('.'),Path('target.png'),p.TARGET_GROUP,receipt)
            except p.StopRun as e:error=str(e)
        return clicks,receipt,error

    def test_first_success_no_retry(self):
        clicks,r,error=self.exercise('first-success')
        self.assertIsNone(error);self.assertEqual(len(clicks),1)

    def test_retry_relocates_from_current_screen(self):
        clicks,r,error=self.exercise('retry-success')
        self.assertIsNone(error);self.assertEqual(clicks,[(200,800),(300,800)])
        self.assertEqual(r['viewerOpenAttempts'],2)

    def test_two_failures_stop_without_third_click(self):
        clicks,r,error=self.exercise('stays-chat')
        self.assertEqual(len(clicks),2);self.assertEqual(error,'image-viewer-not-opened')
        self.assertEqual(r['readbackLastPage'],'target-chat')

    def test_unknown_page_never_clicked(self):
        clicks,r,error=self.exercise('unknown-page')
        self.assertEqual(clicks,[]);self.assertEqual(error,'viewer-page-or-content-not-verified')

    def test_focus_loss_never_clicked(self):
        clicks,r,error=self.exercise('lost-focus')
        self.assertEqual(clicks,[]);self.assertEqual(error,'readback-wechat-not-foreground')

if __name__=='__main__':unittest.main()
