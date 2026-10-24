"""Extracted text/navigation without business cursor, history or authorization."""
import hashlib,re,subprocess,time,uuid
from pathlib import Path
from PIL import Image
from contract import Rejected as StopRun
from ledger import atomic_json

def text_hash(value):return hashlib.sha256(value.encode()).hexdigest()
def normalize(value):return ''.join(value.split())
def claim_send(group,item):
    marker=Path(item['_work'])/'attempt.json'
    with marker.open('x') as f:
        import json,os
        json.dump({'group':group,'sha256':item['sha256'],'sendAttempts':1,'state':'attempted'},f);f.flush();os.fsync(f.fileno())
    return marker
def stable_group_click(device, helpers, work, group_name, candidate):
    entries=helpers.ocr_entries(helpers.screenshot(device,work,'group-before-click'))
    matches=[e for e in entries if exact_target_group_title(e['text'],group_name)
             and abs(e['y']-candidate['y'])<25 and abs(e['x']-candidate['x'])<35]
    if len(matches)!=1:raise StopRun('group-position-not-stable')
    # ADB is bound to the calibrated physical device; fresh OCR coordinates are pixels.
    helpers.adb(device.serial,'shell','input','tap',str(matches[0]['x']),str(matches[0]['y']))

def canonical_group_ocr(value: str) -> str:
    return value.strip()

def exact_target_group_title(value: str, group: str) -> bool:
    value=canonical_group_ocr(value);group=canonical_group_ocr(group)
    if not value.startswith(group):return False
    return bool(re.fullmatch(r'(?:[（(]\d+[)）]\s*(?:[C〇Q]>?)?)?',value[len(group):]))

def group_search_candidates(entries, group_name):
    heading=next((e for e in entries if e['text'] in ('群聊','最常使用')),None)
    if not heading:return []
    boundaries=[e['y'] for e in entries if e['y']>heading['y'] and
                (e['text'] in ('创建新的群聊','聊天记录') or '搜索网络结果' in e['text'])]
    if not boundaries:return []
    boundary=min(boundaries)
    return [e for e in entries if heading['y']<e['y']<boundary and exact_target_group_title(e['text'],group_name)]

def group_title_matches(entries, group_name):
    if any('搜索网络结果' in e['text'] or e['text'] in ('群聊','创建新的群聊') for e in entries):return []
    return [e for e in entries if e['y']<280 and exact_target_group_title(e['text'],group_name)]

def newest_bubble(path, *, count=False):
    im=Image.open(path).convert('RGB');pix=im.load();rows=[]
    for y in range(260,2060,3):
        xs=[x for x in range(150,925,4) if (lambda r,g,b:70<r<210 and g>170 and 50<b<180 and g-r>25 and g-b>50)(*pix[x,y])]
        if len(xs)>35:rows.append((y,min(xs),max(xs)))
    groups=[]
    for row in rows:
        if not groups or row[0]-groups[-1][-1][0]>9:groups.append([])
        groups[-1].append(row)
    groups=[g for g in groups if g[-1][0]-g[0][0]>55]
    if count:return len(groups)
    if not groups:return None
    g=groups[-1];box=(max(0,min(r[1] for r in g)-8),g[0][0]-5,min(950,max(r[2] for r in g)+8),g[-1][0]+6)
    crop=im.crop(box)
    return box,crop,text_hash(crop.tobytes().hex())

def input_anchor(path):
    im=Image.open(path).convert('RGB');px=im.load();groups=[]
    for y in range(1400,2200,3):
        if min(px[145,y])>248 and min(px[765,y])>248:
            if not groups or y-groups[-1][-1]>12:groups.append([])
            groups[-1].append(y)
    groups=[g for g in groups if g[-1]-g[0]>90]
    if not groups:raise StopRun('white-input-region-not-found')
    g=groups[-1];return (210,g[0]+45)

