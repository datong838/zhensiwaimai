import sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from contract import Rejected
from history_verify import verify_existing_files
from evidence import file_frame_matches
from desktop_adapter import find_image_in_chat


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.request={'groupName':'测试群','items':[{'itemId':'file','type':'file','name':'测试.xlsx','size':1024,'sha256':'a'*64}]}
        self.hits=[SimpleNamespace(text='测试.xlsx',cx=800,cy=400),SimpleNamespace(text='1.0K',cx=800,cy=450)]
        wd=SimpleNamespace(screenshot_main_region=lambda p:Image.new('RGB',(1000,800),'white').save(p),
                           ocr=lambda p:self.hits,find_exact_headers=lambda h,g:['header'])
        self.adapter=SimpleNamespace(wd=wd,preflight=lambda r,w:{'ok':True})
    def tearDown(self):self.tmp.cleanup()
    def test_visible_files_verified_without_sender(self):
        r=verify_existing_files(self.request,self.adapter,self.root)
        self.assertTrue(r['ok']);self.assertEqual(r['sendAttempts'],0);self.assertFalse(r['deliveryLedgerWritten'])
    def test_ambiguous_files_rejected(self):
        self.hits.append(self.hits[0])
        with self.assertRaises(Rejected):verify_existing_files(self.request,self.adapter,self.root)
    def test_unsupported_before_preflight(self):
        self.request['items'][0]['type']='text';self.adapter.preflight=lambda *_:self.fail('must not navigate')
        with self.assertRaises(Rejected):verify_existing_files(self.request,self.adapter,self.root)
    def test_wrong_file_size_rejected(self):
        self.hits[1].text='2.0K'
        with self.assertRaises(Rejected):verify_existing_files(self.request,self.adapter,self.root)
    def test_prefix_and_other_filename_not_accepted(self):
        self.assertFalse(file_frame_matches('旧测试.xlsx 1.0K','测试.xlsx',1024))
        self.assertFalse(file_frame_matches('测试.xlsx 11.0KB','测试.xlsx',1024))
    def test_flat_image_rejected(self):
        target=self.root/'white.png';Image.new('RGB',(100,100),'white').save(target)
        image=Image.new('RGB',(400,400),'white')
        self.assertFalse(find_image_in_chat(image,image,target)['ok'])

if __name__=='__main__':unittest.main()
