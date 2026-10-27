"""驱动层：设备连接、健康检查、亮屏解锁。"""
import time
from typing import Any

from config import DEVICE_SERIAL


def connect(serial: str = DEVICE_SERIAL) -> Any:
    """连接设备，优先指定序列号，否则取 USB 第一个。"""
    import uiautomator2 as u2
    d = u2.connect(serial) if serial else u2.connect()
    return d


def healthcheck(d: Any) -> dict:
    """健康检查：返回设备基础信息，用于自检。"""
    info = d.info
    return {
        "model": info.get("model"),
        "serial": info.get("serial"),
        "display": info.get("display"),
        "atx_agent_version": info.get("atxAgentVersion"),
    }


def wake_and_unlock(d: Any) -> None:
    """亮屏并滑动解锁（不处理密码，需设备无锁或已解锁）。"""
    if not d.info.get("screenOn"):
        d.screen_on()
        time.sleep(0.5)
    # 上滑解锁（无密码场景）
    w, h = d.window_size()
    d.swipe(w * 0.5, h * 0.8, w * 0.5, h * 0.2, duration=0.4)


def ensure_atx_running(d: Any) -> bool:
    """确认 ATX 守护进程在线。"""
    try:
        return d.service("uiautomator").running()
    except Exception:
        return False
