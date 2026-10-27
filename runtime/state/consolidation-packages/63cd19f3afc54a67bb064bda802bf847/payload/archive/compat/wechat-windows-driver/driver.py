#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows 微信 UI 自动化驱动（路线 A：uiautomation，安全合规、零注入）
- 通过 UI 树定位微信控件（搜索框 / 联系人 / 输入框 / 发送）
- 依赖：uiautomation（底层 pywin32），仅 Windows 可用

重要：
- 本文件无法在 Mac/Linux 上运行或测试，只能由用户在 Windows 上执行。
- 微信 3.9.x 的控件 Name/ClassName 可能因小版本略有差异。
  首次部署请先调用 action="dump_tree" 把真实 UI 树贴回，我们再据此校准定位器。
"""
import json
import time

try:
    import uiautomation as auto
except ImportError:
    auto = None


def _sendkeys_escape(text):
    """转义 uiautomation.SendKeys 的特殊字符，使其被原样键入。

    SendKeys 把 + ^ % ( ) { } ~ 当作修饰键/语法（'+'=SHIFT），群名
    '电销+直播攻坚组' 里的 '+' 会被当成 SHIFT，导致搜索词残缺、搜不到目标群、
    退回点错会话（2026-10-22 实测：光标进输入框但不发，报打开会话失败）。
    用花括号包裹这些字符即可原样输入。仅作用于 SendKeys 调用；ListItem 的
    Name 精确匹配仍用未转义的真群名。
    """
    if not text:
        return text
    return ''.join('{' + ch + '}' if ch in '+^%(){}~' else ch for ch in text)


def _wx_window():
    """定位微信主窗口。优先按 ClassName，失败退化为按 Name。"""
    if auto is None:
        raise RuntimeError("uiautomation 未安装，请先 pip install uiautomation")
    w = auto.WindowControl(Name="微信", ClassName="WeChatMainWndForPC")
    if w.Exists(3, 0):
        return w
    w = auto.WindowControl(Name="微信")
    if w.Exists(3, 0):
        return w
    raise RuntimeError("找不到微信主窗口（请确认微信已登录且未最小化到托盘）")


def dispatch(action, params):
    """统一的指令分发入口，由 server.py 调用。"""
    if action == "health":
        return {"status": "ok", "uiautomation": auto is not None}
    if action == "dump_tree":
        return dump_tree(params)
    if action == "send_message":
        return send_message(params.get("who"), params.get("text"))
    if action == "list_chats":
        return list_chats()
    raise RuntimeError(f"未知 action: {action}")


def dump_tree(params):
    """诊断用：打印微信窗口的完整 UI 树，用于校准控件定位器。"""
    w = _wx_window()
    depth = int(params.get("depth", 7))
    lines = []

    def walk(ctl, d):
        if d > depth:
            return
        name = ctl.Name or ""
        ctrl = ctl.ControlType or ""
        cls = ctl.ClassName or ""
        aid = ctl.AutomationId or ""
        lines.append("  " * d + f"[{ctrl}] name={name!r} cls={cls!r} id={aid!r}")
        for child in ctl.GetChildren():
            walk(child, d + 1)

    walk(w, 0)
    return {"tree": "\n".join(lines)}


def list_chats():
    """列出左侧会话列表项（用于确认会话名）。"""
    w = _wx_window()
    items = w.ListItemControl(foundIndex=1).GetParentControl().GetChildren()
    names = [it.Name for it in items if it.Name]
    return {"chats": names[:50]}


def send_message(who, text):
    """
    给指定联系人对发送一条消息。
    流程：聚焦微信 -> 搜索框输入对方 -> 选第一项 -> 输入框输入 -> 回车发送。
    """
    if not who or not text:
        raise RuntimeError("who 和 text 必填")

    w = _wx_window()
    w.SetActive()
    w.SetTopmost(True)
    time.sleep(0.3)

    # 1) 搜索框
    search = w.EditControl(Name="搜索")
    if not search.Exists(3, 0):
        # 退化：取窗口内第一个 Edit（搜索框通常是第一个）
        search = w.EditControl(foundIndex=1)
    if not search.Exists(3, 0):
        w.SetTopmost(False)
        raise RuntimeError("找不到搜索框，请先 dump_tree 校准控件名")
    search.Click()
    # 转义 SendKeys 特殊字符：群名 '电销+直播攻坚组' 的 '+' 会被当 SHIFT，
    # 不转义则搜索词残缺、搜不到目标群、退回点错会话。
    search.SendKeys(_sendkeys_escape(who), waitTime=1.0)
    time.sleep(1.2)

    # 2) 搜索结果第一项（联系人/会话）——按窗口内精确名称匹配
    item = w.ListItemControl(Name=who)
    if not item.Exists(3, 0):
        # 退化：全局再找一次（仍限名称精确匹配，绝不退回点左侧列表第一项=错误会话）
        item = auto.ListItemControl(Name=who)
    if not item.Exists(3, 0):
        w.SetTopmost(False)
        raise RuntimeError(f"未找到会话/联系人: {who}（搜索框已输入该名称但未命中精确匹配，"
                           f"可能群名含 SendKeys 特殊字符或搜索结果未加载，已停止以免发错会话）")
    item.Click()
    time.sleep(0.6)

    # 3) 消息输入框并发送
    edit = w.EditControl(Name="输入")
    if not edit.Exists(3, 0):
        edit = w.EditControl(foundIndex=2)  # 搜索框是第1个 Edit，输入框是第2个
    if not edit.Exists(3, 0):
        w.SetTopmost(False)
        raise RuntimeError("找不到消息输入框，请先 dump_tree 校准控件名")
    edit.SendKeys(text, waitTime=1.0)
    time.sleep(0.3)
    edit.SendKeys("{Enter}")  # 回车发送
    time.sleep(0.5)

    w.SetTopmost(False)
    return {"sent": True, "who": who, "len": len(text)}


if __name__ == "__main__":
    if auto is None:
        sys.exit("✗ uiautomation 未安装。请先：pip install uiautomation（或运行 start_agent.bat）")
    # 本地自测：python driver.py 会打印微信窗口的完整 UI 树
    print(json.dumps(dump_tree({}), ensure_ascii=False, indent=2))
