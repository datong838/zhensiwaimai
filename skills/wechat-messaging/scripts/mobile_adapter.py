"""Bound-device, main-WeChat adapter for the shared delivery engine."""
import fcntl,hashlib,json,os,re,subprocess,time
from contextlib import contextmanager
from pathlib import Path
from PIL import Image,ImageChops,ImageStat
from contract import Rejected,file_hash
from ledger import atomic_json
from evidence import file_frame_matches
import mobile_helpers as h
import mobile_text as t
import mobile_files as f

class MobileAdapter:
    channel='mobile'
    supported={'text','image','file'}
    def __init__(self,serial):
        if not serial or serial.startswith('emulator-'):raise Rejected('physical-device-required')
        self.serial=serial;self.device=None
        self.device_hash=hashlib.sha256(serial.encode()).hexdigest()[:12]
    @contextmanager
    def session(self,request):
        import uiautomator2 as u2
        lock=Path(__file__).resolve().parents[1]/'.runtime'/('mobile-'+self.device_hash+'.lock')
        lock.parent.mkdir(exist_ok=True,mode=0o700)
        with lock.open('a') as stream:
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            self.device=u2.connect(self.serial)
            original=h.adb(self.serial,'shell','settings','get','secure','default_input_method')
            try:
                if tuple(self.device.window_size())!=(1080,2340):raise Rejected('unverified-phone-geometry')
                if h.adb(self.serial,'shell','getprop','ro.kernel.qemu')=='1':raise Rejected('physical-device-required')
                yield
            finally:
                if original and original!='null':h.adb(self.serial,'shell','ime','set',original)
                fcntl.flock(stream,fcntl.LOCK_UN)
    def main(self):
        if not h.main_wechat_foreground_evidence(self.serial,self.device)['ok']:raise Rejected('main-wechat-foreground-task-not-verified')
    def preflight(self,request,output):
        output.mkdir(exist_ok=True,parents=True,mode=0o700)
        if request['context']['accountAlias']!='main-wechat':raise Rejected('only-main-wechat-supported')
        t.open_main_wechat_group(self.device,self.serial,h,output,request['groupName'])
        self.main()
        entries=h.ocr_entries(h.screenshot(self.device,output,'verified-group'))
        matches=[e for e in entries if e['y']<280 and re.fullmatch(re.escape(request['groupName'])+r'[（(]\d+[）)]\s*(?:[C〇Q]>?)?',e['text'].strip())]
        if len(matches)!=1:raise Rejected('mobile-group-type-not-proven')
        return {'ok':True,'deviceHash':self.device_hash,'userId':0,'groupTypeVerified':True}
    def claim(self,request,item,work):
        self.main()
        t.claim_send(request['groupName'],item|{'_work':str(work)})
    def stage_remote(self,item,folder):
        # File paths use shell-safe names chosen locally; never interpolate shell text.
        if not re.fullmatch(r'[\w.\-\u3400-\u9fff]+',item['name']):raise Rejected('mobile-filename-not-supported')
        remote=f'/sdcard/{folder}/{item["name"]}'
        h.adb(self.serial,'shell','mkdir','-p',f'/sdcard/{folder}')
        h.run([h.ADB,'-s',self.serial,'push',item['path'],remote],timeout=20)
        if h.adb(self.serial,'shell','sha256sum',remote).split()[0]!=item['sha256']:raise Rejected('mobile-payload-hash-mismatch')
        return remote
    def send_one(self,request,item,work,grant,deadline):
        try:
            self.main()
            if not t.unique_group_in_title(self.device,h,work,request['groupName']):raise Rejected('mobile-group-mismatch')
            if item['type']=='text':
                proof=t.send_and_verify(self.device,self.serial,h,work,request['groupName'],item['text'],item|{'_work':str(work)})
                level='native-text-exact'
            elif item['type']=='image':proof=self.image(request,item,work);level='opened-image-content-match'
            else:proof=self.file(request,item,work);level='file-name-size-ui'
            return {'status':'verified','sendAttempts':1,'verificationLevel':level,'evidence':proof,'deviceHash':self.device_hash,'userId':0}
        except Exception as error:
            attempted=(work/'attempt.json').exists()
            failure={}
            if self.device is not None:
                try:
                    current=self.device.app_current();failure['foreground']=current
                    if current.get('package') in ('com.tencent.mm','com.android.documentsui'):
                        failure['screenshot']=str(h.screenshot(self.device,work,'failure'))
                except Exception:pass
            return {'status':'unknown' if attempted else 'blocked','sendAttempts':1 if attempted else 0,'reason':str(error),'deviceHash':self.device_hash,'failureEvidence':failure}
    def image(self,request,item,work):
        device=self.device;proof={}
        remote=self.stage_remote(item,'Pictures/wechat_messaging')
        h.adb(self.serial,'shell','am','broadcast','-a','android.intent.action.MEDIA_SCANNER_SCAN_FILE','-d','file://'+remote)
        if not h.poll(lambda:h.verify_media_newest(self.serial,item['name']),bool,5):raise Rejected('mobile-media-index-not-ready')
        before=h.screenshot(device,work,'before-image')
        # Calibrated plus position is followed by fresh panel labels, never a send fallback.
        device.click(1020,2140);h.click_text(device,work,'plus-panel','相册')
        gallery=h.poll(lambda:h.ocr_entries(h.screenshot(device,work,'gallery-ready')),h.gallery_ready,6)
        if not h.gallery_ready(gallery):raise Rejected('mobile-gallery-page-not-ready')
        point,distance,method=h.stable_target_thumbnail(device,work,Path(item['path']),proof)
        device.click(*point)
        def selected():return h.ocr_entries(h.screenshot(device,work,'gallery-selected'))
        entries=h.poll(selected,lambda es:any(re.fullmatch(r'预览[（(]1[）)]',e['text'].replace(' ','')) for e in es),5)
        previews=[e for e in entries if re.fullmatch(r'预览[（(]1[）)]',e['text'].replace(' ',''))]
        if len(previews)!=1:raise Rejected('mobile-one-image-not-selected')
        device.click(previews[0]['x'],previews[0]['y'])
        preview=h.poll(lambda:h.screenshot(device,work,'preview-image'),lambda path:h.verify_large_image(path,Path(item['path']))['ok'],5)
        verified=h.verify_large_image(preview,Path(item['path']))
        if not verified['ok']:raise Rejected('mobile-preview-content-mismatch')
        sends=[e for e in h.ocr_entries(preview) if re.fullmatch(r'发送[（(]1[）)]',e['text'].replace(' ',''))]
        if len(sends)!=1:raise Rejected('mobile-one-image-send-not-unique')
        self.claim(request,item,work);device.click(sends[0]['x'],sends[0]['y'])
        if not h.poll(lambda:t.unique_group_in_title(device,h,work,request['groupName']),bool,12):raise Rejected('mobile-post-image-group-missing')
        proof['largeImage']=h.open_and_verify_sent_image(device,work,Path(item['path']),request['groupName'],proof)
        device.press('back')
        if not t.unique_group_in_title(device,h,work,request['groupName']):raise Rejected('mobile-return-from-viewer-failed')
        proof.update(preview=verified,thumbnailDistance=distance,thumbnailMethod=method,originalRequired=False)
        return proof
    def file(self,request,item,work):
        device=self.device;item=item|{'platform':item['itemId']}
        self.stage_remote(item,'Download/wechat_messaging')
        before=h.ocr_entries(h.screenshot(device,work,'before-file'))
        if any(item['name'] in e['text'] for e in before if e['y']>280):raise Rejected('mobile-existing-same-name-visible')
        panel=f.open_file_panel(device,h,work);selection=f.select_phone_file(device,h,work,item)
        shot,entries,send=f.stable_selected_send(device,h,work,item)
        self.claim(request,item,work);device.click(send['x'],send['y'])
        end=time.monotonic()+40;previous=None;frames=[]
        while time.monotonic()<end:
            self.main();shot=h.screenshot(device,work,'file-after-'+str(len(frames)));entries=h.ocr_entries(shot)
            names=[e for e in entries if e['y']>280 and e['x']>300 and e['text'].strip().replace('.xIsx','.xlsx')==item['name']]
            good=False;point=None
            if len(names)==1 and t.group_title_matches(entries,request['groupName']):
                n=names[0];near='\n'.join(e['text'].replace('.xIsx','.xlsx') for e in entries if abs(e['y']-n['y'])<150 and abs(e['x']-n['x'])<400)
                good=file_frame_matches(near,item['name'],item['size']);point=(n['x'],n['y'])
            frames.append(str(shot))
            if good and point==previous:return {'frames':frames[-2:],'fullName':True,'size':True,'uploadComplete':True,'selection':selection,'panel':panel}
            previous=point if good else None;time.sleep(.4)
        raise Rejected('mobile-file-readback-incomplete')
    def reconcile(self,*args):return {'status':'unknown','sendAttempts':0,'reason':'mobile-readonly-reconcile-not-implemented'}
