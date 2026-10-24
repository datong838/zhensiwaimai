#!/usr/bin/env python3
"""WeCom desktop UI sender — AX locate + Quartz input + brief-frontmost discipline.

Channel: local macOS WeCom desktop (com.tencent.WeWorkMac), for the approved
operation group (WeChat external group visible inside WeCom). Official API
routes are all closed for external groups (group bot webhook / intelligent
bot / customer-group broadcast), so UI automation is the only path.

Discipline (SOP hard rule, 2026-10-23, approved by 大同):
  1. Record frontmost app before sending.
  2. Briefly activate WeCom during the send window (navigate -> write -> click
     send), estimated <= 5s.
  3. ALWAYS restore the original frontmost app afterwards — try/finally, no
     exception path may skip it.
  4. Single send attempt; no retry; on failure stop and fall back to the
     Windows gateway (shared ledger prevents double-send).

Verified capabilities (2026-10-23 recon, do not override from memory):
  - AX read: full tree (StaticText/inputs/buttons); occlusion & background OK.
  - AX actions: NONE exposed by WeCom CEF (467 buttons, empty AXActions)
    => AXPress unusable.
  - AXSetValue on input: err=0, readback OK; CEF DOM sync confirmed by
    post-send two-frame readback (末条消息 full text == sent text).
  - Coordinate click: routes to topmost window at that point => must front.
  - Screenshot: screen-recording not granted => CGWindowImage None (no OCR).

Usage:
  python wecom_desktop_sender.py locate --group "<group name>"
  python wecom_desktop_sender.py calibrate --group "<group name>"
  python wecom_desktop_sender.py send --group "<group name>" --text "<text>" [--dry-run]
  python wecom_desktop_sender.py verify --group "<group name>" --text "<text>"

Exit codes: 0 ok / 1 usage / 2 locate-fail / 3 send-fail / 4 verify-fail / 5 env-fail
"""
from __future__ import annotations

import argparse
import atexit
import json
import signal
import os
import re
import subprocess
import sys
import time
from pathlib import Path

from AppKit import NSWorkspace, NSRunningApplication
from ApplicationServices import (
    AXIsProcessTrusted,
    AXUIElementCopyAttributeValue,
    AXUIElementCreateApplication,
    AXUIElementSetAttributeValue,
    AXValueGetValue,
)
import Quartz

BUNDLE = "com.tencent.WeWorkMac"
APP_NAME = "企业微信"
GROUP_DEFAULT = "上海臻肆外卖运营-盯个盯"
ACTIVATE_OPTS = Quartz.kCGEventFlagMaskAlternate  # placeholder, real act via NSRunningApplication
RECEIPT_DIR = Path(__file__).resolve().parent.parent / ".runtime" / "wecom-sender"


# ---------------------------------------------------------------- AX helpers
def ax(el, attr):
    err, v = AXUIElementCopyAttributeValue(el, attr, None)
    return v, err


def ax_pos(el):
    """Return (x, y) screen point of an AX element, or None."""
    raw, err = ax(el, "AXPosition")
    if err or raw is None:
        return None
    try:
        ok, pt = AXValueGetValue(raw, 1, None)  # 1 = kAXValueCGPointType
        return (pt.x, pt.y) if ok else None
    except Exception:
        return None


def ax_size(el):
    raw, err = ax(el, "AXSize")
    if err or raw is None:
        return None
    try:
        ok, sz = AXValueGetValue(raw, 2, None)  # 2 = kAXValueCGSizeType
        return (sz.width, sz.height) if ok else None
    except Exception:
        return None


def find_app():
    for app in NSWorkspace.sharedWorkspace().runningApplications():
        if app.bundleIdentifier() == BUNDLE:
            return app
    return None


def wecom_pid():
    app = find_app()
    return app.processIdentifier() if app else None


def main_window():
    """The MAIN CHAT window only — always the largest AXWindow.

    Hard rule (大同 2026-10-23): one locating method, one target window.
    wins[0] used to float with z-order (settings popups etc.), which could
    point every downstream locator/click at the wrong window — e.g. a hover
    right on the group title. Size-lock to the chat window (1294x781).
    """
    pid = wecom_pid()
    if pid is None:
        return None
    el = AXUIElementCreateApplication(pid)
    wins, err = ax(el, "AXWindows")
    if err or not wins:
        return None
    best, best_area = None, -1
    for w in wins:
        s = ax_size(w)
        if not s:
            continue
        area = s[0] * s[1]
        if area > best_area:
            best, best_area = w, area
    return best


def iter_tree(el):
    """Yield every AX element in the tree (depth-first)."""
    stack = [el]
    seen = 0
    while stack and seen < 20000:
        node = stack.pop()
        seen += 1
        yield node
        kids, err = ax(node, "AXChildren")
        if not err and kids:
            stack.extend(kids)


def iter_controls(el):
    """Search UI controls outside virtual session/message/member tables.

    Editors, the title strip and the search field are siblings of these
    tables. Walking their historical rows costs tens of seconds per pass
    and can also mistake a message's text area for the actual editor.
    """
    stack = [el]
    seen = 0
    while stack and seen < 20000:
        node = stack.pop()
        seen += 1
        role, err = ax(node, 'AXRole')
        if not err and str(role) == 'AXTable':
            continue
        yield node
        kids, err = ax(node, 'AXChildren')
        if not err and kids:
            stack.extend(reversed(kids))


def element_text(el, fast=False):
    if fast:
        v, err = ax(el, "AXValue")
        return str(v).strip() if (not err and v) else ""
    for attr in ("AXValue", "AXTitle", "AXDescription"):
        v, err = ax(el, attr)
        if not err and v:
            s = str(v).strip()
            if s:
                return s
    return ""


# ------------------------------------------------------- group / box locating
def snapshot():
    """One full-tree pass collecting everything needed: group-name hits,
    input-box candidates, and message-tail static texts.

    A single pass is important: after activation the CEF tree has 570+
    elements and every AX call is IPC — multiple passes blow the time budget.
    """
    win = main_window()
    if win is None:
        return None
    group_hits = []
    boxes = []
    statics = []
    for el in iter_tree(win):
        role, err = ax(el, "AXRole")
        if err:
            continue
        role = str(role or "")
        if role in ("AXTextArea", "AXTextField"):
            pos = ax_pos(el)
            size = ax_size(el)
            if pos and size and size[0] > 400 and size[1] > 40:
                boxes.append({"el": el, "pos": pos, "size": size})
        elif role == "AXStaticText":
            v, err2 = ax(el, "AXValue")
            if not err2 and v:
                t = str(v).strip()
                if t:
                    statics.append(t)
                    if GROUP_KEY_DEFAULT in t:
                        group_hits.append({"text": t[:80], "pos": ax_pos(el),
                                           "size": ax_size(el)})
    return {"group_hits": group_hits, "boxes": boxes, "statics": statics,
            "tail": statics[-15:]}


def _win_x():
    win = main_window()
    if win is None:
        return None
    p = ax_pos(win)
    return p[0] if p else None


def _win_y():
    win = main_window()
    if win is None:
        return None
    p = ax_pos(win)
    return p[1] if p else None



# ---------------------------------------------------------------
# 搜索框 vs 群名称：几何实测（2026-10-23 16:05 现场 dump）
#   搜索框  AXTextField x-rel=75  y-rel=15 w=180 h=34  value=''
#   群名称  AXTextField x-rel=326 y-rel=20 w=143 h=24  value='<目标群名>'
# 旧判据 (x-rel<440) 两者全中，且群名称先命中 ⇒ 点群名 = 进入改名状态，
# 随后把目标群名粘进去 = 把当前会话改名（大同两次质问的根因）。
# 收紧为「左栏 + 尺寸特征」，并硬性禁止在标题带做任何点击。
# ---------------------------------------------------------------
SEARCH_BOX_MAX_REL_X = 260      # 左栏；标题/群名在 326 起
TITLE_BAND_REL_X = 260          # x-rel >= 260 且 y-rel <= 120 = 标题/群名带
TITLE_BAND_REL_Y = 120


def find_search_box(win):
    """严格识别左栏顶部搜索框（AXTextField，左栏内，180x34 量级）。"""
    wx, wy = _win_x(), _win_y()
    if wx is None or wy is None:
        return None
    for el in iter_controls(win):
        role, err = ax(el, "AXRole")
        if err or str(role) != "AXTextField":
            continue
        p_, s_ = ax_pos(el), ax_size(el)
        if not p_ or not s_:
            continue
        xr, yr = p_[0] - wx, p_[1] - wy
        # 唯一硬判据 = 不在标题/群名带（群名 x-rel=326 起）。
        # 尺寸区间放宽：下拉浮层弹出时搜索框会被撑宽、CEF 重排后尺寸也会变，
        # 卡死 180x34 会在关键时刻误判（2026-10-23 16:08 实测踩过）。
        if xr < SEARCH_BOX_MAX_REL_X and yr <= 80 and 100 <= s_[0] <= 600 and 16 <= s_[1] <= 60:
            return {"pos": p_, "size": s_, "el": el}
    return None


