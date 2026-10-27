#!/usr/bin/env python3
"""Legacy desktop Chrome bridge for offline comparison only.

当前默认采集器固定连接后台专用 Chrome ``taobao-agent-service:9231``，并按游标日期至
今天的闭区间完成分页采集。本模块保留旧前台 AX/OCR 路径用于历史兼容，不得作为默认
路径，也不得在后台专用 Chrome 失败后自动回退。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

import Quartz

OCR_BIN = Path(
    "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/"
    "daily-top10-to-wechat-group/scripts/ocr_vision"
)
CG_CLICK = Path(
    "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/"
    "daily-top10-to-wechat-group/scripts/cg_click.py"
)
PHONE_VENV = Path("/Users/ddt/work/projects/ai_agent/.venvs/harmonyos3-phone-control/bin/python")
BASE_HOME = "https://open.shop.ele.me/manager/base/home"
MENU_INTENTION = "意向商户管理"
STATE_DIR = Path(
    "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/state/taobao-agent-new-merchants"
)
DEFAULT_RECEIPT = Path("/tmp/zhensi_agent_merchants/collection_receipt.json")
SHOT = Path("/tmp/zhensi-agent-bridge.png")
OPTS = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements


class BridgeError(RuntimeError):
    pass


def today_shanghai() -> str:
    return subprocess.check_output(
        ["bash", "-lc", "TZ=Asia/Shanghai date +%F"], text=True
    ).strip()


def cursor_file_for_group(group_name: str) -> Path:
    if group_name == "电销+直播攻坚组":
        return STATE_DIR / "cursor.json"
    if group_name == "FEIBING NEO AI数字员工":
        return STATE_DIR / "cursor.test.json"
    raise BridgeError(f"unsupported-group:{group_name}")


def run_osascript(script: str) -> str:
    return subprocess.check_output(["osascript", "-e", script], text=True).strip()


def declutter_overlays() -> None:
    """D1: move WeChat/WeCom/AOS dedicated Chrome aside; raise service window."""
    run_osascript(
        """
tell application "System Events"
  repeat with pname in {"微信", "企业微信", "WeChat"}
    if exists process (pname as text) then
      tell process (pname as text)
        repeat with w in windows
          try
            set position of w to {1750, 40}
            set size of w to {420, 300}
          end try
        end repeat
      end tell
    end if
  end repeat
  repeat with p in (every process whose name is "Google Chrome")
    tell p
      repeat with w in windows
        try
          set t to name of w as text
          if t contains "第三方" then
            set position of w to {1750, 40}
            set size of w to {420, 280}
          end if
        end try
      end repeat
    end tell
  end repeat
end tell
"""
    )


def seize_service_chrome() -> None:
    """D2: activate Chrome and raise 淘宝闪购服务商平台."""
    declutter_overlays()
    run_osascript(
        """
tell application "Google Chrome" to activate
tell application "System Events"
  repeat with p in (every process whose name is "Google Chrome")
    tell p
      set frontmost to true
      repeat with w in windows
        try
          set t to name of w as text
          if t contains "淘宝闪购" then
            set value of attribute "AXMinimized" of w to false
            set position of w to {0, 25}
            perform action "AXRaise" of w
          end if
        end try
      end repeat
    end tell
  end repeat
