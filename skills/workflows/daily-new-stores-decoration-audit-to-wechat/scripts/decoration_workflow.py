#!/usr/bin/env python3
"""One-store decoration audit (顶部招牌/店内海报) and at-most-one WeChat reminder."""
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
RUNTIME = SKILL / ".runtime" / "decoration"
EVENTS = RUNTIME / "events"  # 装修提醒去重台账，自包含于本技能目录
COLLECTOR = Path(__file__).with_name("decoration_collector.mjs")
NODE = Path("/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node")
NODE_MODULES = "/Users/ddt/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
WINDOWS_SCRIPTS = Path("/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/skills/wechat-messaging/scripts")
GROUP = "上海臻肆外卖运营-盯个盯-饭敢当 💰发财精英荟💰"
COMPONENTS = ("顶部招牌", "店内海报", "门店头像", "店内橱窗")  # 2026-10-12 晚大同扩充：+门店头像、店内橱窗（仅此四项）
ACCOUNT = "gmfmmZH"
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
# 人工放行闸（大同 2026-10-12 晚指示演化）：
# 初版为「默认关闭、须每日 --arm 才外发」，会让日常调度每天被闸成 blocked/unknown 噪音；
# 故反转语义为【默认放行 + --disarm 制动】：不存在 SEND_DISARMED.json 即允许真实外发，
# 采集/校验/报告照常产出；若要临时暂停日常外发，执行 --disarm 写入 SEND_DISARMED.json。
ARM_FILE = RUNTIME / "SEND_ARMED.json"        # 显式放行（当日有效），仅调试/人工补发用
DISARM_FILE = RUNTIME / "SEND_DISARMED.json"  # 制动文件：存在即禁止外发（跨日有效）


def arm_state() -> dict:
    """默认放行（与其它流水线一致的日常自动发送）；存在制动文件时禁止外发。

    2026-10-12 晚校准：首版做成「默认关闭、需每日 arm」，会让日常调度每天被闸挡成
    blocked/unknown ⇒ 每日告警噪音。故反转语义：默认放行，`--disarm` 才制动。
    """
    try:
        payload = json.loads(DISARM_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"armed": True, "mode": "default-auto"}
    if payload.get("state") != "disarmed":
        return {"armed": True, "mode": "default-auto"}
    return {"armed": False, "reason": "send-disarmed", "by": payload.get("by"), "at": payload.get("at")}


def set_arm(enable: bool, who: str) -> dict:
    if enable:
        try:
            DISARM_FILE.unlink()
        except FileNotFoundError:
            pass
        return {"armed": True, "state": "armed", "mode": "default-auto", "by": who}
    payload = {"state": "disarmed", "by": who, "at": datetime.now(LOCAL_TZ).isoformat()}
    atomic_json(DISARM_FILE, payload)
    return {"armed": False, **payload}


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("x", encoding="utf-8") as stream:
        os.chmod(temporary, 0o600)
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def validate_receipt(receipt: dict, expected_name: str) -> list[str]:
    shop_id = receipt.get("shopId")
    if receipt.get("status") != "complete" or not isinstance(shop_id, str) or not re.fullmatch(r"\d+", shop_id) or receipt.get("account") != ACCOUNT:
        raise ValueError("decoration-receipt-identity-invalid")
    name = receipt.get("shopName")
    if name != expected_name:
        raise ValueError("decoration-receipt-shop-name-invalid")
    if not re.match(rf"^https://melody\.shop\.ele\.me/app/shop/{shop_id}/decorate", receipt.get("pageUrl", "")):
        raise ValueError("decoration-receipt-page-invalid")
    try:
        checked = datetime.fromisoformat(receipt["checkedAt"].replace("Z", "+00:00"))
    except (KeyError, ValueError, TypeError) as error:
        raise ValueError("decoration-receipt-time-invalid") from error
    if checked.tzinfo is None or abs((datetime.now(checked.tzinfo) - checked).total_seconds()) > 600:
        raise ValueError("decoration-receipt-stale")
    components = receipt.get("components")
    if not isinstance(components, dict) or set(components) != set(COMPONENTS):
        raise ValueError("decoration-components-incomplete")
    if any(v not in ("configured", "missing") for v in components.values()):
        raise ValueError("decoration-component-state-invalid")
    if receipt.get("targetStatus") != components:
        raise ValueError("decoration-target-conclusion-mismatch")
    return [c for c in COMPONENTS if components[c] == "missing"]


def not_found_receipt(hit: dict, reason: str) -> dict:
    if (hit.get("channel") != "淘宝" or not isinstance(hit.get("name"), str)
            or not hit["name"].strip() or not re.fullmatch(r"[0-3]天", str(hit.get("days", "")))
            or reason != "decoration-collection-skipped:shop-not-found:未搜索到店铺"):
        raise ValueError("decoration-not-found-source-invalid")
    return {"inspectionOutcome": "master-account-store-not-found", "shopName": hit["name"],
            "days": hit["days"], "account": ACCOUNT, "checkedAt": datetime.now(LOCAL_TZ).isoformat(),
            "reason": reason, "recordNote": "店铺在主账号查不到未能检查"}


