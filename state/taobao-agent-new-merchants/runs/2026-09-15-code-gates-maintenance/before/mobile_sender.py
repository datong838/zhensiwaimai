#!/usr/bin/env python3
"""Fail-closed, transactional merchant-message sender for the authorized main WeChat."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import time
import io
import subprocess
import signal
import fcntl
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from PIL import Image
from pathlib import Path

import uiautomator2 as u2


STATE_DIR = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai/state/taobao-agent-new-merchants")
HISTORY_FILE = STATE_DIR / "send-history.jsonl"
TEST_GROUP = "FEIBING NEO AI数字员工"
PRODUCTION_GROUP = "电销+直播攻坚组"
TEST_AUTHORIZATION = "zhensi-test-main-wechat-merchant-v1"
PHONE_EXECUTOR = Path(__file__).resolve().parents[2] / "daily-top10-to-wechat-group/scripts/phone_executor.py"


class StopRun(RuntimeError):
    pass


def load_phone_helpers():
    spec = importlib.util.spec_from_file_location("zhensi_phone_helpers", PHONE_EXECUTOR)
    if spec is None or spec.loader is None:
        raise StopRun("phone-helper-load-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def install_capture(helpers, serial):
    """Task-local adapter: preserve sealed helpers and avoid u2's flaky image stream."""
    def capture(device, directory, name):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path=directory / (name+'.png')
        for attempt in range(2):
            p=subprocess.run([helpers.ADB,'-s',serial,'exec-out','screencap','-p'],capture_output=True,timeout=8)
            try:
                im=Image.open(io.BytesIO(p.stdout));im.load()
                if im.size!=(1080,2340):raise ValueError('capture-geometry')
                im.save(path);os.chmod(path,0o600);return path
            except (OSError,ValueError):
                if attempt:raise StopRun('phone-capture-invalid-after-retry')
        raise StopRun('phone-capture-failed')
    helpers.screenshot=capture


def stable_group_click(device, helpers, work, group_name, candidate):
    entries=helpers.ocr_entries(helpers.screenshot(device,work,'group-before-click'))
    matches=[e for e in entries if exact_target_group_title(e['text'],group_name)
             and abs(e['y']-candidate['y'])<25 and abs(e['x']-candidate['x'])<35]
    if len(matches)!=1:raise StopRun('group-position-not-stable')
    # ADB is bound to the calibrated physical device; fresh OCR coordinates are pixels.
    helpers.adb(device.serial,'shell','input','tap',str(matches[0]['x']),str(matches[0]['y']))


def canonical_group_ocr(value: str) -> str:
    return value.strip().replace(" ", "").replace("Al", "AI")


def exact_target_group_title(value: str, group: str) -> bool:
    value=canonical_group_ocr(value);group=canonical_group_ocr(group)
    if not value.startswith(group):return False
    return bool(re.fullmatch(r'(?:[（(]\d+[)）])?',value[len(group):]))


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


def send_identity(group,item):
    return text_hash(group+'\n'+item['merchantId']+'\n'+item['recommendTime'])


def claim_send(group,item):
    directory=STATE_DIR/'send-attempts';directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=directory/(send_identity(group,item)+'.json')
    try:
        with path.open('x') as f:
            os.chmod(path,0o600)
            json.dump({'groupName':group,'merchantId':item['merchantId'],'recommendTime':item['recommendTime'],
                       'messageSha256':item['sha256'],'state':'attempted','at':time.time()},f)
            f.flush();os.fsync(f.fileno())
    except FileExistsError:raise StopRun('send-already-attempted-result-must-be-reconciled')
    return path


def audit_collection(receipt):
    date=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d')
    if receipt.get('businessDate')!=date:raise StopRun('collection-date-stale')
    if not all(receipt.get(k) is True for k in ('dateFilterVerified','paginationComplete','ascending','detailsVerified')):
        raise StopRun('collection-evidence-incomplete')
    created=datetime.fromisoformat(receipt['createdAt']).timestamp()
    if not 0<=time.time()-created<1800:raise StopRun('collection-expired')
    start=receipt.get('filterStartDate');end=receipt.get('filterEndDate')
    if not re.fullmatch(r'\d{4}-\d\d-\d\d',start or '') or end!=date or receipt.get('dateFilter')!=f'{start}..{end}':raise StopRun('collection-date-range-invalid')
    messages=receipt['messages']
    if any(m.get('detailVerified') is not True or m.get('status')!='待处理' or not start<=m['recommendTime'][:10]<=end for m in messages):raise StopRun('message-source-invalid')
    keys=[(m['recommendTime'],m['tableOrder']) for m in messages]
    if keys!=sorted(keys):raise StopRun('message-order-invalid')
    if len({(m['merchantId'],m['recommendTime']) for m in messages})!=len(messages):raise StopRun('duplicate-merchant-recommendation')


