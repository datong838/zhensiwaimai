#!/usr/bin/env python3
"""把微信主窗口拉回当前桌面，并验证像素是否真的变成微信。

为什么需要它 —— 已验证的两个「假绿」：

  * `wechat_menu_bar_frontmost()` 只证明「谁是活跃 App」：菜单栏属于活跃 App，
    哪怕它的窗口在别的 Space、根本没被合成。
  * `wechat_window_unobstructed()` 也可能与合成结果矛盾。

决定性证据：微信主窗口（id 2419，1234x636）`screencapture -l` 报
`could not create image from window`，而**同一个进程**的小窗口（2411）可以抓，
WorkBuddy 的窗口也可以抓 ⇒ 不是权限问题，是 2419 没有被合成（不在当前桌面，
或被最小化）。此时任何 `-R<rect>` 抓到的都是别人的像素，定位器于是报
`search-control-count:0`，看起来像「控件找不到」。

本脚本依次尝试几种能把窗口带回当前桌面的机制，每步之后都读一次
`kCGWindowIsOnscreen` 与 `screencapture -l` 的结果，末尾用 OCR 判断像素里到底
有没有微信独有文案。只改窗口的位置/最小化状态，不做任何点击或输入。

用法：`<venv python> runtime/wechat_ax_onspace.py`
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path

import AppKit
import Quartz

SHARED = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/legacy-app-controler/"
              "wechat-desktop-control/scripts")

WECHAT_MARKERS = ("通讯录", "文件传输助手", "订阅号", "服务通知", "微信团队",
                  "折叠的群聊", "搜一搜", "看一看", "视频号", "朋友圈")
FOREIGN_MARKERS = ("美团", "商家", "订单", "商品", "顾客", "财务", "经营",
                   "WorkBuddy", "资料库", "自动化", "专家", "助理")


def wechat_pid() -> int | None:
    for app in AppKit.NSWorkspace.sharedWorkspace().runningApplications():
        if app.localizedName() == "微信":
            return app.processIdentifier()
    return None


def main_window(pid: int) -> tuple:
    """返回 (windowId, onscreen, bounds) —— 微信 layer0 面积最大的那个窗口。"""
    best = None
    for w in Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll,
                                               Quartz.kCGNullWindowID):
        if w.get("kCGWindowOwnerPID") != pid or w.get("kCGWindowLayer") != 0:
            continue
        b = w.get("kCGWindowBounds") or {}
        area = b.get("Width", 0) * b.get("Height", 0)
        if best is None or area > best[1]:
            best = (w.get("kCGWindowNumber"), area, bool(w.get("kCGWindowIsOnscreen")), b)
    if best is None:
        return None, False, {}
    return best[0], best[2], best[3]


def capture_by_id(wid: int, path: Path) -> tuple:
    p = subprocess.run(["/usr/sbin/screencapture", "-x", "-l", str(wid), str(path)],
                       capture_output=True, text=True)
    ok = p.returncode == 0 and path.exists() and path.stat().st_size > 0
    return ok, (p.stderr or "").strip()[:80]


def ocr_markers(path: Path) -> tuple:
    if not path.exists():
        return [], [], ""
    p = subprocess.run([str(SHARED / "ocr_vision_bin"), str(path)],
                       capture_output=True, text=True)
    text = " ".join((p.stdout or "").split())
    return ([m for m in WECHAT_MARKERS if m in text],
            [m for m in FOREIGN_MARKERS if m in text], text)


def report(label: str, pid: int, tmp: Path) -> None:
    wid, onscreen, bounds = main_window(pid)
    shot = tmp / ("%s.png" % label)
    for stale in (shot,):
        try:
            stale.unlink()
        except OSError:
            pass
    ok, err = capture_by_id(wid, shot) if wid else (False, "no-window")
    hits, foreign, text = ocr_markers(shot)
    print("[%-22s] id=%-6s onscreen=%-5s bounds=%-22s capture-l=%-5s wechat=%s foreign=%s"
          % (label, wid, onscreen,
             "%dx%d@%d,%d" % (bounds.get("Width", 0), bounds.get("Height", 0),
                              bounds.get("X", 0), bounds.get("Y", 0)),
             ok, hits or "-", foreign[:4] or "-"))
    if ok and text:
        print("       text: %s" % text[:120])


def run_osascript(script: str) -> str:
    p = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return ((p.stdout or "").strip() + (p.stderr or "").strip())[:120]


def ax_set(el, name: str, value) -> bool:
    from ApplicationServices import AXUIElementSetAttributeValue
    try:
        return AXUIElementSetAttributeValue(el, name, value) == 0
    except Exception:  # noqa: BLE001
        return False


def ax_perform(el, action: str) -> bool:
    from ApplicationServices import AXUIElementPerformAction
    try:
        return AXUIElementPerformAction(el, action) == 0
    except Exception:  # noqa: BLE001
        return False


def ax_windows(pid: int) -> list:
    from ApplicationServices import (AXUIElementCreateApplication,
                                     AXUIElementCopyAttributeValue)
    try:
        app_el = AXUIElementCreateApplication(pid)
        err, value = AXUIElementCopyAttributeValue(app_el, "AXWindows", None)
        return list(value) if err == 0 and value else []
    except Exception:  # noqa: BLE001
        return []


def main() -> int:
    pid = wechat_pid()
    if not pid:
        print("微信未运行")
        return 1
    print("微信 pid = %s" % pid)
    tmp = Path(tempfile.mkdtemp())
    report("baseline", pid, tmp)

    windows = ax_windows(pid)
    print("AX 窗口数 = %d" % len(windows))
    target = None
    for i, win in enumerate(windows):
        from ApplicationServices import AXUIElementCopyAttributeValue
        title = pos = size = mini = None
        for name, slot in (("AXTitle", "title"), ("AXPosition", "pos"),
                           ("AXSize", "size"), ("AXMinimized", "mini")):
            try:
                err, value = AXUIElementCopyAttributeValue(win, name, None)
                if err == 0:
                    if name == "AXSize":
                        size = (value[0], value[1]) if hasattr(value, "__len__") else value
                    elif name == "AXPosition":
                        pos = (value[0], value[1]) if hasattr(value, "__len__") else value
                    elif name == "AXMinimized":
                        mini = bool(value)
                    else:
                        title = value
            except Exception:  # noqa: BLE001
                pass
        area = (size[0] * size[1]) if isinstance(size, tuple) else 0
        print("  ax[%d] title=%-12r size=%-14s pos=%-14s minimized=%s"
              % (i, str(title)[:12], size, pos, mini))
        if target is None or (area, ) > (target[0], ):
            target = (area, win, title, size, mini)

    if target is None:
        print("拿不到 AX 窗口，退回 osascript 尝试")
    else:
        area, win, title, size, mini = target
        print("选中面积最大的 AX 窗口 title=%r size=%s minimized=%s" % (str(title)[:16], size, mini))

        # M1: 解除最小化
        print("M1 取消最小化 ->", ax_set(win, "AXMinimized", False))
        time.sleep(1.0)
        report("M1-unminimize", pid, tmp)

        # M2: 改位置（把窗口拖到当前桌面是唯一能让它被重新合成的合成操作）
        from ApplicationServices import AXValueCreate
        try:
            from ApplicationServices import kAXValueCGPointType as PT
        except Exception:  # noqa: BLE001
            PT = 1
        try:
            pos_value = AXValueCreate(PT, (12.0, 45.0))
        except Exception as error:  # noqa: BLE001
            pos_value = None
            print("  AXValueCreate 失败:", error)
        if pos_value is not None:
            print("M2 设置位置 (12,45) ->", ax_set(win, "AXPosition", pos_value))
            time.sleep(1.2)
            report("M2-setposition", pid, tmp)

        # M3: 提升 + 设为主窗口
        print("M3 AXRaise ->", ax_perform(win, "AXRaise"),
              "| AXMain ->", ax_set(win, "AXMain", True))
        time.sleep(1.0)
        report("M3-raise", pid, tmp)

    # M4: 纯 osascript 路线（走 System Events，等价于用户拖动窗口）
    out = run_osascript('tell application "System Events" to tell process "WeChat" '
                        'to set position of window 1 to {14, 46}')
    print("M4 osascript set position ->", out or "(ok)")
    time.sleep(1.2)
    report("M4-osascript", pid, tmp)

    # M5: 重新打开（reopen 会给离屏窗口一次回到当前 Space 的机会）
    out = run_osascript('tell application "WeChat" to reopen')
    print("M5 osascript reopen ->", out or "(ok)")
    time.sleep(1.5)
    report("M5-reopen", pid, tmp)

    print("\n截图留档：")
    for p in sorted(tmp.glob("*.png")):
        print("  %s (%d bytes)" % (p, p.stat().st_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