def verify_new_bubble(device,helpers,work,message,before_hash):
    path=helpers.screenshot(device,work,'after-send')
    candidate=newest_bubble(path)
    if candidate is None:return {'ok':False}
    if candidate[2]==before_hash and newest_bubble(path,count=True)<=newest_bubble(work/'before-input.png',count=True):return {'ok':False}
    box,crop,fingerprint=candidate;out=work/'new-message-only.png';crop.save(out)
    entries=helpers.ocr_entries(out)
    exact=compact_ocr(entries)==normalize(message)
    return {'ok':exact,'method':'new-bubble-full-ocr','screenshot':str(out),'box':box,'fingerprint':fingerprint}

def copy_exact_text(device,serial,helpers,work,message,point,*,editor=False):
    binary=Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-agent-new-merchants-to-wechat/.runtime/ocr_control_label')
    if not binary.is_file():raise StopRun('control-label-runtime-missing')
    device.set_clipboard('verify-'+str(uuid.uuid4()),label='verification-marker')
    if editor:
        point=input_anchor(helpers.screenshot(device,work,'editor-anchor-after-marker'))
    x,y=map(str,point)
    helpers.adb(serial,'shell','input','swipe',x,y,x,y,'650')
    def menu(label):
        def locate():
            path=helpers.screenshot(device,work,'copy-menu-'+label)
            p=subprocess.run([str(binary),str(path),label],capture_output=True,text=True,timeout=5)
            points=[tuple(map(int,line.split(','))) for line in p.stdout.splitlines()]
            return [p for p in points if 260<p[1]<2200]
        points=helpers.poll(locate,lambda v:len(v)==1,3)
        if len(points)!=1:raise StopRun('copy-menu-not-unique:'+label)
        helpers.adb(serial,'shell','input','tap',str(points[0][0]),str(points[0][1]))
    if editor:menu('全选')
    menu('复制')
    actual=helpers.poll(lambda:device.clipboard,lambda v:v==message,2)
    if actual!=message:raise StopRun('wechat-copied-text-mismatch')
    if editor:helpers.adb(serial,'shell','input','keyevent','22')
    return {'method':'wechat-copy-exact','chars':len(actual),'sha256':text_hash(actual)}

def unique_group_in_title(device, helpers, work: Path, group_name: str) -> bool:
    started=time.monotonic();deadline=started+8
    while True:
        entries = helpers.ocr_entries(helpers.screenshot(device, work, "group-title"))
        if len(group_title_matches(entries, group_name)) == 1:return True
        banner=any('刚刚' in e['text'] and '微信' in e['text'] for e in entries if e['y']<350)
        if time.monotonic()>=deadline or (not banner and time.monotonic()-started>=2):return False
        # Observe the transient notification until it clears; never open another chat.
        time.sleep(.25)

def ensure_wechat_home_wait(device, helpers, work: Path) -> None:
    def is_home(entries):
        return all(helpers.find_exact(entries, label) for label in ("微信", "通讯录", "发现", "我"))

    entries = helpers.poll(
        lambda: helpers.ocr_entries(helpers.screenshot(device, work, "wechat-home-wait")),
        is_home,
        6,
    )
    if is_home(entries):
        return
    for _ in range(4):
        if device.app_current().get("package") != "com.tencent.mm":
            break
        device.press("back")
        entries = helpers.poll(
            lambda: helpers.ocr_entries(helpers.screenshot(device, work, "wechat-home-back")),
            is_home,
            2,
        )
        if is_home(entries):
            return
    raise StopRun("wechat-home-not-recognized")