def search_open_conversation(group_key: str, wait=10.0, type_prefix=None):
    """Open a conversation via the top search box (prefix search).

    Directive 大同 2026-10-23: do NOT needle through the scrollable session
    list — search. Verified flow (screenshot): click search box -> paste
    prefix -> dropdown shows a 群聊 section with the hit (display text may be
    truncated, e.g. "电销 + 直播…", so matching uses the 6-char head) ->
    click the hit -> the conversation opens.

    type_prefix（大同 2026-10-23 21:44 授权）：群名含 💰 等 astral 字符时，
    可传唯一前缀（如"上海臻肆外卖运营-盯个盯-饭敢当"）作为键入词——搜得准；
    标题硬闸仍核对完整群名——验得全。两件事分开，互不降级。

    Fail-closed: 0 hits or >1 distinct hits => Esc and no click. The TITLE
    GATE below is the hard fail-closed identity check: the opened
    conversation's title strip must match the FULL group name, else Esc and
    abort (大同 2026-10-23 21:27：发送前要确定是对的群，对所有工作流生效).
    Returns (ok, detail).
    """
    win = main_window()
    if win is None:
        return False, "no-window"
    wx, wy = _win_x(), _win_y()
    if wx is None or wy is None:
        return False, "no-window-geom"
    query = type_prefix or group_key
    head6 = query[:6]

    # Background WeCom pauses CEF rendering => AX tree can come up empty or
    # half-dead (11 nodes mid-rebuild). Ready = >=100 nodes AND an input
    # element present (2026-10-23: 304 nodes = live, 11 = still rebuilding).
    if not activate_wecom():
        # 2026-10-23 19:05：前台竞争（WorkBuddy/终端持续抢前台）时，单轮激活的
        # 四种手段可能全失败。隔 2s 再来两轮 —— 抢前台是瞬时行为，隔一下常能赢。
        # 仍失败必须返回（绝不带着「不在前台」发任何键）。
        activated = False
        for _ in range(2):
            time.sleep(2.0)
            if activate_wecom():
                activated = True
                break
        if not activated:
            return False, "wecom-not-frontmost"
    tree_ready = False
    for _ in range(12):
        if _tree_nodes(win) >= 100:
            for el in iter_controls(win):
                role, err = ax(el, "AXRole")
                if not err and str(role) in ("AXTextArea", "AXTextField"):
                    tree_ready = True
                    break
        if tree_ready:
            break
        time.sleep(1.0)
    if not tree_ready:
        return False, "ax-tree-empty"

    # 1. the search box —— 严格几何（见 find_search_box 注释）。绝不能用
    #    x-rel<440 这类宽判据：群名称（x-rel=326，可改名 AXTextField）会先
    #    命中，点它即进入改名状态。
    sbox = find_search_box(win)
    if sbox is None:
        return False, "search-box-not-found"

    click_checked(sbox["pos"][0] + 40, sbox["pos"][1] + sbox["size"][1] / 2,
                  "search_box", sbox["pos"])
    time.sleep(0.6)
    if not assert_focus_on(sbox["el"]):
        return False, "focus-not-on-search-before-type"
    press_key(0, Quartz.kCGEventFlagMaskCommand)  # Cmd+A select old query
    time.sleep(0.15)
    press_key(51, 0)                              # Delete
    time.sleep(0.2)
    # 2026-10-23：搜索词也改成「键入」而非粘贴（大同要求输入方式；剪贴板还会
    # 覆盖用户自己的剪贴板）。键入前必须确认真正激活，否则字一个也进不去。
    type_text(query)
    time.sleep(2.4)  # dropdown renders; first 群聊 hit is highlighted by default

    # ★ HARD GATE 2026-10-23 16:0x（大同第三次痛批「你又去改群名字」）：
    # 粘贴后必须回读搜索框内容 == 群名前缀，否则说明击键落到了别处——
    # 最常见是落进当前会话的输入框，接下来那个 Enter 就会把群名当消息发进群
    # （群里多人喊话大同）。fail-closed：Esc 退出，绝不按 Enter。
    # 轮询等待：CEF 重排/下拉浮层渲染期间 AXValue 会滞后 1-3 秒，
    # 单次读空就退出会把「正常的粘贴」误判成失败（16:08 事故）。
    pasted_in_search = False
    seen_value = None
    deadline = time.time() + 8.0
    while time.time() < deadline:
        _sb = find_search_box(win)
        if _sb is not None:
            v, _e = ax(_sb["el"], "AXValue")
            seen_value = v
            if v and head6 in str(v):
                pasted_in_search = True
                break
        time.sleep(0.4)
    if not pasted_in_search:
        # 2026-10-23 19:05 修复（daemon 报 search-paste-missed-no-enter:'' —— 一个字都没落进去）：
        # preflight 只是一次成功快照，preflight 通过后到真正发送之间前台可能被抢
        # （大同在用电脑时必现），此时合成键全被系统丢弃，回读就是空。
        # ⇒ 重新激活 + 重输一次；仍失败才 Esc 放弃（任一分支都绝不按 Enter）。
        if activate_wecom():
            sbox2 = find_search_box(win)
            if sbox2 is not None:
                click_checked(sbox2["pos"][0] + 40,
                              sbox2["pos"][1] + sbox2["size"][1] / 2,
                              "search_box", sbox2["pos"])
                time.sleep(0.5)
                if not assert_focus_on(sbox2["el"]):
                    return False, "focus-not-on-search-before-retry"
                press_key(0, Quartz.kCGEventFlagMaskCommand)
                time.sleep(0.15)
                press_key(51, 0)
                time.sleep(0.2)
                type_text(query)
                retry_deadline = time.time() + 8.0
                while time.time() < retry_deadline:
                    _sb2 = find_search_box(win)
                    if _sb2 is not None:
                        v2, _e2 = ax(_sb2["el"], "AXValue")
                        seen_value = v2
                        if v2 and head6 in str(v2):
                            pasted_in_search = True
                            break
                    time.sleep(0.4)
    if not pasted_in_search:
        press_key(53, 0)  # Esc —— 关闭搜索浮层，绝不 Enter
        return False, "search-type-missed-no-enter:%r" % (str(seen_value or "")[:30],)

    # 2. The dropdown lives in a CEF-private layer NOT reachable via the AX
    #    tree (verified 2026-10-23: app-level AXWindows enumeration also
    #    misses it), so hit-uniqueness cannot be read directly. Instead:
    #    Enter opens the highlighted first hit — caller must pass a prefix
    #    unique across all sessions. The TITLE CHECK below is the hard
    #    fail-closed gate: a wrong conversation is detected and nothing is
    #    ever sent to it.
    press_enter()
    time.sleep(1.4)

    # 3. Behavioral confirmation (the title bar is NOT exposed in the AX tree
    #    — verified 2026-10-23 full-tree scans; only chat-area texts carry the
    #    group name). Opened-conversation evidence = the chat input box
    #    (>400x>40) exists again; while stuck in the search overlay only the
    #    291x18 search box exists. Identity evidence = any tree element with
    #    the group-name head (e.g. the rename system notice in this group).
    opened = locate_input_box() is not None
    if not opened:
        press_key(53, 0)
        return False, "conversation-not-opened"
    # 3. ★★★ HARD FAIL-CLOSED IDENTITY GATE（大同 2026-10-23 21:27 指令：
    #    「发送前要确定是对的群」，且对所有工作流生效，不仅仅是当日台账）。
    #    回读当前会话标题条，必须与目标群名匹配；不匹配一律 Esc 中止 ——
    #    绝不在未确认的会话里落任何键、不粘任何文件。
    #    2026-10-23 21:15 事故：搜索+Enter 打开了错误会话「A欣欣向荣」，
    #    旧软判据（prefix-only / chat-area 扫描）放行，xlsx 文件预览落进了
    #    个人聊天，大同发现后手动撤销。此后身份判据只认标题条。
    title = current_conversation_title(win)
    if not _title_matches_group(title, group_key):
        press_key(53, 0)  # Esc：退出可能的错误会话/搜索态，零发送
        return False, "wrong-conversation:%r" % (str(title)[:40],)
    return True, "chat-title-verified:%r" % (str(title)[:40],)


# Session-list zone: entries sit at the far left of the window. Anything to the
# right of this bound is conversation title / member roster / message body —
# 2026-10-23 live incident: the group-member roster ("盯个盯外卖运营数据分析师-
# Pepo", x≈1279 screen) matched the key and the click never switched sessions,
# so the message went to whichever conversation was already open.
# Session-list area bound (relative to window left edge). Measured 2026-10-23:
# list entries x-rel≈143, conversation TITLE x-rel≈340 (not clickable for
# navigation), chat-area text x-rel≈555. 340 let the title leak in (exact
# boundary <=); 260 splits [143, 340) safely.
SESSION_LIST_MAX_REL_X = 260


def combined_locate(group_key: str):
    """Single early-exit tree pass returning BOTH the session-list entry and
    the message input box. Full snapshot costs ~80s; this costs ~2.4s.

    The input box (first width>400 && height>40 text element) appears before
    the group name in tree order, so both are captured in one pass.

    Matching is restricted to the session-list zone (window-left). Hits are
    collected and must be unique — ambiguous hits fail closed.
    """
    win = main_window()
    if win is None:
        return None, None
    wx = _win_x()
    group = None
    ambiguous = []
    box = None
    for el in iter_tree(win):
        role, err = ax(el, "AXRole")
        if err:
            continue
        role = str(role or "")
        if box is None and role in ("AXTextArea", "AXTextField"):
            pos = ax_pos(el)
            size = ax_size(el)
            if pos and size and size[0] > 400 and size[1] > 40:
                box = {"el": el, "pos": pos, "size": size}
        if group is None or role == "AXStaticText":
            t = element_text(el, fast=True)
            if group_key in t:
                p = ax_pos(el)
                if wx is not None and p and (p[0] - wx) <= SESSION_LIST_MAX_REL_X:
                    if group is None:
                        group = {"text": t[:80], "pos": p, "size": ax_size(el), "el": el}
                    else:
                        ambiguous.append(t[:60])
        if group is not None and box is not None:
            break
    if group is not None and ambiguous:
        raise RuntimeError(f"ambiguous-session-list-match:{len(ambiguous) + 1}")
    return group, box


def _derive_search_prefix(group: str) -> str:
    """为键入词派生 emoji-free 唯一前缀（#105 / 大同 2026-10-24 授权）。

    「临时测试群请忽略 💰发财精英荟💰」与运营群共享后缀「💰发财精英荟💰」，
    全名键入会让 dropdown 群聊区双命中 ⇒ 取第一个 💰（或「发财精英荟」）
    之前的唯一段作键入前缀；标题硬闸仍核对完整群名，安全性不降级。
    不含共享后缀特征的群名返回全名（全名键入无歧义风险）。
    """
    for marker in ('💰', '发财精英荟'):
        i = group.find(marker)
        if i > 0:
            return group[:i].strip()
    return group


GROUP_KEY_DEFAULT = "上海臻肆外卖运营-盯个盯"


