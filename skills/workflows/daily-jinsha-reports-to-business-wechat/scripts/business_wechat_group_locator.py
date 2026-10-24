#!/usr/bin/env python3
"""Business-only adapter for a moving WeChat recent-chat list.

The sealed locator compares the initial candidate with one later frame.  The
business group can move once while WeChat collapses/reflows pinned chats, so
this adapter waits for two *fresh* consecutive exact-title frames and clicks
the newest coordinates.  All post-click title verification remains sealed.
"""

from __future__ import annotations

import importlib.util
import re
import time
from pathlib import Path


ORIGINAL = Path(__file__).resolve().parents[3] / (
    "workflows/daily-agent-new-merchants-to-wechat/scripts/wechat_sender_executor.py"
)


def _load_original():
    spec = importlib.util.spec_from_file_location("sealed_merchant_wechat_locator", ORIGINAL)
    if spec is None or spec.loader is None:
        raise RuntimeError("sealed-merchant-locator-load-failed")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_sealed = _load_original()


def normalize_business_group_title(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("Al数字员工", "AI数字员工")


def exact_business_group_title(value: str, group_name: str) -> bool:
    value = normalize_business_group_title(value)
    group_name = normalize_business_group_title(group_name)
    return bool(re.fullmatch(re.escape(group_name) + r"(?:[（(]\d+[）)])?", value))


def _fresh_stable_group_click(device, helpers, work, group_name, _stale_candidate):
    """Require one unique exact title at a stable position in two fresh frames."""
    deadline = time.monotonic() + 8
    previous = None
    while time.monotonic() < deadline:
        entries = helpers.ocr_entries(helpers.screenshot(device, work, "group-before-click"))
        matches = [
            entry for entry in entries
            if 280 < entry["y"] < 2050
            and exact_business_group_title(entry["text"], group_name)
        ]
        loading = any("加载中" in entry["text"] for entry in entries)
        current = matches[0] if len(matches) == 1 else None
        if (
            not loading
            and
            current is not None
            and previous is not None
            and abs(current["x"] - previous["x"]) < 35
            and abs(current["y"] - previous["y"]) < 25
        ):
            helpers.adb(
                device.serial,
                "shell",
                "input",
                "tap",
                str(current["x"]),
                str(current["y"]),
            )
            return
        previous = current
        time.sleep(0.25)
    raise _sealed.StopRun("group-position-not-stable-two-fresh-frames")


# Patch only the business-loaded module instance.  The sealed source file and
# every other caller keep their original behavior.
_sealed.stable_group_click = _fresh_stable_group_click

unique_group_in_title = _sealed.unique_group_in_title
open_main_wechat_group = _sealed.open_main_wechat_group
