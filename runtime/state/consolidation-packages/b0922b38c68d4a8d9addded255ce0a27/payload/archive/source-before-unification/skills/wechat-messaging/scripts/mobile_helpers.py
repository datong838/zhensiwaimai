"""Generic primitives extracted from validated mobile paths; no business execution."""
import hashlib,io,json,os,re,shutil,subprocess,time
from pathlib import Path
from PIL import Image,ImageOps,ImageStat
from contract import Rejected as StopRun
ADB=shutil.which('adb')
OCR_BIN=Path('/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/workflows/daily-top10-to-wechat-group/scripts/ocr_vision')
def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def run(command: list[str], *, timeout: float = 10, text: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(command, check=True, capture_output=True, text=text, timeout=timeout)

def adb(serial: str, *args: str, timeout: float = 10) -> str:
    return run([ADB, "-s", serial, *args], timeout=timeout).stdout.strip()

def ocr_entries(image: Path) -> list[dict]:
    output = run([str(OCR_BIN), str(image), "zh-Hans"], timeout=15).stdout
    entries = []
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            cx, cy, width, height = (int(value) for value in parts[0].split(","))
            confidence = float(parts[1])
        except ValueError:
            continue
        entries.append({"x": cx, "y": cy, "w": width, "h": height, "confidence": confidence, "text": parts[2].strip()})
    return entries

def find_exact(entries: list[dict], text: str) -> list[dict]:
    normalized = text.replace(" ", "")
    if normalized == '原图':
        return [entry for entry in entries if re.fullmatch(r'[•·○●✓✔√]*原图',entry['text'].replace(' ',''))]
    return [entry for entry in entries if entry["text"].replace(" ", "") == normalized]

def poll(fn, predicate, timeout: float, interval: float = 0.22):
    deadline = time.monotonic() + timeout
    latest = None
    while True:
        latest = fn()
        if predicate(latest):
            return latest
        if time.monotonic() >= deadline:
            return latest
        time.sleep(interval)

def is_main_wechat_foreground(current: dict, resumed: str) -> bool:
    """Require both the WeChat package and the main-space resumed task."""
    return current.get("package") == "com.tencent.mm" and bool(re.search(
        r"(?:mResumedActivity|topResumedActivity|ResumedActivity)[^\n]*\bu0\s+com\.tencent\.mm/",
        resumed,
    ))

def main_wechat_foreground_evidence(serial: str, device) -> dict:
    current = device.app_current()
    resumed = adb(serial, "shell", "dumpsys", "activity", "activities")
    return {"current": current, "resumed": resumed, "ok": is_main_wechat_foreground(current, resumed)}

def input_chinese(serial: str, device, text: str) -> str:
    if device.app_current().get("package") != "com.tencent.mm":
        raise StopRun("wechat-focus-lost-before-input")
    errors = []
    try:
        focused = device(focused=True)
        focused.set_text(text, timeout=1)
        return "focused-set-text"
    except Exception as error:
        errors.append(f"focused:{type(error).__name__}")
    try:
        device.set_clipboard(text, label="zhensi-group")
        if device.clipboard != text:
            raise RuntimeError("clipboard-roundtrip")
        device.jsonrpc.pasteClipboard()
        return "clipboard-paste"
    except Exception as error:
        errors.append(f"clipboard:{type(error).__name__}")
    raise StopRun(f"wechat-input-channels-failed:{','.join(errors)}")

def image_fingerprint(image: Image.Image) -> tuple[int, tuple[float, float, float]]:
    square = ImageOps.fit(image.convert("RGB"), (128, 128))
    gray = square.resize((9, 8)).convert("L")
    pixels = list(gray.getdata())
    bits = 0
    for row in range(8):
        for col in range(8):
            bits = (bits << 1) | int(pixels[row * 9 + col] > pixels[row * 9 + col + 1])
    mean = tuple(ImageStat.Stat(square).mean)
    return bits, mean

def fingerprint_distance(left, right) -> float:
    hamming = (left[0] ^ right[0]).bit_count()
    color = sum(abs(a - b) for a, b in zip(left[1], right[1])) / (3 * 255)
    return hamming + color * 18

def gallery_candidates(screen: Image.Image) -> list[tuple[tuple[int, int, int, int], tuple[int, int]]]:
    width, height = screen.size
    top = round(height * 0.075)
    columns = 4
    cell = width // columns
    candidates = []
    visible_rows = max(1, (height - 220 - top) // cell)
    for row in range(visible_rows):
        for col in range(columns):
            x0, y0 = col * cell, top + row * cell
            box = (x0 + 4, y0 + 4, min(width, x0 + cell - 4), min(height, y0 + cell - 4))
            candidates.append((box, (min(width - 20, x0 + cell - 28), y0 + 70)))
    return candidates

def select_target_thumbnail(screen_path: Path, target_path: Path, *, prefer_newest_first: bool = False, diagnostics=None) -> tuple[tuple[int, int], float, str]:
    # NOTE: no `dict | None` here. The production daemon runs the system
    # interpreter (/usr/bin/python3 = 3.9.6), where PEP 604 unions are a
    # runtime TypeError at def time; the annotation is intentionally omitted.
    with Image.open(target_path) as target, Image.open(screen_path) as screen:
        target_fp = image_fingerprint(target)
        scored = []
        candidates = gallery_candidates(screen)
        first_point = candidates[0][1]
        for box, check_point in candidates:
            scored.append((fingerprint_distance(target_fp, image_fingerprint(screen.crop(box))), check_point))
    scored.sort(key=lambda item: item[0])
    if diagnostics is not None:
        diagnostics.update(bestDistance=round(scored[0][0],3) if scored else None,
                           secondDistance=round(scored[1][0],3) if len(scored)>1 else None,
                           bestPoint=list(scored[0][1]) if scored else None,
                           screenshotSha256=sha256_file(screen_path))
    if not scored or scored[0][0] > 20:
        raise StopRun("target-thumbnail-not-confident")
    if len(scored) > 1 and scored[1][0] - scored[0][0] < 1.5:
        first = next(item for item in scored if item[1] == first_point)
        if prefer_newest_first and first[0] <= scored[0][0] + 1.5 and first[0] <= 20:
            return first[1], round(first[0], 3), "media-newest-top-left-equivalent"
        raise StopRun("target-thumbnail-ambiguous")
    return scored[0][1], round(scored[0][0], 3), "visual-unique"

def stable_target_thumbnail(device, work: Path, image: Path, receipt: dict):
    end=time.monotonic()+6
    previous=None
    receipt['thumbnailObservations']=[]
    while True:
        screen=screenshot(device,work,'gallery-candidate')
        observation={}
        try:
            selected=select_target_thumbnail(screen,image,prefer_newest_first=True,diagnostics=observation)
            observation['accepted']=True
        except StopRun as error:
            selected=None
            observation.update(accepted=False,reason=str(error))
        receipt['thumbnailObservations'].append(observation)
        if selected is not None and previous is not None and selected[0]==previous[0] and abs(selected[1]-previous[1])<=1.5:
            return selected
        previous=selected
        if time.monotonic()>=end:raise StopRun('target-thumbnail-not-stable-or-confident')
        time.sleep(.22)

def verify_media_newest(serial: str, remote_name: str) -> bool:
    output = adb(serial, "shell", "content", "query", "--uri", "content://media/external/images/media", timeout=15)
    lines = [line for line in output.splitlines() if "date_added=" in line]
    target = next((line for line in lines if f"_display_name={remote_name}," in line), None)
    if target is None:
        return False
    target_date = int(re.search(r"\bdate_added=(\d+)", target).group(1))
    newest = max(int(match.group(1)) for line in lines if (match := re.search(r"\bdate_added=(\d+)", line)))
    return target_date == newest

def locate_chat_target(screen_path: Path, target_path: Path) -> tuple[tuple[int, int], float]:
    with Image.open(target_path) as target, Image.open(screen_path) as screen:
        target_fp = image_fingerprint(target)
        target_ratio = target.height / target.width
        width, height = screen.size
        x1 = round(width * 0.852)
        scored = []
        for box_width in (round(width * ratio) for ratio in (0.43, 0.46, 0.50, 0.54)):
            box_height = round(box_width * target_ratio)
            x0 = x1 - box_width
            for y0 in range(round(height * 0.14), max(round(height * 0.90) - box_height, round(height * 0.14) + 1), max(24, round(height * 0.017))):
                box = (x0, y0, x1, y0 + box_height)
                scored.append((fingerprint_distance(target_fp, image_fingerprint(screen.crop(box))), box))
    scored.sort(key=lambda item: item[0])
    if not scored or scored[0][0] > 12:
        raise StopRun("sent-image-bubble-not-confident")
    score, box = scored[0]
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2), round(score, 3)

def verify_large_image(screen_path: Path, target_path: Path) -> dict:
    """Verify the opened viewer image against the exact desktop artifact plus OCR structure."""
    with Image.open(target_path) as target, Image.open(screen_path) as screen:
        target_fp = image_fingerprint(target)
        display_height = round(screen.width * target.height / target.width)
        center_y = (screen.height - display_height) // 2
        scored = []
        for y0 in range(max(0, center_y - 100), min(screen.height - display_height, center_y + 100) + 1, 10):
            crop = screen.crop((0, y0, screen.width, y0 + display_height))
            scored.append((fingerprint_distance(target_fp, image_fingerprint(crop)), y0))
    distance, y0 = min(scored, default=(float("inf"), -1))
    entries = ocr_entries(screen_path)
    matched = []
    return {
        "ok": distance <= 6,
        "distance": round(distance, 3),
        "matched": matched,
        "cropY": y0,
    }

def open_and_verify_sent_image(device, work: Path, image: Path, group: str, receipt: dict) -> dict:
    """Retry opening only on a freshly verified target chat; never retry sending."""
    deadline = time.monotonic() + 12
    attempts = 0
    previous_point = None
    settle_until = 0
    last = {'ok': False, 'page': 'unknown', 'distance': None, 'matched': []}
    events = receipt.setdefault('readbackEvents', [])
    while time.monotonic() < deadline:
        if device.app_current().get('package') != 'com.tencent.mm':
            raise StopRun('readback-wechat-not-foreground')
        screen = screenshot(device, work, 'sent-large-image')
        entries = ocr_entries(screen)
        in_chat = bool(group_title_matches(entries, group))
        page = 'target-chat' if in_chat else 'non-chat-unconfirmed'
        if last['page'] != page:
            events.append({'event': 'page', 'page': page})
        if not in_chat:
            previous_point = None
            last = verify_large_image(screen, image) | {'page': page}
            if last['ok']:
                receipt['viewerOpenAttempts'] = attempts
                return last
        else:
            last = {'ok': False, 'page': page, 'distance': None, 'matched': []}
            if attempts < 2 and time.monotonic() >= settle_until:
                try:
                    point, distance = locate_chat_target(screen, image)
                except StopRun:
                    previous_point = None
                else:
                    if point == previous_point and time.monotonic() < deadline:
                        # Coordinates belong to this screenshot, not the previous attempt.
                        if device.app_current().get('package') != 'com.tencent.mm':
                            raise StopRun('readback-wechat-not-foreground')
                        attempts += 1
                        receipt['viewerOpenAttempts'] = attempts
                        receipt['sentBubbleDistance'] = distance
                        events.append({'event': 'open', 'attempt': attempts, 'point': list(point),
                                       'distance': distance, 'screenshotSha256': sha256_file(screen)})
                        device.click(*point)
                        settle_until = time.monotonic() + 2
                        previous_point = None
                    else:
                        previous_point = point
        time.sleep(.22)
    receipt['viewerOpenAttempts'] = attempts
    receipt['readbackLastPage'] = last['page']
    receipt['largeImageDistance'] = last['distance']
    receipt['largeImageOcrFields'] = last['matched']
    if last['page'] == 'target-chat':
        raise StopRun('image-viewer-not-opened' if attempts else 'sent-image-bubble-not-stable')
    raise StopRun('viewer-page-or-content-not-verified')

def topbar_action_centers(image: Image.Image) -> list[tuple[int, int]]:
    rgb = image.convert("RGB")
    width, height = rgb.size
    x0, x1 = round(width * 0.72), width - 18
    y0, y1 = round(height * 0.034), round(height * 0.095)
    points = set()
    for y in range(y0, y1):
        for x in range(x0, x1):
            red, green, blue = rgb.getpixel((x, y))
            if max(red, green, blue) < 115:
                points.add((x, y))
    components = []
    while points:
        seed = points.pop()
        stack, xs, ys = [seed], [], []
        while stack:
            x, y = stack.pop()
            xs.append(x)
            ys.append(y)
            for nx in (x - 1, x, x + 1):
                for ny in (y - 1, y, y + 1):
                    if (nx, ny) in points:
                        points.remove((nx, ny))
                        stack.append((nx, ny))
        box = (min(xs), min(ys), max(xs), max(ys))
        box_width, box_height = box[2] - box[0] + 1, box[3] - box[1] + 1
        if len(xs) >= 120 and 20 <= box_width <= 75 and 20 <= box_height <= 75:
            components.append(((box[0] + box[2]) // 2, (box[1] + box[3]) // 2))
    groups = []
    for center in sorted(components):
        if groups and abs(center[0] - groups[-1][-1][0]) < 38:
            groups[-1].append(center)
        else:
            groups.append([center])
    centers = [(round(sum(x for x, _ in group) / len(group)), round(sum(y for _, y in group) / len(group))) for group in groups]
    centers = [center for center in centers if center[0] > width * 0.78]
    if len(centers) < 2:
        raise StopRun(f"wechat-topbar-icon-count:{len(centers)}")
    search, plus = centers[-2], centers[-1]
    if not 60 <= plus[0] - search[0] <= 150:
        raise StopRun("wechat-topbar-icon-spacing-invalid")
    return [search, plus]

def green_mark_near(image_path: Path, entry: dict) -> bool:
    with Image.open(image_path) as image:
        x0 = max(0, entry["x"] - entry["w"] // 2 - 70)
        x1 = min(image.width, entry["x"] + entry["w"] // 2 + 20)
        y0 = max(0, entry["y"] - entry["h"])
        y1 = min(image.height, entry["y"] + entry["h"])
        pixels = image.convert("RGB").crop((x0, y0, x1, y1)).getdata()
        return sum(1 for red, green, blue in pixels if green > red + 22 and green > blue + 10 and green > 95) >= 12

def gallery_ready(entries):
    return bool(find_exact(entries,'原图')) and any('预览' in e['text'] for e in entries) and any('发送' in e['text'] for e in entries) and not any(e['text'] in ('发红包','塞钱进红包') for e in entries)

def click_text(device,work,name,text,timeout=5):
    end=time.monotonic()+timeout;previous=None
    while time.monotonic()<end:
        entries=ocr_entries(screenshot(device,work,name))
        matches=find_exact(entries,text)
        if text=='相册' and not all(find_exact(entries,label) for label in ('相册','拍摄','位置')):matches=[]
        if len(matches)==1:
            e=matches[0];point=(e['x'],e['y'])
            if previous and all(abs(a-b)<=5 for a,b in zip(point,previous)):
                device.click(e['x'],e['y']-100 if text=='相册' else e['y'])
                return entries
            previous=point
        else:previous=None
        time.sleep(.3)
    raise StopRun('stable-label-not-found:'+text)


def open_search_page(device, work: Path) -> None:
    entries = ocr_entries(screenshot(device, work, "wechat-home-actions"))
    if find_exact(entries, "发起群聊") or find_exact(entries, "添加朋友"):
        device.press("back")
        entries = poll(lambda: ocr_entries(screenshot(device, work, "wechat-home-actions")),
                       lambda values: not find_exact(values, "发起群聊"), 3)
    def scan_topbar():
        topbar = screenshot(device, work, "wechat-home-topbar")
        try:
            with Image.open(topbar) as image:
                return topbar_action_centers(image)
        except StopRun:
            return []
    centers = poll(scan_topbar, lambda values: len(values) == 2, 3)
    if len(centers) != 2:
        raise StopRun(f"wechat-topbar-icon-count:{len(centers)}")
    search, _ = centers
    device.click(*search)
    search_entries = poll(lambda: ocr_entries(screenshot(device, work, "wechat-search-page")),
                          lambda values: any("搜索" in entry["text"] for entry in values)
                          and not find_exact(values, "发起群聊"), 4)
    if not any("搜索" in entry["text"] for entry in search_entries) or find_exact(search_entries, "发起群聊"):
        raise StopRun("wechat-search-page-not-verified")

def ensure_wechat_home(device, work: Path) -> list[dict]:
    def is_home(entries):
        return all(find_exact(entries, label) for label in ("微信", "通讯录", "发现", "我"))
    entries = ocr_entries(screenshot(device, work, "wechat-home"))
    for attempt in range(6):
        if is_home(entries):
            return entries
        if attempt == 5:
            break
        device.press("back")
        entries = poll(lambda: ocr_entries(screenshot(device, work, "wechat-home")), is_home, 2)
    raise StopRun("wechat-home-not-recognized")

def exact_group_title(value,group):
    return bool(re.fullmatch(re.escape(group)+r'(?:[（(]\d+[）)]\s*(?:[C〇Q]>?)?)?',value.strip()))
def group_title_matches(entries,group):
    if any('搜索网络结果' in e['text'] for e in entries):return []
    return [e for e in entries if e['y']<280 and exact_group_title(e['text'],group)]
def _raw_screenshot(device,directory,name):
    directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    path=directory/(name+'.png')
    p=subprocess.run([ADB,'-s',device.serial,'exec-out','screencap','-p'],capture_output=True,timeout=8,check=True)
    im=Image.open(io.BytesIO(p.stdout));im.load()
    if im.size!=(1080,2340):raise StopRun('unverified-phone-geometry')
    im.save(path);path.chmod(0o600);return path

def notification_visible(entries):
    top=[e['text'] for e in entries if 80<e['y']<380]
    return any('刚刚' in value for value in top) and any('微信' in value for value in top)

def screenshot(device,directory,name):
    end=time.monotonic()+10
    while True:
        path=_raw_screenshot(device,directory,name)
        if not notification_visible(ocr_entries(path)):return path
        if time.monotonic()>=end:raise StopRun('phone-notification-obscures-page')
        time.sleep(.4)
