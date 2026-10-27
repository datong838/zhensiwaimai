import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from registered_ui_routes import allowed_direct,DIRECT,GROUP
from wecom_adapter import WeComAdapter
class DirectRoutes(unittest.TestCase):
    def requests(self):
        for workflow,(item_id,kind,suffix) in DIRECT.items():
            event=suffix.replace(r'\d+','123')
            item={'itemId':item_id,'type':kind}
            item.update({'text':'淘宝闪购     店铺：fixture     缺失项'} if kind=='text' else {'path':'/fixture/report.xlsx'})
            yield {'groupName':GROUP,'context':{'workflowId':workflow,'eventId':'2026-10-25-'+event},'items':[item]}
    def test_exact_original_requests(self):
        for r in self.requests():self.assertTrue(allowed_direct(r))
    def test_wrong_scope_is_rejected(self):
        for r in self.requests():
            for change in [{'groupName':'wrong'},{'items':[]},{'items':r['items']*2},{'context':r['context']|{'eventId':'different'}}]:self.assertFalse(allowed_direct(r|change))
            wrong=copy.deepcopy(r);wrong['items'][0]['itemId']='other';self.assertFalse(allowed_direct(wrong))
            wrong=copy.deepcopy(r);wrong['items'][0]['type']='image';self.assertFalse(allowed_direct(wrong))
    def test_empty_text_and_image_file_rejected(self):
        for r in self.requests():
            item=r['items'][0]
            item.update({'text':'  '} if item['type']=='text' else {'path':'/fixture/report.png'})
            self.assertFalse(allowed_direct(r))
    def test_preflight_uses_only_ui_queue(self):
        for r in self.requests():
            with patch('wecom_ui_queue.exchange',return_value={'ok':True,'resolvedGroup':GROUP,'inputEmpty':True}) as queued,patch.object(WeComAdapter,'_run_sender',side_effect=AssertionError('legacy')):
                self.assertTrue(WeComAdapter().preflight(r,'unused')['ok']);queued.assert_called_once()
if __name__=='__main__':unittest.main()
