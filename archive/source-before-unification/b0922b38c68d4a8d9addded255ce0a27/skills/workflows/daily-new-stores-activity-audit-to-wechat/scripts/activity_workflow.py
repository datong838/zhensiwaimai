#!/usr/bin/env python3
"""One-store activity audit and at-most-one Windows WeChat reminder."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SKILL = Path(__file__).resolve().parents[1]
RUNTIME = SKILL / ".runtime" / "activity"
EVENTS = RUNTIME / "events"  # 活动提醒去重台账，自包含于本技能目录；不再跨仓读 zhensi_waimai（遗留 dev 仓路径）
COLLECTOR = Path(__file__).with_name("activity_collector.mjs")
NODE = Path("/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
NODE_MODULES = "/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
WINDOWS_SCRIPTS = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts")
GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
TARGETS = ("减配送费", "新阶梯红包", "店铺满减")
ACCOUNT = "gmfmmZH"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def validate_receipt(receipt: dict, expected_name: str = "EGO TACO ·伊戈塔可·香辣蟹(雨花店)") -> list[str]:
    shop_id = receipt.get("shopId")
    if receipt.get("status") != "complete" or not isinstance(shop_id, str) or not re.fullmatch(r"\d+", shop_id) or receipt.get("account") != ACCOUNT:
        raise ValueError("activity-receipt-identity-invalid")
    name = receipt.get("shopName")
    if name != expected_name:
        raise ValueError("activity-receipt-shop-name-invalid")
    if not re.match(rf"^https://melody\.shop\.ele\.me/app/shop/{shop_id}/activity__myActivity", receipt.get("pageUrl", "")):
        raise ValueError("activity-receipt-page-invalid")
    try:
        checked = datetime.fromisoformat(receipt["checkedAt"].replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("activity-receipt-time-invalid") from error
    if checked.tzinfo is None or abs((datetime.now(checked.tzinfo) - checked).total_seconds()) > 600:
        raise ValueError("activity-receipt-stale")
    store, flow = receipt.get("store"), receipt.get("flow")
    if not isinstance(store, dict) or not isinstance(flow, dict):
        raise ValueError("activity-coverage-missing")
    all_names = []
    for key, label in (("pending", "待开始"), ("active", "进行中")):
        unit = store.get(key)
        if not isinstance(unit, dict) or unit.get("status") != label:
            raise ValueError("activity-store-status-invalid")
        names, total = unit.get("names"), unit.get("total")
        if type(total) is not int or total < 0 or not isinstance(names, list) or len(names) != total or any(not isinstance(n, str) or not n.strip() for n in names):
            raise ValueError("activity-store-list-incomplete")
        all_names.extend(names)
    names, total, size = flow.get("names"), flow.get("total"), flow.get("pageSize")
    empty_proven = total == 0 and size == 0 and flow.get("emptyEvidence") == "暂无数据"
    paged_proven = type(total) is int and type(size) is int and size >= 1 and total <= size
    if flow.get("status") != "进行中" or type(total) is not int or not (empty_proven or paged_proven) or not isinstance(names, list) or len(names) != total or any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError("activity-flow-list-incomplete")
    all_names.extend(names)
    derived = {target: "present" if target in all_names else "missing" for target in TARGETS}
    if receipt.get("targetStatus") != derived:
        raise ValueError("activity-target-conclusion-mismatch")
    return [target for target in TARGETS if derived[target] == "missing"]


def message(receipt: dict, expected_name: str = "EGO TACO ·伊戈塔可·香辣蟹(雨花店)") -> str | None:
    missing = validate_receipt(receipt, expected_name)
    if not missing:
        return None
    return f"淘宝  {receipt['shopName']}  待配置活动：{'、'.join(missing)}；请尽快配置。"


def collect(run_dir: Path, shop_name: str = "EGO TACO ·伊戈塔可·香辣蟹(雨花店)") -> dict:
    path = run_dir / "activity-collection.json"
    env = dict(os.environ, NODE_PATH=NODE_MODULES)
    result = subprocess.run([str(NODE), str(COLLECTOR), str(path), shop_name], env=env,
                            capture_output=True, text=True, timeout=45, check=False)
    if result.returncode or not path.is_file():
        # 工位忙：采集器为避免抢浏览器会向 **stdout** 写 {"status":"skipped","reason":"post-lease-busy"}
        # 并退出 0、不落文件。旧实现只看 stderr ⇒ 误报成「空 reason」的 activity-collection-unknown
        # （2026-10-10 实测：并发体检持锁期间守护侧即此形状，误导根因定位）。显式识别之。
        if '"post-lease-busy"' in (result.stdout or ""):
            raise RuntimeError("activity-collection-skipped:post-lease-busy")
        # 2026-10-11 非营业中店（暂停营业/已下线）：采集器同样 stdout skipped JSON + 退出 0。
        # 暂停营业店无活动巡检意义，记 skipped 不算 unknown（消除每日连败告警噪音）。
        if '"shop-not-operating' in (result.stdout or ""):
            m = re.search(r'"reason":"(shop-not-operating:[^"]+)"', result.stdout or "")
            raise RuntimeError(f"activity-collection-skipped:{m.group(1) if m else 'shop-not-operating'}")
        # 2026-10-12 店铺树无此店（代理商侧新店未同步到品牌商账号，如重庆鸡公煲·赣职理工店）
        # 或搜索空态超时：采集器同样 skipped JSON + 退出 0，同 skipped 语义不上报为 unknown。
        if '"shop-not-found' in (result.stdout or "") or '"shop-search-timeout' in (result.stdout or ""):
            m = re.search(r'"reason":"(shop-(?:not-found|search-timeout)[^"]*)"', result.stdout or "")
            raise RuntimeError(f"activity-collection-skipped:{m.group(1) if m else 'shop-not-found'}")
        raise RuntimeError(f"activity-collection-unknown:{(result.stderr or '')[-250:]}")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    validate_receipt(receipt, shop_name)
    return receipt


def deliver(receipt: dict, run_dir: Path, expected_name: str = "EGO TACO ·伊戈塔可·香辣蟹(雨花店)") -> dict:
    body = message(receipt, expected_name)
    if body is None:
        return {"status": "no-missing", "sendAttempts": 0}
    day = datetime.now(LOCAL_TZ).date().isoformat()
    event = f"{day}-taobao-{receipt['shopId']}-activity-reminder"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if not EVENTS.is_dir():
        return {"status": "blocked", "reason": "canonical-activity-ledger-unavailable", "sendAttempts": 0}
    marker = EVENTS / f"{event}.json"
    if marker.exists():
        prior = json.loads(marker.read_text(encoding="utf-8"))
        if prior.get("sha256") != digest:
            # 当日已 verified 但产物字节变了（xlsx/png 内嵌时间戳等）：一事一发的正确语义是
            # 「当日已发、不重发」，记为 already_verified；绝不可重发（重复外发），也不可记
            # UNKNOWN 故障（2026-10-20 实战：nourish 11:40 档因此被判 FAILED/UNKNOWN，误导看护）。
            if prior.get("state") == "verified":
                return {"status": "already_verified", "sendAttempts": 0, "event": event,
                        "reason": "verified-earlier-today-payload-changed-no-resend"}
            return {"status": "blocked", "reason": "same-event-payload-conflict", "sendAttempts": 0}
        if prior.get("state") == "verified":
            return {"status": "already_verified", "sendAttempts": 0, "event": event}
        return {"status": "unknown", "reason": "prior-attempt-requires-read-only-reconciliation",
                "sendAttempts": 0, "event": event}
    if str(WINDOWS_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(WINDOWS_SCRIPTS))
    from wecom_adapter import WeComAdapter as WindowsAdapter, target_preflight_verified  # 2026-10-23 channel switch
    from contract import Rejected
    deadline = int(time.time()) + 180
    request = {"schemaVersion": 1, "groupName": GROUP,
               "items": [{"itemId": "missing-activity", "type": "text", "text": body, "sha256": digest}],
               "context": {"workflowId": "daily-new-stores-activity-reminder", "eventId": event,
                           "accountAlias": "main-wechat", "channel": "desktop", "deadlineAt": deadline}}
    grant = {"schemaVersion": 1, "accountAlias": "main-wechat", "groupName": GROUP,
             "channel": "desktop", "expiresAt": deadline,
             "authorizationRef": "user-20261001-daily-new-store-activity-missing-reminder-windows-gateway"}
    try:
        adapter = WindowsAdapter()
        with adapter.session(request):
            if marker.exists():
                prior = json.loads(marker.read_text(encoding="utf-8"))
                if prior.get("sha256") != digest:
                    if prior.get("state") == "verified":
                        return {"status": "already_verified", "sendAttempts": 0, "event": event,
                                "reason": "verified-earlier-today-payload-changed-no-resend"}
                    return {"status": "blocked", "reason": "same-event-payload-conflict", "sendAttempts": 0}
                return {"status": "already_verified" if prior.get("state") == "verified" else "unknown",
                        "reason": None if prior.get("state") == "verified" else "prior-attempt-requires-read-only-reconciliation",
                        "sendAttempts": 0, "event": event}
            preflight = adapter.preflight(request, run_dir / "windows-preflight")
            if not target_preflight_verified(preflight, GROUP):
                return {"status": "blocked", "reason": preflight.get("reason") or "target-group-not-exactly-listed",
                        "sendAttempts": 0}
            atomic_json(marker, {"state": "attempted", "event": event, "sha256": digest,
                                 "groupName": GROUP, "text": body, "sendAttempts": None})
            try:
                result = adapter.send_one(request, request["items"][0], run_dir / "windows-send", grant, deadline)
            except Exception as error:
                atomic_json(marker, {"state": "unknown", "event": event, "sha256": digest,
                                     "groupName": GROUP, "text": body, "reason": str(error), "sendAttempts": None})
                return {"status": "unknown", "reason": f"windows-execution-error:{error}", "sendAttempts": None}
    except Rejected as error:
        return {"status": "blocked", "reason": str(error), "sendAttempts": 0}
    if result.get("status") == "verified":
        atomic_json(marker, {"state": "verified", "event": event, "sha256": digest,
                             "groupName": GROUP, "text": body, "sendAttempts": result.get("sendAttempts"),
                             "verificationLevel": result.get("verificationLevel"), "evidence": result.get("evidence")})
        return {"status": "verified", "sendAttempts": result.get("sendAttempts"), "event": event,
                "verificationLevel": result.get("verificationLevel")}
    atomic_json(marker, {"state": "unknown", "event": event, "sha256": digest,
                         "groupName": GROUP, "text": body, "sendAttempts": result.get("sendAttempts"),
                         "reason": result.get("reason")})
    return {"status": "unknown", "reason": result.get("reason"),
            "sendAttempts": result.get("sendAttempts"), "event": event}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="allow one authorized reminder send")
    parser.add_argument("--shop-name", default="EGO TACO ·伊戈塔可·香辣蟹(雨花店)")
    args = parser.parse_args()
    run_dir = RUNTIME / "runs" / f"{datetime.now(LOCAL_TZ):%Y-%m-%d}-{time.time_ns()}"
    run_dir.mkdir(parents=True, mode=0o700)
    try:
        receipt = collect(run_dir, args.shop_name)
        body = message(receipt, args.shop_name)
        result = deliver(receipt, run_dir, args.shop_name) if args.execute else {"status": "ready" if body else "no-missing", "sendAttempts": 0}
        result.update({"shopId": receipt["shopId"], "targetStatus": receipt["targetStatus"],
                       "groupName": GROUP, "text": body, "sha256": hashlib.sha256(body.encode()).hexdigest() if body else None,
                       "runDir": str(run_dir)})
    except Exception as error:
        result = {"status": "unknown", "reason": str(error), "sendAttempts": 0, "runDir": str(run_dir)}
    atomic_json(run_dir / "summary.json", result)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] not in ("verified", "already_verified", "ready", "no-missing"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