def open_main_wechat_group(device, serial: str, helpers, work: Path, group_name: str) -> None:
    helpers.adb(serial, "shell", "am", "start", "-n", "com.tencent.mm/.ui.LauncherUI")
    # W1：双开 chooser 可能慢于 2s；精确点「微信」而非「微信分身」。
    deadline = time.time() + 6
    saw_chooser = False
    while time.time() < deadline:
        current = device.app_current()
        activity = current.get("activity", "")
        if "HwChooserActivity" in activity:
            saw_chooser = True
            main = device(description="微信")
            if not main.exists(timeout=1):
                main = device(text="微信")
            if main.exists(timeout=1):
                main.click()
                break
            time.sleep(0.25)
            continue
        if current.get("package") == "com.tencent.mm":
            break
        time.sleep(0.25)
    else:
        if saw_chooser:
            raise StopRun("main-wechat-chooser-not-found")
        raise StopRun("main-wechat-not-foreground")
    current = helpers.poll(lambda: device.app_current(), lambda value: value.get("package") == "com.tencent.mm", 6)
    stable_end=time.monotonic()+8;picker_backs=0
    while time.monotonic()<stable_end:
        current=device.app_current()
        if current.get('package')=='com.android.documentsui' and picker_backs<2:
            device.press('back');picker_backs+=1;time.sleep(.4);continue
        if helpers.main_wechat_foreground_evidence(serial,device)['ok']:break
        time.sleep(.3)
    else:raise StopRun('main-wechat-foreground-task-not-verified')
    if current.get("package") != "com.tencent.mm":
        raise StopRun("main-wechat-not-foreground")
    processes = helpers.adb(serial, "shell", "ps", "-A", "-o", "USER,PID,NAME")
    if not re.search(r"^u0_a\d+\s+\d+\s+com\.tencent\.mm$", processes, re.MULTILINE):
        raise StopRun("main-wechat-process-not-verified")
    if unique_group_in_title(device,helpers,work,group_name):return
    ensure_wechat_home_wait(device, helpers, work)
    home_entries = helpers.ocr_entries(helpers.screenshot(device, work, "wechat-home-groups"))
    normalized_group = group_name.replace(" ", "")
    visible = [entry for entry in home_entries
               if 280 < entry["y"] < 2050 and exact_target_group_title(entry['text'],group_name)]
    if len(visible) == 1:
        stable_group_click(device,helpers,work,group_name,visible[0])
        verified = helpers.poll(lambda: unique_group_in_title(device, helpers, work, group_name), bool, 6)
        if not verified:
            raise StopRun("visible-group-title-not-verified")
        return
    if len(visible) > 1:
        raise StopRun(f"visible-group-count:{len(visible)}")
    helpers.open_search_page(device, work)
    helpers.input_chinese(serial, device, group_name)
    entries = helpers.poll(
        lambda: helpers.ocr_entries(helpers.screenshot(device, work, "group-search")),
        lambda values: bool(group_search_candidates(values, group_name)),
        6,
    )
    matches = group_search_candidates(entries, group_name)
    if len(matches) != 1:
        raise StopRun(f"group-result-count:{len(matches)}")
    stable_group_click(device,helpers,work,group_name,matches[0])
    verified = helpers.poll(lambda: unique_group_in_title(device, helpers, work, group_name), bool, 6)
    if not verified:
        raise StopRun("group-title-not-verified")

def compact_ocr(entries: list[dict], *, y_min: int = 0, y_max: int = 9999) -> str:
    selected = sorted(
        (entry for entry in entries if y_min <= entry["y"] <= y_max),
        key=lambda entry: (entry["y"], entry["x"]),
    )
    return normalize("".join(entry["text"] for entry in selected))

