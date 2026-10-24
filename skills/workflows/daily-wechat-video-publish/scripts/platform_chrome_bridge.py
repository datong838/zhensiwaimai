#!/usr/bin/env python3
"""快手 / 视频号：复用已登录普通 Chrome，禁止 CDP / Playwright / 自动新开窗。"""
from __future__ import annotations

import os
import sys

VENV_PYTHON = '/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python'
if os.path.realpath(sys.executable) != os.path.realpath(VENV_PYTHON):
    os.execv(VENV_PYTHON, [VENV_PYTHON, *sys.argv])

import argparse
import json
import time
from pathlib import Path

from lib import chrome_ax, chrome_common as cc
from lib.focus import FocusError
from lib.platform_spec import SPECS, PlatformSpec


class BridgeError(RuntimeError):
    pass


def wait_edit_page(spec: PlatformSpec, *, timeout_sec: float = 90.0) -> None:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            web = chrome_ax.web_for_title(spec.window_title)
            if chrome_ax.walk(web, lambda e: chrome_ax.role_is(e, 'AXTextArea')):
                return
            texts = ' '.join(chrome_ax.text_of(e) for e in chrome_ax.walk(web, lambda e: True))
            if any(bit in texts for bit in spec.edit_text_bits):
                return
        except Exception:
            pass
        time.sleep(2.0)
    raise BridgeError(f'edit-page-timeout:{spec.name}')


def upload_video(spec: PlatformSpec, video: Path) -> None:
    cc.prepare_chrome(spec)
    cc.goto(spec.upload_url)
    deadline = time.time() + 30
    button = None
    while time.time() < deadline and button is None:
        try:
            web = chrome_ax.web_for_title(spec.window_title)
            buttons = chrome_ax.walk(
                web,
                lambda element: chrome_ax.role_is(element, 'AXButton')
                and (
                    chrome_ax.text_of(element).strip() == spec.upload_button
                    or (
                        spec.name == 'channels'
                        and chrome_ax.text_of(element).strip().startswith('上传时长')
                    )
                ),
            )
            button = buttons[0] if buttons else None
        except Exception:
            button = None
        if button is None:
            time.sleep(0.8)
    if button is None:
        raise BridgeError(f'upload-button-missing:{spec.name}')
    # 上传入口是可访问性按钮，不允许退回到说明文字的物理中心坐标。
    chrome_ax.press(button)
    if not cc.wait_for_file_dialog():
        raise BridgeError('pre_upload_failed:file-dialog-missing')
    cc.pick_file_in_dialog(video, dialog_confirmed=True)
    wait_edit_page(spec)
    # Unified upload-complete gate. Small videos can expose the edit form while
    # background upload is still finishing; keep a deterministic quiet window.
    time.sleep(10.0)


def fill_and_publish(spec: PlatformSpec, caption: str, *, confirm: bool) -> dict:
    web = chrome_ax.web_for_title(spec.window_title)
    chrome_ax.fill_description_on(web, caption)
    web = chrome_ax.web_for_title(spec.window_title)
    if spec.name == 'channels':
        chrome_ax.fill_short_title_on(web, '红太阳鱼杂王 蜀湘川菜')
        web = chrome_ax.web_for_title(spec.window_title)
    chosen = chrome_ax.fill_location_on(
        web,
        spec.poi_query,
        must=spec.poi_must,
        forbid=spec.poi_forbid,
        platform=spec.name,
    )
    if confirm:
        web = chrome_ax.web_for_title(spec.window_title)
        chrome_ax.click_named_button(web, spec.publish_button)
        deadline = time.time() + (90 if spec.name == 'kuaishou' else 45)
        while time.time() < deadline:
            if spec.manage_url in cc.active_tab_url():
                break
            if spec.name == 'kuaishou':
                web = chrome_ax.web_for_title(spec.window_title)
                pending = any(
                    '请在视频上传完成后再点击发布' in chrome_ax.text_of(e)
                    for e in chrome_ax.walk(web, lambda e: True)
                )
                if pending:
                    confirms = chrome_ax.walk(
                        web,
                        lambda e: chrome_ax.role_is(e, 'AXButton')
                        and chrome_ax.text_of(e).replace(' ', '').strip() == '确认',
                    )
                    if not confirms:
                        raise BridgeError('kuaishou-upload-pending-confirm-missing')
                    chrome_ax.press(confirms[0])
                    time.sleep(10.0)
                    web = chrome_ax.web_for_title(spec.window_title)
                    chrome_ax.click_named_button(web, spec.publish_button)
                    continue
            time.sleep(1.0)
        else:
            raise BridgeError(f'publish-not-completed:{spec.name}')
    return {
        'ok': True,
        'state': 'submitted' if confirm else 'publish_pending',
        'location_selected': chosen,
        'bridge': f'chrome-ax:{spec.name}',
        'platform': spec.name,
    }


def verify_on_manage(spec: PlatformSpec, caption: str) -> bool:
    if spec.manage_url not in cc.active_tab_url():
        return False
    snippet = caption.replace('😋', '')[:8]
    deadline = time.time() + 20
    while time.time() < deadline:
        try:
            web = chrome_ax.web_for_title(spec.window_title)
            if chrome_ax.page_has_snippet(web, snippet):
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def publish(spec: PlatformSpec, video: Path, caption: str, *, confirm: bool) -> dict:
    if not video.is_file():
        raise BridgeError(f'video-missing:{video}')
    upload_video(spec, video)
    filled = fill_and_publish(spec, caption, confirm=confirm)
    state = filled['state']
    verified = False
    if confirm:
        verified = verify_on_manage(spec, caption)
        state = 'verified' if verified else 'publish_unknown'
    return {
        'ok': state in ('publish_pending', 'verified', 'submitted'),
        'state': state,
        'verified': verified,
        'video': str(video),
        'location_selected': filled.get('location_selected'),
        'bridge': filled.get('bridge'),
        'platform': spec.name,
    }


def run_cli(platform: str) -> int:
    spec = SPECS[platform]
    p = argparse.ArgumentParser()
    p.add_argument('--video')
    p.add_argument('--caption')
    p.add_argument('--location', help='保留与抖音 CLI 对齐；POI 以平台合同为准')
    p.add_argument('--confirm-publish', action='store_true')
    p.add_argument('--preflight', action='store_true')
    args = p.parse_args()
    try:
        if args.preflight:
            url = cc.prepare_chrome(spec)
            print(json.dumps({'ok': True, 'url': url, 'platform': spec.name, 'bridge': 'control-existing-chrome'}, ensure_ascii=False))
            return 0
        if not all([args.video, args.caption]):
            raise BridgeError('publish 需要 --video --caption')
        result = publish(spec, Path(args.video), args.caption, confirm=args.confirm_publish)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['ok'] else 1
    except Exception as exc:  # noqa: BLE001
        err = str(exc)
        if isinstance(exc, FocusError):
            err = f'focus:{err}'
        print(json.dumps({'ok': False, 'error': err, 'platform': spec.name}, ensure_ascii=False))
        return 1
