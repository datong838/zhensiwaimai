import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import run_all
class LedgerDeliveryTests(unittest.TestCase):
    def test_failed_delivery_never_marks_sent(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(run_all,'send_ledger_via_wechat',return_value=False):
            path=Path(folder)/'sent.json'
            with patch.object(run_all,'SENT_TODAY',path):run_all._maybe_send_ledger(Path(folder)/'report.xlsx',True,True,'2026-10-24')
            self.assertFalse(path.exists())
    def test_wrong_frozen_path_never_sends(self):
        with patch('authorized_supplement.load_grant',return_value={'item':{'path':'/fixed/report.xlsx'}}),patch('authorized_supplement.deliver_once') as send:
            self.assertFalse(run_all.send_ledger_via_wechat(Path('/other/report.xlsx')));send.assert_not_called()
    def test_verified_original_delivery_marks_sent(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(run_all,'send_ledger_via_wechat',return_value=True):
            path=Path(folder)/'sent.json'
            with patch.object(run_all,'SENT_TODAY',path):run_all._maybe_send_ledger(Path(folder)/'report.xlsx',True,True,'2026-10-24')
            self.assertTrue(path.exists())
if __name__=='__main__':unittest.main()