def locate_group(group_key: str):
    """Session-list entry matching group_key — x-constrained + ambiguity check.

    Hardened 2026-10-23 (D1): the group name also appears as the conversation
    title (x~438) and inside message history (e.g. rename system notices,
    x~653). First-hit tree order once returned a chat-area match and clicked
    nothing (Pepo incident, 11:08). All send paths must use session-list-area
    matching only; a non-unique match is a hard fail (fail-closed).
    """
    win = main_window()
    if win is None:
        return None
    wx = _win_x()
    hits = []
    for el in iter_tree(win):
        t = element_text(el)
        if group_key not in t:
            continue
        p = ax_pos(el)
        if wx is None or not p or (p[0] - wx) > SESSION_LIST_MAX_REL_X:
            continue
        hits.append({"text": t[:80], "pos": p, "size": ax_size(el), "el": el})
    if not hits:
        return None
    if len(hits) > 1:
        raise RuntimeError(f"ambiguous-session-list-match:{len(hits)}")
    return hits[0]


def locate_input_box():
    """Find the message input box of the currently open conversation.

    WeCom CEF exposes ~570 text elements (search box, chat bubbles, virtual
    list placeholders, ...). Quartz CANNOT see the WeCom main window (it is
    not in the standard CGWindowList), so geometry filtering must use only
    element-local size: the message input is wide (>400px) and tall (>40px).
    Verified 2026-10-23: input = (423,816) 822x88; search box = 180x34.

    ★ 2026-10-23 17:42 修复（险些点错）：树里**不止一个**「宽>400 高>40」的
    AXTextArea —— 群的公告/描述在滚动区里也会命中，且常常排在树序更前、
    坐标为负（滚出窗口，实测 y=-74）。旧实现「取第一个」就会选到它，
    后续点击落在窗口外/描述区。现在：**只在窗口矩形内取 y 最大的那个**
    （消息输入框永远在底部），候选为空则返回 None（fail-closed）。
    """
    win = main_window()
    if win is None:
        return None
    wy, wx = _win_y(), _win_x()
    wh = None
    try:
        wsz = ax_size(win)
        wh = wsz[1] if wsz else None
    except Exception:
        wh = None
    best = None
    for el in iter_controls(win):
        role, err = ax(el, "AXRole")
        if not err and str(role) in ("AXTextArea", "AXTextField"):
            pos = ax_pos(el)
            size = ax_size(el)
            if not (pos and size and size[0] > 400 and size[1] > 40):
                continue
            if wy is not None and wh is not None:
                # 必须在窗口可视区内（排除滚出窗口的公告/描述）
                if not (wy <= pos[1] <= wy + wh - 20):
                    continue
            if best is None or pos[1] > best["pos"][1]:
                best = {"el": el, "pos": pos, "size": size}
    return best


# ------------------------------------------------------------- mouse / front
def ensure_clean_modifiers():
    """Drop any stuck modifier state before a send.

    2026-10-23 incident: a lost Cmd keyup (from earlier Cmd+A/Cmd+V combos)
    left the session-level flags with CMD active, so every synthesized Enter
    reached WeCom as Cmd+Enter = newline. Send silently failed for ~40min.
    Re-posting all modifier keyups is idempotent and cheap.
    """
    try:
        flags = Quartz.CGEventSourceFlagsState(Quartz.kCGEventSourceStateCombinedSessionState)
        stuck = []
        for bit, vk in ((Quartz.kCGEventFlagMaskCommand, 55), (Quartz.kCGEventFlagMaskCommand, 54),
                        (Quartz.kCGEventFlagMaskShift, 56), (Quartz.kCGEventFlagMaskShift, 57),
                        (Quartz.kCGEventFlagMaskControl, 59), (Quartz.kCGEventFlagMaskControl, 58),
                        (Quartz.kCGEventFlagMaskAlternate, 58), (Quartz.kCGEventFlagMaskAlternate, 61)):
            if flags & bit and vk not in stuck:
                stuck.append(vk)
        for vk in stuck:
            e = Quartz.CGEventCreateKeyboardEvent(None, vk, False)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, e)
            time.sleep(0.02)
        return bool(stuck)
    except Exception:
        return False


def assert_focus_on(expected_el) -> bool:
    """Final 大同 directive (2026-10-23): before ANY typed/pasted/entered
    input, the caret MUST be verified to sit on the intended element.
    Reads the app's AXFocusedUIElement and compares it with the target.
    Returns False (caller must abort) when focus is anywhere else — a
    mis-aimed Enter/paste in the rename box or search box is an incident."""
    from ApplicationServices import AXUIElementCreateApplication
    app_el = AXUIElementCreateApplication(wecom_pid())
    focused, err = ax(app_el, "AXFocusedUIElement")
    if err or focused is None:
        return False
    # AX elements don't compare by identity; compare position+role signature
    fp, ep = ax_pos(focused), ax_pos(expected_el)
    if fp is None or ep is None:
        return False
    frole, e1 = ax(focused, "AXRole")
    erole, e2 = ax(expected_el, "AXRole")
    return (fp == ep and str(frole) == str(erole))


def restore_media_input_focus(group):
    """Reacquire the editor after the Office preview sheet closed; no send."""
    if not wecom_is_frontmost() or not _title_matches_group(current_conversation_title(),group):
        return None
    box=locate_input_box()
    if box is None:
        return None
    if not assert_focus_on(box['el']):
        bx,by=box['pos'];bw,bh=box['size']
        click_checked(bx+bw*0.7,by+bh*0.7,'input_box',box['pos'])
        time.sleep(0.3)
    if (not assert_focus_on(box['el']) or not wecom_is_frontmost()
            or not _title_matches_group(current_conversation_title(),group)):
        return None
    return box


# Hard rule (大同 2026-10-23): every click must be AX-located AND verified
# against a declared safe zone BEFORE posting. A stray click on the
# conversation title can RENAME THE GROUP (the 11:00 incident) — coordinate
# guesses near the title / settings areas are forbidden.
SAFE_ZONES = {
    # rel-y bounds relative to the main-window top edge
    "search_box": (0, 110),      # top strip of the left rail
    "input_box": (550, 20000),   # bottom area; input measured at rel-y≈640
    # xlsx/office「发送到聊天」预览 sheet 的动作区（2026-10-23 21:15 实测：
    # 「转为在线表格」rel-y 454、「使用原文件」rel-y 502、右上角关闭钮
    # rel-y 252——全部远低于标题带 rel-y<=120，X 轴也无群名风险）
    "file_sheet": (121, 20000),
}


SAFE_ZONE_X = {
    # rel-x bounds relative to the main-window left edge.
    # 2026-10-23 16:05 现场实测：左栏搜索框 x-rel=75，群名称（可改名
    # AXTextField）x-rel=326。x-rel>=260 且 y-rel<=120 一律视为标题/群名带，
    # 永不点击 —— 两次「群名被改」都是鼠标落进了这个带。
    "search_box": (0, 260),
    "input_box": (0, 20000),
    # sheet 动作区：X 轴不设限（标题带禁点由全局 TITLE_BAND 检查兜底）
    "file_sheet": (0, 20000),
}
TITLE_BAND_X = 260
TITLE_BAND_Y = 120


def click_checked(x, y, zone, anchor_xy):
    """Click only if both the point and its AX anchor sit inside the declared
    safe zone. Fail-closed on any doubt.

    2026-10-23：新增 X 轴约束 + 标题带全局禁点（群名可编辑，点即改名）。
    """
    wy = _win_y()
    wx = _win_x()
    if wy is None or wx is None:
        raise RuntimeError("click-checked:no-window-geometry")
    lo, hi = SAFE_ZONES[zone]
    xlo, xhi = SAFE_ZONE_X[zone]
    rel_y = y - wy
    a_rel_y = anchor_xy[1] - wy
    rel_x = x - wx
    a_rel_x = anchor_xy[0] - wx
    # 标题/群名带：绝对禁区，任何 zone 都不放行
    for lbl, ry, rx in (("anchor", a_rel_y, a_rel_x), ("click", rel_y, rel_x)):
        if rx >= TITLE_BAND_X and ry <= TITLE_BAND_Y:
            raise RuntimeError(f"title-band-forbidden:{lbl}:rel_x={round(rx)}:rel_y={round(ry)}")
    if not (lo <= a_rel_y <= hi):
        raise RuntimeError(f"anchor-outside-safe-zone:{zone}:rel_y={round(a_rel_y)}")
    if not (lo <= rel_y <= hi):
        raise RuntimeError(f"click-outside-safe-zone:{zone}:rel_y={round(rel_y)}")
    if not (xlo <= a_rel_x <= xhi):
        raise RuntimeError(f"anchor-outside-safe-zone-x:{zone}:rel_x={round(a_rel_x)}")
    if not (xlo <= rel_x <= xhi):
        raise RuntimeError(f"click-outside-safe-zone-x:{zone}:rel_x={round(rel_x)}")
    click_at(x, y)


def click_at(x, y):
    ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (x, y), 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    time.sleep(0.05)
    ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseDown, (x, y), 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
    time.sleep(0.03)
    ev = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventLeftMouseUp, (x, y), 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)


def frontmost_app():
    return NSWorkspace.sharedWorkspace().frontmostApplication()


# Global for signal/atexit safety net: the SOP requires frontmost restoration
# on EVERY exit path (including SIGTERM), not only the happy path.
_PREV_FRONT = None


def _restore_frontmost():
    global _PREV_FRONT
    if _PREV_FRONT is not None:
        try:
            _PREV_FRONT.activateWithOptions_(0)
        except Exception:
            pass
        _PREV_FRONT = None


def _signal_restore(signum, frame):
    _restore_frontmost()
    sys.exit(128 + signum)


atexit.register(_restore_frontmost)
signal.signal(signal.SIGTERM, _signal_restore)
signal.signal(signal.SIGINT, _signal_restore)


def wecom_is_frontmost():
    """True only when 企业微信 is REALLY active (NSRunningApplication.isActive).

    ★ 2026-10-23 17:10 定案（本轮所有「键入不进字」的总根因）：
    `NSWorkspace.frontmostApplication()` 在本机不可信 —— 它会把企业微信报成
    前台，而 `NSRunningApplication.isActive()` 明确是 False（真前台还是
    WorkBuddy）。此时合成键全部被丢，一个字符也进不去，回读就像「写不进去」。
    判据必须以 isActive 为准；frontmostApplication 只作辅助记录。

    历史事故：16:45 企微没被真正激活，keystrokes 打进 WorkBuddy 输入框 ——
    群里一条没收到。任何合成键/输入之前必须先过这道硬闸。
    """
    try:
        app = find_app()
        if app is None:
            return False
        return bool(app.isActive())
    except Exception:
        return False


