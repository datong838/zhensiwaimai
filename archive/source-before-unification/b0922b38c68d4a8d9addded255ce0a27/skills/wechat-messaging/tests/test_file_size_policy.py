import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from file_size_policy import displayed_size_matches,safe_upload_budget
class FileSizePolicyTests(unittest.TestCase):
 def test_contract_quantization(self):
  for text in ['88K','89K','88.6KiB']:self.assertTrue(displayed_size_matches(90735,text))
  for text in ['87K','90K','100K']:self.assertFalse(displayed_size_matches(90735,text))
 def test_precision_and_units(self):
  self.assertTrue(displayed_size_matches(1048576,'1.0MB'))
  self.assertTrue(displayed_size_matches(123,'123B'))
  self.assertFalse(displayed_size_matches(1048576,'1.2M'))
  for text in ['nanK','-1K','infinity','89T','89K extra']:self.assertFalse(displayed_size_matches(90735,text))
 def test_actual_limit_has_margin(self):
  self.assertEqual(safe_upload_budget(88000),83600)
  for limit in [None,0,-1,88.6]:
   with self.assertRaises(ValueError):safe_upload_budget(limit)
