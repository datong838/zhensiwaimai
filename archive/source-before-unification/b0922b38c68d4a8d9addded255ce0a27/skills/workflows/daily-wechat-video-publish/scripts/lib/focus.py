"""操作前抢焦点：先 activate + frontmost 校验，再截图/点击/键盘。"""
from __future__ import annotations

import subprocess
import time


class FocusError(RuntimeError):
    pass


def frontmost_process() -> str:
    return subprocess.check_output(
        [
            'osascript',
            '-e',
            'tell application "System Events" to return name of first process whose frontmost is true',
        ],
        text=True,
    ).strip()


def seize_wechat(*, retries: int = 4) -> None:
    activate = """
tell application "WeChat" to activate
tell application "WeChat" to reopen
delay 0.15
tell application "System Events"
  try
    click UI element "微信" of list 1 of application process "Dock"
  end try
  if exists process "WeChat" then
    tell process "WeChat"
      set frontmost to true
      if (count of windows) > 0 then
        set w to front window
        set value of attribute "AXMinimized" of w to false
        perform action "AXRaise" of w
      end if
    end tell
  else if exists process "微信" then
    tell process "微信"
      set frontmost to true
    end tell
  end if
end tell
"""
    for _ in range(retries):
        subprocess.run(['osascript', '-e', activate], check=False)
        time.sleep(0.45)
        front = frontmost_process()
        if front in ('WeChat', '微信'):
            return
    raise FocusError('无法抢到微信焦点：请把微信主窗口置前并关闭遮挡')


def seize_chrome(*, retries: int = 4) -> None:
    activate = """
tell application "Google Chrome" to activate
delay 0.15
tell application "System Events"
  tell process "Google Chrome"
    set frontmost to true
    repeat with w in windows
      try
        set value of attribute "AXMinimized" of w to false
        perform action "AXRaise" of w
      end try
    end repeat
  end tell
end tell
"""
    for _ in range(retries):
        subprocess.run(['osascript', '-e', activate], check=False)
        time.sleep(0.45)
        if frontmost_process() == 'Google Chrome':
            return
    raise FocusError('无法抢到 Chrome 焦点：请把已登录抖音的 Chrome 窗口置前')


def assert_wechat_screenshot(hits) -> None:
    joined = ' '.join(h.text for h in hits)
    has_wechat = any(g in joined for g in ('微信', '搜索', '发送', '聊天记录', 'WeChat', '文件 编辑'))
    has_foreign = any(b in joined for b in ('Cursor', 'Agents', 'Composer', 'ChatGPT'))
    if has_foreign and not has_wechat:
        raise FocusError('截图不像微信窗口（可能截到了 Cursor/其他 app），请先置前微信')
    if not has_wechat:
        raise FocusError('截图未识别到微信界面，请先点击微信窗口再重试')


def assert_chrome_screenshot(entries: list[dict]) -> None:
    joined = ' '.join(e.get('text', '') for e in entries)
    if 'creator.douyin.com' in joined or '抖音' in joined or '发布' in joined or '上传' in joined:
        return
    bad = ('Cursor', '微信', 'WeChat')
    if any(b in joined for b in bad):
        raise FocusError('截图不像抖音创作者中心（可能截到了其他 app），请先置前 Chrome')