end tell
"""
    )
    time.sleep(0.35)


def service_window() -> dict:
    wins = [
        w
        for w in Quartz.CGWindowListCopyWindowInfo(OPTS, Quartz.kCGNullWindowID)
        if w.get("kCGWindowOwnerName") == "Google Chrome" and w.get("kCGWindowLayer", 0) == 0
    ]
    preferred = [w for w in wins if "淘宝闪购服务商" in (w.get("kCGWindowName") or "")]
    if not preferred:
        raise BridgeError("service-window-missing")
    target = preferred[0]
    bounds = dict(target["kCGWindowBounds"])
    for w in wins:
        name = w.get("kCGWindowName") or ""
        if "淘宝闪购服务商" in name:
            continue
        ob = w.get("kCGWindowBounds") or {}
        if (
            abs(ob.get("X", -999) - bounds["X"]) < 8
            and abs(ob.get("Y", -999) - bounds["Y"]) < 8
            and abs(ob.get("Width", 0) - bounds["Width"]) < 24
        ):
            raise BridgeError(f"overlay-still-present:{name}")
    return {
        "id": int(target["kCGWindowNumber"]),
        "bounds": bounds,
        "name": target.get("kCGWindowName") or "",
        "pid": int(target["kCGWindowOwnerPID"]),
    }


def capture_service(shot: Path = SHOT) -> dict:
    seize_service_chrome()
    window = service_window()
    subprocess.check_call(["/usr/sbin/screencapture", "-x", "-l", str(window["id"]), str(shot)])
    return window


def image_size(shot: Path) -> tuple[int, int]:
    meta = subprocess.check_output(
        ["/usr/bin/sips", "-g", "pixelWidth", "-g", "pixelHeight", str(shot)], text=True
    )
    return (
        int(re.search(r"pixelWidth:\s*(\d+)", meta).group(1)),
        int(re.search(r"pixelHeight:\s*(\d+)", meta).group(1)),
    )


def ocr_entries(shot: Path = SHOT) -> list[dict]:
    out = subprocess.check_output([str(OCR_BIN), str(shot), "zh-Hans"], text=True)
    entries = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        x, y, w, h = map(float, parts[0].split(","))
        entries.append({"x": x, "y": y, "w": w, "h": h, "text": "\t".join(parts[2:]).strip()})
    return entries


def to_screen(entry: dict, bounds: dict, iw: int, ih: int, frac=(0.5, 0.5)) -> tuple[float, float]:
    x = entry["x"] + entry["w"] * frac[0]
    y = entry["y"] + entry["h"] * frac[1]
    return (
        bounds["X"] + x / (iw / bounds["Width"]),
        bounds["Y"] + y / (ih / bounds["Height"]),
    )


def click_xy(sx: float, sy: float) -> None:
    seize_service_chrome()
    subprocess.check_call([str(PHONE_VENV), str(CG_CLICK), str(sx), str(sy)])


def ax_click_label(label: str) -> bool:
    """D3: System Events AX click by exact value/name."""
    seize_service_chrome()
    result = run_osascript(
        f"""
tell application "Google Chrome" to activate
delay 0.15
tell application "System Events"
  tell process "Google Chrome"
    set frontmost to true
    try
      set els to entire contents of window 1
      repeat with el in els
        set v to ""
        try
          set v to value of el as text
        end try
        if v is "" then
          try
            set v to name of el as text
          end try
        end if
        if v is "{label}" then
          click el
          return "ok"
        end if
      end repeat
    end try
  end tell
end tell
return "miss"
"""
    )
    return result == "ok"


def intention_list_open(entries: list[dict]) -> bool:
    """D3: title OCR 或 待处理+详情 兜底."""
    texts = [e["text"] for e in entries]
    joined = "\n".join(texts)
    has_menu = any(e.replace(" ", "") == MENU_INTENTION for e in texts)
    if not has_menu:
        return False
    if "商家意向列表" in joined:
        return True
    return any("待处理" in t for t in texts) and any("详情" in t for t in texts)


def focus_existing_open_shop_tab(*, reload_entry: bool = False) -> str:
    """附着已有 Chrome 会话中的 open.shop 标签；默认不重载、不新开窗。

    - 禁止启动/重启 Chrome 进程。
    - 禁止 make new window / make new tab（缺标签直接失败，由人打开已登录页）。
    - reload_entry=False：只激活已有 open.shop 标签，保留 SPA 状态。
    - reload_entry=True：仅在该已有标签上导航到 base/home（仍不新开浏览器）。
    """
    seize_service_chrome()
    # 先确认服务商窗已在：没有就停，绝不另起浏览器。
    service_window()
    script = f"""
