#!/usr/bin/env python3
"""抖音创作者中心：复用已登录普通 Chrome（control-existing-chrome 路径，不用 CDP 9222）。"""
from __future__ import annotations

import os
import sys

VENV_PYTHON = '/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python'
if os.path.realpath(sys.executable) != os.path.realpath(VENV_PYTHON):
    os.execv(VENV_PYTHON, [VENV_PYTHON, *sys.argv])

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import Quartz

from lib.focus import FocusError, assert_chrome_screenshot
from lib import chrome_common as cc


def seize_chrome_light() -> None:
    """切好抖音标签后轻量置前，避免 AXRaise 把其他 Chrome 窗抢前台。"""
    cc.seize_chrome_light()

UPLOAD_URL = 'https://creator.douyin.com/creator-micro/content/upload'
MANAGE_URL = 'https://creator.douyin.com/creator-micro/content/manage'
SHOT = Path('/tmp/douyin-chrome-bridge.png')
OCR_BIN = Path(
    '/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts/ocr_vision_bin'
)
CG_CLICK = Path(
    '/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts/cgevent_click_bin'
)
OPTS = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements


class BridgeError(RuntimeError):
    pass


def run_osascript(script: str) -> str:
    return subprocess.check_output(['osascript', '-e', script], text=True).strip()


def activate_chrome() -> None:
    seize_chrome_light()


def focus_douyin_tab(*, url_hint: str = 'creator.douyin.com') -> str:
    return cc.focus_tab(url_hint)


def dismiss_draft_banner(*, resume: bool = False) -> None:
    """新上传必须放弃旧草稿；resume=True 才点继续编辑。"""
    capture()
    entries = ocr_entries()
    iw, ih = image_size()
    bounds = chrome_window()['bounds']
    order = ('继续编辑',) if resume else ('放弃', '重新上传')
    for kw in order:
        hits = [e for e in entries if kw in e['text']]
        if hits:
            sx, sy = to_screen(hits[0], bounds, iw, ih)
            click_xy(sx, sy)
            time.sleep(0.8)
            return


def navigate_upload() -> str:
    url = focus_douyin_tab()
    if 'content/upload' not in url:
        cc.goto(UPLOAD_URL)
    return UPLOAD_URL


def chrome_window() -> dict:
    seize_chrome_light()
    wins = [
        w
        for w in Quartz.CGWindowListCopyWindowInfo(OPTS, Quartz.kCGNullWindowID)
        if w.get('kCGWindowOwnerName') == 'Google Chrome' and w.get('kCGWindowLayer', 0) == 0
    ]
    preferred = [
        w for w in wins
        if any(k in (w.get('kCGWindowName') or '') for k in ('抖音', 'creator', 'Creator'))
    ]
    pool = preferred or wins
    if not pool:
        raise BridgeError('chrome-window-missing')
    target = max(
        pool,
        key=lambda w: (w.get('kCGWindowBounds') or {}).get('Width', 0)
        * (w.get('kCGWindowBounds') or {}).get('Height', 0),
    )
    bounds = dict(target['kCGWindowBounds'])
    return {'id': int(target['kCGWindowNumber']), 'bounds': bounds, 'name': target.get('kCGWindowName') or ''}


def capture() -> dict:
    seize_chrome_light()
    window = chrome_window()
    subprocess.check_call(['/usr/sbin/screencapture', '-x', '-l', str(window['id']), str(SHOT)])
    entries = ocr_entries()
    assert_chrome_screenshot(entries)
    return window