def _raise_main_window():
    """把企微主窗 raise 成 main 窗口 —— 纯 AX API，不移动鼠标、不点任何控件。

    2026-10-23 17:56 实测：企微存在 AXDialog（智能助理提示）与「群管理」子窗
    时，activateWithOptions/osascript 都返回成功但 isActive 恒为 False；
    AXRaise + AXMain=True 后立刻 True。主窗判据=宽度最大（实测 1294>1000>680>320）。
    """
    pid = wecom_pid()
    if not pid:
        return False
    app = AXUIElementCreateApplication(pid)
    wins, err = ax(app, "AXWindows")
    if err or not wins:
        return False
    best, best_w = None, -1.0
    for w in wins:
        size = ax_size(w)
        if size and size[0] > best_w:
            best, best_w = w, size[0]
    if best is None:
        return False
    try:
        from ApplicationServices import AXUIElementPerformAction, AXUIElementSetAttributeValue
        AXUIElementPerformAction(best, "AXRaise")
        AXUIElementSetAttributeValue(best, "AXMain", True)
    except Exception:
        return False
    return True


def _strip_icon_glyphs(s):
    """Drop private-use icon glyphs (e.g. '\\ue050') from AX title strings."""
    return "".join(ch for ch in str(s) if not (0xE000 <= ord(ch) <= 0xF8FF)).strip()


def current_conversation_title(win=None):
    """Title strip of the currently-open conversation, or None.

    Verified 2026-10-23 21:2x by full-tree dump: the title IS exposed in the
    AX tree at x-rel ~326, y-rel ~20 — group chats as AXTextField (the group
    name itself), single chats as AXStaticText (e.g. 'A欣欣向荣\\ue050').
    The earlier comment claiming "title bar is NOT exposed" was WRONG.
    Read-only: AXValue read, no click, no focus change.
    """
    win = win or main_window()
    if win is None:
        return None
    wx, wy = _win_x(), _win_y()
    if wx is None:
        return None
    cands = []
    for el in iter_controls(win):
        p = ax_pos(el)
        if not p:
            continue
        relx, rely = p[0] - wx, p[1] - wy
        if not (280 <= relx <= 440 and 0 <= rely < 40):
            continue
        role, e = ax(el, "AXRole")
        if e or str(role) not in ("AXTextField", "AXStaticText"):
            continue
        v, e2 = ax(el, "AXValue")
        if e2 or not v:
            continue
        t = _strip_icon_glyphs(v)
        if len(t) < 2:
            continue
        # 群描述行（「由微信用户创建的外部群，含45位外部联系人 | 群主: …」）
        # 也在标题带内，必须排除，它不是会话标题。
        if any(k in t for k in ("群主", "外部联系", "内部群", "|", "含")):
            continue
        cands.append((rely, 0 if str(role) == "AXTextField" else 1, t))
    if not cands:
        return None
    cands.sort()
    return cands[0][2]


def _title_matches_group(title, group):
    """Fail-closed title match: True only when the title clearly IS the group.

    大同 2026-10-23 21:27 指令「发送前要确定是对的群」：会话标题必须与目标
    群名互相包含（显示名可能被截断），匹配片段至少 4 字符；绝不用「搜索
    回车开了什么都算过」的软判据。
    """
    t = _strip_icon_glyphs(title or "")
    g = _strip_icon_glyphs(group or "")
    if not t or not g:
        return False
    return t == g


def activate_wecom():
    app = find_app()
    if app is None:
        return False
    # Strong activation: flags=0 is a weak raise that does NOT always wake
    # the CEF AX server (2026-10-23: background tree stayed empty for 10s
    # until activateWithOptions_(IgnoringOtherApps|ActivateAllWindows)).
    app.activateWithOptions_(
        Quartz.NSApplicationActivateIgnoringOtherApps
        | Quartz.NSApplicationActivateAllWindows)
    # 硬闸：激活后必须确认 isActive（真前台），否则返回 False（调用方必须中止，
    # 不得再发任何键 —— 否则键会打到别的应用里）。
    for _ in range(12):
        if wecom_is_frontmost():
            return True
        time.sleep(0.25)
    # 兜底①（2026-10-23 17:56 实测最有效）：AXRaise 主窗 + AXMain=True。
    # 有 AXDialog（如"智能助理"提示气泡）或群管理子窗挡在前面时，
    # activateWithOptions 与 osascript 都返回成功但 isActive 仍为 False；
    # 只有把主窗真正 raise 成 main 才能抢到前台（err=0 且立刻 isActive=True）。
    try:
        _raise_main_window()
    except Exception:
        pass
    for _ in range(12):
        if wecom_is_frontmost():
            return True
        time.sleep(0.25)
    # 兜底②：AppleScript activate —— 实测 rc=0 且 isActive 转 True（2026-10-23 17:09）。
    for _ in range(3):
        try:
            subprocess.run(['osascript', '-e', 'tell application "企业微信" to activate'],
                           capture_output=True, timeout=10)
        except Exception:
            pass
        for _ in range(8):
            if wecom_is_frontmost():
                return True
            time.sleep(0.25)
    # 兜底③（2026-10-23 18:35 实测）：`open -a 企业微信`。
    # 前三种都返回成功但 isActive 仍 False（WorkBuddy 持续抢前台）时，open -a
    # 会在 1-2 秒后生效 —— 注意**有延迟**，上一轮判定完才转 True，
    # 所以这里必须给足等待（20×0.25=5s），否则会误判成激活失败。
    for _ in range(2):
        try:
            subprocess.run(['open', '-a', '企业微信'], capture_output=True, timeout=10)
        except Exception:
            pass
        for _ in range(20):
            if wecom_is_frontmost():
                return True
            time.sleep(0.25)
    return False


def _tree_nodes(win):
    try:
        # The only caller tests >=100; don't enumerate all historical rows.
        count = 0
        for count, _ in enumerate(iter_tree(win), 1):
            if count >= 100:
                return count
        return count
    except Exception:
        return 0


def activate_app(app):
    if app is None:
        return False
    try:
        return app.activateWithOptions_(0)
    except Exception:
        return False


# ------------------------------------------------------------------- actions
# Chat pane x-domain (relative to window left): 2026-10-23 measured chat-area
# elements at rel_x 311-1150; session-list previews sit at rel_x≈241 and the
# member roster at rel_x≈1279. Tree-order "last texts" without this filter
# picks up session-list previews of OTHER conversations (verify false reads).
CHAT_X_MIN, CHAT_X_MAX = 300, 1180


def last_message_texts(limit=8):
    """Read the last static texts of the conversation pane (message tail)."""
    win = main_window()
    if win is None:
        return []
    wx = _win_x()
    texts = []
    for el in iter_tree(win):
        role, err = ax(el, "AXRole")
        if not err and str(role) == "AXStaticText":
            t = element_text(el)
            if t and len(t) >= 2:
                if wx is not None:
                    p = ax_pos(el)
                    if not p or not (CHAT_X_MIN <= p[0] - wx <= CHAT_X_MAX):
                        continue
                texts.append(t)
    return texts[-limit:]


def verify_sent(text: str):
    """Verify send with two cheap signals (full-tree pass costs ~80s on the
    activated CEF tree — 1860 statics × AX IPC — so it is used ONCE):

      frame1: single full-tree snapshot, probe in message tail
      frame2: input box cleared (CEF empties the box after a successful send)

    A second full-tree frame would blow the caller's time budget.
    """
    # 2026-10-23 16:20 修复：snapshot()["tail"] 只回了会话列表最后几行（实测
    # 拿到的是左栏预览），导致消息明明已进群仍判 verify-fail（假失败，
    # 会诱发重复发送）。改为在聊天区 x 域内现场扫描，用前 12 字做锚点。
    probe = text[:12]
    win = main_window()
    t1 = []
    if win is not None:
        wx, wy = _win_x(), _win_y()
        # ★ 必须排除消息输入框区域：输入框本身就在聊天区 x 域内，写入后
        # AXValue 里就是待发文本 —— 不排除就会把「还没发出去」判成已送达
        # （2026-10-23 16:40 事故：2 条未发出的消息被误判 verified）。
        box_now = locate_input_box()
        cut_y = 900
        box_el = None
        if box_now is not None:
            cut_y = box_now["pos"][1] - wy - 12
            box_el = box_now["el"]
        for el in iter_tree(win):
            if box_el is not None and el == box_el:
                continue
            pp, ss = ax_pos(el), ax_size(el)
            if not pp or not ss:
                continue
            xr, yr = pp[0] - wx, pp[1] - wy
            if not (300 <= xr <= 1180 and 0 <= yr <= cut_y):
                continue
            v, _e = ax(el, "AXValue")
            if v and str(v).strip():
                t1.append(str(v))
    hit1 = any(probe in t for t in t1)
    box = locate_input_box()
    cleared = False
    if box is not None:
        v, _ = ax(box["el"], "AXValue")
        cleared = not str(v or "").strip()
    # verified 只认 frame1（消息确实出现在聊天区）——这是送达的硬证据。
    # frame2（输入框已清空）在 CEF 下常滞后/残留，作为辅助信号，不再一票否决：
    # 2026-10-23 16:33 实测 frame1=True 却因 frame2=False 判 verify-fail，
    # 会诱发「明明发出去了又重发」。
    return {"frame1": hit1, "frame2_input_cleared": cleared,
            "verified": bool(hit1), "tail1": t1[-4:]}


