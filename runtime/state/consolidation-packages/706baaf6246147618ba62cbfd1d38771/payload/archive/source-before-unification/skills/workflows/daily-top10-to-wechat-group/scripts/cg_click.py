#!/usr/bin/env python3
"""Quartz CGEvent 鼠标点击工具（macOS）。
用法:
  cg_click.py <x> <y>            # 左键单击（全屏坐标）
  cg_click.py --double <x> <y>   # 双击
依赖: pyobjc-framework-Quartz（venv: harmonyos3-phone-control）
"""
import sys
from Quartz import (
    CGEventCreateMouseEvent, CGEventPost, CGEventSourceCreate,
    kCGEventSourceStateHIDSystemState,
    kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp,
    kCGHIDEventTap,
)

# 带正式事件源（Chrome 等应用会忽略无源合成事件）
SRC = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)


def click(x: float, y: float, double: bool = False):
    # 先移动（部分应用要求 hover 才响应点击）
    move = CGEventCreateMouseEvent(SRC, kCGEventMouseMoved, (x, y), 0)
    CGEventPost(kCGHIDEventTap, move)
    import time
    time.sleep(0.05)
    down = CGEventCreateMouseEvent(SRC, kCGEventLeftMouseDown, (x, y), 0)
    up = CGEventCreateMouseEvent(SRC, kCGEventLeftMouseUp, (x, y), 0)
    CGEventPost(kCGHIDEventTap, down)
    import time as t
    t.sleep(0.05)
    CGEventPost(kCGHIDEventTap, up)
    if double:
        CGEventPost(kCGHIDEventTap, down)
        CGEventPost(kCGHIDEventTap, up)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    double = "--double" in sys.argv
    if len(args) != 2:
        sys.exit("用法: cg_click.py [--double] <x> <y>")
    click(float(args[0]), float(args[1]), double)
    print(f"clicked ({args[0]}, {args[1]}){' x2' if double else ''}")
