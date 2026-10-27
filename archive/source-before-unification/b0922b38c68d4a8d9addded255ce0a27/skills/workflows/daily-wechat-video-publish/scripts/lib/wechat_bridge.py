"""封装 wechat-desktop-control：先抢微信焦点，再截图/点击/输入。"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

WECHAT_SKILL = Path('/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts')
if str(WECHAT_SKILL) not in sys.path:
    sys.path.insert(0, str(WECHAT_SKILL))

import wechat_desktop as wd  # noqa: E402

from lib.focus import FocusError, assert_wechat_screenshot, seize_wechat  # noqa: E402

VENV_PYTHON = '/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python'


@dataclass
class WindowBounds:
    x: float
    y: float
    w: float
    h: float


def _largest_wechat_window_id() -> int | None:
    script = """
import Quartz
OPTS = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
wins = [
    w for w in Quartz.CGWindowListCopyWindowInfo(OPTS, Quartz.kCGNullWindowID)
    if w.get('kCGWindowOwnerName') in ('WeChat', '微信') and w.get('kCGWindowLayer', 0) == 0
]
if not wins:
    print(0)
else:
    best = max(
        wins,
        key=lambda w: (w.get('kCGWindowBounds') or {}).get('Width', 0)
        * (w.get('kCGWindowBounds') or {}).get('Height', 0),
    )
    print(int(best['kCGWindowNumber']))
"""
    try:
        wid = int(subprocess.check_output([VENV_PYTHON, '-c', script], text=True).strip())
        return wid if wid > 0 else None
    except (subprocess.CalledProcessError, ValueError):
        return None


def window_bounds() -> WindowBounds:
    seize_wechat()
    script = """
tell application "System Events"
  tell process "WeChat"
    set w to front window
    set p to position of w
    set s to size of w
    return (item 1 of p as text) & "," & (item 2 of p as text) & "," & (item 1 of s as text) & "," & (item 2 of s as text)
  end tell
