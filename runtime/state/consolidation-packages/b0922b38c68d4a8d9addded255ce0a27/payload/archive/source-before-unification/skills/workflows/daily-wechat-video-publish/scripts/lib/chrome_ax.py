"""Chrome Accessibility 树：定位抖音编辑页输入框/按钮，避免 OCR 点偏。"""
from __future__ import annotations

import re
import subprocess
import time
from typing import Any

import ApplicationServices as AX
from AppKit import NSPasteboard, NSStringPboardType, NSWorkspace

CG_CLICK = (
    '/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/'
    'wechat-desktop-control/scripts/cgevent_click_bin'
)


class AxError(RuntimeError):
    pass


COVER_FORBIDDEN = ('封面', '竖封面', '横封面', 'AI生成封面', '选择封面', '设置封面', '上传封面')


def _attr(el: Any, name: str) -> Any:
    err, val = AX.AXUIElementCopyAttributeValue(el, name, None)
    return val if err == 0 else None


def _children(el: Any) -> list[Any]:
    return list(_attr(el, 'AXChildren') or [])


def _point(el: Any) -> tuple[float, float, float, float]:
    pos, size = _attr(el, 'AXPosition'), _attr(el, 'AXSize')
    if pos is None or size is None:
        raise AxError('ax-geometry-missing')
    mx = re.search(r'x:([0-9.]+)', str(pos))
    my = re.search(r'y:([0-9.]+)', str(pos))
    mw = re.search(r'w:([0-9.]+)', str(size))
    mh = re.search(r'h:([0-9.]+)', str(size))
    if not all((mx, my, mw, mh)):
        raise AxError(f'ax-geometry-unparsed:{pos}:{size}')
    return float(mx.group(1)), float(my.group(1)), float(mw.group(1)), float(mh.group(1))


def chrome_app() -> Any:
    """Return the visible ordinary Chrome, never a same-name headless process."""
    visible: list[tuple[float, Any]] = []
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.localizedName() != 'Google Chrome':
            continue
        root = AX.AXUIElementCreateApplication(int(app.processIdentifier()))
        for window in (_attr(root, 'AXWindows') or []):
            if (_attr(window, 'AXRole') or '') != 'AXWindow':
                continue
            try:
                _, _, width, height = _point(window)
            except AxError:
                continue
            if width > 0 and height > 0 and str(_attr(window, 'AXTitle') or ''):
                visible.append((width * height, root))
                break
    if not visible:
        raise AxError('chrome-missing')
    return max(visible, key=lambda item: item[0])[1]


def douyin_web() -> Any:
    app = chrome_app()
    win = next(
        (w for w in (_attr(app, 'AXWindows') or []) if '抖音' in str(_attr(w, 'AXTitle') or '')),
        None,
    )
    if win is None:
        raise AxError('douyin-window-missing')

    def rec(el: Any, depth: int = 0) -> Any:
        if depth > 100:
            return None
        if (_attr(el, 'AXRole') or '') == 'AXWebArea':
            return el
        for ch in _children(el):
            hit = rec(ch, depth + 1)
            if hit:
                return hit
        return None

    web = rec(win)
    if web is None:
        raise AxError('webarea-missing')
    return web


def walk(el: Any, pred, *, depth: int = 0, acc: list | None = None) -> list:
    acc = acc if acc is not None else []
    if depth > 100:
        return acc
    if pred(el):
        acc.append(el)
    for ch in _children(el):
        walk(ch, pred, depth=depth + 1, acc=acc)
    return acc


def role_is(el: Any, role: str) -> bool:
    return (_attr(el, 'AXRole') or '') == role


def text_of(el: Any) -> str:
    return f"{_attr(el, 'AXTitle') or ''}{_attr(el, 'AXValue') or ''}"


def is_cover_node(el: Any) -> bool:
    return any(k in text_of(el) for k in COVER_FORBIDDEN)


def press(el: Any) -> None:
    if is_cover_node(el):
        raise AxError('refuse-cover-control')
    AX.AXUIElementPerformAction(el, 'AXScrollToVisible')
    time.sleep(0.15)
    AX.AXUIElementPerformAction(el, 'AXPress')


