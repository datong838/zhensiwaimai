"""混合定位器：text -> resourceId -> XPath -> 坐标，逐级降级。

微信/美团/淘宝均存在动态 resourceId 与 WebView 混排，
单一选择器不稳定，故采用降级策略 + 指纹池。
"""
import time
from typing import Any

from config import SELECTORS, Platform
from human import click


def find(d: Any, platform: Platform, key: str, timeout: int = 5):
    """按 SELECTORS 指纹池查找控件；未命中则 None。"""
    selectors = SELECTORS.get(platform, {}).get(key, {})
    if not selectors:
        return None
    if "resourceId" in selectors:
        el = d(resourceId=selectors["resourceId"])
    elif "text" in selectors:
        el = d(text=selectors["text"])
    elif "className" in selectors:
        el = d(className=selectors["className"])
    else:
        return None
    return el if el.exists(timeout=timeout) else None


def click_primary(d: Any, platform: Platform, key: str) -> bool:
    """按指纹池点击，成功返回 True。"""
    el = find(d, platform, key)
    if el:
        click(d, element=el)
        return True
    return False


def wait_gone(d: Any, text: str, timeout: int = 10) -> bool:
    """等待某文本消失（用于判断页面跳转）。"""
    return d(text=text).wait_gone(timeout=timeout)


def current_activity(d: Any) -> str:
    """获取当前前台 Activity，用于断言页面。"""
    return d.app_current().get("activity", "")