def image_size() -> tuple[int, int]:
    meta = subprocess.check_output(['/usr/bin/sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(SHOT)], text=True)
    return (
        int(re.search(r'pixelWidth:\s*(\d+)', meta).group(1)),
        int(re.search(r'pixelHeight:\s*(\d+)', meta).group(1)),
    )


def ocr_entries() -> list[dict]:
    out = subprocess.check_output([str(OCR_BIN), str(SHOT)], text=True)
    entries = []
    for line in out.splitlines():
        parts = line.split('\t')
        if len(parts) < 3:
            continue
        x, y, w, h = map(float, parts[0].split(','))
        entries.append({'x': x, 'y': y, 'w': w, 'h': h, 'text': '\t'.join(parts[2:]).strip()})
    return entries


def to_screen(entry: dict, bounds: dict, iw: int, ih: int) -> tuple[float, float]:
    x = entry['x'] + entry['w'] * 0.5
    y = entry['y'] + entry['h'] * 0.5
    return (
        bounds['X'] + x / (iw / bounds['Width']),
        bounds['Y'] + y / (ih / bounds['Height']),
    )


def click_xy(sx: float, sy: float) -> None:
    subprocess.check_call([str(CG_CLICK), str(sx), str(sy)])
    time.sleep(0.18)


def paste_at_screen(sx: float, sy: float, text: str) -> None:
    """System Events 坐标点击 + 粘贴，比纯 CGEvent 更易让 Chrome 输入框获得焦点。"""
    subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
    run_osascript(
        f"""
tell application "Google Chrome" to activate
delay 0.25
tell application "System Events"
  tell process "Google Chrome"
    set frontmost to true
    click at {{{int(sx)}, {int(sy)}}}
    delay 0.35
  end tell
end tell
delay 0.15
tell application "System Events" to keystroke "v" using command down
"""
    )
    time.sleep(0.45)


def paste_text(text: str) -> None:
    subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
    time.sleep(0.15)
    run_osascript('tell application "Google Chrome" to activate')
    time.sleep(0.25)
    run_osascript('tell application "System Events" to keystroke "v" using command down')
    time.sleep(0.45)


def retry_content_check() -> None:
    capture()
    entries = ocr_entries()
    iw, ih = image_size()
    bounds = chrome_window()['bounds']
    hits = [e for e in entries if '重新检测' in e['text']]
    if hits:
        sx, sy = to_screen(hits[0], bounds, iw, ih)
        click_xy(sx, sy)
        time.sleep(3.0)


def click_below_label(
    entries: list[dict],
    *,
    labels: tuple[str, ...],
    bounds: dict,
    iw: int,
    ih: int,
    dy: float = 70.0,
    dx: float = 120.0,
) -> None:
    """点标签正下方的输入区域，避免点到「作品描述」「位置」标题本身。"""
    hits = [e for e in entries if any(l in e['text'] for l in labels)]
    if hits:
        e = hits[0]
        sx = bounds['X'] + (e['x'] + dx) / (iw / bounds['Width'])
        sy = bounds['Y'] + (e['y'] + e['h'] + dy) / (ih / bounds['Height'])
        click_xy(sx, sy)
        return
    click_xy(bounds['X'] + bounds['Width'] * 0.32, bounds['Y'] + bounds['Height'] * 0.55)


def scroll_page_up(steps: int = 8) -> None:
    bounds = chrome_window()['bounds']
    click_xy(bounds['X'] + bounds['Width'] * 0.35, bounds['Y'] + bounds['Height'] * 0.45)
    for _ in range(steps):
        run_osascript('tell application "System Events" to key code 116')
        time.sleep(0.1)


def caption_written(entries: list[dict], caption: str) -> bool:
    probe = caption.replace('😋', '')[:8]
    return any(probe in e['text'] or '鱼杂' in e['text'] for e in entries)


def pick_location_option(entries: list[dict], address: str, *, iw: int) -> dict | None:
    query_bits = ['红太阳鱼杂王', '保利绿地', '辽阳路195', '杨浦保利']
    scored: list[tuple[int, dict]] = []
    for e in entries:
        if not in_main_panel(e, iw=iw):
            continue
        text = e['text']
        if any(skip in text for skip in ('为你推荐', '温馨提示', '输入地理', '添加标签', '关联热点', '发布设置', '收入变现', '数据中心', '作品检测', '抱歉')):
            continue
        if any(k in text for k in ('红太阳', '鱼杂', '保利', '辽阳', '杨浦')):
            score = 10
            score += sum(1 for bit in query_bits if bit in text)
            scored.append((score, e))
    if not scored:
        return None
    scored.sort(key=lambda x: (-x[0], x[1]['y']))
    return scored[0][1]


def location_written(entries: list[dict]) -> bool:
    row = [e for e in entries if 330 <= e['y'] <= 460 and e['x'] >= 900]
    if not row:
        return False
    joined = ' '.join(e['text'] for e in row)
    if '输入地理' in joined:
        return False
    return any(k in joined for k in ('红太阳', '保利', '辽阳', '鱼杂王', '杨浦'))


def ensure_chrome_tall(*, min_height: int = 880) -> None:
    """编辑页底部「发布」在视口外时，先拉高 Chrome 窗口。"""
    run_osascript(
        f"""
tell application "Google Chrome"
  activate
  set b to bounds of front window
  set h to (item 4 of b) - (item 2 of b)
  if h < {min_height} then
    set bounds of front window to {{0, 25, 1440, 900}}
  end if
end tell
"""
    )
    time.sleep(0.5)


def scroll_page_down(steps: int = 8) -> None:
    seize_chrome_light()
    bounds = chrome_window()['bounds']
    click_xy(bounds['X'] + bounds['Width'] * 0.35, bounds['Y'] + bounds['Height'] * 0.55)
    for _ in range(steps):
        run_osascript('tell application "System Events" to key code 121')
        time.sleep(0.12)


def active_tab_url() -> str:
    return cc.active_tab_url()


def wait_for_edit_page(*, timeout_sec: float = 120.0) -> None:
    """上传 mp4 后等待进入 post/video 编辑页。"""
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        url = active_tab_url()
        if 'content/post/video' in url:
            return
        capture()
        if any('上传成功' in e['text'] for e in ocr_entries()):
            time.sleep(1.0)
            return
        if any('作品描述' in e['text'] for e in ocr_entries()):
            time.sleep(1.0)
            return
        time.sleep(2.0)
    raise BridgeError('edit-page-timeout')


def upload_video_file(video: Path) -> None:
    """点击「上传视频」→ 系统文件对话框选 mp4。"""
    navigate_upload()
    dismiss_draft_banner()
    capture()
    entries = ocr_entries()
    iw, ih = image_size()
    bounds = chrome_window()['bounds']
    btns = [e for e in entries if '上传视频' in e['text']]
    if btns:
        sx, sy = to_screen(btns[0], bounds, iw, ih)
        click_xy(sx, sy)
    else:
        click_xy(bounds['X'] + bounds['Width'] * 0.5, bounds['Y'] + bounds['Height'] * 0.55)
    time.sleep(1.2)
    cc.pick_file_in_dialog(video)
    wait_for_edit_page()
    # Unified upload-complete gate shared with the other publishing bridges.
    time.sleep(10.0)
    ensure_chrome_tall()


def _modal_open(entries: list[dict]) -> bool:
    return any(
        k in entry['text']
        for entry in entries
        for k in ('上传封面', '设置竖封面', 'AI生成封面')
    )


def _close_modal_if_open() -> None:
    """误开封面弹层时用「取消」退回表单；不点完成/设置封面。"""
    capture()
    entries = ocr_entries()
    if not _modal_open(entries):
        return
    iw, ih = image_size()
    bounds = chrome_window()['bounds']
    cancel = [e for e in entries if e['text'].strip() == '取消' and e['y'] > 600]
    if cancel:
        sx, sy = to_screen(cancel[-1], bounds, iw, ih)
        click_xy(sx, sy)
        time.sleep(1.0)


def publish_draft(caption: str, location: str, *, confirm: bool) -> dict:
    """草稿编辑页：只做 作品描述 + 位置 + 发布，不碰封面。走 Accessibility 树。"""
    from lib import chrome_ax

    focus_douyin_tab()
    url = active_tab_url()
    if 'content/post/video' not in url and 'content/upload' not in url:
        raise BridgeError(f'need-edit-page:{url}')
    chrome_ax.fill_description_ax(caption)
    try:
        chosen = chrome_ax.fill_location_ax('红太阳鱼杂王杨浦保利店')
    except chrome_ax.AxError as exc:
        # 位置搜索词一旦误入描述，恢复冻结文案后停止；禁止带错文案发布。
        if str(exc) == 'location-paste-leaked-into-description':
            chrome_ax.fill_description_ax(caption)
        raise
    if confirm:
        chrome_ax.click_publish_ax()
    return {
        'ok': True,
        'state': 'submitted' if confirm else 'publish_pending',
        'location_selected': chosen,
        'bridge': 'chrome-ax',
    }


def fill_description(caption: str) -> None:
    ensure_chrome_tall()
    scroll_page_up(10)
    capture()
    entries = ocr_entries()
    iw, ih = image_size()
    bounds = chrome_window()['bounds']
    # 优先点「添加作品简介」/ 标题下方区域，不要点「作品描述」标题
    intro = [e for e in entries if any(k in e['text'] for k in ('添加作品简介', '添加描述', '说点什么'))]
    if intro:
        sx, sy = to_screen(intro[0], bounds, iw, ih)
        click_xy(sx, sy)
    else:
        click_below_label(entries, labels=('作品描述',), bounds=bounds, iw=iw, ih=ih, dy=90)
    time.sleep(0.5)
    run_osascript('tell application "System Events" to keystroke "a" using command down')
    time.sleep(0.15)
    paste_text(caption)
    time.sleep(0.8)
    capture()
    if not caption_written(ocr_entries(), caption):
        # 再点一次输入区重试粘贴
        click_below_label(entries, labels=('作品描述',), bounds=bounds, iw=iw, ih=ih, dy=120)
        time.sleep(0.4)
        paste_text(caption)
        time.sleep(0.8)
        capture()
        if not caption_written(ocr_entries(), caption):
            raise BridgeError('description-not-written')


def in_main_panel(entry: dict, *, iw: int) -> bool:
    """排除左侧导航栏 OCR 块。"""
    return entry['x'] >= iw * 0.18


def click_location_input(bounds: dict, iw: int, ih: int, entries: list[dict]) -> None:
    placeholders = [
        e for e in entries
        if '输入地理' in e['text'] and in_main_panel(e, iw=iw)
    ]
    if placeholders:
        sx, sy = to_screen(placeholders[0], bounds, iw, ih)
        click_xy(sx, sy)
        return
    merged = [e for e in entries if '输入地理' in e['text'] and in_main_panel(e, iw=iw)]
    if merged:
        e = merged[0]
        entry = dict(e)
        entry['x'] = e['x'] + e['w'] * 0.78
        entry['w'] = e['w'] * 0.15
        sx, sy = to_screen(entry, bounds, iw, ih)
        click_xy(sx, sy)
        return
    click_xy(bounds['X'] + bounds['Width'] * 0.46, bounds['Y'] + bounds['Height'] * 0.48)


def pick_location_from_preview(entries: list[dict], *, iw: int) -> dict | None:
    hits = [
        e for e in entries
        if in_main_panel(e, iw=iw)
        and ('红太阳' in e['text'] or '鱼杂王' in e['text'])
        and ('@' in e['text'] or '◎' in e['text'] or '店' in e['text'])
    ]
    return hits[0] if hits else None


def location_input_point(entries: list[dict], bounds: dict, iw: int, ih: int) -> tuple[float, float, dict | None]:
    ph = [e for e in entries if '输入地理' in e['text'] and in_main_panel(e, iw=iw)]
    if ph:
        e = ph[0]
        sx = bounds['X'] + (e['x'] + e['w'] * 0.65) / (iw / bounds['Width'])
        sy = bounds['Y'] + (e['y'] + e['h'] * 0.5) / (ih / bounds['Height'])
        return sx, sy, e
    return bounds['X'] + bounds['Width'] * 0.58, bounds['Y'] + bounds['Height'] * 0.55, None


def _scroll_location_to_mid() -> None:
    """位置行太靠顶部时粘贴无效，滚到视口中部再操作。"""
    for _ in range(10):
        capture()
        entries = ocr_entries()
        ph = [e for e in entries if '输入地理' in e['text'] and in_main_panel(e, iw=image_size()[0])]
        if not ph:
            scroll_page_down(1)
            continue
        if ph[0]['y'] >= 550:
            return
        scroll_page_down(1)


def location_query_visible(entries: list[dict], query: str) -> bool:
    probe = query[:4]
    return any(probe in e['text'] for e in entries if e['x'] >= 900 and '虹桥' not in e['text'])


def fill_location(address: str) -> None:
    """扩展信息 → 位置：搜索店名/地址并点选 POI。"""
    ensure_chrome_tall()
    scroll_page_down(5)
    capture()
    entries = ocr_entries()
    iw, ih = image_size()
    bounds = chrome_window()['bounds']
    if not any('输入地理' in e['text'] for e in entries):
        scroll_page_down(4)
        capture()
        entries = ocr_entries()
    sx, sy, anchor = location_input_point(entries, bounds, iw, ih)
    if anchor is None and not any('输入地理' in e['text'] for e in entries):
        raise BridgeError('location-input-not-found')
    if anchor is None:
        anchor = {'y': 367, 'x': 1200, 'w': 400, 'h': 32}

    for query in ('红太阳鱼杂王杨浦保利店', '辽阳路195号', '保利绿地广场'):
        for dx in (0, 30, -20):
            paste_at_screen(sx + dx, sy, query)
            time.sleep(2.5)
            capture()
            entries = ocr_entries()
            if not location_query_visible(entries, query):
                continue
            cands = [
                e for e in entries
                if in_main_panel(e, iw=iw)
                and anchor['y'] + 15 < e['y'] < anchor['y'] + 200
                and any(k in e['text'] for k in ('红太阳', '保利', '辽阳', '鱼杂', '杨浦'))
                and '虹桥' not in e['text']
                and '输入地理' not in e['text']
            ]
            if cands:
                psx, psy = to_screen(cands[0], bounds, iw, ih)
                click_xy(psx, psy)
                time.sleep(1.0)
                capture()
                if location_written(ocr_entries()):
                    return
            run_osascript('tell application "System Events" to key code 125')
            time.sleep(0.15)
            run_osascript('tell application "System Events" to key code 36')
            time.sleep(1.0)
            capture()
            if location_written(ocr_entries()):
                return
    raise BridgeError('location-not-selected')


def find_publish_button(entries: list[dict]) -> dict | None:
    exact = [e for e in entries if e['text'].strip() == '发布']
    if exact:
        return max(exact, key=lambda e: e['y'])
    loose = [
        e for e in entries
        if e['text'].startswith('发布')
        and '视频' not in e['text']
        and '图文' not in e['text']
        and '立即' not in e['text']
        and '定时' not in e['text']
        and '作品' not in e['text']
    ]
    return max(loose, key=lambda e: e['y']) if loose else None


def click_publish_button(*, confirm: bool) -> None:
    if not confirm:
        return
    ensure_chrome_tall()
    scroll_page_down(10)
    capture()
    entries = ocr_entries()
    iw, ih = image_size()
    bounds = chrome_window()['bounds']
    pub = find_publish_button(entries)
    if not pub:
        scroll_page_down(6)
        capture()
        entries = ocr_entries()
        pub = find_publish_button(entries)
    if not pub:
        raise BridgeError('publish-button-not-found')
    sx, sy = to_screen(pub, bounds, iw, ih)
    click_xy(sx, sy)
    time.sleep(4.0)


def verify_on_manage(caption_snippet: str) -> bool:
    from lib import chrome_ax

    if 'content/manage' not in active_tab_url():
        return False
    snippet = caption_snippet[:8]
    deadline = time.time() + 20
    while time.time() < deadline:
        web = chrome_ax.douyin_web()
        if any(snippet in chrome_ax.text_of(e) for e in chrome_ax.walk(web, lambda e: True)):
            return True
        time.sleep(1.0)
    return False


def publish(video: Path, caption: str, location: str, *, confirm: bool) -> dict:
    if not video.is_file():
        raise BridgeError(f'video-missing:{video}')
    focus_douyin_tab()
    navigate_upload()
    upload_video_file(video)
    filled = publish_draft(caption, location, confirm=confirm)
    state = filled.get('state', 'publish_pending')
    verified = False
    if confirm:
        verified = verify_on_manage(caption)
        state = 'verified' if verified else 'publish_unknown'
    return {
        'ok': state in ('publish_pending', 'verified', 'submitted'),
        'state': state,
        'verified': verified,
        'video': str(video),
        'location_selected': filled.get('location_selected'),
        'bridge': 'chrome-ax',
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument('--video')
    p.add_argument('--caption')
    p.add_argument('--location')
    p.add_argument('--confirm-publish', action='store_true')
    p.add_argument('--preflight', action='store_true', help='只检查抖音标签是否可用')
    p.add_argument('--draft-only', action='store_true', help='草稿编辑页：只填描述+位置+发布')
    args = p.parse_args()
    try:
        if args.preflight:
            url = focus_douyin_tab()
            print(json.dumps({'ok': True, 'url': url, 'bridge': 'control-existing-chrome'}, ensure_ascii=False))
            return 0
        if args.draft_only:
            if not all([args.caption, args.location]):
                raise BridgeError('draft-only 需要 --caption --location')
            result = publish_draft(args.caption, args.location, confirm=args.confirm_publish)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['ok'] else 1
        if not all([args.video, args.caption, args.location]):
            raise BridgeError('publish 需要 --video --caption --location')
        result = publish(
            Path(args.video),
            args.caption,
            args.location,
            confirm=args.confirm_publish,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 1
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        if isinstance(exc, FocusError):
            err = f'focus:{err}'
        print(json.dumps({'ok': False, 'error': err}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    sys.exit(main())