end tell
"""
    raw = wd.osascript(script)
    x, y, w, h = (float(v) for v in raw.split(','))
    return WindowBounds(x, y, w, h)


def click_window_local(cx: float, cy: float, *, activate: bool = True) -> None:
    """先抢微信焦点，再点击（OCR 像素坐标 → 屏幕逻辑点）。"""
    if activate:
        seize_wechat()
    else:
        seize_wechat()
    scale = wd.screen_scale()
    bounds = window_bounds()
    sx = bounds.x + cx / scale
    sy = bounds.y + cy / scale
    wd.click(sx, sy, activate=False, scale=1.0)
    time.sleep(0.15)


def right_click_window_local(cx: float, cy: float) -> None:
    seize_wechat()
    scale = wd.screen_scale()
    bounds = window_bounds()
    sx = bounds.x + cx / scale
    sy = bounds.y + cy / scale
    bin_path = WECHAT_SKILL / 'cgevent_right_click_bin'
    subprocess.run([str(bin_path), str(sx), str(sy)], check=True)
    time.sleep(0.35)


def screenshot_screen(path: Path) -> list:
    path.parent.mkdir(parents=True, exist_ok=True)
    seize_wechat()
    proc = subprocess.run(['screencapture', '-x', str(path)], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or 'screencapture failed')
    return wd.ocr(path)


def screenshot_window(path: Path) -> list[wd.OcrHit]:
    path.parent.mkdir(parents=True, exist_ok=True)
    seize_wechat()
    wd.ensure_window_size()
    time.sleep(0.25)
    wid = _largest_wechat_window_id() or wd.wechat_window_id()
    if not wid:
        raise FocusError('未找到微信窗口')
    proc = subprocess.run(['screencapture', '-x', '-l', str(wid), str(path)], capture_output=True, text=True)
    if proc.returncode:
        raise RuntimeError(proc.stderr.strip() or 'screencapture failed')
    hits = wd.ocr(path)
    assert_wechat_screenshot(hits)
    return hits


def _sidebar_group_row(hits, group: str):
    key = group[:6]
    rows = [
        h for h in hits
        if (key in h.text or '红太阳' in h.text or '鱼杂王' in h.text)
        and h.cx < 700 and 170 < h.cy < 380
    ]
    if not rows:
        return None
    return min(rows, key=lambda h: h.cy)


def _click_sidebar_group(group: str, artifacts: Path) -> bool:
    shot = artifacts / 'sidebar_click.png'
    hits = screenshot_window(shot)
    row = _sidebar_group_row(hits, group)
    if not row:
        return False
    click_window_local(row.cx, row.cy + 20)
    time.sleep(1.0)
    return True


def _group_header_visible(hits, group: str) -> bool:
    key = group[:6]
    # 聊天区顶栏标题（排除左侧会话列表里的群名 preview，cy 通常 < 150）
    return any(key in h.text and h.cy < 150 and h.cx > 500 for h in hits)


def _chat_visible(hits, *, sender: str | None = None, group: str | None = None) -> bool:
    if group and _group_header_visible(hits, group):
        return True
    if sender and any(h.text == sender and h.cx > 650 and h.cy > 280 for h in hits):
        return True
    return False


def _search_open_group(group: str, artifacts: Path) -> bool:
    shot = artifacts / 'search_before.png'
    hits = screenshot_window(shot)
    search = next(
        (h for h in hits if ('搜索' in h.text or h.text.strip() in ('Q', 'Q ')) and h.cx < 520 and h.cy < 280),
        None,
    )
    if search:
        click_window_local(search.cx, search.cy)
    else:
        click_window_local(375, 185)
    time.sleep(0.35)
    type_text(group)
    time.sleep(1.6)
    shot2 = artifacts / 'search_after.png'
    hits2 = screenshot_window(shot2)
    key = group[:8]
    rows = [h for h in hits2 if (key in h.text or '红太阳' in h.text or '鱼杂王' in h.text) and h.cx < 720]
    if not rows:
        return False
    row = max(rows, key=lambda h: h.cy)
    click_window_local(row.cx, row.cy)
    time.sleep(1.0)
    return True


def open_group(group: str, artifacts: Path, *, sender: str | None = None) -> wd.Receipt:
    artifacts.mkdir(parents=True, exist_ok=True)
    if not wd.wechat_running():
        return wd.Receipt(ok=False, action='open-group', group=group, note='WeChat 未运行')

    try:
        seize_wechat()
    except FocusError as exc:
        return wd.Receipt(ok=False, action='open-group', group=group, note=str(exc))

    wd.ensure_window_size()
    time.sleep(0.35)

    for attempt in range(4):
        shot = artifacts / f'preflight_{attempt:02d}.png'
        try:
            hits = screenshot_window(shot)
        except (RuntimeError, FocusError):
            time.sleep(0.6)
            continue
        if _group_header_visible(hits, group) and _chat_visible(hits, sender=sender, group=group):
            header = next(h.text for h in hits if group[:6] in h.text and h.cy < 320)
            return wd.Receipt(
                ok=True,
                action='open-group',
                group=group,
                header=header,
                artifacts=[str(shot)],
                note='already-open',
            )
        if _click_sidebar_group(group, artifacts):
            shot2 = artifacts / f'after_sidebar_{attempt:02d}.png'
            hits2 = screenshot_window(shot2)
            if _group_header_visible(hits2, group):
                header = next(
                    (h.text for h in hits2 if group[:6] in h.text and h.cy < 320),
                    group,
                )
                return wd.Receipt(
                    ok=True,
                    action='open-group',
                    group=group,
                    header=header,
                    artifacts=[str(shot), str(shot2)],
                    note='sidebar-open',
                )
        if _search_open_group(group, artifacts):
            shot2 = artifacts / f'after_search_{attempt:02d}.png'
            hits2 = screenshot_window(shot2)
            if _group_header_visible(hits2, group):
                header = next(
                    (h.text for h in hits2 if group[:6] in h.text and h.cy < 320),
                    group,
                )
                return wd.Receipt(
                    ok=True,
                    action='open-group',
                    group=group,
                    header=header,
                    artifacts=[str(shot), str(shot2)],
                    note='search-open',
                )
        seize_wechat()
        receipt = wd.open_group(group, artifacts)
        if receipt.ok:
            return receipt
        time.sleep(0.6)

    return wd.Receipt(
        ok=False,
        action='open-group',
        group=group,
        note='无法打开目标群：请确认微信主窗口可见且群名正确',
        artifacts=[str(p) for p in artifacts.glob('*.png')],
    )


def _chat_looks_latest(hits) -> bool:
    chat = [h for h in hits if h.cx > 720]
    blob = ''.join(h.text for h in chat)
    old_mark = any(
        any(k in h.text for k in ('昨天', '星期六', '星期日', '星期五', '周四', '周三'))
        for h in chat
    )
    today_mark = any(
        h.cx > 900 and bool(re.fullmatch(r'([1-9]|1\d|2[0-3]):[0-5]\d', h.text.strip()))
        for h in chat
    )
    if old_mark and not today_mark:
        return False
    if '动画表情' in blob:
        return True
    return today_mark


def jump_to_latest(artifacts: Path, group: str | None = None) -> bool:
    """先回到群最新：点会话、点跳转按钮、再向下滚，直到看见今天的尾巴。"""
    artifacts.mkdir(parents=True, exist_ok=True)
    if group:
        _click_sidebar_group(group, artifacts)
        time.sleep(0.7)
    hits = screenshot_window(artifacts / 'jump_latest.png')
    btn = next((h for h in hits if '跳转到最新' in h.text or '最新消息' in h.text), None)
    if btn:
        click_window_local(btn.cx, btn.cy)
        time.sleep(0.9)
        hits = screenshot_window(artifacts / 'jump_latest_after.png')
    if _chat_looks_latest(hits):
        return True
    for i in range(18):
        scroll_chat_down_small()
        hits = screenshot_window(artifacts / f'jump_down_{i:02d}.png')
        if _chat_looks_latest(hits):
            return True
    return _chat_looks_latest(hits)


def scroll_chat_up_small() -> None:
    """很小一步上翻，从最新往回看，避免一下翻到上周。"""
    scroll_chat_up(steps=1, wheel_per_step=2)


def scroll_chat_down_small() -> None:
    scroll_chat_up(steps=1, wheel_per_step=2, direction=-1)


def scroll_chat_up(steps: int = 1, *, wheel_per_step: int = 6, direction: int = 1) -> None:
    """在聊天区滚轮。direction>0 上翻看更早，<0 下翻回最新。"""
    seize_wechat()
    click_window_local(1400, 700, activate=False)
    time.sleep(0.12)
    bounds = window_bounds()
    scale = wd.screen_scale()
    sx = bounds.x + 1400 / scale
    sy = bounds.y + 700 / scale
    wheel_lines = max(1, abs(steps) * abs(wheel_per_step))
    delta = 4 if direction >= 0 else -4
    script = f"""
import Quartz, time
x, y = {sx}, {sy}
evt = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), Quartz.kCGMouseButtonLeft)
Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
time.sleep(0.05)
for _ in range({wheel_lines}):
    e = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, {delta})
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
    time.sleep(0.04)
"""
    subprocess.run([VENV_PYTHON, '-c', script], check=False)
    time.sleep(0.35)


def type_text(text: str) -> None:
    seize_wechat()
    escaped = text.replace('\\', '\\\\').replace('"', '\\"')
    subprocess.run(['osascript', '-e', f'set the clipboard to "{escaped}"'], check=True)
    seize_wechat()
    subprocess.run(
        ['osascript', '-e', 'tell application "System Events" to keystroke "v" using command down'],
        check=True,
    )
