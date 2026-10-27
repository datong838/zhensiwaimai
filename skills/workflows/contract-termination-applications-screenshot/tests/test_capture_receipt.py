import base64
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from contract_capture_receipt import capture_images, load_run_images, HOME, ROUTE

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jZQAAAABJRU5ErkJggg==')
DAY='2026-10-28'

class CaptureReceiptTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.folder=self.root/'shot-out'/DAY;self.folder.mkdir(parents=True)
        self.receipt={'ok':True,'route':ROUTE,'taskStatus':'处理中','at':'2026-10-28T01:00:00+08:00',
                      'reset':HOME,'outDir':str(self.folder),'pager':{'pages':2,'total':2},
                      'headers':['门店ID','任务状态'],'statusCheck':{'index':1,'bad':0},
                      'rows':[['1','处理中'],['2','处理中']],'pages':[]}
        for n in (1,2):
            f=self.folder/f'{DAY}_合同解约申请_处理中_p{n}.png';f.write_bytes(PNG)
            self.receipt['pages'].append({'page':n,'rows':1,'file':str(f),'bytes':len(PNG),'innerHScroll':False})
    def validate(self,r=None):return capture_images(r or self.receipt,DAY,self.root)
    def test_complete_multipage_and_single_page(self):
        self.assertEqual(len(self.validate()),2)
        r=copy.deepcopy(self.receipt);r['pages']=r['pages'][:1];r['rows']=r['rows'][:1];r['pager']={'pages':1,'total':1}
        self.assertEqual(len(self.validate(r)),1)
    def test_zero_rows_is_no_report_after_complete_validation(self):
        r=copy.deepcopy(self.receipt);r['pages']=r['pages'][:1];r['pages'][0]['rows']=0;r['rows']=[];r['pager']={'pages':1,'total':0}
        self.assertEqual(self.validate(r),[])
    def test_partial_or_missing_or_duplicate_page_rejected(self):
        for change in ('missing','duplicate','reordered','boolean-page','boolean-count'):
            r=copy.deepcopy(self.receipt)
            if change=='missing':r['pages'].pop()
            elif change=='duplicate':r['pages'][1]['page']=1
            elif change=='reordered':r['pages'].reverse()
            elif change=='boolean-page':r['pages'][0]['page']=True
            else:r['pages'][0]['rows']=True
            with self.subTest(change=change),self.assertRaises(ValueError):self.validate(r)
    def test_known_total_row_count_and_row_state_must_match(self):
        for change in ('total','row-count','row-status','missing-status','missing-column','row-schema','clipped'):
            r=copy.deepcopy(self.receipt)
            if change=='total':r['pager']['total']=3
            elif change=='row-count':r['pages'][0]['rows']=2
            elif change=='row-status':r['rows'][0][1]='已完成'
            elif change=='missing-status':r.pop('statusCheck')
            elif change=='missing-column':r['headers'][1]='其他'
            elif change=='row-schema':r['rows'][0].append('unexpected')
            else:r['pages'][0]['innerHScroll']=True
            with self.subTest(change=change),self.assertRaises(ValueError):self.validate(r)
    def test_stale_future_naive_or_bad_date_rejected(self):
        for at in ('2026-10-27T01:00:00+08:00','2026-10-29T01:00:00+08:00','2026-10-28T01:00:00','bad'):
            with self.subTest(at=at),self.assertRaisesRegex(ValueError,'business-date'):self.validate(self.receipt|{'at':at})
    def test_utc_timestamp_uses_shanghai_day(self):
        self.assertEqual(len(self.validate(self.receipt|{'at':'2026-10-27T17:00:00Z'})),2)
    def test_failed_dry_wrong_route_status_or_reset_rejected(self):
        for change in ({'ok':False},{'dryRun':True},{'route':HOME},{'taskStatus':'已完成'},{'reset':None}):
            with self.subTest(change=change),self.assertRaises(ValueError):self.validate(self.receipt|change)
    def test_missing_file_is_not_silently_dropped(self):
        Path(self.receipt['pages'][1]['file']).unlink()
        with self.assertRaisesRegex(ValueError,'image-path-or-missing'):self.validate()
    def test_symlink_or_foreign_directory_rejected(self):
        f=Path(self.receipt['pages'][0]['file']);external=self.root/'outside.png';external.write_bytes(PNG)
        f.unlink();f.symlink_to(external)
        with self.assertRaises(ValueError):self.validate()
        r=copy.deepcopy(self.receipt);r['pages'][0]['file']=str(external)
        with self.assertRaises(ValueError):self.validate(r)
    def test_size_and_png_structure_must_match(self):
        r=copy.deepcopy(self.receipt);r['pages'][0]['bytes']+=1
        with self.assertRaisesRegex(ValueError,'image-size'):self.validate(r)
        Path(self.receipt['pages'][0]['file']).write_bytes(b'x'*len(PNG))
        with self.assertRaisesRegex(ValueError,'image-format'):self.validate()
    def test_original_receipt_controls_images_and_extra_png_is_ignored(self):
        (self.folder/'unrelated.png').write_bytes(PNG)
        p=self.folder/f'{DAY}_contract-termination_run-0900.json';p.write_text(json.dumps(self.receipt))
        self.assertEqual(load_run_images(self.root,DAY)[0],self.validate())
        with self.assertRaises(ValueError):load_run_images(self.root,'2026-10-29')
    def test_ambiguous_or_missing_or_symlink_receipt_rejected(self):
        with self.assertRaises(ValueError):load_run_images(self.root,DAY)
        p=self.folder/f'{DAY}_contract-termination_run-0900.json';p.write_text(json.dumps(self.receipt))
        q=self.folder/f'{DAY}_contract-termination_run-0901.json';q.write_text(json.dumps(self.receipt))
        with self.assertRaises(ValueError):load_run_images(self.root,DAY)
        q.unlink();external=self.root/'external.json';p.rename(external);p.symlink_to(external)
        with self.assertRaises(ValueError):load_run_images(self.root,DAY)

if __name__=='__main__':unittest.main()