tell application "Google Chrome"
  activate
  set hit to false
  set wi to 1
  set foundUrl to ""
  repeat with w in windows
    set ti to 1
    repeat with t in tabs of w
      set u to URL of t as text
      if u contains "open.shop.ele.me" then
        set active tab index of window wi to ti
        set index of window wi to 1
        if {str(reload_entry).lower()} then
          set URL of t to "{BASE_HOME}"
          delay 1.2
        end if
        set foundUrl to URL of t as text
        set hit to true
        exit repeat
      end if
      set ti to ti + 1
    end repeat
    if hit then exit repeat
    set wi to wi + 1
  end repeat
  if not hit then
    error "existing-open-shop-tab-missing"
  end if
  return foundUrl
end tell
"""
    try:
        return run_osascript(script)
    except subprocess.CalledProcessError as error:
        raise BridgeError(
            "existing-browser-required:需要已打开并登录的淘宝闪购服务商标签页"
            "（open.shop.ele.me），禁止自动新开浏览器"
        ) from error


def click_sidebar_by_ocr(label: str) -> None:
    window = capture_service()
    entries = ocr_entries()
    iw, ih = image_size(SHOT)
    bounds = window["bounds"]
    exact = [
        e
        for e in entries
        if e["text"].replace(" ", "") == label.replace(" ", "") and e["x"] < iw * 0.45
    ]
    if len(exact) > 1:
        left = min(e["x"] for e in exact)
        exact = [e for e in exact if abs(e["x"] - left) < 40]
    if len(exact) != 1:
        raise BridgeError(f"sidebar-ocr-count:{label}:{len(exact)}")
    sx, sy = to_screen(exact[0], bounds, iw, ih, frac=(0.5, 0.5))
    click_xy(sx, sy)


def _legacy_open_intention_page(*, reload_entry: bool = False) -> dict:
    """使用已存在的服务商 Chrome 窗；已在意向列表则零导航。"""
    seize_service_chrome()
    window = capture_service()
    entries = ocr_entries()
    if intention_list_open(entries):
        return {
            "ok": True,
            "alreadyOpen": True,
            "reloaded": False,
            "window": window["name"],
        }

    # 未在列表：只聚焦已有 open.shop 标签，默认不整页重载。
    url = focus_existing_open_shop_tab(reload_entry=reload_entry)
    time.sleep(0.8 if not reload_entry else 1.5)
    window = capture_service()
    entries = ocr_entries()
    if intention_list_open(entries):
        return {
            "ok": True,
            "alreadyOpen": True,
            "reloaded": reload_entry,
            "activeUrl": url,
            "window": window["name"],
        }

    if not ax_click_label(MENU_INTENTION):
        intention_visible = any(
            e["text"].replace(" ", "") == MENU_INTENTION and e["x"] < 1200 for e in entries
        )
        labels = [MENU_INTENTION] if intention_visible else ["代运营", "客户管理", MENU_INTENTION]
        for label in labels:
            try:
                if not ax_click_label(label):
                    click_sidebar_by_ocr(label)
            except BridgeError:
                if label == MENU_INTENTION:
                    raise
            time.sleep(1.4)
    else:
        time.sleep(1.8)
    window = capture_service()
    entries = ocr_entries()
    if not intention_list_open(entries):
        raise BridgeError("intention-merchant-page-not-open")
    return {
        "ok": True,
        "alreadyOpen": False,
        "reloaded": reload_entry,
        "activeUrl": url,
        "window": window["name"],
    }


def open_intention_page(*, reload_entry: bool = False) -> dict:
    if reload_entry:
        return _legacy_open_intention_page(reload_entry=True)
    from native_service_ui import navigate
    result = navigate()
    if not result['ok']:
        raise BridgeError(result.get('error', 'structured-navigation-failed'))
    return result


def reveal_date_filters() -> None:
    """D4: bring 开始日期 into view."""
    window = capture_service()
    entries = ocr_entries()
    if any("开始日期" in e["text"] for e in entries):
        return
    bounds = window["bounds"]
    click_xy(bounds["X"] + bounds["Width"] * 0.45, bounds["Y"] + bounds["Height"] * 0.35)
    time.sleep(0.15)
    for _ in range(6):
        run_osascript('tell application "System Events" to key code 116')
        time.sleep(0.12)
    run_osascript('tell application "System Events" to key code 115')
    time.sleep(0.35)


def _paste_today_right_of(label: str, today: str) -> bool:
    window = capture_service()
    entries = ocr_entries()
    iw, ih = image_size(SHOT)
    bounds = window["bounds"]
    labs = [e for e in entries if e["text"] == label or e["text"].startswith(label)]
    if not labs:
        return False
    e = labs[0]
    sx = bounds["X"] + (e["x"] + e["w"] + 50) / (iw / bounds["Width"])
    sy = bounds["Y"] + (e["y"] + e["h"] / 2) / (ih / bounds["Height"])
    click_xy(sx, sy)
    time.sleep(0.12)
    run_osascript(f'set the clipboard to "{today}"')
    run_osascript('tell application "System Events" to keystroke "a" using command down')
    time.sleep(0.04)
    run_osascript('tell application "System Events" to keystroke "v" using command down')
    time.sleep(0.06)
    run_osascript('tell application "System Events" to key code 36')
    time.sleep(0.25)
    return True


def apply_today_filter(today: str) -> None:
    reveal_date_filters()
    if not _paste_today_right_of("开始日期", today):
        raise BridgeError("start-date-missing")
    if not _paste_today_right_of("结束日期", today):
        _paste_today_right_of("至 结束日期", today)
    window = capture_service()
    entries = ocr_entries()
    iw, ih = image_size(SHOT)
    bounds = window["bounds"]
    queries = [e for e in entries if e["text"].replace(" ", "") == "查询"]
    if not queries:
        raise BridgeError("query-button-missing")
    click_xy(*to_screen(sorted(queries, key=lambda z: z["x"])[-1], bounds, iw, ih))
    time.sleep(2.4)


def horizontal_scroll_for_recommend_time(direction: int = -4) -> None:
    """D5: shift+wheel until datetime cells visible (direction -4 right / +4 left)."""
    window = capture_service()
    bounds = window["bounds"]
    x = bounds["X"] + bounds["Width"] * 0.65
    y = bounds["Y"] + bounds["Height"] * 0.72
    evt = Quartz.CGEventCreateMouseEvent(
        None, Quartz.kCGEventMouseMoved, (x, y), Quartz.kCGMouseButtonLeft
    )
    Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
    time.sleep(0.05)
    for _ in range(18):
        evt = Quartz.CGEventCreateScrollWheelEvent(
            None, Quartz.kCGScrollEventUnitLine, 1, direction
        )
        Quartz.CGEventSetFlags(evt, Quartz.kCGEventFlagMaskShift)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, evt)
        time.sleep(0.025)
    time.sleep(0.4)


def close_modal_if_any() -> None:
    window = capture_service()
    entries = ocr_entries()
    if not any(e["text"] == "推荐商家详情" for e in entries):
        return
    iw, ih = image_size(SHOT)
    bounds = window["bounds"]
    crosses = [e for e in entries if e["text"] in ("×", "X", "x") and e["x"] > 1400]
    if crosses:
        click_xy(*to_screen(crosses[0], bounds, iw, ih))
    else:
        run_osascript('tell application "System Events" to key code 53')
    time.sleep(0.7)


def parse_modal_fields(entries: list[dict]) -> dict:
    """D7: only modal band."""
    modal = [e for e in entries if 980 < e["x"] < 1650 and e["y"] > 500]
    if not any(e["text"] == "推荐商家详情" for e in entries):
        raise BridgeError("detail-modal-missing")

    def mval(label: str) -> str:
        labs = [e for e in modal if e["text"].replace(" ", "") == label]
        if not labs:
            return ""
        lab = labs[0]
        rights = [
            e
            for e in modal
            if e["x"] > lab["x"] + lab["w"] - 5
            and abs(e["y"] - lab["y"]) < 48
            and e["text"].replace(" ", "") != label
        ]
        return sorted(rights, key=lambda z: z["x"])[0]["text"] if rights else ""

    contact = mval("商家联系人")
    contact = re.sub(r"[⑦?？\s]+$", "", contact or "")
    contact = re.sub(r"\s*,\s*", "，", contact)
    contact = re.sub(r"\s+", "", contact)
    if contact and "，" not in contact:
        m = re.match(r"^(.*?)(1\d{10})$", contact)
        if m:
            contact = f"{m.group(1)}，{m.group(2)}"
    addr = mval("商家地址")
    if not addr or len(addr) < 6:
        lab = next((e for e in modal if e["text"].replace(" ", "") == "商家地址"), None)
        if lab:
            parts = [
                e
                for e in modal
                if e["x"] > lab["x"] + 40
                and lab["y"] - 5 < e["y"] < lab["y"] + 95
                and e["text"] not in ("商家地址", "商家联系人", "商家ID", "商家名称")
            ]
            addr = "".join(e["text"] for e in sorted(parts, key=lambda z: (z["y"], z["x"])))
    mid = re.sub(r"\D", "", mval("商家ID"))
    return {
        "merchantName": mval("商家名称"),
        "merchantId": mid,
        "address": addr,
        "contact": contact,
    }


def format_message(city: str, contact: str, name: str, address: str) -> str:
    def usable(value: str, miss: str) -> str:
        v = (value or "").strip()
        return v if v and v not in ("-", "--", "暂无", "无") else miss

    return "\n".join(
        [
            usable(city, "（城市字段缺失）"),
            usable(contact, "（商家联系人字段缺失）"),
            usable(name, "（商家名称字段缺失）"),
            usable(address, "（商家地址字段缺失）"),
        ]
    )


def select_incremental(rows: list[dict], cursor: dict, business_date: str) -> list[dict]:
    ordered = sorted(rows, key=lambda r: (r["recommendTime"], r["merchantId"]))
    for i, row in enumerate(ordered, 1):
        row["tableOrder"] = i
    day_start = f"{business_date} 00:00:00"
    if cursor["recommendTime"] < day_start:
        return ordered
    exact = next(
        (
            i
            for i, r in enumerate(ordered)
            if r["merchantId"] == cursor["merchantId"]
            and r["recommendTime"] == cursor["recommendTime"]
        ),
        -1,
    )
    if exact >= 0:
        return ordered[exact + 1 :]
    after = [r for r in ordered if r["recommendTime"] > cursor["recommendTime"]]
    if after and not any(r["recommendTime"] == cursor["recommendTime"] for r in ordered):
        raise BridgeError("same-day-cursor-not-found")
    return after


def collect_legacy_ocr(
    group_name: str,
    cursor_path: Path,
    out_path: Path,
    *,
    reload_entry: bool = False,
) -> dict:
    today = today_shanghai()
    cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
    open_intention_page(reload_entry=reload_entry)
    close_modal_if_any()
    apply_today_filter(today)
    capture_service()
    entries = ocr_entries()
    pending_y = [e["y"] for e in entries if "待处理" in e["text"]]
    ids = [e for e in entries if re.match(r"^\d{7,}$", e["text"])]
    base_rows = []
    for id_e in ids:
        if pending_y and not any(abs(id_e["y"] - y) < 90 for y in pending_y):
            continue
        names = [
            e
            for e in entries
            if e["x"] < id_e["x"] - 10
            and abs(e["y"] - id_e["y"]) < 95
            and re.search(r"[\u4e00-\u9fff]", e["text"])
            and e["x"] > 450
            and e["text"]
            not in ("详情", "去签约", "释放", "待处理", "商家邀约", "商家名称", "商家ID")
            and "服务市场" not in e["text"]
        ]
        name = "".join(e["text"] for e in sorted(names, key=lambda z: (z["y"], z["x"])))
        cities = [
            e
            for e in entries
            if id_e["x"] < e["x"]
            and abs(e["y"] - id_e["y"]) < 90
            and e["text"].endswith(("市", "州", "盟", "县"))
        ]
        base_rows.append(
            {
                "merchantId": id_e["text"],
                "merchantName": name,
                "city": cities[0]["text"] if cities else "",
                "y": id_e["y"],
            }
        )
    base_rows = list({r["merchantId"]: r for r in base_rows}.values())
    if not base_rows:
        raise BridgeError("no-pending-rows-after-today-filter")

    horizontal_scroll_for_recommend_time(-4)
    capture_service()
    entries = ocr_entries()
    times = [
        e for e in entries if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", e["text"])
    ]
    if not times:
        horizontal_scroll_for_recommend_time(-4)
        capture_service()
        entries = ocr_entries()
        times = [
            e for e in entries if re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$", e["text"])
        ]
    for row in base_rows:
        id_e = next((e for e in entries if e["text"] == row["merchantId"]), None)
        name_e = next(
            (e for e in entries if row["merchantName"] and e["text"] == row["merchantName"]),
            None,
        )
        anchor_y = (id_e or name_e or {"y": row["y"]})["y"]
        near = sorted(times, key=lambda e: abs(e["y"] - anchor_y))
        if near and abs(near[0]["y"] - anchor_y) < 120:
            row["recommendTime"] = near[0]["text"]
        elif len(base_rows) == 1 and len(times) == 1 and times[0]["text"].startswith(today):
            row["recommendTime"] = times[0]["text"]
        else:
            row["recommendTime"] = ""

    missing_rt = [r["merchantId"] for r in base_rows if not r.get("recommendTime")]
    if missing_rt:
        raise BridgeError(f"recommend-time-missing:{','.join(missing_rt)}")

    today_rows = [r for r in base_rows if r["recommendTime"].startswith(today)]
    targets = select_incremental(today_rows, cursor, today)

    horizontal_scroll_for_recommend_time(4)

    merchants = []
    for row in targets:
        window = capture_service()
        entries = ocr_entries()
        iw, ih = image_size(SHOT)
        bounds = window["bounds"]
        id_e = next((e for e in entries if e["text"] == row["merchantId"]), None)
        if not id_e:
            raise BridgeError(f"row-not-visible:{row['merchantId']}")
        details = [
            e
            for e in entries
            if (e["text"] == "详情" or e["text"].startswith("详情"))
            and abs(e["y"] - id_e["y"]) < 95
            and e["x"] > id_e["x"]
        ]
        if not details:
            raise BridgeError(f"detail-button-missing:{row['merchantId']}")
        click_xy(*to_screen(details[0], bounds, iw, ih, frac=(0.08, 0.5)))
        time.sleep(1.8)
        capture_service()
        entries = ocr_entries()
        detail = parse_modal_fields(entries)
        close_modal_if_any()
        name = detail["merchantName"] or row["merchantName"]
        mid = detail["merchantId"] or row["merchantId"]
        contact = detail["contact"]
        address = detail["address"]
        city = row.get("city") or ""
        text = format_message(city, contact, name, address)
        merchants.append(
            {
                "merchantId": mid,
                "merchantName": name,
                "recommendTime": row["recommendTime"],
                "tableOrder": row["tableOrder"],
                "city": city,
                "contact": contact,
                "address": address,
                "text": text,
                "sha256": hashlib.sha256(text.encode()).hexdigest(),
            }
        )

    receipt = {
        "ok": True,
        "executor": "merchant-collector",
        "groupName": group_name,
        "businessDate": today,
        "cursor": cursor,
        "cursorSource": "local",
        "eligibility": "status=待处理",
        "dateFilter": f"{today}..{today}",
        "bridge": "chrome_desktop_bridge",
        "targetCount": len(merchants),
        "messages": [
            {
                k: m[k]
                for k in (
                    "merchantId",
                    "merchantName",
                    "recommendTime",
                    "tableOrder",
                    "text",
                    "sha256",
                )
            }
            for m in merchants
        ],
        "merchants": merchants,
        "ascending": True,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt


def collect(group_name, cursor_path, out_path, *, reload_entry=False):
    if reload_entry:
        return collect_legacy_ocr(group_name,cursor_path,out_path,reload_entry=True)
    from structured_merchant_collector import collect as structured_collect
    receipt=structured_collect(group_name,cursor_path,out_path)
    if not receipt['ok']:raise BridgeError(receipt['error'])
    return receipt


def self_test() -> dict:
    assert today_shanghai()
    assert cursor_file_for_group("FEIBING NEO AI数字员工").name == "cursor.test.json"
    msg = format_message("", "", "店", "")
    assert "（商家联系人字段缺失）" in msg
    rows = [
        {"merchantId": "2", "recommendTime": "2026-09-03 11:00:00"},
        {"merchantId": "1", "recommendTime": "2026-09-03 10:00:00"},
    ]
    cursor = {"merchantId": "x", "recommendTime": "2026-09-02 23:59:59"}
    selected = select_incremental(rows, cursor, "2026-09-03")
    assert [r["merchantId"] for r in selected] == ["1", "2"]
    assert intention_list_open(
        [{"text": MENU_INTENTION}, {"text": "•待处理"}, {"text": "详情 去签约"}]
    )
    assert not intention_list_open([{"text": MENU_INTENTION}, {"text": "工作台"}])
    return {"ok": True, "tests": 5}


def main() -> int:
    parser = argparse.ArgumentParser(description="Chrome desktop bridge for merchant collector")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--declutter", action="store_true")
    parser.add_argument("--preflight-nav", action="store_true")
    parser.add_argument("--collect", action="store_true")
    parser.add_argument(
        "--reload-entry",
        action="store_true",
        help="仅在已有 open.shop 标签上重载 base/home；默认不重载、不新开浏览器",
    )
    parser.add_argument("--group", default="FEIBING NEO AI数字员工")
    parser.add_argument("--cursor-file", default="")
    parser.add_argument("--out", default=str(DEFAULT_RECEIPT))
    args = parser.parse_args()

    try:
        if args.self_test:
            print(json.dumps(self_test(), ensure_ascii=False, indent=2))
            return 0
        if args.declutter:
            declutter_overlays()
            seize_service_chrome()
            w = service_window()
            print(json.dumps({"ok": True, "mode": "declutter", "window": w}, ensure_ascii=False, indent=2))
            return 0
        if args.preflight_nav:
            if args.reload_entry:
                result = open_intention_page(reload_entry=True)
                capture_service()
                ok = intention_list_open(ocr_entries())
            else:
                from native_service_ui import navigate
                result = navigate()
                ok = result['ok']
            print(
                json.dumps(
                    {
                        "ok": ok,
                        "mode": "preflight-nav",
                        "entryUrl": BASE_HOME,
                        "intentionListVisible": ok,
                        "attachOnly": not args.reload_entry,
                        **result,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0 if ok else 1
        if args.collect:
            cursor_path = (
                Path(args.cursor_file) if args.cursor_file else cursor_file_for_group(args.group)
            )
            if not cursor_path.is_file():
                raise BridgeError(f"cursor-missing:{cursor_path}")
            receipt = collect(
                args.group,
                cursor_path,
                Path(args.out),
                reload_entry=args.reload_entry,
            )
            print(
                json.dumps(
                    {
                        "ok": True,
                        "mode": "collect",
                        "targetCount": receipt["targetCount"],
                        "out": args.out,
                        "attachOnly": not args.reload_entry,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0
        parser.print_help()
        return 2
    except Exception as error:  # noqa: BLE001 — executor boundary
        print(json.dumps({"ok": False, "error": str(error)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())
