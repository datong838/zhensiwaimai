import io
import sys
import unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from image_copy_readback import fresh_match,pixels

class ExactImageProof(unittest.TestCase):
 def picture(self,color,fmt='PNG',size=(8,9)):
  out=io.BytesIO();Image.new('RGB',size,color).save(out,format=fmt);return out.getvalue()
 def test_lossless_copy_formats_match_pixels(self):
  source=self.picture('red');copied=self.picture('red','TIFF')
  self.assertTrue(fresh_match(source,copied,nonce_before='fresh',nonce_after='',count_before=10,count_after=11))
  self.assertEqual(pixels(source),pixels(copied))
 def test_stale_clipboard_and_wrong_image_are_rejected(self):
  source=self.picture('red')
  self.assertFalse(fresh_match(source,source,nonce_before='fresh',nonce_after='fresh',count_before=10,count_after=11))
  self.assertFalse(fresh_match(source,source,nonce_before='fresh',nonce_after='',count_before=10,count_after=10))
  self.assertFalse(fresh_match(source,self.picture('blue'),nonce_before='fresh',nonce_after='',count_before=10,count_after=11))
  self.assertFalse(fresh_match(source,self.picture('red',size=(9,9)),nonce_before='fresh',nonce_after='',count_before=10,count_after=11))
if __name__=='__main__':unittest.main()
