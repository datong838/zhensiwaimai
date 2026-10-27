import sys,unittest,tempfile
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from desktop_image import find_image_in_chat
class MatchTests(unittest.TestCase):
 def test_new_image_and_static_rejection(self):
  with tempfile.TemporaryDirectory() as d:
   target=Image.new('RGB',(400,300),'white');draw=ImageDraw.Draw(target)
   for x in range(10,390,25):draw.rectangle((x,10,x+10,280),fill=(x%200,30,150))
   path=Path(d)/'source.png';target.save(path)
   before=Image.new('RGB',(1200,800),(249,249,249));after=before.copy();after.paste(target.resize((240,180)),(875,420))
   self.assertTrue(find_image_in_chat(after,before,path)['ok'])
   self.assertFalse(find_image_in_chat(after,after,path)['ok'])
