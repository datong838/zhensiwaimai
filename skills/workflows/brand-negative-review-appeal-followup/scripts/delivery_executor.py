#!/usr/bin/env python3
"""Deterministic brand-review delivery loop; all WeChat effects stay in executor.py."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WECHAT = ROOT.parent.parent / "wechat-messaging"
SCRIPTS = WECHAT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import heartbeat_recovery  # noqa: E402
import policy_registration  # noqa: E402
from contract import file_hash, normalize, request_digest  # noqa: E402
from prepare_delivery import (FIELDS, _daily_rows, _human_audit_path, _item_ledger,
                              _requests_for_day, delivery_state, item_id, prepare_next)  # noqa: E402

EXECUTOR = SCRIPTS / "executor.py"
MAX_EVENTS = 20


def _windows_run(action: str, request_path: Path, authorization_path: Path) -> dict:
    """2026-09-30 通道切换：进程内以 WindowsAdapter 直跑 deliver 引擎。

    桌面微信不再给 AI 使用；封印的 executor.py CLI 只能路由 Mac 桌面适配器，
    故在此以同一合同（normalize + check_grant + deliver）走 Windows 驱动传输。
    返回结构与 heartbeat_recovery.run 保持一致（ok/status/reason/sendAttempts/
    initial/final/review/reviewSummary/elapsedMs）。
    """
    import time as _time
    from contract import check_grant, normalize
    from executor import deliver
    from wecom_adapter import WeComAdapter as WindowsAdapter  # 2026-10-23 channel switch → 企微

    started = _time.monotonic()
    result = {"ok": False, "action": action, "status": "blocked", "recoveryUsed": False,
              "sendAttempts": 0, "runtimeModelDecisions": 0, "review": [],
              "transport": "windows-driver"}

    def stage(name, fn):
        tick = _time.monotonic()
        row = {"stage": name, "status": "running", "pitfalls": []}
        result["review"].append(row)
        try:
            value = fn()
            row["status"] = "completed" if value.get("ok") else "failed"
            if not value.get("ok"):
                row["pitfalls"] = [str(value.get("reason") or value.get("status"))]
            return value
        except Exception as error:
            row.update(status="failed", pitfalls=[str(error)])
            return {"ok": False, "status": "blocked", "reason": str(error), "sendAttempts": None}
        finally:
            row["elapsedMs"] = round((_time.monotonic() - tick) * 1000)

    def _run_once():
        request = normalize(json.loads(Path(request_path).read_text(encoding="utf-8")))
        grant = json.loads(Path(authorization_path).read_text(encoding="utf-8"))
        check_grant(request, grant)
        return deliver(request, grant, WECHAT / ".runtime", WindowsAdapter(),
                       reconcile=(action == "reconcile"))

    final = stage(f"Windows 传输执行:{action}", _run_once)
    result["initial"] = final
    result["final"] = final
    counts = [final.get("sendAttempts")] + [i.get("sendAttempts") for i in final.get("items", [])]
    known = [c for c in counts if isinstance(c, int) and c >= 0]
    result["sendAttempts"] = max(known) if known else -1
    result.update(ok=bool(final.get("ok")), status=final.get("status", "blocked"),
                  reason=final.get("reason"))
    result["elapsedMs"] = round((_time.monotonic() - started) * 1000)
    result["reviewSummary"] = {"totalElapsedMs": result["elapsedMs"], "result": result["status"],
                               "stageCount": len(result["review"]),
                               "failedStages": [r["stage"] for r in result["review"]
                                                if r["status"] == "failed"]}
    return result


def _now_shanghai_yesterday() -> str:
    today = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).date()
    return (today - timedelta(days=1)).isoformat()


def _explicit_zero(result: dict) -> bool:
    if result.get("sendAttempts") != 0:
        return False
    for item in result.get("items", []):
        if item.get("sendAttempts") != 0 or item.get("status") in {"attempted", "unknown", "partial"}:
            return False
    return True


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, name = tempfile.mkstemp(dir=path.parent, prefix="." + path.name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            json.dump(value, target, ensure_ascii=False, indent=2)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _archive_untracked_summary(path: Path, archive_dir: Path) -> Path | None:
    """Preserve the legacy fixed summary byte-for-byte before its first replacement."""
    if not path.is_file():
        return None
    previous = json.loads(path.read_text(encoding="utf-8"))
    payload = path.read_bytes()
    archived_path = previous.get("summaryArchivePath")
    if archived_path:
        prior_archive = Path(archived_path)
        if prior_archive.is_file() and prior_archive.read_bytes() == payload:
            return prior_archive
    archive_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = hashlib.sha256(payload).hexdigest()[:12]
    archive_path = archive_dir / f"legacy-{time.time_ns()}-{digest}.json"
    fd, name = tempfile.mkstemp(dir=archive_dir, prefix=".legacy-")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(name, archive_path)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    if archive_path.read_bytes() != payload:
        raise ValueError("prior-workflow-summary-archive-readback-mismatch")
    return archive_path


def project_csv(business_date: str) -> dict:
    """Project only authoritative item receipts; keep unknown distinct from unsent."""
    source = ROOT / "outputs" / f"{business_date}差评申诉跟进.csv"
    requests = _requests_for_day(business_date)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or list(rows[0]) != FIELDS:
        raise ValueError("daily-csv-schema-mismatch")
    changed = 0
    counts = {"已发送": 0, "核验未知": 0, "未发送": 0}
    evidence_counts = {"machineVerified": 0, "humanConfirmedDelivered": 0,
                       "needsReconcile": 0, "untouched": 0}
    for row in rows:
        state, receipt = delivery_state(row, requests)
        if state == "verified":
            desired_status = "已发送"
            row["备注"] = "统一执行器回执核验 verified/already_verified"
            evidence_counts["machineVerified"] += 1
        elif state == "human-confirmed-delivered":
            desired_status = "核验未知"
            row["备注"] = f"用户人工核验截图确认已送达；机器原文回读仍未知；审计引用:{receipt.get('auditId')}"
            evidence_counts["humanConfirmedDelivered"] += 1
        elif state == "unresolved":
            desired_status = "核验未知"
            row["备注"] = str((receipt or {}).get("reason") or "存在发送尝试；须只读对账，禁止重发")
            evidence_counts["needsReconcile"] += 1
        else:
            # The executor ledger is authoritative; never trust a stale CSV success mark.
            desired_status = "未发送"
            evidence_counts["untouched"] += 1
        if row["发送状态"] != desired_status:
            row["发送状态"] = desired_status
            changed += 1
        if row["发送状态"] not in counts:
            raise ValueError("daily-csv-status-invalid")
        counts[row["发送状态"]] += 1
    fd, name = tempfile.mkstemp(dir=source.parent, prefix="." + source.name, suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(name, source)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    with source.open(encoding="utf-8-sig", newline="") as handle:
        roundtrip = list(csv.DictReader(handle))
    if (len(roundtrip) != len(rows)
            or any(roundtrip[index] != rows[index] for index in range(len(rows)))):
        raise ValueError("daily-csv-projection-readback-mismatch")
    return {"changed": changed, "counts": counts, "evidenceCounts": evidence_counts}


def _call_preflight(request_path: Path) -> dict:
    import subprocess
    process = subprocess.run([sys.executable, str(EXECUTOR), "preflight", "--request", str(request_path)],
                             cwd=WECHAT, text=True, capture_output=True, timeout=90)
    lines = [line for line in (process.stdout or "").splitlines() if line.strip()]
    if not lines:
        return {"ok": False, "reason": "preflight-no-json", "sendAttempts": None,
                "returnCode": process.returncode}
    try:
        result = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"ok": False, "reason": "preflight-invalid-json", "sendAttempts": None,
                "returnCode": process.returncode}
    result["returnCode"] = process.returncode
    return result


def _register_policy(request_path: Path, authorization_path: Path) -> dict:
    event_id = normalize(json.loads(request_path.read_text(encoding="utf-8")))["context"]["eventId"]
    output = ROOT / ".runtime" / "policy-registration" / f"{event_id}-{time.time_ns()}"
    return policy_registration.prepare(request_path, authorization_path, output)


def _safe_delivery_summary(delivery: dict) -> dict:
    return {"ok": delivery.get("ok"), "status": delivery.get("status"),
            "reason": delivery.get("reason"), "sendAttempts": delivery.get("sendAttempts"),
            "elapsedMs": delivery.get("elapsedMs"), "returnCode": delivery.get("returnCode"),
            "items": [{key: item.get(key) for key in
                       ("itemId", "status", "sendAttempts", "verificationLevel", "reason")
                       if key in item} for item in delivery.get("items", [])],
            "review": delivery.get("review", [])}


def _attempted_item_ids(request: dict, delivery: dict) -> set[str]:
    """Identify only items with explicit send evidence before read-only reconcile."""
    attempted = set()
    for item in delivery.get("items", []):
        attempts = item.get("sendAttempts")
        if (item.get("status") in {"attempted", "unknown", "partial"}
                or (isinstance(attempts, int) and attempts > 0)):
            attempted.add(item.get("itemId"))
    for item in request["items"]:
        receipt, marker = _item_ledger(request, item)
        transport = (receipt or {}).get("transport") or {}
        attempts = transport.get("sendAttempts", (receipt or {}).get("sendAttempts"))
        if (marker or (receipt or {}).get("status") in {"attempted", "unknown", "partial"}
                or (isinstance(attempts, int) and attempts > 0)):
            attempted.add(item["itemId"])
    attempted.discard(None)
    return attempted


def _record_human_audits(business_date: str, confirmed_item_ids: list[str], evidence_path: str) -> dict:
    """Persist user-confirmed delivery evidence solely to prevent a duplicate send."""
    if not confirmed_item_ids:
        return {"ok": True, "status": "not-requested", "items": [], "sendAttempts": 0}
    if len(set(confirmed_item_ids)) != len(confirmed_item_ids):
        return {"ok": False, "reason": "human-audit-duplicate-item", "sendAttempts": 0}
    evidence = Path(evidence_path).expanduser().resolve()
    if not evidence.is_file():
        return {"ok": False, "reason": "human-audit-evidence-missing", "sendAttempts": 0}
    evidence_sha = file_hash(evidence)
    rows = _daily_rows(business_date)
    requests = _requests_for_day(business_date)
    records = []
    for target in confirmed_item_ids:
        candidates = [row for row in rows if item_id(row) == target]
        if len(candidates) != 1:
            return {"ok": False, "reason": "human-audit-item-not-unique", "sendAttempts": 0}
        row = candidates[0]
        state, _ = delivery_state(row, requests)
        if state == "human-confirmed-delivered":
            prior_audit = delivery_state(row, requests)[1]
            if prior_audit.get("evidenceSha256") == evidence_sha:
                records.append({"itemId": target, "auditId": prior_audit["auditId"], "status": "reused"})
                continue
            return {"ok": False, "reason": "human-audit-evidence-conflict", "sendAttempts": 0}
        if state != "unresolved":
            return {"ok": False, "reason": "human-audit-item-not-unresolved", "sendAttempts": 0}
        matches = []
        for request_path, request in requests:
            for item in request["items"]:
                if item["itemId"] == target:
                    receipt, marker = _item_ledger(request, item)
                    matches.append((request_path, request, item, receipt, marker))
        if len(matches) != 1:
            return {"ok": False, "reason": "human-audit-source-event-not-unique", "sendAttempts": 0}
        _, request, item, receipt, marker = matches[0]
        transport = (receipt or {}).get("transport") or {}
        if ((receipt or {}).get("status") not in {"unknown", "partial"}
                or not marker or transport.get("sendAttempts") != 1):
            return {"ok": False, "reason": "human-audit-attempt-not-proven", "sendAttempts": 0}

        target_dir = _human_audit_path(business_date, target).parent
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        stored_evidence = target_dir / "evidence.png"
        audit_path = target_dir / "audit.json"
        audit = {"schemaVersion": 1, "businessDate": business_date,
                 "recordKey": row["记录键"], "itemId": target,
                 "eventId": request["context"]["eventId"],
                 "requestDigest": request_digest(request),
                 "groupName": request["groupName"], "itemSha256": item["sha256"],
                 "confirmedDelivered": True,
                 "confirmationSource": "user-confirmed-attached-screenshot",
                 "evidenceSha256": evidence_sha,
                 "userConfirmation": "用户明确确认该条已发送；所附群聊截图显示该通知",
                 "recordedAtUtc": datetime.now(timezone.utc).isoformat()}
        identity = {key: audit[key] for key in ("schemaVersion", "businessDate", "recordKey", "itemId",
                    "eventId", "requestDigest", "groupName", "itemSha256", "confirmedDelivered",
                    "confirmationSource", "evidenceSha256", "userConfirmation")}
        audit_id = hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                             separators=(",", ":")).encode()).hexdigest()
        audit["auditId"] = audit_id
        if audit_path.exists():
            prior = json.loads(audit_path.read_text(encoding="utf-8"))
            if prior.get("auditId") != audit_id:
                return {"ok": False, "reason": "human-audit-evidence-conflict", "sendAttempts": 0}
            if not stored_evidence.is_file() or file_hash(stored_evidence) != evidence_sha:
                return {"ok": False, "reason": "human-audit-evidence-conflict", "sendAttempts": 0}
            records.append({"itemId": target, "auditId": audit_id, "status": "reused"})
            continue
        fd, name = tempfile.mkstemp(dir=target_dir, prefix=".evidence-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as output, evidence.open("rb") as source:
                shutil.copyfileobj(source, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(name, stored_evidence)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        audit["evidencePath"] = str(stored_evidence)
        _write_json(audit_path, audit)
        state, checked = delivery_state(row, requests)
        if state != "human-confirmed-delivered" or checked.get("auditId") != audit_id:
            return {"ok": False, "reason": "human-audit-readback-failed", "sendAttempts": 0}
        records.append({"itemId": target, "auditId": audit_id, "status": "recorded"})
    return {"ok": True, "status": "recorded", "items": records, "sendAttempts": 0}


def _epoch_now() -> int:
    """Wall-clock epoch seconds. 可打桩的时间缝：测试用假纪元造授权，生产用真实时间。"""
    return int(time.time())


def _reconcile_existing(business_date: str, result: dict, stage) -> bool:
    """Resolve prior attempts before registering a new digest or creating a continuation."""
    rows = _daily_rows(business_date)
    for request_path, request in _requests_for_day(business_date):
        unresolved = [row for row in rows if row["记录键"] and
                      any(item["itemId"] == f"appeal-{row['记录键'][:20]}"
                          and delivery_state(row, [(request_path, request)])[0] == "unresolved"
                          for item in request["items"])]
        if not unresolved:
            continue
        authorization_path = request_path.parent / "authorization.json"
        if not authorization_path.is_file():
            result.update(status="blocked", reason="prior-authorization-missing")
            return False
        policy = stage(f"原事件策略精确回登:{request['context']['eventId']}",
                       lambda p=request_path, a=authorization_path: _register_policy(p, a))
        if not policy.get("ok"):
            # 2026-09-30 大同授权「过期视为事件关闭」：混合场景（部分事件授权过期、
            # 部分仍有效）下，过期事件记录关闭并跳过，不再阻断其余事件的对账；
            # 全部过期的情况由 run() 入口守卫统一以 skipped 收口。
            if policy.get("reason") == "authorization-or-request-expired":
                result["events"].append({"eventId": request["context"]["eventId"],
                                         "closed": "prior-event-authorization-expired"})
                continue
            result.update(status="blocked", reason=policy.get("reason") or "prior-policy-registration-failed")
            return False
        reconciled = stage(f"原事件只读对账:{request['context']['eventId']}",
                           lambda p=request_path, a=authorization_path:
                           _windows_run("reconcile", p, a))
        result["events"].append({"eventId": request["context"]["eventId"],
                                 "requestDigest": reconciled.get("requestDigest"),
                                 "reconcile": reconciled})
        states = {row["记录键"]: delivery_state(row, _requests_for_day(business_date))[0] for row in rows}
        stage("CSV回执状态投影", lambda: {"ok": True, **project_csv(business_date)})
        if any(state == "unresolved" for state in states.values()):
            result.update(status="unknown", reason="prior-attempt-still-unknown", itemStates=states)
            return False
    return True


def run(*, business_date: str | None = None, clock=time.monotonic,
        human_confirmed_items: list[str] | None = None,
        human_audit_evidence: str | None = None) -> dict:
    started = clock()
    business_date = business_date or _now_shanghai_yesterday()
    result = {"ok": False, "status": "blocked", "businessDate": business_date,
              "runtimeModelDecisions": 0, "review": [], "events": []}

    def stage(name, fn):
        tick = clock()
        try:
            value = fn()
            status = "completed" if value.get("ok") else "failed"
            pitfalls = [] if status == "completed" else [str(value.get("reason") or value.get("status"))]
            result["review"].append({"stage": name, "status": status,
                                     "elapsedMs": round((clock() - tick) * 1000), "pitfalls": pitfalls})
            return value
        except Exception as error:
            result["review"].append({"stage": name, "status": "failed",
                                     "elapsedMs": round((clock() - tick) * 1000),
                                     "pitfalls": [str(error)]})
            return {"ok": False, "status": "blocked", "reason": str(error)}

    try:
        rows = stage("读取并校验日报", lambda: {"ok": True, "rows": _daily_rows(business_date)})
        if not rows.get("ok"):
            result.update(reason=rows.get("reason"), status="blocked")
            return _finish(result, started, clock)
        rows = rows["rows"]
        confirmed = human_confirmed_items or []
        if bool(confirmed) != bool(human_audit_evidence):
            result.update(status="blocked", reason="human-audit-item-and-evidence-required-together")
            return _finish(result, started, clock)
        if confirmed:
            audit = stage("记录用户截图人工核验", lambda: _record_human_audits(
                business_date, confirmed, human_audit_evidence))
            result["humanAudit"] = {key: audit.get(key) for key in ("status", "items", "reason") if key in audit}
            if not audit.get("ok"):
                result.update(reason=audit.get("reason"), status="blocked")
                return _finish(result, started, clock)
        # 2026-09-30 大同授权「过期视为事件关闭」：当天全部事件的授权窗口（1 小时）
        # 均已过期时，历史事件无法再对账、也不再重放（重放等价于签发新授权），
        # 该轮以 skipped 收口（ok=True，不计 FAILED），等业务日期自然滚动到新一天
        # 再走正常流程；未投递的通知随事件一并关闭。
        day_requests = _requests_for_day(business_date)

        def _grant_expired(request_path: Path) -> bool:
            try:
                grant = json.loads((request_path.parent / "authorization.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return False
            return not _epoch_now() < grant.get("expiresAt", 0)

        if day_requests and all(_grant_expired(path) for path, _ in day_requests):
            states = {row["记录键"]: delivery_state(row, day_requests)[0] for row in rows}
            result.update(ok=True, status="skipped",
                          reason="prior-event-authorization-expired-event-closed",
                          closedEvents=sorted({req["context"]["eventId"] for _, req in day_requests}),
                          itemStates=states, sendAttempts=0)
            return _finish(result, started, clock)
        if not _reconcile_existing(business_date, result, stage):
            return _finish(result, started, clock)
        for event_number in range(MAX_EVENTS):
            prepared = stage("冻结初始/续发请求", lambda: prepare_next(business_date=business_date))
            if not prepared.get("ok"):
                result.update(reason=prepared.get("reason"), status=prepared.get("status", "blocked"))
                break
            if prepared.get("status") == "complete":
                projection = stage("CSV回执状态投影", lambda: {"ok": True, **project_csv(business_date)})
                result.update(ok=projection.get("ok", False), status="complete" if projection.get("ok") else "blocked",
                              csv=projection, reason=projection.get("reason"))
                break
            request_path = Path(prepared["request"])
            authorization_path = Path(prepared["authorization"])
            request = normalize(json.loads(request_path.read_text(encoding="utf-8")))
            policy = stage("精确请求策略登记", lambda: _register_policy(request_path, authorization_path))
            if not policy.get("ok"):
                result.update(reason=policy.get("reason"), status="blocked")
                break

            execute_stage_name = f"总执行器执行:{request['context']['eventId']}"
            delivery = stage(execute_stage_name,
                             lambda: _windows_run("execute", request_path, authorization_path))
            execute_review = result["review"][-1]
            # One bounded, read-only re-sample for the observed stale-composer gate.
            if (not delivery.get("ok") and delivery.get("reason") == "current-group-composer-not-empty"
                    and _explicit_zero(delivery.get("initial", {}))):
                preflight = stage("同一当前群只读空框复采样", lambda: _call_preflight(request_path))
                if (preflight.get("ok") and preflight.get("group") == request["groupName"]
                        and preflight.get("groupTypeVerified") is True
                        and preflight.get("composerVerifiedEmpty") is True):
                    delivery = stage(f"总执行器一次受控续跑:{request['context']['eventId']}",
                                     lambda: _windows_run("execute", request_path, authorization_path))
                else:
                    delivery = {"ok": False, "status": "blocked", "reason": "composer-resample-not-proven-empty",
                                "sendAttempts": 0, "initial": delivery}

            if delivery.get("status") in {"unknown", "partial"} or any(
                    item.get("status") in {"attempted", "unknown", "partial"} for item in delivery.get("items", [])):
                # Reconcile before registering another digest; this preserves the active exact policy scope.
                attempted_item_ids = _attempted_item_ids(request, delivery)
                reconcile_stage_name = f"只读对账:{request['context']['eventId']}"
                delivery = stage(reconcile_stage_name,
                                 lambda: _windows_run("reconcile", request_path, authorization_path))
                if delivery.get("ok") and delivery.get("status") in {"verified", "already_verified"}:
                    reconcile_states = {
                        item["itemId"]: next((delivery_state(row, [(request_path, request)])[0]
                                              for row in rows if item_id(row) == item["itemId"]), "missing")
                        for item in request["items"]
                    }
                    execute_review["reconcileItemStates"] = reconcile_states
                    if (attempted_item_ids and all(reconcile_states.get(item_id) == "verified"
                                                   for item_id in attempted_item_ids)):
                        execute_review["recoveredBy"] = reconcile_stage_name
            result["events"].append({"eventId": request["context"]["eventId"],
                                     "requestDigest": prepared["requestDigest"],
                                     "result": _safe_delivery_summary(delivery)})
            projection = stage("CSV回执状态投影", lambda: {"ok": True, **project_csv(business_date)})
            if not projection.get("ok"):
                result.update(reason=projection.get("reason"), status="blocked")
                break
            requests = _requests_for_day(business_date)
            states = {row["记录键"]: delivery_state(row, requests)[0] for row in rows}
            if any(state == "unresolved" for state in states.values()):
                result.update(status="unknown", reason="attempted-items-still-require-reconcile",
                              csv=projection, itemStates=states)
                break
            if all(state == "verified" for state in states.values()):
                result.update(ok=True, status="complete", csv=projection, itemStates=states)
                break
            if not delivery.get("ok") and delivery.get("status") not in {"partial", "unknown"}:
                result.update(status=delivery.get("status", "blocked"),
                              reason=delivery.get("reason"), csv=projection, itemStates=states)
                break
        else:
            result.update(status="blocked", reason="continuation-event-limit-reached")
    except Exception as error:
        result.update(ok=False, status="blocked", reason=str(error))
    return _finish(result, started, clock)


def _finish(result: dict, started, clock):
    result["elapsedMs"] = round((clock() - started) * 1000)
    review_pitfalls = []
    recovered_pitfalls = []
    for row in result.get("review", []):
        for pitfall in row.get("pitfalls", []):
            finding = {"stage": row.get("stage"), "code": pitfall}
            if row.get("recoveredBy"):
                finding["recoveredBy"] = row["recoveredBy"]
                recovered_pitfalls.append(finding)
            else:
                review_pitfalls.append(finding)
    csv_result = result.get("csv") or {}
    result["completionReview"] = {"codeEnforced": True, "totalElapsedMs": result["elapsedMs"],
                                  "result": result.get("status"), "reviewItems": result.get("review", []),
                                  "deliveryEvidenceCounts": csv_result.get("evidenceCounts"),
                                  "businessWorkComplete": (result.get("status") == "complete"
                                                           and not (csv_result.get("evidenceCounts") or {}).get("needsReconcile", 0)
                                                           and not (csv_result.get("evidenceCounts") or {}).get("untouched", 0)),
                                  "recoveredPitfalls": recovered_pitfalls,
                                  "unresolvedPitfalls": review_pitfalls}
    business_date = result.get("businessDate")
    if business_date:
        path = ROOT / ".runtime" / f"delivery-{business_date}-workflow-summary.json"
        archive_dir = ROOT / ".runtime" / "delivery-run-history" / business_date
        _archive_untracked_summary(path, archive_dir)
        archive_path = archive_dir / f"{time.time_ns()}-{uuid.uuid4().hex[:12]}.json"
        result["summaryPath"] = str(path)
        result["summaryArchivePath"] = str(archive_path)
        _write_json(archive_path, result)
        _write_json(path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--human-confirmed-delivered-item", action="append", default=[])
    parser.add_argument("--human-audit-evidence")
    args = parser.parse_args()
    if args.self_test:
        assert _explicit_zero({"sendAttempts": 0, "items": [{"sendAttempts": 0, "status": "blocked"}]})
        assert not _explicit_zero({"sendAttempts": 0, "items": [{"sendAttempts": None, "status": "unknown"}]})
        print(json.dumps({"ok": True, "runtimeModelDecisions": 0}))
        return 0
    result = run(human_confirmed_items=args.human_confirmed_delivered_item,
                 human_audit_evidence=args.human_audit_evidence)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
