"""已登录 Chrome 共用动作：轻量置前、找标签、挪开淘宝闪购、系统文件框选 mp4。"""
from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

import Quartz
from AppKit import NSPasteboard, NSStringPboardType, NSWorkspace

from lib.platform_spec import TAOBAO_STOW_BOUNDS, PlatformSpec
from lib import chrome_ax

OCR_BIN = Path(
    '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/legacy-app-controler/wechat-desktop-control/scripts/ocr_vision_bin'
)
CG_CLICK = Path(
    '/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/legacy-app-controler/wechat-desktop-control/scripts/cgevent_click_bin'
)
SHOT = Path('/tmp/zhensi-chrome-bridge.png')
OPTS = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements


class ChromeCommonError(RuntimeError):
    pass


def run_osascript(script: str) -> str:
    return subprocess.check_output(['osascript', '-e', script], text=True).strip()


def seize_chrome_light() -> None:
    visible: list[tuple[float, object]] = []
    for candidate in NSWorkspace.sharedWorkspace().runningApplications():
        if candidate.localizedName() != 'Google Chrome':
            continue
        root = __import__('ApplicationServices').AXUIElementCreateApplication(
            int(candidate.processIdentifier())
        )
        for window in (chrome_ax._attr(root, 'AXWindows') or []):
            if chrome_ax._attr(window, 'AXRole') != 'AXWindow':
                continue
            try:
                _, _, width, height = chrome_ax._point(window)
            except chrome_ax.AxError:
                continue
            if width > 0 and height > 0 and str(chrome_ax._attr(window, 'AXTitle') or ''):
                visible.append((width * height, candidate))
                break
    if not visible:
        raise ChromeCommonError('visible-chrome-app-missing')
    app = max(visible, key=lambda item: item[0])[1]
    app.activateWithOptions_(1)
    time.sleep(0.35)


def _post_key(code: int, flags: int = 0) -> None:
    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    down = Quartz.CGEventCreateKeyboardEvent(source, code, True)
    up = Quartz.CGEventCreateKeyboardEvent(source, code, False)
    Quartz.CGEventSetFlags(down, flags)
    Quartz.CGEventSetFlags(up, flags)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.08)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def _paste_visible_chrome(text: str) -> None:
    board = NSPasteboard.generalPasteboard()
    previous = board.stringForType_(NSStringPboardType)
    board.clearContents()
    board.setString_forType_(text, NSStringPboardType)
    _post_key(9, Quartz.kCGEventFlagMaskCommand)
    time.sleep(0.18)
    board.clearContents()
    if previous is not None:
        board.setString_forType_(previous, NSStringPboardType)


def _active_web() -> object:
    # Chrome briefly detaches AXWebArea while a page transition is underway.
    # Stay on the same visible Chrome process and wait; never fall back to a
    # same-name headless process.
    deadline = time.time() + 10.0
    while time.time() < deadline:
        app = chrome_ax.chrome_app()
        windows = chrome_ax._attr(app, 'AXWindows') or []
        for window in windows:
            found = chrome_ax.walk(
                window,
                lambda element: chrome_ax.role_is(element, 'AXWebArea'),
            )
            if found:
                return found[0]
        time.sleep(0.25)
    raise ChromeCommonError('visible-chrome-webarea-missing')


def file_dialog_visible() -> bool:
    """是否已打开当前可见 Chrome 的原生选文件框。"""
    try:
        app = chrome_ax.chrome_app()
        roots = chrome_ax._attr(app, 'AXWindows') or []
        dialogs = chrome_ax.walk(
            app,
            lambda element: chrome_ax.role_is(element, 'AXSheet')
            or chrome_ax.role_is(element, 'AXDialog'),
        )
        # 某些 macOS 版本把文件框作为独立 AXWindow 暴露。
        dialogs.extend(
            window for window in roots
            if chrome_ax.role_is(window, 'AXSheet') or chrome_ax.role_is(window, 'AXDialog')
        )
        for dialog in dialogs:
            text = ' '.join(
                chrome_ax.text_of(element)
                for element in chrome_ax.walk(dialog, lambda element: True)
            )
            if any(token in text for token in ('打开', '取消', '最近使用', '个人收藏')):
                return True
    except Exception:
        return False
    return False


