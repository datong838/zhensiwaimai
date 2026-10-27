#!/usr/bin/env python3
"""Finish an explicitly authorized, recently verified phone preview exactly once."""
import argparse,json,re,time,signal,tempfile
from pathlib import Path
import uiautomator2 as u2
import phone_executor as p


def finish(args):
    started=time.monotonic();work=Path(tempfile.mkdtemp(prefix='zhensi-finish-'));result={'ok':False,'executor':'phone-finish','sendAttempts':0,'stageMs':{},'receiptFile':str(work/'send_receipt.json')}
    try:
        def timeout(*_):raise p.StopRun('prepared-send-deadline')
        signal.signal(signal.SIGALRM,timeout);signal.setitimer(signal.ITIMER_REAL,90)
        done=p.stage(result,'verify_prepared')
        source=Path(args.training_receipt);trained=json.loads(source.read_text())
        if args.standing_authorization!=p.AUTHORIZATION:raise p.StopRun('standing-authorization-missing')
        if not trained.get('ok') or not trained.get('previewVerified') or trained.get('sendAttempts')!=0 or trained.get('group')!=p.TARGET_GROUP or trained.get('mode')!='training-preview-no-send':raise p.StopRun('training-receipt-invalid')
        if not 0<=time.time()-source.stat().st_mtime<180:raise p.StopRun('prepared-preview-expired')
        desktop,image=p.load_receipt(Path(args.desktop_receipt),for_training=True)
        if desktop['sha256']!=trained['fileSha256']:raise p.StopRun('prepared-image-changed')
        serial=json.loads(Path(args.transport_file).read_text())['serial'];d=u2.connect(serial)
        if d.app_current().get('package')!='com.tencent.mm':raise p.StopRun('wechat-not-foreground')
        if not re.search(r'(?:mResumedActivity|topResumedActivity)[^\n]*\bu0\s+com\.tencent\.mm/',p.adb(serial,'shell','dumpsys','activity','activities')):raise p.StopRun('main-wechat-not-foreground')
        screen=p.screenshot(d,work,'prepared-preview');entries=p.ocr_entries(screen)
        match=p.verify_large_image(screen,image)
        if not match['ok'] or not all(any(t in e['text'] for e in entries) for t in p.REQUIRED_IMAGE_TEXT):raise p.StopRun('prepared-preview-content-mismatch')
        original=p.find_exact(entries,'原图');send=[e for e in entries if re.fullmatch(r'发送[（(]1[）)]',e['text'].replace(' ',''))]
        if len(original)!=1 or not p.green_mark_near(screen,original[0]) or len(send)!=1:raise p.StopRun('prepared-original-or-count-mismatch')
        result.update(group=p.TARGET_GROUP,dataDate=desktop['dataDate'],runId=desktop['runId'],fileSha256=desktop['sha256'],previewDistance=match['distance']);done()
        done=p.stage(result,'send_once');p.claim_send_once(desktop);result['sendAttempts']=1;d.click(send[0]['x'],send[0]['y']);done()
        done=p.stage(result,'verify_sent')
        chat=p.poll(lambda:p.screenshot(d,work,'sent-chat'),lambda f:bool(p.group_title_matches(p.ocr_entries(f),p.TARGET_GROUP)),10)
        if not p.group_title_matches(p.ocr_entries(chat),p.TARGET_GROUP):raise p.StopRun('post-send-group-title-missing')
        point,distance=p.locate_chat_target(chat,image);result['sentBubbleDistance']=distance;d.click(*point)
        evidence=p.poll(lambda:p.verify_large_image(p.screenshot(d,work,'sent-large-image'),image),lambda v:v['ok'],12)
        result['largeImageVerification']=evidence
        if not evidence['ok']:raise p.StopRun('sent-image-not-verified')
        done();result.update(ok=True,verified=True)
    except Exception as e:result['reason']=str(e)
    finally:
        signal.setitimer(signal.ITIMER_REAL,0)
        t=result.pop('stageStartedMonotonic',None)
        if t is not None and result.get('stage') not in result['stageMs']:result['stageMs'][result['stage']]=round((time.monotonic()-t)*1000)
        result['elapsedMs']=round((time.monotonic()-started)*1000)
        Path(result['receiptFile']).write_text(json.dumps(result,ensure_ascii=False,indent=2));Path(result['receiptFile']).chmod(0o600)
        (work/'sent-chat.png').unlink(missing_ok=True)
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['training-receipt','desktop-receipt','transport-file','standing-authorization']:parser.add_argument('--'+name,required=True)
    r=finish(parser.parse_args());print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r['ok'] else 1)
