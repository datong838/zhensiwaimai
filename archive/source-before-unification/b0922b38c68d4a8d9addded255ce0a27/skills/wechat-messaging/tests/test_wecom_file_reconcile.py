import contextlib
import hashlib
import json
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock,patch
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from wecom_file_reconcile import reconcile_run

class WorkflowReadback(unittest.TestCase):
 def fixture(self,root):
  day=datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
  run=root/'runs'/f'{day}-{time.time_ns()}';run.mkdir(parents=True)
  file=run/'report.xlsx';file.write_bytes(b'original report')
  summary={'status':'unknown','reportPath':str(file),'report':file.name,'day':day}
  (run/'summary.json').write_text(json.dumps(summary))
  events=root/'events';events.mkdir()
  event=f'{day}-test-file';marker=events/f'{event}.json'
  prior={'state':'unknown','event':event,'sha256':hashlib.sha256(file.read_bytes()).hexdigest(),
         'name':file.name,'groupName':'业务群','sendAttempts':1}
  marker.write_text(json.dumps(prior))
  return run,file,marker,summary
 def test_original_file_is_reconciled_with_audit_and_no_send(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);run,file,marker,summary=self.fixture(root);original=marker.read_bytes()
   adapter=MagicMock();adapter.session.return_value=contextlib.nullcontext()
   adapter.reconcile.return_value={'status':'verified','verificationLevel':'file-name-size-ui','evidence':{'frames':[]},'newSendAttempts':0}
   with patch('wecom_file_reconcile.WeComAdapter',return_value=adapter):
    result=reconcile_run(run,runs=root/'runs',events=root/'events',group='业务群',event_suffix='test-file',whole_flow=False)
   self.assertEqual(result['status'],'detail-verified-image-pending')
   self.assertEqual(json.loads(marker.read_text())['state'],'verified')
   self.assertEqual(json.loads(marker.read_text())['sendAttempts'],1)
   self.assertEqual(next((run/'readonly-reconciliation').glob('*/original-marker.json')).read_bytes(),original)
   adapter.send_one.assert_not_called()
 def test_changed_original_file_is_rejected_without_ui_or_marker_write(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);run,file,marker,summary=self.fixture(root);original=marker.read_bytes();file.write_bytes(b'different')
   with patch('wecom_file_reconcile.WeComAdapter') as adapter:
    with self.assertRaisesRegex(ValueError,'marker-binding'):
     reconcile_run(run,runs=root/'runs',events=root/'events',group='业务群',event_suffix='test-file',whole_flow=True)
   adapter.assert_not_called();self.assertEqual(marker.read_bytes(),original)
if __name__=='__main__':unittest.main()
