"""Bounded current-viewport verification of explicitly named historical files.

No scrolling, copying unrelated messages, download, send, or delivery-ledger writes.
Historical visibility is never a new delivery receipt.
"""
from pathlib import Path
import time
from PIL import Image
from contract import Rejected
from evidence import file_frame_matches


def verify_existing_files(request, adapter, work):
    if any(item['type'] != 'file' for item in request['items']):
        raise Rejected('history-verifier-supports-files-only')
    started = time.monotonic()
    work = Path(work); work.mkdir(parents=True,exist_ok=True,mode=0o700)
    preflight = adapter.preflight(request, work/'preflight')
    if preflight.get('ok') is not True:
        raise Rejected(preflight.get('reason','history-preflight-failed'))
    frames=[]
    for number in (1,2):
        shot=work/f'history-{number}.png'
        adapter.wd.screenshot_main_region(shot)
        shot.chmod(0o600)
        hits=adapter.wd.ocr(shot)
        if len(adapter.wd.find_exact_headers(hits,request['groupName']))!=1:
            raise Rejected('history-group-title-not-unique')
        with Image.open(shot) as image:
            width,height=image.size
        current=[]
        for item in request['items']:
            matches=[h for h in hits if h.text.strip()==item['name']
                     and h.cx>width*.45 and height*.12<h.cy<height*.82]
            if len(matches)!=1:
                raise Rejected('historical-file-not-unique')
            hit=matches[0]
            text='\n'.join(h.text for h in hits if abs(h.cy-hit.cy)<100 and abs(h.cx-hit.cx)<240)
            if not file_frame_matches(text,item['name'],item['size']):
                raise Rejected('historical-file-name-size-mismatch')
            current.append({'itemId':item['itemId'],'name':item['name'],'size':item['size'],
                            'sourceSha256':item['sha256'],'position':[hit.cx,hit.cy]})
        frames.append(current)
        if number==1:time.sleep(.4)
    for a,b in zip(*frames):
        if any(abs(x-y)>6 for x,y in zip(a['position'],b['position'])):
            raise Rejected('historical-file-not-stable')
    return {'ok':True,'mode':'verify-existing-no-send','status':'historical_visible_verified',
            'groupName':request['groupName'],'sendAttempts':0,'deliveryLedgerWritten':False,
            'byteExact':False,'verificationLevel':'historical-file-name-size-ui',
            'items':frames[-1],'frames':frames,'preflight':preflight,
            'elapsedMs':round((time.monotonic()-started)*1000)}