def newest_bubble(path):
    im=Image.open(path).convert('RGB');pix=im.load();rows=[]
    for y in range(260,2060,3):
        xs=[x for x in range(150,925,4) if (lambda r,g,b:70<r<210 and g>170 and 50<b<180 and g-r>25 and g-b>50)(*pix[x,y])]
        if len(xs)>35:rows.append((y,min(xs),max(xs)))
    groups=[]
    for row in rows:
        if not groups or row[0]-groups[-1][-1][0]>9:groups.append([])
        groups[-1].append(row)
    groups=[g for g in groups if g[-1][0]-g[0][0]>55]
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
    if candidate is None or candidate[2]==before_hash:return {'ok':False}
    box,crop,fingerprint=candidate;out=work/'new-message-only.png';crop.save(out)
    entries=helpers.ocr_entries(out)
    exact=compact_ocr(entries)==normalize(message)
    return {'ok':exact,'method':'new-bubble-full-ocr','screenshot':str(out),'box':box,'fingerprint':fingerprint}


def copy_exact_text(device,serial,helpers,work,message,point,*,editor=False):
    binary=Path(__file__).resolve().parents[1]/'.runtime/ocr_control_label'
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


def reconcile_attempt(collection_path, serial, item_work):
    """Read back the interrupted item from retained evidence. Never click send."""
    started=time.monotonic();item_work=Path(item_work)
    collection=load_collection(Path(collection_path),TEST_GROUP);audit_collection(collection)
    items=[m for m in collection['messages'] if m['merchantId']==item_work.name]
    if len(items)!=1:raise StopRun('reconcile-item-not-unique')
    item=items[0];marker=STATE_DIR/'send-attempts'/(send_identity(TEST_GROUP,item)+'.json')
    attempt=json.loads(marker.read_text())
    if attempt.get('state')!='attempted' or attempt.get('messageSha256')!=item['sha256']:raise StopRun('reconcile-attempt-mismatch')
    before=newest_bubble(item_work/'before-input.png');h=load_phone_helpers();install_capture(h,serial);device=u2.connect(serial)
    if device.app_current().get('package')!='com.tencent.mm' or not unique_group_in_title(device,h,item_work,TEST_GROUP):raise StopRun('reconcile-group-not-ready')
    verified=verify_new_bubble(device,h,item_work,item['text'],before[2] if before else None)
    if not verified['ok']:raise StopRun('reconcile-current-bubble-not-exact')
    entries=h.ocr_entries(h.screenshot(device,item_work,'reconcile-input-empty'))
    if any(e['x']>850 and 1400<e['y']<2250 for e in h.find_exact(entries,'发送')):raise StopRun('reconcile-input-not-empty')
    history=[]
    if HISTORY_FILE.exists():history=[json.loads(x) for x in HISTORY_FILE.read_text().splitlines()]
    if any(x.get('groupName')==TEST_GROUP and x.get('merchantId')==item['merchantId'] and x.get('recommendTime')==item['recommendTime'] for x in history):raise StopRun('reconcile-already-committed')
    append_history_then_cursor(TEST_GROUP,collection['businessDate'],item)
    atomic_write_json(marker,{'state':'verified','reconciled':True,'merchantId':item['merchantId'],'sha256':item['sha256']})
    return {'ok':True,'mode':'readback-only-reconciliation','sendAttempts':0,'merchantId':item['merchantId'],'verification':verified,'elapsedMs':round((time.monotonic()-started)*1000)}


def cursor_file(group_name: str) -> Path:
    if group_name == TEST_GROUP:
        return STATE_DIR / "cursor.test.json"
    if group_name == PRODUCTION_GROUP:
        return STATE_DIR / "cursor.json"
    raise StopRun(f"unsupported-group:{group_name}")


def text_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize(value: str) -> str:
    return re.sub(r"\s+", "", value or "").replace("，", ",").replace("（", "(").replace("）", ")").replace('•','·').replace('⋅','·')


def load_collection(path: Path, expected_group: str) -> dict:
    if not path.is_file():
        raise StopRun("collection-receipt-missing")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    if receipt.get("ok") is not True or receipt.get("executor") != "merchant-collector":
        raise StopRun("collection-receipt-invalid")
    if receipt.get("groupName") != expected_group:
        raise StopRun("collection-group-mismatch")
    messages = receipt.get("messages")
    if not isinstance(messages, list):
        raise StopRun("collection-messages-invalid")
    seen = set()
    for item in messages:
        required = ("merchantId", "merchantName", "recommendTime", "tableOrder", "text", "sha256")
        if not all(item.get(key) not in (None, "") for key in required):
            raise StopRun("message-contract-incomplete")
        if text_hash(item["text"]) != item["sha256"]:
            raise StopRun(f"message-hash-mismatch:{item['merchantId']}")
        identity = (item["merchantId"], item["recommendTime"], item["tableOrder"])
        if identity in seen:
            raise StopRun("duplicate-message-identity")
        seen.add(identity)
        if len(item["text"].splitlines()) != 4:
            raise StopRun(f"message-line-count:{item['merchantId']}")
    return receipt