def set_message_without_send(device, serial: str, helpers, work: Path, message: str) -> dict:
    width, height = device.window_size()
    device.click(width // 2, int(height * 0.925))
    device.set_clipboard(message, label="zhensi-merchant-message")
    if device.clipboard != message:
        raise StopRun("message-clipboard-roundtrip-failed")
    # 微信当前版本的 selector.set_text 会追加到既有草稿。FastInputIME 先整体清空、
    # 再从已回读的剪贴板粘贴，保证每次输入恰好一份四行文本。
    def selection():
        state=helpers.adb(serial,'shell','dumpsys','input_method')
        match=re.search(r'mCursorSelStart=(\d+) mCursorSelEnd=(\d+)',state)
        if 'packageName=com.tencent.mm' not in state or not match:return None
        return tuple(map(int,match.groups()))
    if selection()!=(0,0):raise StopRun('existing-phone-draft')
    device.clear_text()
    cleared=helpers.poll(selection,lambda value:value==(0,0),1)
    if cleared!=(0,0):
        helpers.adb(serial,'shell','input','keyevent',*(['67']*256))
        cleared=helpers.poll(selection,lambda value:value==(0,0),2)
    if cleared!=(0,0):raise StopRun('input-not-empty-after-bounded-clear')
    device.send_keys(message)
    input_method = "fastinput-clear-then-paste"
    source=helpers.screenshot(device, work, "message-input")
    # Crop before OCR so the recognizer cannot merge the left voice icon into an address.
    crop=work/'input-text-only.png'
    Image.open(source).crop((135,int(height*.60),805,int(height*.96))).save(crop)
    visible = compact_ocr(helpers.ocr_entries(crop))
    ime=helpers.adb(serial,'shell','dumpsys','input_method')
    selection=re.search(r'mCursorSelStart=(\d+) mCursorSelEnd=(\d+)',ime)
    chars=len(message.encode('utf-16-le'))//2
    if not selection or tuple(map(int,selection.groups()))!=(chars,chars) or 'packageName=com.tencent.mm' not in ime:
        raise StopRun('input-length-or-target-not-verified')
    copied=copy_exact_text(device,serial,helpers,work,message,input_anchor(source),editor=True)
    return {'ok':True,'inputMethod':input_method,'chars':chars,'fullTextVerified':True,'copyReadback':copied}

def send_and_verify(device, serial, helpers, work, group_name, message, item=None):
    timings={}
    helpers.current_message_timings=timings
    def stage(name,fn):
        start=time.monotonic()
        try:return fn()
        finally:timings[name]=round((time.monotonic()-start)*1000)
    if device.app_current().get('package')!='com.tencent.mm':raise StopRun('wechat-focus-lost-before-send')
    if not unique_group_in_title(device,helpers,work,group_name):raise StopRun('group-title-lost-before-send')
    before=helpers.screenshot(device,work,'before-input')
    bubble=newest_bubble(before);before_hash=bubble[2] if bubble else None
    input_check=stage('input_and_verify',lambda:set_message_without_send(device,serial,helpers,work,message))
    entries=helpers.ocr_entries(helpers.screenshot(device,work,'before-send'))
    matches=[e for e in helpers.find_exact(entries,'发送') if 1400<e['y']<2250 and e['x']>850]
    if len(matches)!=1:raise StopRun('send-button-not-unique')
    if not unique_group_in_title(device,helpers,work,group_name):raise StopRun('group-changed-before-send')
    if item is None:raise StopRun('send-item-contract-required')
    marker=claim_send(group_name,item)
    stage('send_once',lambda:helpers.adb(serial,'shell','input','tap',str(matches[0]['x']),str(matches[0]['y'])))
    last_candidate=None
    def stable_bubble():
        nonlocal last_candidate
        candidate=verify_new_bubble(device,helpers,work,message,before_hash)
        stable=candidate.get('fingerprint') and last_candidate==candidate.get('fingerprint')
        last_candidate=candidate.get('fingerprint');candidate['stable']=bool(stable);return candidate
    verified=stage('new_bubble_stable',lambda:helpers.poll(stable_bubble,lambda v:v['stable'],8))
    if not verified.get('stable'):raise StopRun('new-bubble-not-stable')
    b=verified['box']
    copied=stage('new_bubble_copy_readback',lambda:copy_exact_text(device,serial,helpers,work,message,(b[0]+65,b[1]+50)))
    verified.update(ok=True,method='new-bubble-wechat-copy-exact',copied=copied)
    def input_empty():
        entries=helpers.ocr_entries(helpers.screenshot(device,work,'input-empty'))
        return not [e for e in helpers.find_exact(entries,'发送') if 1400<e['y']<2250 and e['x']>850]
    if not stage('input_clear_check',lambda:helpers.poll(input_empty,bool,3)):raise StopRun('sent-but-input-not-empty')
    if not unique_group_in_title(device,helpers,work,group_name):raise StopRun('post-send-group-title-missing')
    return {'input':input_check,'postSend':verified,'stageMs':timings,'attemptMarker':str(marker)}
