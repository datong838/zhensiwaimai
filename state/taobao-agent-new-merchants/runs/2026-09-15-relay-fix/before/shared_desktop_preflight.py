#!/usr/bin/env python3
"""Shared, no-send desktop WeChat preflight for business workflows."""
from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import os
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from wechat_interaction_lock import WeChatInteractionLock


LOCATOR = SCRIPT_DIR / "wechat_desktop.py"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR.parent / "artifacts" / "preflight-runs"


def _load_locator():
    spec = importlib.util.spec_from_file_location("shared_wechat_desktop_locator", LOCATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError("desktop-wechat-locator-load-failed")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def normalize_failure(error: BaseException | str) -> str:
    raw = str(error)
    known = (
        "wechat-window-capture-target-missing",
        "wechat-window-capture-failed",
        "wechat-main-window-count-not-one",
        "wechat-process-count-not-one",
        "wechat-unexpected-secondary-window",
        "wechat-visible-screen-too-small",
        "wechat-interaction-lock-timeout",
        "wechat-search-region-contended",
        "blocked-login",
    )
    for code in known:
        if code in raw:
            return code
    match = re.search(r"(?:ax-)?exact-(?:group-)?(?:header|row|result)-count:(?:\d+|multiple)", raw)
    if match:
        return match.group(0)
    return "desktop-wechat-preflight-failed"


def is_hard_gate(reason: str) -> bool:
    return any(
        marker in reason
        for marker in (
            "blocked-login",
            "window-capture",
            "main-window-count",
            "process-count",
            "unexpected-secondary-window",
            "visible-screen-too-small",
            "count:multiple",
            "count:2",
            "count:3",
        )
    )


def run_exact_group_preflight(
    group: str,
    output_dir: str | Path | None = None,
    *,
    locator=None,
    acquire_lock: bool = True,
) -> dict:
    started = time.monotonic()
    result = {
        "ok": False,
        "action": "open-group",
        "group": group,
        "header": None,
        "note": None,
        "reason": None,
        "sendAttempts": 0,
        "runtimeModelDecisions": 0,
        "stageMs": {},
    }
    if not isinstance(group, str) or not group.strip() or "\n" in group or "\r" in group:
        result.update(reason="desktop-wechat-group-argument-invalid", hardGate=True)
        return result
    target_dir = Path(output_dir or DEFAULT_OUTPUT_DIR).resolve()
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    try:
        wd = locator or _load_locator()
        if acquire_lock:
            lease = WeChatInteractionLock(f"preflight:{os.getpid()}:{time.time_ns()}").acquire()
        else:
            lease = None
        try:
            receipt = wd.open_group(group, target_dir, exact=True)
        finally:
            if lease is not None:
                lease.release()
                result["interactionLock"] = lease.receipt()
        result.update(
            ok=receipt.ok is True,
            action=receipt.action,
            group=receipt.group,
            header=receipt.header,
            note=receipt.note,
            artifacts=receipt.artifacts or [],
        )
        if receipt.ok is not True:
            reason = normalize_failure(receipt.note or "desktop-wechat-preflight-failed")
            result.update(reason=reason, hardGate=is_hard_gate(reason))
        else:
            result.update(reason=None, hardGate=False)
    except Exception as error:
        reason = normalize_failure(error)
        result.update(reason=reason, note=str(error), hardGate=is_hard_gate(reason))
    result["stageMs"]["exact_group_preflight"] = round((time.monotonic() - started) * 1000)
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Shared desktop WeChat exact-group preflight")
    parser.add_argument("--group", required=True)
    parser.add_argument("--output-dir")
    parser.add_argument("--receipt-file")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    receipt = run_exact_group_preflight(args.group, args.output_dir)
    if args.receipt_file:
        receipt_file = Path(args.receipt_file).resolve()
        receipt_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = receipt_file.with_suffix(receipt_file.suffix + ".tmp")
        temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.chmod(0o600)
        temporary.replace(receipt_file)
    print(json.dumps(receipt, ensure_ascii=False))
    return 0 if receipt.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
