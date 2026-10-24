"""企业微信 macOS 客户端的可见、语义化读取。"""
from __future__ import annotations

import subprocess
import time
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import ApplicationServices as AX
import Quartz
from AppKit import NSWorkspace

from lib.cover_ocr import ocr_image
from lib.wecom_media import Attachment, parse_attachments


class DesktopError(RuntimeError):
    pass


@dataclass(frozen=True)
class NativeVideo:
    sender: str
    message_time: str
    duration_seconds: int
    row_sequence: int


def _attr(element: Any, name: str) -> Any:
    error, value = AX.AXUIElementCopyAttributeValue(element, name, None)
    return value if error == 0 else None


def _children(element: Any) -> list[Any]:
    return list(_attr(element, 'AXChildren') or [])


def text_of(element: Any) -> str:
    values = []
    for name in ('AXTitle', 'AXValue', 'AXDescription', 'AXHelp'):
        value = _attr(element, name)
        if isinstance(value, str) and value.strip():
            values.append(value.strip())
    return ' '.join(dict.fromkeys(values))


def walk(element: Any, *, depth: int = 0, output: list[Any] | None = None) -> list[Any]:
    output = output if output is not None else []
    if depth > 24:
        return output
    output.append(element)
    for child in _children(element):
        walk(child, depth=depth + 1, output=output)
    return output


def wecom_app() -> tuple[Any, int]:
    apps = [
        app for app in NSWorkspace.sharedWorkspace().runningApplications()
        if app.bundleIdentifier() == 'com.tencent.WeWorkMac' or app.localizedName() in ('企业微信', 'WeCom')
    ]
    if not apps:
        raise DesktopError('blocked_login: 企业微信未运行')
    app = apps[0]
    pid = int(app.processIdentifier())
    return AX.AXUIElementCreateApplication(pid), pid


def activate() -> None:
    subprocess.run(['osascript', '-e', 'tell application "企业微信" to activate'], capture_output=True, check=False)
    time.sleep(0.35)


def _main_window(app: Any) -> Any:
    windows = list(_attr(app, 'AXWindows') or [])
    if not windows:
        raise DesktopError('blocked_login: 企业微信没有可读窗口')
    return max(windows, key=lambda item: len(walk(item, output=[])))


def current_tree() -> tuple[Any, list[Any], int]:
    app, pid = wecom_app()
    window = _main_window(app)
    return window, walk(window, output=[]), pid


def _pressable(element: Any) -> Any | None:
    current = element
    for _ in range(7):
        if current is None:
            return None
        error, actions = AX.AXUIElementCopyActionNames(current, None)
        if error == 0 and 'AXPress' in list(actions or []):
            return current
        current = _attr(current, 'AXParent')
    return None


def _group_is_open(elements: list[Any], group: str) -> bool:
    for element in elements:
        role = _attr(element, 'AXRole') or ''
        if role in ('AXTextField', 'AXStaticText') and text_of(element).strip() == group:
            # 左侧搜索框约从 x=60 开始；聊天标题位于右侧聊天区。
            position = str(_attr(element, 'AXPosition') or '')
            match = re.search(r'x:([0-9.]+)', position)
            if match and float(match.group(1)) >= 300:
                return True
    return False


def open_group(group: str) -> list[Any]:
    activate()
    _, elements, _ = current_tree()
    if _group_is_open(elements, group):
        return elements
    candidates = [
        element for element in elements
        if (_attr(element, 'AXRole') or '') != 'AXTextField'
        and text_of(element).strip().split('\n', 1)[0] == group
    ]
    for candidate in candidates:
        target = _pressable(candidate)
        if target is not None:
            AX.AXUIElementPerformAction(target, 'AXPress')
            time.sleep(0.8)
            _, refreshed, _ = current_tree()
            if _group_is_open(refreshed, group):
                return refreshed
    search_fields = [
        element for element in elements
        if (_attr(element, 'AXRole') or '') == 'AXTextField'
        and (lambda m: bool(m and float(m.group(1)) < 300))(
            re.search(r'x:([0-9.]+)', str(_attr(element, 'AXPosition') or ''))
        )
    ]
    if search_fields:
        field = search_fields[0]
        AX.AXUIElementSetAttributeValue(field, 'AXFocused', True)
        subprocess.run(['pbcopy'], input=group.encode('utf-8'), check=True)
        subprocess.run(
            ['osascript', '-e', 'tell application "System Events" to keystroke "a" using command down',
             '-e', 'tell application "System Events" to keystroke "v" using command down'],
            check=True,
        )
        time.sleep(1.0)
        subprocess.run(['osascript', '-e', 'tell application "System Events" to key code 36'], check=True)
        time.sleep(0.8)
        _, refreshed, _ = current_tree()
        if _group_is_open(refreshed, group):
            return refreshed
    raise DesktopError(f'blocked_group: 无法精确打开或回读群标题 {group!r}')


