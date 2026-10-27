#!/usr/bin/env python3
"""一次性人工更正（2026-10-12 装修流 v1 判据误发事故，大同在聊天中批准）。

独立事件 `2026-10-12-taobao-decoration-correction`，与四家店的日常提醒事件互不冲突；
走 wechat-messaging WindowsAdapter 完整契约（preflight 群身份校验 + send_one 回读验证），
发送结果写回同一自包含台账 `.runtime/decoration/events/`。
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / ".." / ".." / "wechat-messaging" / "scripts"))
from windows_adapter import WindowsAdapter  # noqa: E402
from contract import Rejected  # noqa: E402

GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
EVENT = "2026-10-12-taobao-decoration-correction"
TEXT = (
    "更正：今日新店装修巡检因识别逻辑有误，缺失项以本条为准：\n"
    "虬师傅·沙县小吃(汇海广场店)：无缺失，前条作废\n"
    "甬潮·宁波小市(静安大融城店)：店内橱窗\n"
    "重庆鸡公煲·特色纸包鱼烤鱼(赣职理工店)：顶部招牌\n"
    "甬潮·宁波小市(新邻店)：店内橱窗"
)
EVENTS = SKILL / ".runtime" / "decoration" / "events"
RUN_DIR = SKILL / ".runtime" / "decoration" / "runs" / "correction-20261012"


def atomic_json(path: Path, value: dict) -> None:
    import os
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with tmp.open("x", encoding="utf-8") as s:
        os.chmod(tmp, 0o600)
        json.dump(value, s, ensure_ascii=False, indent=2)
        s.flush()
        os.fsync(s.fileno())
    tmp.replace(path)


def main() -> None:
    digest = hashlib.sha256(TEXT.encode("utf-8")).hexdigest()
    marker = EVENTS / f"{EVENT}.json"
    if marker.exists() and json.loads(marker.read_text(encoding="utf-8")).get("state") == "verified":
        print(json.dumps({"status": "already_verified", "sendAttempts": 0}, ensure_ascii=False))
        return
    if not EVENTS.is_dir():
        print(json.dumps({"status": "blocked", "reason": "ledger-unavailable"}, ensure_ascii=False))
        raise SystemExit(1)
    deadline = int(time.time()) + 180
    request = {"schemaVersion": 1, "groupName": GROUP,
               "items": [{"itemId": "decoration-correction", "type": "text", "text": TEXT, "sha256": digest}],
               "context": {"workflowId": "daily-new-stores-decoration-reminder", "eventId": EVENT,
                           "accountAlias": "main-wechat", "channel": "desktop", "deadlineAt": deadline}}
    grant = {"schemaVersion": 1, "accountAlias": "main-wechat", "groupName": GROUP,
             "channel": "desktop", "expiresAt": deadline,
             "authorizationRef": "user-20261012-decoration-correction-approved-by-datong"}
    result = None
    try:
        adapter = WindowsAdapter()
        with adapter.session(request):
            preflight = adapter.preflight(request, RUN_DIR / "windows-preflight")
            if not preflight.get("ok") or not preflight.get("sessionListVerified") or preflight.get("resolvedGroup") != GROUP:
                print(json.dumps({"status": "blocked", "reason": preflight.get("reason") or "target-group-not-exactly-listed",
                                  "sendAttempts": 0}, ensure_ascii=False))
                return
            atomic_json(marker, {"state": "attempted", "event": EVENT, "sha256": digest,
                                 "groupName": GROUP, "text": TEXT, "sendAttempts": None,
                                 "note": "v1 判据误发的更正，大同聊天批准"})
            result = adapter.send_one(request, request["items"][0], RUN_DIR / "windows-send", grant, deadline)
    except Rejected as error:
        print(json.dumps({"status": "blocked", "reason": str(error), "sendAttempts": 0}, ensure_ascii=False))
        return
    if result.get("status") == "verified":
        atomic_json(marker, {"state": "verified", "event": EVENT, "sha256": digest,
                             "groupName": GROUP, "text": TEXT, "sendAttempts": result.get("sendAttempts"),
                             "verificationLevel": result.get("verificationLevel"), "evidence": result.get("evidence"),
                             "note": "v1 判据误发的更正，大同聊天批准"})
    print(json.dumps({"status": result.get("status"), "sendAttempts": result.get("sendAttempts"),
                      "verificationLevel": result.get("verificationLevel"), "reason": result.get("reason")},
                     ensure_ascii=False))
    if result.get("status") != "verified":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
