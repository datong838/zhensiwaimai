import unittest,tempfile,json,hashlib
from pathlib import Path
import reconcile_ui_post_zero as r
class Tests(unittest.TestCase):
 def test_no_intent_and_explicit_zero_required(self):
  old=r.QUEUE
  try:
   with tempfile.TemporaryDirectory() as tmp:
    r.QUEUE=Path(tmp);p=r.QUEUE/'task';p.mkdir()
    d={'taskId':'id','stage':'send','request':{'groupName':'g'},'item':{'sha256':'a'}};d['binding']=hashlib.sha256(json.dumps(d,sort_keys=True,ensure_ascii=False).encode()).hexdigest();(p/'task.json').write_text(json.dumps(d))
    with self.assertRaisesRegex(ValueError,'zero-send-not-proven'):r.reconcile(p)
    (p/'claim.json').write_text('{}');(p/'send-intent.json').write_text('{}')
    with self.assertRaisesRegex(ValueError,'zero-send-not-proven'):r.reconcile(p)
    (p/'send-intent.json').unlink();(p/'response.json').write_text(json.dumps({'taskId':'id','binding':d['binding'],'result':{'status':'unknown','sendAttempts':1,'resolvedGroup':'g'}}))
    with self.assertRaisesRegex(ValueError,'zero-response-invalid'):r.reconcile(p)
  finally:r.QUEUE=old
if __name__=='__main__':unittest.main()