def click_center(el: Any) -> None:
    if is_cover_node(el):
        raise AxError('refuse-cover-control')
    px, py, pw, ph = _point(el)
    subprocess.run(['osascript', '-e', 'tell application "Google Chrome" to activate'], check=True)
    time.sleep(0.2)
    subprocess.run([CG_CLICK, str(px + pw / 2), str(py + ph / 2)], check=True)
    time.sleep(0.2)


def paste(text: str, *, select_all: bool = True) -> None:
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    pb.setString_forType_(text, NSStringPboardType)
    subprocess.run(['osascript', '-e', 'tell application "Google Chrome" to activate'], check=True)
    time.sleep(0.12)
    if select_all:
        subprocess.run(
            ['osascript', '-e', 'tell application "System Events" to keystroke "a" using command down'],
            check=True,
        )
        time.sleep(0.08)
    subprocess.run(
        ['osascript', '-e', 'tell application "System Events" to keystroke "v" using command down'],
        check=True,
    )


def description_has_junk(text: str) -> bool:
    return text.count('红太阳鱼杂王杨浦保利店') >= 2 or text.count('辽阳路195号') >= 2 or '👉' in text


def read_description() -> str:
    web = douyin_web()
    areas = walk(web, lambda e: role_is(e, 'AXTextArea'))
    return text_of(areas[0]) if areas else ''


def location_selected(web: Any | None = None) -> bool:
    web = web or douyin_web()
    texts = [text_of(e) for e in walk(web, lambda e: role_is(e, 'AXStaticText'))]
    if any(t == '输入地理位置' for t in texts):
        return False
    return any('红太阳鱼杂王(杨浦店)' in t and len(t) < 40 for t in texts)


def fill_description_ax(caption: str) -> None:
    web = douyin_web()
    areas = walk(web, lambda e: role_is(e, 'AXTextArea'))
    if not areas:
        raise AxError('description-box-missing')
    current = text_of(areas[0])
    if (
        '鱼杂王中王' in current
        and caption[:8] in current
        and not description_has_junk(current)
        and current.rstrip().endswith('👈')
    ):
        return
    AX.AXUIElementSetAttributeValue(areas[0], 'AXValue', caption)
    AX.AXUIElementSetAttributeValue(areas[0], 'AXFocused', True)
    press(areas[0])
    paste(caption, select_all=True)
    time.sleep(0.6)
    written = read_description().replace('\u200b', '').rstrip()
    if written != caption.rstrip() or description_has_junk(written):
        raise AxError('description-not-written')


