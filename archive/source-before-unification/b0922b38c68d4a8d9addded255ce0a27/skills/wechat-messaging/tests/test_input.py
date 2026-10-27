import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from desktop_input import choose_composer
from contract import Rejected
class InputTests(unittest.TestCase):
 def test_excludes_search(self):self.assertEqual(choose_composer([('search',(156,18)),('chat',(774,51))])[0],'chat')
 def test_zero_or_multiple_rejected(self):
  for xs in [[],[('a',(774,51)),('b',(774,51))]]:
   with self.assertRaises(Rejected):choose_composer(xs)
 def test_process_id_exact_unique(self):
  from desktop_input import unique_pid
  self.assertEqual(unique_pid('51688\n'),51688)
  for value in ('','1\n2','abc'):
   with self.assertRaises(Rejected):unique_pid(value)