def type_text(text: str, gap=0.05):
    """用真实键事件逐字符「键入」文本（绝不走剪贴板）。

    大同硬要求 2026-10-23：「不要复制黏贴，你直接输入的方式」「文字内容也要
    输入的方式」。剪贴板粘贴在 CEF 下还容易把 file-url 和正文顺序搞乱。

    ★ 前置条件：wecom_is_frontmost()（isActive 真前台）必须为真，否则键会
    被系统丢掉，回读就是「一个字符也没进去」。
    ★ 只对已聚焦的目标生效 —— 调用方必须先 click_checked + assert_focus_on。
    """
    # Normalize CRLF/CR before typing; ordinary Return submits a message.
    for ch in text.replace("\r\n", "\n").replace("\r", "\n"):
        if ch == "\n":
            press_key(VK_RETURN, Quartz.kCGEventFlagMaskShift)
            time.sleep(gap)
            continue
        # UTF-16 单元数：代理对（emoji 等 astral 字符，如 💰 U+1F4B0）占 2 个
        # 单元。CGEventKeyboardSetUnicodeString 的第 2 参数要的是 UTF-16
        # 单元数——2026-10-23 修：按 Python len(ch)=1 传会被截成孤立高位代理，
        # 群名里的 💰 全烂掉，搜索匹配随之失败。
        n = len(ch.encode("utf-16-le")) // 2
        d = Quartz.CGEventCreateKeyboardEvent(None, 0, True)
        u = Quartz.CGEventCreateKeyboardEvent(None, 0, False)
        # 显式清空修饰位：万一有残留 Cmd，字母键会变成快捷键（曾把企微 Cmd+Q 关掉）
        Quartz.CGEventSetFlags(d, 0)
        Quartz.CGEventSetFlags(u, 0)
        Quartz.CGEventKeyboardSetUnicodeString(d, n, ch)
        # CEF may commit Unicode on both events; attach text to key-down only.
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, d)
        time.sleep(0.01)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, u)
        time.sleep(gap)


def _norm_text(s: str) -> str:
    return re.sub(r"\s+", "", str(s or ""))


def write_input(text: str, expected_group=None):
    """把正文「键入」到消息输入框：点（受控）→ 焦点闸门 → 清残留 → 逐字键入
    → 回读逐字校验。校验不过就清空重试一次，仍不过则 fail-closed。

    为什么不用 AXSetValue（2026-10-23 血泪）：AXValue 能写进去也能读回来，看起来
    「写成功了」，但 CEF/前端框架不把这段文字登记进编辑器正文模型 —— 回车/⌘↩
    提交时「没有内容可发」，全部静默失败。只有真实键事件才会走编辑器输入路径。
    """
    if expected_group and not _title_matches_group(current_conversation_title(), expected_group):
        return False, "wrong-conversation-before-write"
    if not wecom_is_frontmost():
        return False, "wecom-not-frontmost-before-write"
    box = locate_input_box()
    if box is None:
        return False, "no input box"
    el = box["el"]
    bx, by = box["pos"]
    bw, bh = box["size"]
    click_checked(bx + bw * 0.35, by + bh * 0.5, "input_box", box["pos"])
    time.sleep(0.4)
    if not assert_focus_on(el):
        return False, "focus-not-on-input-after-click"

    detail = ""
    # A multiline input failure must not replay possibly submitted fragments.
    write_attempts = (1,) if "\n" in text or "\r" in text else (1, 2)
    for attempt in write_attempts:
        # 2026-10-23 19:05：第 2 次尝试前若已不在前台，必须先重新激活并重新点输入框。
        # 否则「前台被抢导致键全丢」时，重试同样一个字符都进不去（daemon 实测）。
        if attempt > 1 and not wecom_is_frontmost():
            activate_wecom()
            time.sleep(0.3)
            click_checked(bx + bw * 0.35, by + bh * 0.5, "input_box", box["pos"])
            time.sleep(0.4)
        if expected_group and not _title_matches_group(current_conversation_title(), expected_group):
            return False, "wrong-conversation-before-type"
        if not assert_focus_on(el):
            return False, "focus-not-on-input-before-type"
        # 清残留（上一轮换行残留 / 半截文本）
        press_key(0, Quartz.kCGEventFlagMaskCommand)   # Cmd+A
        time.sleep(0.12)
        press_key(51, 0)                               # Delete
        time.sleep(0.25)
        type_text(text)
        time.sleep(0.6)
        v, _ = ax(el, "AXValue")
        cur = str(v or "")
        if _norm_text(cur) == _norm_text(text):
            return True, (f"pos={box['pos']} attempt={attempt} len={len(cur)} "
                          f"head={cur[:20]!r}")
        detail = (f"attempt={attempt} got_len={len(_norm_text(cur))} "
                  f"want_len={len(_norm_text(text))} head={cur[:20]!r}")
        time.sleep(0.4)
    # 收尾：清空，绝不留半截正文给下一轮/误发
    press_key(0, Quartz.kCGEventFlagMaskCommand)
    time.sleep(0.12)
    press_key(51, 0)
    return False, f"type-not-registered:{detail}"


def click_send(send_xy):
    """Click the send button. send_xy = (x, y) screen point."""
    click_at(send_xy[0], send_xy[1])


def press_key(vk, flags=0):
    """Synthesize a key press (virtual-key code) via Quartz."""
    down = Quartz.CGEventCreateKeyboardEvent(None, vk, True)
    up = Quartz.CGEventCreateKeyboardEvent(None, vk, False)
    Quartz.CGEventSetFlags(down, flags)
    Quartz.CGEventSetFlags(up, 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.03)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


VK_RETURN = 36


def press_enter():
    """Send via Enter key. WeCom default: Enter sends (some setups use
    Ctrl+Enter). If Enter only inserts a newline, caller falls back."""
    if not wecom_is_frontmost():
        raise RuntimeError('wecom-not-frontmost-before-enter')
    ensure_clean_modifiers()
    press_key(VK_RETURN, 0)


def press_ctrl_enter():
    press_key(VK_RETURN, Quartz.kCGEventFlagMaskControl)


def press_cmd_v():
    """Cmd+V via Quartz. pyobjc's CGEventCreateKeyboardEvent takes 3 args;
    the Command flag must be set with CGEventSetFlags AFTER creation.
    Verified 2026-10-23: text paste into the WeCom input works this way."""
    flags = Quartz.kCGEventFlagMaskCommand
    vk_v = 9  # 'v'
    down = Quartz.CGEventCreateKeyboardEvent(None, vk_v, True)
    up = Quartz.CGEventCreateKeyboardEvent(None, vk_v, False)
    Quartz.CGEventSetFlags(down, flags)
    Quartz.CGEventSetFlags(up, 0)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, down)
    time.sleep(0.05)
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, up)


def clipboard_set_png(path: str):
    """Put a PNG file on the clipboard as public.png."""
    from AppKit import NSPasteboard
    from Foundation import NSData
    data = NSData.dataWithContentsOfFile_(path)
    if data is None:
        return False
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    return bool(pb.setData_forType_(data, "public.png"))


def clipboard_set_file(path: str):
    """Put a file on the clipboard as a file-url (paste -> file card)."""
    from AppKit import NSPasteboard, NSURL
    from Foundation import NSArray
    url = NSURL.fileURLWithPath_(path)
    pb = NSPasteboard.generalPasteboard()
    pb.clearContents()
    return bool(pb.writeObjects_(NSArray.arrayWithObject_(url)))


def input_subtree_sig(box):
    """Set of (role, pos, size) for the input-box subtree.

    Paste verification: CEF-rendered previews do NOT expose AXImage — an
    image paste appears as a new AXUnknown ~136x69 at the input position; a
    file paste as AXUnknown ~260x65. Verified 2026-10-23.
    """
    if not box:
        return set()
    sig = set()
    for el in iter_tree(box["el"]):
        role, err = ax(el, "AXRole")
        sig.add((str(role or "?"), ax_pos(el), ax_size(el)))
    sig.add(("BOX", box["pos"], box["size"]))
    return sig


def paste_verify(box_before_sig, expect, source_size=None):
    """After Cmd+V: the input subtree must gain exactly one new element.

    expect: 'image' (new el width 100-200) or 'file' (width 200-400).
    Returns (ok, detail).
    """
    box = locate_input_box()
    sig_after = input_subtree_sig(box)
    new = sig_after - box_before_sig
    new = {n for n in new if n[0] != "BOX"}
    if not new:
        return False, "no new element in input subtree"
    image_previews = []
    for role, pos, size in new:
        w = size[0] if size else 0
        h = size[1] if size else 0
        if (expect == "image" and role in ('AXUnknown', 'AXImage')
                and 8 <= w <= 250 and 8 <= h <= 250 and max(w, h) >= 32
                and source_size and source_size[0] > 0 and source_size[1] > 0
                and abs((w / h) / (source_size[0] / source_size[1]) - 1) <= .20):
            image_previews.append((role, pos, size))
        if expect == "file" and 150 <= w <= 500:
            return True, f"file card {role} {size} @{pos}"
    if len(image_previews) == 1:
        role, pos, size = image_previews[0]
        return True, f"image preview {role} {size} @{pos}"
    return False, f"unexpected new elements: {new}"


# ------------------------------------------------- xlsx/office paste sheet
# 2026-10-23 21:15 实证：xlsx 粘贴后企微不直接把文件挂进输入框，而是弹出
# 「发送到聊天」预览 sheet（AXSheet）：标题 + 「转为在线表格」大按钮 +
# 「使用原文件」小按钮 + 右上角 30×30 关闭钮。文件卡片渲染在输入框子树
# 之外，旧 paste_verify 必然假阴性；且必须点「使用原文件」才会把原文件
# 挂进输入框（点「转为在线表格」会改变交付形态，禁止）。

def _find_ax_sheet(win=None):
    win = win or main_window()
    if win is None:
        return None
    for el in iter_controls(win):
        role, e = ax(el, "AXRole")
        if not e and str(role) == "AXSheet":
            return el
    return None


def _resolve_file_sheet(win=None, before_choice=None):
    """点「使用原文件」把原文件挂进输入框。返回 detail；无 sheet 返回 None。

    只点标题含「使用原文件」的按钮（物理点击，CEF 按钮 AXPress 无效——
    2026-10-23 21:24 实证）。绝不点「转为在线表格」。
    """
    sheet = _find_ax_sheet(win)
    if sheet is None:
        return None
    target = None
    for el in iter_tree(sheet):
        role, e = ax(el, "AXRole")
        if e or str(role) != "AXButton":
            continue
        t, _ = ax(el, "AXTitle")
        if "使用原文件" in str(t or ""):
            target = el
            break
    if target is None:
        return "sheet-without-original-file-button"
    p = ax_pos(target)
    if not p:
        return "sheet-button-no-pos"
    size = ax_size(target)
    if not size or size[0] <= 0 or size[1] <= 0:
        return "sheet-button-no-size"
    if before_choice is not None:
        before_choice()
    click_checked(p[0]+size[0]/2, p[1]+size[1]/2, "file_sheet", p)
    for _ in range(12):
        if _find_ax_sheet(win) is None:
            return "use-original-file-clicked"
        time.sleep(0.25)
    return "sheet-still-open"