def atomic_write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def append_history_then_cursor(group_name: str, business_date: str, item: dict) -> dict:
    sent_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    history = {
        "schemaVersion": 1,
        "groupName": group_name,
        "mode": "test" if group_name == TEST_GROUP else "production",
        "businessDate": business_date,
        "merchantName": item["merchantName"],
        "merchantId": item["merchantId"],
        "recommendTime": item["recommendTime"],
        "tableOrder": item["tableOrder"],
        "messageSha256": item["sha256"],
        "sentAt": sent_at,
        "verified": True,
    }
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with HISTORY_FILE.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(history, ensure_ascii=False, separators=(",", ":")) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    atomic_write_json(cursor_file(group_name), history)
    return history


def unique_group_in_title(device, helpers, work: Path, group_name: str) -> bool:
    deadline=time.monotonic()+8
    while True:
        entries = helpers.ocr_entries(helpers.screenshot(device, work, "group-title"))
        if len(group_title_matches(entries, group_name)) == 1:return True
        banner=any('刚刚' in e['text'] and '微信' in e['text'] for e in entries if e['y']<350)
        if not banner or time.monotonic()>=deadline:return False
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


def message_features(message: str) -> list[str]:
    lines = [normalize(line) for line in message.splitlines()]
    features = []
    for index, line in enumerate(lines):
        if index == 1:
            phone = re.sub(r"\D", "", line)
            features.append(phone if len(phone) >= 7 else line)
        elif len(line) > 12:
            features.append(line[-10:])
        else:
            features.append(line)
    return features


def verify_message_ocr(entries: list[dict], message: str, *, y_min: int, y_max: int,
                       required_count: int, require_name: bool = True) -> dict:
    haystack = compact_ocr(entries, y_min=y_min, y_max=y_max)
    features = message_features(message)
    matched = [feature for feature in features if feature and feature in haystack]
    name_ok = len(features) >= 3 and features[2] in haystack
    return {"ok": len(matched) >= required_count and (name_ok or not require_name),
            "matched": matched, "nameOk": name_ok, "features": features}


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


