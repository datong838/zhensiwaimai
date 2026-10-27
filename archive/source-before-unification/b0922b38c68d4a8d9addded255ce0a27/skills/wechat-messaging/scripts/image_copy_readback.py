"""Two fresh native image copies, compared byte-exactly after lossless decode.
No send, no marker mutation. Native copy gestures are performed through CUA.
"""
import argparse
import fcntl
import hashlib
import io
import json
import signal
import sys
import time
import uuid
from pathlib import Path
from PIL import Image


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pixels(data):
    with Image.open(io.BytesIO(data)) as picture:
        image=picture.convert('RGBA')
        return {'width':image.width,'height':image.height,'rgbaSha256':sha(image.tobytes())}


def fresh_match(original, copied, *, nonce_before, nonce_after, count_before, count_after):
    return (isinstance(nonce_before,str) and bool(nonce_before) and nonce_after!=nonce_before
            and count_after>count_before and pixels(original)==pixels(copied))


def bound_source(prior, source_arg=None):
    if prior.get('state') != 'unknown' or type(prior.get('sendAttempts')) is not int or prior['sendAttempts'] < 1:
        raise ValueError('image-copy-readback-scope-invalid')
    if source_arg is None:
        if prior.get('payloadType') != 'image' or len(prior.get('payloads', [])) != 1:
            raise ValueError('image-copy-readback-scope-invalid')
        return prior['payloads'][0]
    source = Path(source_arg).resolve()
    data = source.read_bytes()
    if source.suffix.lower() != '.png' or prior.get('name') != source.name or prior.get('sha256') != sha(data):
        raise ValueError('image-copy-source-binding-mismatch')
    return {'path': str(source), 'name': source.name, 'size': len(data), 'sha256': sha(data)}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--marker',required=True);parser.add_argument('--output',required=True)
    parser.add_argument('--source')
    args=parser.parse_args();marker=Path(args.marker).resolve();prior=json.loads(marker.read_text())
    item=bound_source(prior,args.source);source=Path(item['path']);original=source.read_bytes()
    if sha(original)!=item['sha256'] or len(original)!=item['size']:
        raise ValueError('image-copy-source-binding-mismatch')
    from AppKit import NSPasteboard,NSPasteboardTypeString,NSPasteboardItem,NSWorkspace
    from Foundation import NSData
    import wecom_desktop_sender as sender
    from wecom_adapter import LOCK_PATH
    from ledger import atomic_json
    output=Path(args.output).resolve();output.mkdir(parents=True,exist_ok=True,mode=0o700)
    def current_group():
        # AX title may be temporarily absent during the app activation animation.
        # Only observe absence; an actual different title fails immediately.
        end=time.monotonic()+5
        while True:
            title=sender.current_conversation_title()
            if sender._title_matches_group(title,prior['groupName']):return title
            if title or time.monotonic()>=end:raise ValueError('image-copy-current-group-mismatch')
            time.sleep(0.25)
    def timeout(signum,frame):raise TimeoutError('image-copy-readback-timeout')
    signal.signal(signal.SIGALRM,timeout);signal.alarm(180)
    with LOCK_PATH.open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        previous_app=next((app for app in NSWorkspace.sharedWorkspace().runningApplications() if app.isActive()),None)
        pb=NSPasteboard.generalPasteboard();saved=[]
        for entry in pb.pasteboardItems() or []:
            restored=NSPasteboardItem.alloc().init()
            for kind in entry.types():
                data=entry.dataForType_(kind)
                if data is not None:restored.setData_forType_(data,kind)
            saved.append(restored)
        frames=[];nonce=None;count=None
        try:
            if not sender.activate_wecom() or not sender.wecom_is_frontmost():
                raise ValueError('image-copy-wecom-not-frontmost')
            while len(frames)<2:
                title=current_group();nonce='zhensi-readback-'+uuid.uuid4().hex
                pb.clearContents();pb.setString_forType_(nonce,NSPasteboardTypeString);count=int(pb.changeCount())
                print(json.dumps({'phase':'ready-for-cua-copy','frame':len(frames)+1,'group':title,'sendAttempts':0}),flush=True)
                command=json.loads(sys.stdin.readline())
                if command.get('copied') is not True:raise ValueError('image-copy-action-not-confirmed')
                title_after=current_group();after=int(pb.changeCount());text=pb.stringForType_(NSPasteboardTypeString)
                copied=None;kind_used=None
                for kind in ['public.png','public.tiff','NeXT TIFF v4.0 pasteboard type']:
                    data=pb.dataForType_(kind)
                    if data is not None:copied=bytes(data);kind_used=kind;break
                if copied is None or not fresh_match(original,copied,nonce_before=nonce,nonce_after=str(text or ''),count_before=count,count_after=after):
                    raise ValueError('fresh-copied-image-pixels-do-not-match')
                path=output/f'copied-frame-{len(frames)+1}.image';path.write_bytes(copied);path.chmod(0o600)
                frame={'groupBefore':title,'groupAfter':title_after,'clipboardNonceSha256':sha(nonce.encode()),
                       'changeCountBefore':count,'changeCountAfter':after,'pasteboardType':kind_used,
                       'copiedEncodedSha256':sha(copied),'pixels':pixels(copied),'copiedFile':str(path),'verified':True}
                frames.append(frame);print(json.dumps({'phase':'frame-verified','frame':len(frames),'sendAttempts':0}),flush=True)
            proof={'ok':True,'verificationLevel':'native-image-copy-pixels-exact-two-frame','marker':str(marker),
                   'markerSha256':sha(marker.read_bytes()),'groupName':prior['groupName'],'source':item,
                   'sourcePixels':pixels(original),'frames':frames,'sendAttempts':0,'reconciledWithoutSend':True,
                   'interaction':'CUA native copy only; no send gesture'}
            if json.loads(marker.read_text())!=prior:raise ValueError('image-copy-marker-changed')
            atomic_json(output/'proof.json',proof);print(json.dumps({'phase':'verified','proof':str(output/'proof.json'),'sendAttempts':0}),flush=True)
        finally:
            pb.clearContents()
            if saved:pb.writeObjects_(saved)
            if previous_app is not None:previous_app.activateWithOptions_(0)
            signal.alarm(0)

if __name__=='__main__':
    main()