def _dismiss_file_sheet(win=None):
    """安全关闭待发送文件预览 sheet：点右上角 20-40px 的无标题按钮（X）。

    用于中止分支的清理——绝不点「转为在线表格」「使用原文件」，也绝不在
    sheet 打开时按 Enter（那会把文件发出去）。
    """
    sheet = _find_ax_sheet(win)
    if sheet is None:
        return "no-sheet"
    wx, wy = _win_x(), _win_y()
    cands = []
    for el in iter_tree(sheet):
        role, e = ax(el, "AXRole")
        if e or str(role) != "AXButton":
            continue
        t, _ = ax(el, "AXTitle")
        if str(t or "").strip():
            continue
        p = ax_pos(el)
        size = ax_size(el)
        if not p or not size:
            continue
        w = size[0]
        if 20 <= w <= 40:
            cands.append((p[1], p[0], p, size))
    if not cands:
        return "no-close-button"
    cands.sort()
    p, size = cands[0][2], cands[0][3]
    click_checked(p[0] + size[0] / 2, p[1] + size[1] / 2, "file_sheet", p)
    return "sheet-closed"


def _file_card_present(path, win=None):
    """文件卡片判据（chat-area 版）：窗口树里出现文件名文本即算挂上。

    2026-10-23 21:15 实证：xlsx 卡片渲染在输入框子树之外（聊天区
    y-rel 256-398），只扫输入框子树会假阴性。
    """
    win = win or main_window()
    if win is None:
        return False, "no-window"
    name = Path(path).name
    for el in iter_tree(win):
        v, e = ax(el, "AXValue")
        if e or not v:
            continue
        s = str(v)
        if name in s or (len(name) >= 8 and name[:12] in s):
            return True, "file-card-text:%r" % s[:40]
    return False, "file-card-not-found"


# ---------------------------------------------------------------------- main
def cmd_locate(args):
    if not AXIsProcessTrusted():
        print("AXIsProcessTrusted=False：辅助功能未授权给本 python 二进制", file=sys.stderr)
        return 5
    pid = wecom_pid()
    if not pid:
        print("企业微信未运行", file=sys.stderr)
        return 5
    g = locate_group(args.group)
    if not g:
        print(f"未定位到群: {args.group}", file=sys.stderr)
        return 2
    print(json.dumps({"pid": pid, "group": g["text"], "pos": g["pos"], "size": g["size"]},
                     ensure_ascii=False))
    return 0


def cmd_calibrate(args):
    """Dump coordinates for: group list item, input box, and candidate send-button anchor."""
    if not AXIsProcessTrusted():
        print("AXIsProcessTrusted=False", file=sys.stderr)
        return 5
    out = {"pid": wecom_pid()}
    g = locate_group(args.group)
    out["group"] = {"text": g["text"], "pos": g["pos"], "size": g["size"]} if g else None
    box = locate_input_box()
    if box is not None:
        bp, bs = box["pos"], box["size"]
        out["input_box"] = {"pos": bp, "size": bs}
        # candidate send anchors (right end of input box); calibrate by eye.
        # WeCom send button sits at the right end of the input box.
        out["send_candidates"] = [
            {"name": "right-mid", "xy": (bp[0] + bs[0] - 25, bp[1] + bs[1] / 2)},
            {"name": "right-inset", "xy": (bp[0] + bs[0] - 60, bp[1] + bs[1] / 2)},
        ]
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def cmd_verify(args):
    if not AXIsProcessTrusted():
        print("AXIsProcessTrusted=False", file=sys.stderr)
        return 5
    r = verify_sent(args.text)
    print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r["verified"] else 4


def cmd_frontmost(args):
    """只读前台探针（零副作用），供 adapter 预检硬闸（大同 2026-10-23 20:00）。

    ★ 预检缺陷修法：旧 preflight 只验「窗口在+登录在」，不验企微是否真前台
    ⇒ 大同同时用电脑时一路走到发送才报 search-paste-missed-no-enter，白走一整轮。
    现在预检第一步先跑本探针：不激活、不点击、不抢焦点，只回答「此刻是否真前台」。
    判据=wecom_is_frontmost()（NSRunningApplication.isActive()，★不是
    frontmostApplication——本机报假前台）；辅助记录对照字段。
    始终 exit 0 + JSON（result 字段承载判定），探针失败不是异常。
    """
    trusted = bool(AXIsProcessTrusted())
    pid = wecom_pid()
    win = main_window() if pid else None
    active = bool(wecom_is_frontmost())
    ws_app = None
    try:
        ws_app = frontmost_app()
    except Exception:
        ws_app = None
    ok = bool(trusted and pid and win is not None and active)
    print(json.dumps({
        "result": "frontmost-ok" if ok else "not-frontmost",
        "axTrusted": trusted,
        "pid": pid,
        "windowFound": win is not None,
        "isActive": active,
        "frontmostApp": (ws_app.localizedName() if ws_app else None),
    }, ensure_ascii=False))
    return 0




def _text_is_group_name(text, group):
    """2026-10-23 事故硬闸（大同 14:55 痛批）：正文绝不允许与目标群名互相包含。

    根因形态：搜索导航的搜索词=群名，若焦点判断错位被粘进聊天输入框，
    随后 Enter 会把群名当消息发出去（已发生，群里多人看到）。
    归一化去空白后双向包含即拒发，fail-closed。
    """
    t = re.sub(r"\s+", "", str(text or ""))
    g = re.sub(r"\s+", "", str(group or ""))
    return bool(t) and bool(g) and (t == g or g in t or t in g)

def cmd_send(args):
    if not AXIsProcessTrusted():
        print("AXIsProcessTrusted=False：辅助功能未授权", file=sys.stderr)
        return 5
    if not wecom_pid():
        print("企业微信未运行", file=sys.stderr)
        return 5

    global _PREV_FRONT
    prev_front = frontmost_app()
    _PREV_FRONT = prev_front  # signal/atexit safety net
    receipt = {"group": args.group, "text": args.text, "dry_run": args.dry_run,
               "modifiers_cleared": ensure_clean_modifiers(),
               "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": []}
    try:
        activated = activate_wecom()
        receipt["wecom_activated"] = bool(activated)
        time.sleep(1.2)  # CEF re-renders AX tree after activation

        # 1. navigate by SEARCH (directive 大同 2026-10-23: no session-list
        # needle-in-haystack). search_open_conversation clicks the unique
        # dropdown hit itself and confirms the title.
        ok_nav, nav_detail = search_open_conversation(
            args.group, type_prefix=args.search_prefix)
        receipt["steps"].append({"navigate": nav_detail})
        if not ok_nav:
            receipt["result"] = f"locate-fail:{nav_detail}"
            print(json.dumps(receipt, ensure_ascii=False))
            return 2
        time.sleep(0.5)

        # ★ HARD GATE（大同 2026-10-23 21:27，对所有工作流生效）：写入输入框
        # 之前再回读一次标题条，错群零副作用中止（纵深防御，导航与落键之间
        # 焦点可能被抢）。
        title_now = current_conversation_title()
        receipt["steps"].append({"title_gate": str(title_now)[:40]})
        if not _title_matches_group(title_now, args.group):
            receipt["result"] = "wrong-conversation-abort"
            print(json.dumps(receipt, ensure_ascii=False))
            return 2

        receipt['resolvedGroup'] = title_now

        # HARD GATE 2026-10-23: payload text must never equal/contain the
        # group name (search-term-pasted-into-input incident, group renamed).
        if _text_is_group_name(args.text, args.group):
            receipt["result"] = "group-name-as-payload-blocked"
            receipt["steps"].append({"hard_gate": "payload==group-name"})
            print(json.dumps(receipt, ensure_ascii=False))
            return 6

        # 2. write input via PASTE (physical click focus -> Cmd+V).
        # AXSetValue alone leaves CEF/React state unsynced for send purposes
        # and a pre-existing caption BLOCKS file-url pasting (2026-10-23),
        # so both text and file go through the clipboard in the right order.
        ok, info = write_input(args.text, expected_group=args.group)
        receipt["steps"].append({"write": ok, "info": info})
        if not ok:
            receipt["result"] = "write-fail"
            print(json.dumps(receipt, ensure_ascii=False))
            return 3

        if args.dry_run:
            # readback only; clear input; DO NOT send
            box = locate_input_box()
            if box is not None:
                AXUIElementSetAttributeValue(box["el"], "AXValue", "")
            receipt["result"] = "dry-run-ok"
            print(json.dumps(receipt, ensure_ascii=False))
            return 0

        # 3. send (enter key by default; click as fallback with --send-xy).
        # Physical click focus first — AXSetValue alone does not move real
        # keyboard focus (2026-10-23: Enter was swallowed, text never sent,
        # same IME/focus issue the media path already solves with a click).
        #
        # ★ LAST HARD GATE（大同 2026-10-23 21:27）：按 Enter 前最后一刻
        # 再核对标题条。错群 ⇒ 清空输入框，绝不发送。
        title_final = current_conversation_title()
        receipt["steps"].append({"title_gate_final": str(title_final)[:40]})
        if not _title_matches_group(title_final, args.group):
            receipt["result"] = "wrong-conversation-before-enter"
            box_f0 = locate_input_box()
            if box_f0 is not None:
                AXUIElementSetAttributeValue(box_f0["el"], "AXValue", "")
                for _ in range(6):
                    press_key(51, 0)
                    time.sleep(0.1)
            print(json.dumps(receipt, ensure_ascii=False))
            return 6
        send_mode = "click" if args.send_xy else "enter"
        if send_mode == "enter":
            box_f = locate_input_box()
            if box_f is not None:
                bx, by = box_f["pos"]
                bw, bh = box_f["size"]
                click_checked(bx + bw * 0.3, by + bh * 0.5, "input_box", box_f["pos"])
                time.sleep(0.4)
                if not assert_focus_on(box_f["el"]):
                    receipt["result"] = "focus-not-on-input-before-enter"
                    print(json.dumps(receipt, ensure_ascii=False))
                    return 3
            press_enter()
            time.sleep(1.0)
            # if Enter did not clear the input (i.e. only inserted a newline),
            # try Ctrl+Enter before giving up
            box_after = locate_input_box()
            still_has = False
            if box_after is not None:
                v, _ = ax(box_after["el"], "AXValue")
                still_has = args.text[:12] in str(v or "")
            receipt["steps"].append({"send_mode": "enter-once",
                                     "send_attempts": [{"try": "enter", "input_clean": not still_has}]})
        else:
            sx, sy = args.send_xy
            click_send((sx, sy))
            receipt["steps"].append({"send_click": [sx, sy]})
        time.sleep(1.2)

        # 4. two-frame verify
        r = verify_sent(args.text)
        receipt["verify"] = r
        receipt["result"] = "verified" if r["verified"] else "verify-fail"
        rc = 0 if r["verified"] else 4

        # 5. post-send cleanup: clear input residue (newline fallback or
        # failed send) so the next message never carries stale text
        box2 = locate_input_box()
        if box2 is not None:
            v2, _ = ax(box2["el"], "AXValue")
            if v2:
                AXUIElementSetAttributeValue(box2["el"], "AXValue", "")
                receipt["input_cleared"] = True
    finally:
        if os.environ.get("WECOM_AUTOSWEEP"):
            # 自主扫描模式：发送后钉住企微前台，不归还焦点（避免被其它 App 抢走
            # 导致后续流 fail-closed）。仅在该环境变量被显式置位时生效，正常人工
            # 发送不受影响。
            try:
                activate_wecom()
            except Exception:
                pass
            receipt["frontmost_restored"] = True
        else:
            activate_app(prev_front)
            receipt["frontmost_restored"] = True

    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    rp = RECEIPT_DIR / f"receipt-{time.strftime('%Y%m%d-%H%M%S')}.json"
    rp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return rc