def run(args) -> dict:
    started = time.monotonic()
    result = {"ok": False, "executor": "wechat-sender", "groupName": args.group, "sent": 0, "stage": "contract"}
    work = Path(tempfile.mkdtemp(prefix="zhensi-merchant-wechat-"))
    device = None
    serial = None
    original_ime = None
    helpers = None
    lock=None
    try:
        if args.execute:
            lock=open(STATE_DIR/'sender.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        collection = load_collection(Path(args.collection_receipt), args.group)
        messages = collection["messages"]
        if args.execute and not args.probe_locate_group:
            audit_collection(collection)
            history=[]
            if HISTORY_FILE.exists():history=[json.loads(line) for line in HISTORY_FILE.read_text().splitlines()]
            sent_keys={send_identity(args.group,h) for h in history if h.get('groupName')==args.group and h.get('verified') is True}
            messages=[m for m in messages if send_identity(args.group,m) not in sent_keys]
            result['historySkipped']=len(collection['messages'])-len(messages)
        if args.execute and args.group == TEST_GROUP and args.standing_authorization != TEST_AUTHORIZATION:
            raise StopRun("test-standing-authorization-missing")
        if args.execute and args.group == PRODUCTION_GROUP:
            raise StopRun("production-send-not-authorized-by-this-run")
        result.update({"businessDate": collection["businessDate"], "messageCount": len(messages)})
        if not args.execute:
            result.update({"ok": True, "mode": "dry-run", "elapsedMs": round((time.monotonic() - started) * 1000)})
            return result
        if not messages and not args.probe_locate_group:
            result.update({"ok": True, "mode": "execute-noop", "elapsedMs": round((time.monotonic() - started) * 1000)})
            return result
        helpers = load_phone_helpers()
        devices = helpers.physical_devices()
        if args.serial:
            devices = [item for item in devices if item["serial"] == args.serial]
        if len(devices) != 1 or "HLK" not in devices[0]["model"].upper():
            raise StopRun(f"physical-device-contract:{devices}")
        serial = devices[0]["serial"]
        device = u2.connect(serial)
        install_capture(helpers,serial)
        original_ime = device.current_ime()
        if tuple(device.window_size()) != (1080, 2340):
            raise StopRun(f"unverified-display-geometry:{device.window_size()}")
        result["stage"] = "locate_group"
        stage_start=time.monotonic()
        open_main_wechat_group(device, serial, helpers, work, args.group)
        result.setdefault('stageMs',{})['locate_group']=round((time.monotonic()-stage_start)*1000)
        result["groupTitleVerified"] = True
        if args.probe_locate_group:
            result.update({"ok": True, "mode": "probe-locate-group", "stage": "complete",
                           "elapsedMs": round((time.monotonic() - started) * 1000)})
            return result
        result["stage"] = "send"
        for item in messages:
            if collection['businessDate']!=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d'):raise StopRun('business-date-changed')
            item_work=work/item['merchantId'];item_work.mkdir(mode=0o700)
            item_start=time.monotonic()
            def timeout_handler(signum, frame):raise StopRun('message-60s-budget-exceeded')
            prior_handler=signal.signal(signal.SIGALRM,timeout_handler);signal.alarm(60)
            try:verification = send_and_verify(device, serial, helpers, item_work, args.group, item["text"],item)
            finally:signal.alarm(0);signal.signal(signal.SIGALRM,prior_handler)
            commit_start=time.monotonic()
            append_history_then_cursor(args.group, collection["businessDate"], item)
            atomic_write_json(Path(verification['attemptMarker']),{'state':'verified','groupName':args.group,'merchantId':item['merchantId'],'sha256':item['sha256']})
            verification['stageMs']['history_cursor_commit']=round((time.monotonic()-commit_start)*1000)
            verification['elapsedMs']=round((time.monotonic()-item_start)*1000)
            result["sent"] += 1
            result["lastMerchantId"] = item["merchantId"]
            result.setdefault("verifications", []).append({"merchantId": item["merchantId"], **verification})
        result.update({"ok": True, "verified": True, "stage": "complete",
                       "elapsedMs": round((time.monotonic() - started) * 1000)})
        return result
    except Exception as error:
        result.update({"reason": str(error), "elapsedMs": round((time.monotonic() - started) * 1000)})
        if helpers is not None:result['failedMessageStageMs']=getattr(helpers,'current_message_timings',{})
        return result
    finally:
        if device is not None and serial and original_ime and helpers is not None:
            try:
                helpers.adb(serial, "shell", "ime", "set", original_ime)
            except Exception:
                pass
        result['evidenceDir']=str(work)
        if lock is not None:lock.close()


def self_test() -> dict:
    sample = {
        "ok": True,
        "executor": "merchant-collector",
        "groupName": TEST_GROUP,
        "businessDate": "2026-09-02",
        "messages": [{
            "merchantId": "1332573048",
            "merchantName": "御京荷北京烤鸭",
            "recommendTime": "2026-09-02 19:16:10",
            "tableOrder": 1,
            "text": "聊城市\n韩，15811127835\n御京荷北京烤鸭\n测试地址",
            "sha256": "",
        }],
    }
    sample["messages"][0]["sha256"] = text_hash(sample["messages"][0]["text"])
    with tempfile.TemporaryDirectory() as directory:
        receipt = Path(directory) / "receipt.json"
        receipt.write_text(json.dumps(sample, ensure_ascii=False), encoding="utf-8")
        loaded = load_collection(receipt, TEST_GROUP)
        if loaded["messages"][0]["merchantId"] != "1332573048":
            raise AssertionError("receipt-load-test")
    if cursor_file(TEST_GROUP).name != "cursor.test.json" or cursor_file(PRODUCTION_GROUP).name != "cursor.json":
        raise AssertionError("cursor-isolation-test")
    if normalize("韩， 158") != normalize("韩,158"):
        raise AssertionError("message-normalization-test")
    features = message_features(sample["messages"][0]["text"])
    if features[1] != "15811127835" or features[2] != "御京荷北京烤鸭":
        raise AssertionError("ocr-feature-test")
    fake_entries = [{"x": 1, "y": 500, "text": text, "w": 1, "h": 1, "confidence": 1.0}
                    for text in ("聊城市", "韩，15811127835", "御京荷北京烤鸭", "测试地址")]
    if not verify_message_ocr(fake_entries, sample["messages"][0]["text"], y_min=0, y_max=1000,
                              required_count=3)["ok"]:
        raise AssertionError("ocr-verification-test")
    return {"ok": True, "tests": 5}


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--collection-receipt", default="/tmp/zhensi_agent_merchants/collection_receipt.json")
    parser.add_argument("--group", default=TEST_GROUP)
    parser.add_argument("--serial")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--probe-locate-group", action="store_true")
    parser.add_argument("--standing-authorization")
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    output = self_test() if args.self_test else run(args)
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    raise SystemExit(0 if output.get("ok") else 1)