def not_found_message(receipt: dict, expected_name: str) -> str:
    not_found_receipt({"channel": "淘宝", "name": receipt.get("shopName"), "days": receipt.get("days")}, receipt.get("reason"))
    checked = datetime.fromisoformat(receipt["checkedAt"])
    if (receipt.get("shopName") != expected_name or receipt.get("account") != ACCOUNT
            or receipt.get("recordNote") != "店铺在主账号查不到未能检查"
            or checked.tzinfo is None or checked.astimezone(LOCAL_TZ).date() != datetime.now(LOCAL_TZ).date()
            or abs((datetime.now(LOCAL_TZ) - checked).total_seconds()) > 600):
        raise ValueError("decoration-not-found-receipt-invalid")
    return f"店铺装修巡检：{expected_name} 新店铺（开业{receipt['days']}）淘宝闪购商家版 查无此店铺"


def message(receipt: dict, expected_name: str) -> str | None:
    if receipt.get("inspectionOutcome") == "master-account-store-not-found":
        return not_found_message(receipt, expected_name)
    missing = validate_receipt(receipt, expected_name)
    if not missing:
        return None
    # 大同 2026-10-12 指定格式：淘宝闪购 / 店铺：X / 店铺装修缺失：顶部招牌 / 请尽快配置
    return "     ".join(("淘宝闪购", f"店铺：{receipt['shopName']}", f"店铺装修缺失：{'、'.join(missing)}", "请尽快配置"))


def collector_failure_reason(stderr: str) -> str:
    for line in reversed((stderr or '').splitlines()):
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get('reason'), str) and payload['reason']:
            return payload['reason'][:1200]
    return (stderr or '')[-250:]


def collect(run_dir: Path, shop_name: str) -> dict:
    path = run_dir / "decoration-collection.json"
    env = dict(os.environ, NODE_PATH=NODE_MODULES)
    # 2026-10-12 校准：单店采集含选店(≤65s) + 装修页菜单/iframe/编辑页渲染(≤85s)，
    # 原 120s 会把「已成功落盘」的采集掐成超时 unknown ⇒ 提到 300s。
    result = subprocess.run([str(NODE), str(COLLECTOR), str(path), shop_name], env=env,
                            capture_output=True, text=True, timeout=300, check=False)
    for name, content in [('collector.stdout.log', result.stdout), ('collector.stderr.log', result.stderr)]:
        evidence = run_dir / name
        evidence.write_text(content or '', encoding='utf-8')
        evidence.chmod(0o600)
    if result.returncode or not path.is_file():
        # 工位忙：采集器为避免抢浏览器会向 **stdout** 写 {"status":"skipped","reason":"post-lease-busy"}
        # 并退出 0、不落文件（对齐 activity_collector 语义）。
        if '"post-lease-busy"' in (result.stdout or ""):
            raise RuntimeError("decoration-collection-skipped:post-lease-busy")
        # 2026-10-11/12 语义（从 activity_collector 平移）：非营业中店 / 店铺树无此店 /
        # 搜索空态超时均为业务数据缺口，记 skipped 不算 unknown，避免每日连败告警噪音。
        m = re.search(r'"reason":"((?:shop-not-operating|shop-not-found|shop-search-timeout)[^"]*)"', result.stdout or "")
        if m:
            raise RuntimeError(f"decoration-collection-skipped:{m.group(1)}")
        raise RuntimeError(f"decoration-collection-unknown:{collector_failure_reason(result.stderr)}")
    receipt = json.loads(path.read_text(encoding="utf-8"))
    validate_receipt(receipt, shop_name)
    return receipt


def deliver(receipt: dict, run_dir: Path, expected_name: str) -> dict:
    body = message(receipt, expected_name)
    if body is None:
        return {"status": "no-missing", "sendAttempts": 0}
    # 人工放行闸：默认放行；存在 SEND_DISARMED.json（--disarm）才制动零外发（大同 2026-10-12 校准）
    gate = arm_state()
    if not gate["armed"]:
        return {"status": "blocked", "reason": gate["reason"], "sendAttempts": 0,
                "text": body, "awaitingHumanGo": True}
    day = datetime.now(LOCAL_TZ).date().isoformat()
    store_key = ("not-found-" + hashlib.sha256(expected_name.encode()).hexdigest()[:24]
                 if receipt.get("inspectionOutcome") == "master-account-store-not-found" else receipt['shopId'])
    event = f"{day}-taobao-{store_key}-decoration-reminder"
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    if not EVENTS.is_dir():
        return {"status": "blocked", "reason": "canonical-decoration-ledger-unavailable", "sendAttempts": 0}
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
               "items": [{"itemId": "missing-decoration", "type": "text", "text": body, "sha256": digest}],
               "context": {"workflowId": "daily-new-stores-decoration-reminder", "eventId": event,
                           "accountAlias": "main-wechat", "channel": "desktop", "deadlineAt": deadline}}
    grant = {"schemaVersion": 1, "accountAlias": "main-wechat", "groupName": GROUP,
             "channel": "desktop", "expiresAt": deadline,
             "authorizationRef": ("user-20261027-new-store-master-account-not-found-notice"
                                  if receipt.get("inspectionOutcome") == "master-account-store-not-found" else "user-20261012-daily-new-store-decoration-missing-reminder-windows-gateway")}
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
    parser.add_argument("--shop-name")
    parser.add_argument("--arm", action="store_true", help="人工放行：允许当日真实外发（须人工确认后执行）")
    parser.add_argument("--disarm", action="store_true", help="收回放行：立即禁止外发")
    parser.add_argument("--arm-status", action="store_true")
    args = parser.parse_args()
    if args.arm or args.disarm:
        print(json.dumps(set_arm(args.arm, os.environ.get("ZHENSI_ARMED_BY", "operator")), ensure_ascii=False))
        return
    if args.arm_status:
        print(json.dumps(arm_state(), ensure_ascii=False))
        return
    if not args.shop_name:
        parser.error("--shop-name 必填")
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