def wait_for_file_dialog(*, timeout_sec: float = 5.0) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        if file_dialog_visible():
            return True
        time.sleep(0.2)
    return False


def stow_taobao_flash_window() -> None:
    # Same-name headless Chrome processes cannot be safely addressed by
    # AppleScript. The visible publishing window is raised instead.
    seize_chrome_light()


def focus_tab(url_hint: str) -> str:
    """Attach the current visible ordinary Chrome tab; do not touch headless tabs."""
    seize_chrome_light()
    return active_tab_url()


def active_tab_url() -> str:
    return str(chrome_ax._attr(_active_web(), 'AXURL') or '')


def goto(url: str) -> None:
    seize_chrome_light()
    _post_key(37, Quartz.kCGEventFlagMaskCommand)
    time.sleep(0.12)
    _paste_visible_chrome(url)
    _post_key(36)
    time.sleep(2.4)


def paste_text(text: str) -> None:
    seize_chrome_light()
    _paste_visible_chrome(text)
    time.sleep(0.4)


def pick_file_in_dialog(path: Path, *, dialog_confirmed: bool = False) -> None:
    if not dialog_confirmed and not wait_for_file_dialog():
        raise ChromeCommonError('pre_upload_failed:file-dialog-missing')
    _post_key(5, Quartz.kCGEventFlagMaskCommand | Quartz.kCGEventFlagMaskShift)
    time.sleep(0.45)
    _paste_visible_chrome(str(path.resolve()))
    time.sleep(0.3)
    _post_key(36)
    time.sleep(0.3)
    _post_key(36)


def prepare_chrome(spec: PlatformSpec) -> str:
    stow_taobao_flash_window()
    return focus_tab(spec.url_hint)


def chrome_window(title_needles: tuple[str, ...] = ()) -> dict:
    seize_chrome_light()
    wins = [
        w
        for w in Quartz.CGWindowListCopyWindowInfo(OPTS, Quartz.kCGNullWindowID)
        if w.get('kCGWindowOwnerName') == 'Google Chrome' and w.get('kCGWindowLayer', 0) == 0
    ]
    preferred = [
        w for w in wins
        if any(k.lower() in (w.get('kCGWindowName') or '').lower() for k in title_needles)
    ] if title_needles else []
    pool = preferred or wins
    if not pool:
        raise ChromeCommonError('chrome-window-missing')
    target = max(
        pool,
        key=lambda w: (w.get('kCGWindowBounds') or {}).get('Width', 0)
        * (w.get('kCGWindowBounds') or {}).get('Height', 0),
    )
    return {
        'id': int(target['kCGWindowNumber']),
        'bounds': dict(target['kCGWindowBounds']),
        'name': target.get('kCGWindowName') or '',
    }


def capture(title_needles: tuple[str, ...] = ()) -> dict:
    window = chrome_window(title_needles)
    subprocess.check_call(['/usr/sbin/screencapture', '-x', '-l', str(window['id']), str(SHOT)])
    return window


def image_size() -> tuple[int, int]:
    meta = subprocess.check_output(
        ['/usr/bin/sips', '-g', 'pixelWidth', '-g', 'pixelHeight', str(SHOT)],
        text=True,
    )
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


def click_ocr(keywords: tuple[str, ...], title_needles: tuple[str, ...] = ()) -> bool:
    window = capture(title_needles)
    entries = ocr_entries()
    iw, ih = image_size()
    hits = [e for e in entries if any(k in e['text'] for k in keywords)]
    if not hits:
        return False
    sx, sy = to_screen(hits[0], window['bounds'], iw, ih)
    click_xy(sx, sy)
    time.sleep(0.6)
    return True
