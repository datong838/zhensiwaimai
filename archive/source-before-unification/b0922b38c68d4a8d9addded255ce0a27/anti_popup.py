"""业务层可关闭弹窗与经授权的系统权限处理。"""
import time
from typing import Any

from human import click

# 各应用常见的"关闭/跳过"文案，按优先级匹配
POPUP_TEXTS = [
    "我知道了", "取消", "稍后再说", "跳过", "下次再说",
    "✕", "×", "X", "关闭",
]


def dismiss(d: Any, texts: list = None, timeout: int = 3) -> int:
    """检测到弹窗即点击关闭，返回处理数量。"""
    targets = texts or POPUP_TEXTS
    count = 0
    for txt in targets:
        if d(text=txt).exists(timeout=0.5):
            try:
                click(d, text=txt)
                count += 1
                time.sleep(0.5)
            except Exception:
                pass
    return count


def ensure_permission(d: Any, permission_texts=("允许", "始终允许", "确定"), authorized: bool = False):
    """仅在调用方明确授权后处理系统权限弹窗。"""
    if not authorized:
        return 0
    count = 0
    for txt in permission_texts:
        if d(text=txt).exists(timeout=0.5):
            click(d, text=txt)
            time.sleep(0.5)
            count += 1
    return count