def _window_id(pid: int) -> int:
    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
    matches = [w for w in windows if int(w.get('kCGWindowOwnerPID', -1)) == pid and int(w.get('kCGWindowLayer', 1)) == 0]
    if not matches:
        raise DesktopError('企业微信窗口截图目标不存在')
    return int(max(matches, key=lambda w: float(w.get('kCGWindowBounds', {}).get('Width', 0)) * float(w.get('kCGWindowBounds', {}).get('Height', 0)))['kCGWindowNumber'])


def capture_window(path: Path, pid: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(['screencapture', '-x', '-l', str(_window_id(pid)), str(path)], capture_output=True, text=True)
    if proc.returncode != 0 or not path.is_file():
        raise DesktopError(f'企业微信窗口截图失败: {(proc.stderr or proc.stdout).strip()}')
    return path


def verify_enterprise(marker: str, artifacts: Path, pid: int) -> Path:
    screenshot = capture_window(artifacts / 'enterprise-preflight.png', pid)
    text = ''.join(value for value, confidence in ocr_image(screenshot) if confidence >= 0.2)
    compact = ''.join(text.split())
    expected = ''.join(marker.split())
    if expected not in compact:
        raise DesktopError(f'blocked_login: 当前企业微信窗口未回读到企业标识 {marker!r}')
    return screenshot


def discover(group: str, enterprise_marker: str, artifacts: Path) -> tuple[list[Attachment], Path]:
    elements = open_group(group)
    _, _, pid = current_tree()
    screenshot = verify_enterprise(enterprise_marker, artifacts, pid)
    texts = [text_of(element) for element in elements if text_of(element)]
    attachments = parse_attachments(texts)
    if not attachments:
        # 部分客户端把文件名和大小拆成相邻节点；按视觉顺序合并后再解析。
        attachments = parse_attachments([' '.join(texts)])
    return attachments, screenshot


def _clock(text: str, now: datetime) -> datetime | None:
    compact = ''.join(text.split())
    match = re.fullmatch(r'(?:(昨天))?(上午|下午)(\d{1,2}):(\d{2})', compact)
    if not match:
        return None
    hour, minute = int(match.group(3)), int(match.group(4))
    if not (1 <= hour <= 12 and 0 <= minute <= 59):
        return None
    if match.group(2) == '下午' and hour != 12:
        hour += 12
    elif match.group(2) == '上午' and hour == 12:
        hour = 0
    day = now.astimezone().date() - (timedelta(days=1) if match.group(1) else timedelta())
    return datetime.combine(day, datetime.min.time(), tzinfo=now.astimezone().tzinfo).replace(hour=hour, minute=minute)


def _duration(text: str) -> int | None:
    match = re.fullmatch(r'(\d{1,2}):(\d{2})', text.strip())
    if not match:
        return None
    seconds = int(match.group(1)) * 60 + int(match.group(2))
    return seconds if 0 < seconds <= 3600 else None


def discover_native_videos(
    group: str,
    enterprise_marker: str,
    sender: str,
    artifacts: Path,
    *,
    now: datetime | None = None,
) -> tuple[list[NativeVideo], Path]:
    elements = open_group(group)
    _, _, pid = current_tree()
    screenshot = verify_enterprise(enterprise_marker, artifacts, pid)
    tables = [element for element in elements if (_attr(element, 'AXRole') or '') == 'AXTable']
    if not tables:
        raise DesktopError('目标群聊天消息表不可读')

    def video_count(table: Any) -> int:
        return sum(
            1 for element in walk(table, output=[])
            if (_attr(element, 'AXRole') or '') == 'AXImage' and 'play action play' in text_of(element)
        )

    table = max(tables, key=video_count)
    if video_count(table) == 0:
        return [], screenshot
    current_time: datetime | None = None
    found: list[NativeVideo] = []
    clock_now = now or datetime.now().astimezone()
    rows = [element for element in _children(table) if (_attr(element, 'AXRole') or '') == 'AXRow']
    for sequence, row in enumerate(rows):
        descendants = walk(row, output=[])
        texts = [text_of(element) for element in descendants if text_of(element)]
        for value in texts:
            parsed = _clock(value, clock_now)
            if parsed:
                current_time = parsed
        has_native_play = any(
            (_attr(element, 'AXRole') or '') == 'AXImage' and 'play action play' in text_of(element)
            for element in descendants
        )
        is_channel = any('[视频号]' in value or 'sph imagecover' in value or 'sph logo' in value for value in texts)
        senders = [
            text_of(element) for element in descendants
            if (_attr(element, 'AXRole') or '') == 'AXButton' and text_of(element)
        ]
        durations = [seconds for value in texts if (seconds := _duration(value)) is not None]
        if has_native_play and not is_channel and sender in senders and current_time and durations:
            found.append(NativeVideo(sender, current_time.isoformat(), durations[-1], sequence))
    return found, screenshot
