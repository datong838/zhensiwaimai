import copy
import io
import json
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from reconcile_native_image import reconcile, sha, pixels

class ReconciliationTests(unittest.TestCase):
    def fixture(self, root):
        buf=io.BytesIO();Image.new('RGBA',(4,4),(20,50,70,255)).save(buf,format='PNG');data=buf.getvalue()
        source=root/'source.png';source.write_bytes(data)
        payload={'path':str(source),'name':source.name,'size':len(data),'sha256':sha(data)}
        marker=root/'marker.json';key='a'*64;event=root/'.wechat-messaging/events'/key
        item_dir=event/'item';item_dir.mkdir(parents=True)
        prior={'state':'unknown','payloadType':'image','payloads':[payload],'groupName':'授权群','sendAttempts':1,'commonReceipt':{'eventKey':key}}
        marker.write_text(json.dumps(prior,ensure_ascii=False))
        binding={'groupName':'授权群','accountAlias':'main-wechat','items':[{'itemId':'0','type':'image',**{k:payload[k] for k in ['name','size','sha256']}}]}
        (event/'binding.json').write_text(json.dumps({'digest':sha(json.dumps(binding,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())}))
        delivery=item_dir/'delivery.json';delivery.write_text(json.dumps({'status':'unknown','type':'image','sha256':sha(data),'sendAttempts':1}))
        frames=[]
        for n in [1,2]:
            copied=root/f'copy{n}.png';copied.write_bytes(data)
            frames.append({'verified':True,'groupBefore':'授权群','groupAfter':'授权群','copiedFile':str(copied),'copiedEncodedSha256':sha(data),'pixels':pixels(data),'clipboardNonceSha256':str(n)*64,'changeCountBefore':n*2,'changeCountAfter':n*2+1})
        proof={'ok':True,'sendAttempts':0,'reconciledWithoutSend':True,'verificationLevel':'native-image-copy-pixels-exact-two-frame','marker':str(marker),'markerSha256':sha(marker.read_bytes()),'groupName':'授权群','source':payload,'sourcePixels':pixels(data),'frames':frames}
        path=root/'proof.json';path.write_text(json.dumps(proof,ensure_ascii=False));return path,marker,delivery,proof

    def test_dry_run_and_apply_preserve_original_attempt(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);proof,marker,delivery,_=self.fixture(root);original=marker.read_bytes()
            self.assertFalse(reconcile(proof,root=root)['applied']);self.assertEqual(marker.read_bytes(),original)
            self.assertTrue(reconcile(proof,root=root,apply=True)['verified'])
            final=json.loads(marker.read_bytes());self.assertEqual(final['sendAttempts'],1);self.assertEqual(final['newSendAttempts'],0)
            self.assertEqual(json.loads(delivery.read_bytes())['status'],'verified')
            self.assertEqual(next(root.glob('native-copy-reconciliation/*/original-marker.json')).read_bytes(),original)
            with self.assertRaises(ValueError):reconcile(proof,root=root,apply=True)

    def test_bad_proofs_do_not_mutate(self):
        for change in [lambda p:p.update(groupName='其他群'),lambda p:p['frames'].pop(),lambda p:p['frames'][1].update(clipboardNonceSha256='1'*64),lambda p:p['frames'][0].update(changeCountAfter=0),lambda p:p['frames'][0].update(copiedEncodedSha256='0'*64),lambda p:p['sourcePixels'].update(width=9)]:
            with self.subTest(change=change),tempfile.TemporaryDirectory() as td:
                root=Path(td);path,marker,delivery,proof=self.fixture(root);old=marker.read_bytes();old_item=delivery.read_bytes();change(proof);path.write_text(json.dumps(proof,ensure_ascii=False))
                with self.assertRaises(ValueError):reconcile(path,root=root,apply=True)
                self.assertEqual(marker.read_bytes(),old);self.assertEqual(delivery.read_bytes(),old_item)

if __name__=='__main__':unittest.main()
