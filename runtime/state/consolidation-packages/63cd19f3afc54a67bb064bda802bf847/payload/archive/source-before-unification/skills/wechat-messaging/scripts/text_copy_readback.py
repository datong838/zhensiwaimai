"""Original text marker reconciliation evidence only. CUA performs copying."""
import argparse,fcntl,hashlib,json,signal,sys,uuid,time
from pathlib import Path

def sha(data):return hashlib.sha256(data).hexdigest()
def bound_text(prior):
    payload=prior.get('payloads') or []
    if prior.get('payloadType')!='text' or len(payload)!=1 or prior.get('sendAttempts')!=1 or prior.get('groupName')!='电销+直播攻坚组':raise ValueError('scope-invalid')
    text=payload[0]['text']
    if sha(text.encode())!=payload[0]['sha256']:raise ValueError('payload-hash-invalid')
    return text

def main():
    p=argparse.ArgumentParser();p.add_argument('--marker',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    marker=Path(a.marker).resolve();raw=marker.read_bytes();prior=json.loads(raw);expected=bound_text(prior)
    from AppKit import NSPasteboard,NSPasteboardItem,NSPasteboardTypeString
    import wecom_desktop_sender as s
    from wecom_adapter import LOCK_PATH
    from ledger import atomic_json
    pb=NSPasteboard.generalPasteboard();saved=[]
    with LOCK_PATH.open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for entry in pb.pasteboardItems() or []:
            restored=NSPasteboardItem.alloc().init()
            for kind in entry.types():
                data=entry.dataForType_(kind)
                if data is not None:restored.setData_forType_(data,kind)
            saved.append(restored)
        signal.signal(signal.SIGALRM,lambda *args: (_ for _ in ()).throw(TimeoutError('copy-timeout')));signal.alarm(180)
        frames=[]
        def observe():
            group=s.current_conversation_title();box=s.locate_input_box()
            if group!=prior['groupName'] or box is None or s.ax(box['el'],'AXValue')[0]:raise ValueError('wrong-group-or-nonempty-input')
            matches=[]
            for el in s.iter_tree(s.main_window()):
                role,err=s.ax(el,'AXRole');v,_=s.ax(el,'AXValue');pos=s.ax_pos(el)
                if not err and str(role)=='AXTextArea' and str(v or '')==expected and pos and pos[0]>s._win_x()+250:matches.append(pos)
            if len(matches)!=1:raise ValueError('payload-node-not-unique:'+str(len(matches)))
            return group,matches[0]
        try:
            if not s.activate_wecom() or not s.wecom_is_frontmost():raise ValueError("wecom-not-frontmost")
            time.sleep(1.2)
            ok,detail=s.search_open_conversation(prior["groupName"])
            if not ok:raise ValueError("target-navigation-failed:"+detail)
            for i in range(2):
                group,pos=observe();nonce='zhensi-text-'+uuid.uuid4().hex;pb.clearContents();pb.setString_forType_(nonce,NSPasteboardTypeString);before=int(pb.changeCount())
                print(json.dumps({'phase':'ready','frame':i+1,'position':pos,'sendAttempts':0}),flush=True)
                cmd=json.loads(sys.stdin.readline());copied=pb.stringForType_(NSPasteboardTypeString);after=int(pb.changeCount());group2,pos2=observe()
                if cmd.get('copied') is not True or cmd.get('copyMenuCount')!=1 or copied!=expected or after<=before or copied==nonce:raise ValueError('native-copy-not-exact')
                frames.append({'groupBefore':group,'groupAfter':group2,'composerEmpty':True,'bubblePosition':pos2,'copyMenuCount':1,'copiedTextSha256':sha(copied.encode()),'nonceSha256':sha(nonce.encode()),'changeCountBefore':before,'changeCountAfter':after})
                print(json.dumps({'phase':'frame-verified','frame':i+1}),flush=True)
            if marker.read_bytes()!=raw:raise ValueError('marker-changed')
            out=Path(a.output);out.mkdir(parents=True,exist_ok=True,mode=0o700);atomic_json(out/'proof.json',{'ok':True,'marker':str(marker),'markerSha256':sha(raw),'groupName':prior['groupName'],'payloadSha256':sha(expected.encode()),'frames':frames,'sendAttempts':0,'reconciledWithoutSend':True});print(json.dumps({'phase':'verified','proof':str(out/'proof.json')}),flush=True)
        finally:
            pb.clearContents()
            if saved:pb.writeObjects_(saved)
            signal.alarm(0)
if __name__=='__main__':main()
