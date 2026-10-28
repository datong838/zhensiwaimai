import copy
import io
import json
from pathlib import Path
import unittest
from PIL import Image
import native_image_content as C


def picture(color, fmt='PNG'):
    stream=io.BytesIO();Image.new('RGBA',(3,2),color).save(stream,format=fmt);return stream.getvalue()


class Driver:
    def __init__(self, source):
        self.source=source;self.copied=picture('red','TIFF');self.calls=0;self.count=0;self.seeded=0
        self.state={'groupName':'精确群','inputEmpty':True,'frontmost':True,'cellRole':'AXCell',
                    'fileCard':False,'rowPath':[0,27,9,0,0,0,20],'rowCount':21}
        self.owner=True;self.intent=True;self.stale=False;self.change_row=False;self.change_source=False
        self.kind='public.tiff';self.action_ok=True
    def owner_active(self, owner):return self.owner
    def intent_matches(self,*args):return self.intent
    def snapshot(self):
        state=copy.deepcopy(self.state)
        if self.change_row and self.calls:state['rowPath'][-1]+=1
        return state
    def read_source(self):return picture('blue') if self.change_source and self.calls else self.source
    def seed_nonce(self, nonce):
        assert nonce.startswith('zhensi-image-readback-');self.count+=1;self.seeded=self.count;return self.count
    def copy_image(self,row,group):
        self.calls+=1;self.count+=1
        return {'backend':'system-events-ui-tree','copied':self.action_ok,'rowPath':row,'menuShortcut':'C','menuModifiers':0}
    def clipboard_image(self):return {'type':self.kind,'changeCount':self.seeded if self.stale else self.count,'data':self.copied}


class CopyCandidateTests(unittest.TestCase):
    def setUp(self):
        self.source=picture('red');self.driver=Driver(self.source)
        self.task={'taskId':'original-task','stage':'send','owner':{'pid':123},
                   'expectedPresentation':'inline-image','request':{'groupName':'精确群'},
                   'item':{'type':'image','size':len(self.source),'sha256':C.sha(self.source)}}
        self.bind()
    def bind(self):
        bare={k:v for k,v in self.task.items() if k!='binding'}
        self.task['binding']=C.sha(json.dumps(bare,sort_keys=True,ensure_ascii=False).encode())
    def verify(self):return C.verify_copies(self.task,self.source,20,self.driver)
    def test_png_to_tiff_exact_pixels_two_fresh_copies_not_installation(self):
        result=self.verify();self.assertEqual(self.driver.calls,2);self.assertEqual(len(result['observations']),2)
        self.assertEqual(result['sendAttempts'],0);self.assertFalse(result['ledgerModified'])
        self.assertNotEqual(result['observations'][0]['clipboardNonceSha256'],result['observations'][1]['clipboardNonceSha256'])
    def test_stale_clipboard_and_wrong_format_reject(self):
        self.driver.stale=True
        with self.assertRaisesRegex(RuntimeError,'not-fresh-image'):self.verify()
        self.driver.stale=False;self.driver.kind='public.utf8-plain-text'
        with self.assertRaisesRegex(RuntimeError,'not-fresh-image'):self.verify()
    def test_wrong_pixels_cannot_be_meeting_icon_or_other_image(self):
        self.driver.copied=picture('blue')
        with self.assertRaisesRegex(RuntimeError,'pixels-mismatch'):self.verify()
    def test_exact_group_empty_input_foreground_new_row_and_file_card_gates(self):
        for mutation in [{'groupName':'别的群'},{'inputEmpty':False},{'frontmost':False},
                         {'rowCount':20},{'cellRole':'AXImage'},{'fileCard':True}]:
            driver=Driver(self.source);driver.state.update(mutation)
            with self.assertRaisesRegex(RuntimeError,'new-inline-row-invalid'):
                C.verify_copies(self.task,self.source,20,driver)
            self.assertEqual(driver.calls,0)
    def test_owner_and_original_intent_required_before_copy(self):
        for attr in ['owner','intent']:
            driver=Driver(self.source);setattr(driver,attr,False)
            with self.assertRaises(RuntimeError):C.verify_copies(self.task,self.source,20,driver)
            self.assertEqual(driver.calls,0)
    def test_row_or_source_change_aborts_without_second_copy(self):
        for attr in ['change_row','change_source']:
            driver=Driver(self.source);setattr(driver,attr,True)
            with self.assertRaises(RuntimeError):C.verify_copies(self.task,self.source,20,driver)
            self.assertEqual(driver.calls,1)
    def test_task_binding_kind_size_and_source_digest_cannot_be_substituted(self):
        self.task['request']['groupName']='changed'
        with self.assertRaises(ValueError):self.verify()
        self.bind();self.task['item']['type']='file';self.bind()
        with self.assertRaises(ValueError):self.verify()
        self.assertEqual(self.driver.calls,0)
    def test_unconfirmed_native_copy_action_rejects(self):
        self.driver.action_ok=False
        with self.assertRaisesRegex(RuntimeError,'action-not-confirmed'):self.verify()
    def test_candidate_ui_script_has_only_visible_click_copy_no_key_probe_or_capture(self):
        text=(Path(__file__).resolve().parents[1] / 'scripts/native_image_content.jxa').read_text()
        for forbidden in ['keyCode','keystroke','AXSetValue','CGEvent','screenshot','captureScreen','CUA']:
            self.assertNotIn(forbidden,text)
        self.assertIn("menuItems.byName('复制')",text)
        self.assertIn("if(!p.frontmost())",text)


if __name__=='__main__':unittest.main()