def fill_location_ax(query: str = '红太阳鱼杂王杨浦保利店') -> str:
    """打开位置框、搜索、点选杨浦店 POI。返回选中文案。"""
    web = douyin_web()
    if location_selected(web):
        return next(
            (text_of(e) for e in walk(web, lambda e: '杨浦店' in text_of(e) and role_is(e, 'AXStaticText'))),
            query,
        )
    placeholder = walk(
        web,
        lambda e: role_is(e, 'AXStaticText') and text_of(e) == '输入地理位置',
    )
    field = walk(
        web,
        lambda e: role_is(e, 'AXTextField')
        and (
            '地理' in str(_attr(e, 'AXPlaceholderValue') or '')
            or '红太阳' in text_of(e)
            or '辽阳' in text_of(e)
            or '保利' in text_of(e)
        ),
    )
    if placeholder:
        AX.AXUIElementPerformAction(placeholder[0], 'AXScrollToVisible')
        time.sleep(0.35)
        # 高度为零说明控件仍在视口外，绝不能继续物理点击或粘贴。
        _, _, _, height = _point(placeholder[0])
        if height <= 0:
            raise AxError('location-input-offscreen')
        parent = _attr(placeholder[0], 'AXParent')
        pressable = parent
        while pressable is not None:
            err, acts = AX.AXUIElementCopyActionNames(pressable, None)
            acts = list(acts) if err == 0 else []
            if 'AXPress' in acts:
                press(pressable)
                break
            pressable = _attr(pressable, 'AXParent')
        else:
            try:
                click_center(placeholder[0])
            except AxError:
                raise AxError('location-input-missing')
    elif field:
        AX.AXUIElementSetAttributeValue(field[0], 'AXFocused', True)
        press(field[0])
    else:
        raise AxError('location-input-missing')
    time.sleep(0.4)
    web = douyin_web()
    loc_fields = walk(
        web,
        lambda e: role_is(e, 'AXTextField')
        and e is not None
        and (
            '地理' in str(_attr(e, 'AXPlaceholderValue') or '')
            or any(k in text_of(e) for k in ('红太阳', '辽阳', '保利', '杨浦'))
        ),
    )
    if not loc_fields:
        # 抖音位置弹层的搜索框有时没有 placeholder；排除标题框后，选择
        # 当前可见的最后一个输入框。
        visible_fields = []
        for candidate in walk(web, lambda e: role_is(e, 'AXTextField')):
            try:
                _, _, _, candidate_height = _point(candidate)
            except AxError:
                continue
            placeholder_value = str(_attr(candidate, 'AXPlaceholderValue') or '')
            if candidate_height > 5 and '作品标题' not in placeholder_value:
                visible_fields.append(candidate)
        loc_fields = visible_fields[-1:]
    if loc_fields:
        AX.AXUIElementSetAttributeValue(loc_fields[0], 'AXFocused', True)
        press(loc_fields[0])
        time.sleep(0.2)
    else:
        raise AxError('location-search-field-missing')
    before_desc = read_description()
    paste(query, select_all=True)
    time.sleep(2.6)
    after_desc = read_description()
    if description_has_junk(after_desc) or (before_desc and after_desc != before_desc and query in after_desc):
        raise AxError('location-paste-leaked-into-description')

    web = douyin_web()
    cands = walk(
        web,
        lambda e: role_is(e, 'AXStaticText')
        and '红太阳鱼杂王(杨浦店)' in text_of(e)
        and '九亭' not in text_of(e),
    )
    if not cands:
        raise AxError('location-poi-missing')
    pick = min(cands, key=lambda e: len(text_of(e)))
    press(pick)
    parent = _attr(pick, 'AXParent')
    if parent:
        press(parent)
    try:
        click_center(pick)
    except AxError:
        pass
    time.sleep(0.8)
    web = douyin_web()
    if not location_selected(web):
        raise AxError('location-not-selected')
    chosen = next(
        (text_of(e) for e in walk(web, lambda e: '杨浦店' in text_of(e) and role_is(e, 'AXStaticText'))),
        query,
    )
    return chosen


def publishing_visible(web: Any | None = None) -> bool:
    web = web or douyin_web()
    return any(text_of(e) == '正在发布' for e in walk(web, lambda e: role_is(e, 'AXStaticText')))


def sms_verification_visible(web: Any | None = None) -> bool:
    web = web or douyin_web()
    return any('接收短信验证码' in text_of(e) for e in walk(web, lambda e: True))


def click_publish_ax() -> None:
    # 只能回读当前可见普通 Chrome；按应用名 AppleScript 会误命中后台无头
    # Chrome，导致已提交页面被错误判为超时。
    from lib import chrome_common as cc

    web = douyin_web()
    if any(is_cover_node(e) and role_is(e, 'AXButton') for e in walk(web, lambda e: True)):
        cancels = walk(web, lambda e: role_is(e, 'AXButton') and (_attr(e, 'AXTitle') or '') == '取消')
        if cancels:
            press(cancels[0])
            time.sleep(0.8)
            web = douyin_web()
    btns = walk(
        web,
        lambda e: role_is(e, 'AXButton')
        and (_attr(e, 'AXTitle') or '') == '发布'
        and '封面' not in text_of(e),
    )
    if not btns:
        raise AxError('publish-button-missing')
    press(btns[0])
    deadline = time.time() + 45
    saw = False
    refreshed = False
    while time.time() < deadline:
        url = cc.active_tab_url()
        if 'content/manage' in url:
            return
        web = douyin_web()
        if sms_verification_visible(web):
            if refreshed:
                raise AxError('sms-verification-repeated')
            subprocess.run(
                ['osascript', '-e', 'tell application "System Events" to keystroke "r" using command down'],
                check=True,
            )
            refreshed = True
            time.sleep(4.0)
            if not read_description() or not location_selected():
                raise AxError('draft-lost-after-sms-refresh')
            web = douyin_web()
            retry = walk(
                web,
                lambda e: role_is(e, 'AXButton')
                and (_attr(e, 'AXTitle') or '') == '发布'
                and '封面' not in text_of(e),
            )
            if not retry:
                raise AxError('publish-button-missing-after-sms-refresh')
            press(retry[0])
            continue
        if publishing_visible(web):
            saw = True
        elif saw and 'content/post/video' not in url:
            return
        time.sleep(1.2)
    raise AxError('publish-not-completed')


