"""安全操作节奏：页面稳定等待、坐标容错和失败退避。"""
import random
import time
from typing import Any

from config import HUMAN


def jitter(x: int, y: int, j: int = HUMAN.COORD_JITTER):
    """坐标微偏移。"""
    return x + random.randint(-j, j), y + random.randint(-j, j)


def click(d: Any, x: int = None, y: int = None,
          element=None, text: str = None, resource_id: str = None):
    """统一点击入口：支持坐标 / 控件 / text / resourceId，并等待界面稳定。"""
    time.sleep(random.uniform(*HUMAN.CLICK_BEFORE))

    if element is not None:
        element.click()
    elif text:
        d(text=text).click()
    elif resource_id:
        d(resourceId=resource_id).click()
    elif x is not None and y is not None:
        jx, jy = jitter(x, y)
        d.click(jx, jy)
    else:
        raise ValueError("click 需提供 element / text / resource_id / (x,y) 之一")

    time.sleep(random.uniform(*HUMAN.CLICK_AFTER))


def type_text(d: Any, text: str):
    """逐字符输入并留出界面处理时间，避免丢字。"""
    for ch in text:
        d.send_keys(ch)
        time.sleep(random.uniform(*HUMAN.TYPING))


def swipe_up(d: Any, times: int = 1):
    """向上滑动（浏览列表），带随机速度与后置等待。"""
    w, h = d.window_size()
    for _ in range(times):
        d.swipe(w * 0.5, h * 0.8, w * 0.5, h * 0.2,
                duration=random.uniform(*HUMAN.SWIPE))
        time.sleep(random.uniform(*HUMAN.SCROLL_AFTER))


def exponential_backoff(attempt: int) -> float:
    """指数退避：用于失败重试的等待时长。"""
    return HUMAN.BACKOFF_BASE * (2 ** attempt) + random.uniform(0, 0.5)
