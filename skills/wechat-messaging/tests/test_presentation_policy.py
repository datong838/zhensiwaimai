import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from presentation_policy import violation, expected_presentation
from wecom_ui_queue import validate_response

class PresentationTests(unittest.TestCase):
 def test_correct_text_image_file_paths(self):
  for item,expected in [({'type':'text','text':'notice'},'text-message'),({'type':'image','path':'shot.png'},'inline-image'),({'type':'file','path':'report.xlsx'},'file-card')]:
   self.assertIsNone(violation(item));self.assertEqual(expected_presentation(item),expected)
 def test_wrong_presentation_is_rejected_before_transport(self):
  from wecom_adapter import WeComAdapter
  for item in [{'type':'file','path':'shot.png'},{'type':'image','path':'report.xlsx'}]:
   with patch.object(WeComAdapter,'_send_one',side_effect=AssertionError('transport must not run')):
    result=WeComAdapter().send_one({},item,'unused',{},0)
   self.assertEqual(result['status'],'blocked');self.assertEqual(result['sendAttempts'],0)
 def test_new_image_task_requires_actual_inline_observations(self):
  task={'taskId':'i','binding':'b','stage':'send','expectedPresentation':'inline-image',
        'request':{'groupName':'g'},'item':{'type':'image','sha256':'source'}}
  frames=[{'groupName':'g','inputEmpty':True,'newMessageVisible':True,
           'presentation':'inline-image','visibleImageContent':'observed table contents'} for _ in range(2)]
  reply={'taskId':'i','binding':'b','result':{'resolvedGroup':'g','status':'verified','sendAttempts':1,'sha256':'source','observations':frames}}
  self.assertEqual(validate_response(task,reply)['verificationLevel'],'wecom-ui-tree-image')
  frames[1]['presentation']='file-card'
  with self.assertRaisesRegex(ValueError,'inline-image'):validate_response(task,reply)
  frames[1]['presentation']='inline-image';frames[1]['visibleImageContent']=''
  with self.assertRaisesRegex(ValueError,'inline-image'):validate_response(task,reply)
 def test_legacy_image_receipt_is_not_rewritten(self):
  task={'taskId':'i','binding':'b','stage':'send','request':{'groupName':'g'},'item':{'type':'image','sha256':'source'}}
  frames=[{'groupName':'g','inputEmpty':True,'newMessageVisible':True} for _ in range(2)]
  reply={'taskId':'i','binding':'b','result':{'resolvedGroup':'g','status':'verified','sendAttempts':1,'sha256':'source','observations':frames}}
  self.assertEqual(validate_response(task,reply)['status'],'verified')