def web_for_title(needles: tuple[str, ...]) -> Any:
    app = chrome_app()
    wins = [
        w for w in (_attr(app, 'AXWindows') or [])
        if any(n.lower() in str(_attr(w, 'AXTitle') or '').lower() for n in needles)
    ]
    if not wins:
        raise AxError(f'window-missing:{needles}')

    def rec(el: Any, depth: int = 0) -> Any:
        if depth > 100:
            return None
        if (_attr(el, 'AXRole') or '') == 'AXWebArea':
            return el
        for ch in _children(el):
            hit = rec(ch, depth + 1)
            if hit:
                return hit
        return None

    for win in wins:
        web = rec(win)
        if web is not None:
            return web
    raise AxError('webarea-missing')


def fill_description_on(web: Any, caption: str) -> None:
    areas = walk(web, lambda e: role_is(e, 'AXTextArea'))
    if not areas:
        raise AxError('description-box-missing')
    AX.AXUIElementSetAttributeValue(areas[0], 'AXFocused', True)
    press(areas[0])
    paste(caption, select_all=True)
    time.sleep(0.5)


def fill_short_title_on(web: Any, title: str) -> None:
    fields = walk(
        web,
        lambda e: role_is(e, 'AXTextField')
        and '短标题' in str(_attr(e, 'AXPlaceholderValue') or ''),
    )
    if not fields:
        raise AxError('short-title-missing')
    AX.AXUIElementSetAttributeValue(fields[0], 'AXFocused', True)
    press(fields[0])
    paste(title, select_all=True)
    time.sleep(0.4)