def cmd_send_media(args, kind):
    """Send image or file (with optional caption text) to the group.

    kind: 'image' | 'file'. Flow: caption text -> physical click focus ->
    Cmd+V (paste preview) -> subtree-diff verify -> Enter -> tail verify ->
    cleanup -> restore frontmost.
    """
    if not AXIsProcessTrusted():
        print("AXIsProcessTrusted=False：辅助功能未授权", file=sys.stderr)
        return 5
    if not wecom_pid():
        print("企业微信未运行", file=sys.stderr)
        return 5
    path = args.image if kind == "image" else args.file
    if not path:
        print(f"send-{kind} 需要 --{kind} <path>", file=sys.stderr)
        return 1
    source_size = None
    if kind == 'image':
        from PIL import Image
        with Image.open(path) as source_image:
            source_size = source_image.size

    global _PREV_FRONT
    prev_front = frontmost_app()
    _PREV_FRONT = prev_front
    receipt = {"kind": kind, "path": path, "group": args.group,
               "text": args.text, "ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "steps": [],
               "modifiers_cleared": ensure_clean_modifiers()}
    try:
        activated = activate_wecom()
        receipt["wecom_activated"] = bool(activated)
        time.sleep(1.2)

        # navigate by SEARCH (directive 大同 2026-10-23). The unique dropdown
        # hit is clicked inside search_open_conversation.
        ok_nav, nav_detail = search_open_conversation(
            args.group, type_prefix=args.search_prefix)
        receipt["steps"].append({"navigate": nav_detail})
        if not ok_nav:
            receipt["result"] = f"locate-fail:{nav_detail}"
            print(json.dumps(receipt, ensure_ascii=False))
            return 2
        time.sleep(0.5)

        # ★ HARD GATE（大同 2026-10-23 21:27，对所有工作流生效）：导航成功后
        # 落任何键/粘任何文件之前，再回读一次标题条。导航与粘贴之间焦点可能
        # 被抢、会话可能被切换——这一层是纵深防御，错群零副作用中止。
        title_now = current_conversation_title()
        receipt["steps"].append({"title_gate": str(title_now)[:40]})
        if not _title_matches_group(title_now, args.group):
            receipt["result"] = "wrong-conversation-abort"
            print(json.dumps(receipt, ensure_ascii=False))
            return 2

        # clipboard（放在身份闸之后：群没认对就绝不碰剪贴板）
        if kind == "image":
            cb_ok = clipboard_set_png(path)
        else:
            cb_ok = clipboard_set_file(path)
        receipt["clipboard"] = bool(cb_ok)
        if not cb_ok:
            receipt["result"] = "clipboard-fail"
            print(json.dumps(receipt, ensure_ascii=False))
            return 3

        # 2. paste the media FIRST on an empty input box (2026-10-23: a
        # pre-existing caption blocks file-url pasting; writing text via
        # AXSetValue after the paste drops the preview). Caption is appended
        # afterwards via clipboard paste, which coexists with the preview.
        # After search navigation CEF is still re-rendering — settle, and the
        # paste itself retries once (retry has no external side effect; the
        # send key is pressed only after a confirmed preview).
        time.sleep(2.0)
        paste_ok, detail = False, "no-input-box"
        sheet_detail = None
        for paste_try in range(2):
            box = locate_input_box()
            if box is None:
                time.sleep(1.5)
                continue
            if paste_try == 1:
                # clear any partial residue from the failed first attempt
                AXUIElementSetAttributeValue(box["el"], "AXValue", "")
                time.sleep(0.4)
            sig_before = input_subtree_sig(box)
            bx, by = box["pos"]
            bw, bh = box["size"]
            click_checked(bx + bw * 0.3, by + bh * 0.5, "input_box", box["pos"])
            time.sleep(0.4)
            if not assert_focus_on(box["el"]):
                detail = "focus-not-on-input-before-paste"
                continue
            press_cmd_v()
            time.sleep(2.0)
            # xlsx/office 文件粘贴后弹出「发送到聊天」预览 sheet：先点
            # 「使用原文件」把原文件挂进输入框，再验卡片（2026-10-23 21:15
            # 实证：卡片在输入框子树之外，只扫子树必假阴性）。
            sheet_detail = _resolve_file_sheet(before_choice=lambda: receipt["steps"].append({"office_choice_attempted": True}))
            if sheet_detail:
                receipt["steps"].append({"file_sheet": sheet_detail})
                time.sleep(1.2)
                if sheet_detail != "use-original-file-clicked":
                    receipt["result"] = "paste-fail"
                    receipt["steps"].append({"sheet_cleanup": _dismiss_file_sheet()})
                    print(json.dumps(receipt, ensure_ascii=False))
                    return 3
            paste_ok, detail = paste_verify(sig_before, kind, source_size)
            if not paste_ok and kind == "file":
                paste_ok, detail = _file_card_present(path)
            if paste_ok:
                break
        if not paste_ok:
            receipt["steps"].append({"paste": False, "detail": detail})
            receipt["result"] = "paste-fail"
            # 清理：若 xlsx 预览 sheet 开着，先点它的 X 安全关闭（绝不点
            # 「使用原文件/转为在线表格」），再清输入框——绝不在 sheet
            # 打开状态按 Enter。
            receipt["steps"].append({"sheet_cleanup": _dismiss_file_sheet()})
            box2 = locate_input_box()
            if box2 is not None:
                AXUIElementSetAttributeValue(box2["el"], "AXValue", "")
                for _ in range(6):
                    press_key(51, 0)
                    time.sleep(0.1)
            print(json.dumps(receipt, ensure_ascii=False))
            return 3
        receipt["steps"].append({"paste": True, "try": paste_try + 1})

        # HARD GATE 2026-10-23: caption must never equal/contain group name.
        if args.text and _text_is_group_name(args.text, args.group):
            receipt["result"] = "group-name-as-payload-blocked"
            receipt["steps"].append({"hard_gate": "caption==group-name"})
            print(json.dumps(receipt, ensure_ascii=False))
            return 6

        # 2b. append caption AFTER the media paste (clipboard paste keeps the
        # preview alive; AXSetValue would replace it with plain text).
        if args.text:
            subprocess.run(["pbcopy"], input=args.text.encode("utf-8"), check=True)
            press_cmd_v()
            time.sleep(1.0)
            box_t = locate_input_box()
            cap_ok = False
            if box_t is not None:
                v, _ = ax(box_t["el"], "AXValue")
                cap_ok = args.text[:16] in str(v or "")
            receipt["steps"].append({"caption_paste": cap_ok})
            if not cap_ok:
                receipt["result"] = "caption-paste-fail"
                print(json.dumps(receipt, ensure_ascii=False))
                return 3

        # send with IME-aware fallback chain. Enter is swallowed by an active
        # Chinese IME (physical click activates the IME; AXSetValue alone
        # does not). Chain: Enter -> Ctrl+Enter -> Esc(close IME compose)+Enter.
        # Success criterion: input subtree returns to baseline (preview gone).
        #
        # ★ LAST HARD GATE（大同 2026-10-23 21:27）：按 Enter 前最后一刻
        # 再核对标题条。错群 ⇒ 清空输入/关 sheet，绝不发送。
        title_final = current_conversation_title()
        receipt["steps"].append({"title_gate_final": str(title_final)[:40]})
        if not _title_matches_group(title_final, args.group):
            receipt["result"] = "wrong-conversation-before-enter"
            receipt["steps"].append({"sheet_cleanup": _dismiss_file_sheet()})
            box2 = locate_input_box()
            if box2 is not None:
                AXUIElementSetAttributeValue(box2["el"], "AXValue", "")
                for _ in range(6):
                    press_key(51, 0)
                    time.sleep(0.1)
            print(json.dumps(receipt, ensure_ascii=False))
            return 6
        box_final = restore_media_input_focus(args.group)
        if box_final is None:
            receipt["result"] = "focus-not-on-input-before-enter"
            print(json.dumps(receipt, ensure_ascii=False))
            return 3
        box = box_final
        baseline = {("AXTextArea", box["pos"], box["size"]), ("BOX", box["pos"], box["size"])}
        sent = False
        attempts = []
        for label, fn in (("enter", press_enter),):
            if label == "esc-enter":
                press_key(53, 0)  # Esc: dismiss IME compose state
                time.sleep(0.2)
                press_enter()
            else:
                fn()
            time.sleep(1.5)
            box_now = locate_input_box()
            sig_now = input_subtree_sig(box_now)
            clean = not (sig_now - baseline)
            attempts.append({"try": label, "input_clean": clean})
            if clean:
                sent = True
                break
        receipt["steps"].append({"send_attempts": attempts, "sent": sent})
        if not sent:
            receipt["result"] = "send-fail"
            # A send key was issued. Preserve the preview and report unknown
            # through the adapter; never clear or press another send key here.
            print(json.dumps(receipt, ensure_ascii=False))
            return 3

        # tail verify: media messages render in the CEF tree as sender-prefixed
        # media markers ("xx: [图片]" / "xx: [文件]") — the caption text is NOT a
        # standalone static text, so probing only the caption always misses
        # (2026-10-23 02:54 receipt: paste ok + input_clean ok but verify-fail).
        # Primary success criterion = `sent` (input subtree back to baseline).
        # Tail hit (caption OR media marker OR filename) is corroboration only;
        # a miss must NOT downgrade the outcome nor trigger a resend
        # (attempted semantics, same discipline as the Windows bridge).
        probes = []
        if args.text:
            probes.append(args.text[:24])
        probes.append("[图片]" if kind == "image" else "[文件]")
        probes.append(Path(path).name[:20])
        r = verify_sent(probes[0])
        t1 = r.get("tail1") or []
        tail_hit = any(any(p in t for t in t1) for p in probes)
        media_marker_hit = any(("[图片]" if kind == "image" else "[文件]") in t for t in t1)
        receipt["verify"] = {"tail_hit": tail_hit, "media_marker_hit": media_marker_hit,
                             "sent": sent, "tail1": t1[-4:]}
        if sent and tail_hit:
            receipt["result"] = "verified"
            rc = 0
        elif sent:
            # strong local criterion passed but tail snapshot inconclusive
            # (tree lag / marker rendering). Never resend on this branch.
            receipt["result"] = "sent-tail-unconfirmed"
            rc = 0
        else:
            receipt["result"] = "send-fail"
            rc = 3

        # cleanup residue
        box2 = locate_input_box()
        if box2 is not None:
            v2, _ = ax(box2["el"], "AXValue")
            if v2:
                AXUIElementSetAttributeValue(box2["el"], "AXValue", "")
    finally:
        if os.environ.get("WECOM_AUTOSWEEP"):
            # 自主扫描模式：发送后钉住企微前台，不归还焦点（避免被其它 App 抢走
            # 导致后续流 fail-closed）。仅在该环境变量被显式置位时生效，正常人工
            # 发送不受影响。
            try:
                activate_wecom()
            except Exception:
                pass
            receipt["frontmost_restored"] = True
        else:
            activate_app(prev_front)
            receipt["frontmost_restored"] = True

    RECEIPT_DIR.mkdir(parents=True, exist_ok=True)
    rp = RECEIPT_DIR / f"receipt-{time.strftime('%Y%m%d-%H%M%S')}.json"
    rp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(receipt, ensure_ascii=False))
    return rc