def fill_location_on(
    web: Any,
    query: str,
    *,
    must: tuple[str, ...],
    forbid: tuple[str, ...],
    platform: str = '',
) -> str:
    if platform == 'channels':
        locations = walk(
            web,
            lambda e: role_is(e, 'AXStaticText')
            and text_of(e).strip() in ('上海市', '添加位置'),
        )
        if not locations:
            raise AxError('channels-location-missing')
        location = max(locations, key=lambda e: _point(e)[0])
        press(_attr(location, 'AXParent'))
        time.sleep(0.6)
        web = web_for_title(('视频号', 'channels'))
        searches = walk(
            web,
            lambda e: role_is(e, 'AXTextField')
            and '搜索附近位置' in str(_attr(e, 'AXPlaceholderValue') or ''),
        )
        if not searches:
            raise AxError('channels-location-search-missing')
        AX.AXUIElementSetAttributeValue(searches[0], 'AXFocused', True)
        press(searches[0])
        paste('辽阳路195号', select_all=True)
        time.sleep(2.6)
        web = web_for_title(('视频号', 'channels'))
        matches = walk(
            web,
            lambda e: role_is(e, 'AXStaticText')
            and text_of(e).strip() == '红太阳鱼杂王·蜀湘川菜',
        )
        if not matches:
            raise AxError('channels-location-poi-missing')
        pick = matches[-1]
        AX.AXUIElementPerformAction(pick, 'AXScrollToVisible')
        time.sleep(0.4)
        chosen = text_of(pick).strip()
        press(_attr(pick, 'AXParent'))
        time.sleep(0.6)
        return chosen
    kuaishou_regions = walk(
        web,
        lambda e: role_is(e, 'AXStaticText') and text_of(e).strip() in ('请选择所在地区', '上海市'),
    )
    if platform == 'kuaishou' and any(text_of(e).strip() == '请选择所在地区' for e in kuaishou_regions):
        placeholder = next(e for e in kuaishou_regions if text_of(e).strip() == '请选择所在地区')
        press(_attr(placeholder, 'AXParent'))
        time.sleep(0.5)
        web = web_for_title(('快手', 'kuaishou', 'Kuaishou'))
        shanghai = walk(web, lambda e: role_is(e, 'AXStaticText') and text_of(e).strip() == '上海市')
        if not shanghai:
            raise AxError('kuaishou-region-missing')
        press(_attr(shanghai[-1], 'AXParent'))
        time.sleep(0.5)
        return '上海市'
    fields = walk(web, lambda e: role_is(e, 'AXTextField'))
    placeholders = walk(
        web,
        lambda e: role_is(e, 'AXStaticText')
        and any(k in text_of(e) for k in ('位置', '地点', '地理', '添加位置')),
    )
    target = fields[0] if fields else None
    if target is None and placeholders:
        AX.AXUIElementPerformAction(placeholders[0], 'AXScrollToVisible')
        time.sleep(0.45)
        web = web_for_title(('快手', 'kuaishou', 'Kuaishou', '视频号', 'channels'))
        placeholders = walk(
            web,
            lambda e: role_is(e, 'AXStaticText')
            and any(k in text_of(e) for k in ('位置', '地点', '地理', '添加位置')),
        ) or placeholders
        parent = _attr(placeholders[0], 'AXParent')
        pressable = parent
        while pressable is not None:
            err, acts = AX.AXUIElementCopyActionNames(pressable, None)
            acts = list(acts) if err == 0 else []
            if 'AXPress' in acts:
                press(pressable)
                break
            pressable = _attr(pressable, 'AXParent')
        else:
            click_center(placeholders[0])
        time.sleep(0.35)
        web = web_for_title(('快手', 'kuaishou', 'Kuaishou', '视频号', 'channels'))
        fields = walk(web, lambda e: role_is(e, 'AXTextField')) if web else []
        target = fields[0] if fields else None
    if target is None:
        raise AxError('location-input-missing')
    AX.AXUIElementSetAttributeValue(target, 'AXFocused', True)
    press(target)
    paste(query, select_all=True)
    time.sleep(2.2)
    cands = walk(
        web,
        lambda e: role_is(e, 'AXStaticText')
        and any(m in text_of(e) for m in must)
        and not any(b in text_of(e) for b in forbid),
    )
    if not cands:
        raise AxError('location-poi-missing')
    pick = min(cands, key=lambda e: len(text_of(e)))
    press(pick)
    try:
        click_center(pick)
    except AxError:
        pass
    time.sleep(0.6)
    return text_of(pick)


def click_named_button(web: Any, title: str) -> None:
    if any(is_cover_node(e) and role_is(e, 'AXButton') for e in walk(web, lambda e: True)):
        cancels = walk(web, lambda e: role_is(e, 'AXButton') and (_attr(e, 'AXTitle') or '') == '取消')
        if cancels:
            press(cancels[0])
            time.sleep(0.6)
            web = _attr(cancels[0], 'AXParent') or web
    btns = walk(
        web,
        lambda e: role_is(e, 'AXButton')
        and (_attr(e, 'AXTitle') or '') == title
        and '封面' not in text_of(e),
    )
    if not btns:
        labels = walk(web, lambda e: role_is(e, 'AXStaticText') and text_of(e).strip() == title)
        target = None
        for label in labels:
            current = _attr(label, 'AXParent')
            for _ in range(5):
                if current is None:
                    break
                err, actions = AX.AXUIElementCopyActionNames(current, None)
                if err == 0 and 'AXPress' in list(actions or []):
                    target = current
                    break
                current = _attr(current, 'AXParent')
            if target is not None:
                break
        if target is None:
            raise AxError(f'publish-button-missing:{title}')
        press(target)
    else:
        press(btns[0])
    time.sleep(2.0)


def page_has_snippet(web: Any, snippet: str) -> bool:
    return any(snippet in text_of(e) for e in walk(web, lambda e: True))