def file_card_matches(item, text):
    import re
    match = re.fullmatch(re.escape(item['name']) + r"\s+([0-9]+(?:\.[0-9]+)?)\s*([KMG]?)B?", text.strip(), re.I)
    if not match:
        return False
    scale = {'': 1, 'K': 1024, 'M': 1024**2, 'G': 1024**3}[match[2].upper()]
    return abs(float(match[1]) * scale - item['size']) < scale


def visible_file_cards(not_before=None):
    import re
    win = main_window()
    wx = _win_x()
    if win is None or wx is None:
        return []
    cards = []
    rows = []
    stack = [win]
    while stack:
        node = stack.pop()
        role, error = ax(node, 'AXRole')
        if not error and str(role) == 'AXTable':
            pos, size = ax_pos(node), ax_size(node)
            if pos and size and CHAT_X_MIN <= pos[0]-wx <= CHAT_X_MAX and size[0] > 400:
                children, err = ax(node, 'AXChildren')
                if not err and children:
                    rows.extend(children)
            continue
        children, err = ax(node, 'AXChildren')
        if not err and children:
            stack.extend(children)
    inherited_times = set()
    for row in rows:
        values = set()
        in_chat = False
        for el in iter_tree(row):
            for attr in ('AXValue', 'AXTitle', 'AXDescription', 'AXHelp'):
                value, error = ax(el, attr)
                if not error and value:
                    text = str(value).strip()
                    values.add(text)
                    if '.xlsx' in text:
                        pos = ax_pos(el)
                        if pos and CHAT_X_MIN <= pos[0] - wx <= CHAT_X_MAX:
                            in_chat = True
        if not_before is not None:
            from datetime import datetime
            from zoneinfo import ZoneInfo
            start=datetime.fromtimestamp(not_before,ZoneInfo('Asia/Shanghai'))
            expected={(start.hour*60+start.minute+offset)%(24*60) for offset in range(-5,3)}
            observed=set()
            for value in values:
                match=re.fullmatch(r'(上午|下午)?\s*([0-9]{1,2}):([0-9]{2})',value)
                if match:
                    hour=int(match[2]);hour=(hour%12+12) if match[1]=='下午' else hour%12 if match[1]=='上午' else hour
                    observed.add(hour*60+int(match[3]))
            if observed:
                inherited_times = observed
            if not expected.intersection(observed or inherited_times):
                continue
        if not in_chat:
            continue
        full = [v for v in values if re.fullmatch(r'.+\.xlsx\s+[0-9.]+\s*[KMG]B?',v,re.I)]
        if len(full) == 1:
            cards.append(full[0])
            continue
        names = [v for v in values if v.endswith('.xlsx')]
        sizes = [v for v in values if re.fullmatch(r'[0-9]+(?:\.[0-9]+)?\s*[KMG]B?',v,re.I)]
        if len(names) == 1 and len(sizes) == 1:
            cards.append(names[0]+' '+sizes[0])
        elif names:
            cards.append('UNRESOLVED '+repr(sorted(values)))
    return cards


def cmd_verify_file(args):
    import hashlib
    path = Path(args.file)
    item = {'name': path.name, 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    frames = []
    for _ in range(2):
        title = current_conversation_title()
        cards = visible_file_cards(getattr(args, "sent_after_unix", None))
        matches = [text for text in cards if file_card_matches(item, text)]
        box = locate_input_box()
        value = ax(box['el'], 'AXValue')[0] if box else None
        frames.append({'groupTitle': title, 'matches': matches,
                       'inputEmpty': box is not None and not value,
                       'candidateCards': [c for c in cards if item['name'] in c],
                       'verified': _title_matches_group(title, args.group) and len(matches) == 1
                                   and box is not None and not value})
    result = {'result': 'verified' if all(f['verified'] for f in frames) else 'not-verified',
              'sendAttempts': 0, 'resolvedGroup': args.group, 'item': item,
              'verificationLevel': 'file-name-size-ui', 'frames': frames}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result['result'] == 'verified' else 1


def ui_tree_only_blocks(command, policy=None):
    policy = Path(policy) if policy is not None else Path(__file__).resolve().parent.parent / '.runtime/UI_TREE_ONLY.json'
    return command in ('send', 'send-image', 'send-file') and policy.exists()


def main():
    p = argparse.ArgumentParser(description="WeCom desktop UI sender")
    p.add_argument("cmd", choices=["locate", "calibrate", "verify", "frontmost", "send",
                                   "send-image", "send-file", "verify-file"])
    p.add_argument("--group", default=GROUP_DEFAULT)
    p.add_argument("--search-prefix", default=None,
                   help="optional emoji-free unique prefix to TYPE into the search box; the title gate still verifies the full --group name")
    p.add_argument("--text", default="")
    p.add_argument("--send-xy", default=None, help="x,y screen point of send button")
    p.add_argument("--image", default=None, help="PNG path for send-image")
    p.add_argument("--file", default=None, help="file path for send-file")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--sent-after-unix", type=float)
    args = p.parse_args()
    if ui_tree_only_blocks(args.cmd):
        print(json.dumps({'result': 'ui-tree-only-required', 'status': 'blocked',
                          'sendAttempts': 0, 'sent': False,
                          'reason': 'user-requires-visible-ui-tree-actions'}, ensure_ascii=False))
        return 2
    if args.send_xy:
        args.send_xy = tuple(float(v) for v in args.send_xy.split(","))

    # 2026-10-23 测试群覆盖（fail-safe 单点翻转）：设置 WECHAT_TEST_GROUP 后，本发送器
    # 把「所有流的落群」强制重定向到该测试群（locate/send/send-image/send-file 全部生效），
    # 不设则保持各流写死的正式群。用于「逐流跑测试群→验证→切回正式群」流程：
    # 误设只会错发测试群、绝不会错发生产群（生产群名从不出现在目标里），可随时 unset 复原。
    _test_group = os.environ.get("WECHAT_TEST_GROUP", "").strip()
    if _test_group:
        print(f"[WECHAT_TEST_GROUP OVERRIDE] 落群被强制重定向到测试群: {_test_group!r}（原 {args.group!r}）",
              file=sys.stderr)
        args.group = _test_group
        if not args.search_prefix:
            args.search_prefix = _derive_search_prefix(_test_group)
            print(f"[WECHAT_TEST_GROUP] 派生键入前缀: {args.search_prefix!r}（防共享后缀误命中）",
                  file=sys.stderr)

    if args.cmd == "verify-file":
        return cmd_verify_file(args)
    if args.cmd == "locate":
        return cmd_locate(args)
    if args.cmd == "calibrate":
        return cmd_calibrate(args)
    if args.cmd == "frontmost":
        return cmd_frontmost(args)
    if args.cmd == "verify":
        if not args.text:
            print("verify 需要 --text", file=sys.stderr)
            return 1
        return cmd_verify(args)
    if args.cmd == "send":
        if not args.text:
            print("send 需要 --text", file=sys.stderr)
            return 1
        return cmd_send(args)
    if args.cmd == "send-image":
        return cmd_send_media(args, "image")
    if args.cmd == "send-file":
        return cmd_send_media(args, "file")
    return 1


if __name__ == "__main__":
    sys.exit(main())
