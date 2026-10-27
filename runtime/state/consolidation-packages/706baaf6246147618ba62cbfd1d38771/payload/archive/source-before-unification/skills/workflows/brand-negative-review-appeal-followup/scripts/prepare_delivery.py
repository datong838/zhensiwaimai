#!/usr/bin/env python3
"""Prepare the initial or next safe delivery event; never opens WeChat."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WECHAT = ROOT.parent.parent / "wechat-messaging"
SCRIPTS = WECHAT / "scripts"
sys.path.insert(0, str(SCRIPTS))
from contract import event_key, item_key, normalize, request_digest  # noqa: E402
from ledger import read_json  # noqa: E402
import render_manifest  # noqa: E402

GROUP = "李老哈（品牌）💰臻肆外卖运营对接群"
SEARCH = "李老哈"
# 与 daily_executor.mjs::SENDABLE_STATUSES 必须逐字一致。
# 「未申诉（已开启自动申诉）」= 2026-10-06 大同指令新增：页面显示未申诉、但平台
# 自动申诉已开启（到点自动发起），故在标记里写明，避免群里误判"无人跟进"。
AUTHORIZED = {"未申诉", "未申诉（已开启自动申诉）", "申诉中", "申诉成功", "差评免责"}
AUTH_REF = "automation-10-user-authorized-brand-negative-appeal-all-outcomes-20260921"
FIELDS = ["记录键", "品牌", "平台", "门店", "评价时间", "评价等级", "申诉结果", "评价内容", "通知正文", "群检索结果", "发送状态", "备注"]

# 授权时效必须**短**：与 wechat-messaging 的 policy_registration.MAX_SCOPE_SECONDS
# (2h) 对齐。此前这里铸 9h 授权 + 8.25h deadline，而策略只接受 ≤2h 的作用域，
# 两者结构性冲突——只有在「铸后 7~9 小时」那一小段窗口才碰巧通过，其余时刻一律
# policy-scope-expiry-invalid 失败关闭（2026-10-02 实测根因：品牌流整个上午全败，
# 而 09-30 只在 17:51 成功过一次）。
# 修法是让铸造对齐策略（短时效），而不是放宽策略的安全属性。
GRANT_SCOPE_SECONDS = 6900  # 1.92h，对 2h 上限留 5 分钟余量


def yesterday_shanghai() -> str:
    now = datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))
    return (now.date() - timedelta(days=1)).isoformat()


def _daily_rows(business_date: str) -> list[dict]:
    path = ROOT / "outputs" / f"{business_date}差评申诉跟进.csv"
    with path.open(encoding="utf-8-sig", newline="") as source:
        rows = list(csv.DictReader(source))
    if not rows or any(row.get("品牌") != SEARCH or row.get("申诉结果") not in AUTHORIZED or not row.get("通知正文") for row in rows):
        raise ValueError("daily-rows-not-all-explicitly-reportable")
    if len({row["记录键"] for row in rows}) != len(rows):
        raise ValueError("daily-record-key-duplicate")
    return rows


def item_id(row: dict) -> str:
    return f"appeal-{row['记录键'][:20]}"


def notice_text_digest(row: dict) -> str:
    """通知正文自身的摘要 —— 历史文本载荷的身份（2026-09-29 及之前）。"""
    return hashlib.sha256(row["通知正文"].encode()).hexdigest()


def notice_image_digest(row: dict) -> str:
    """通知图片的摘要 —— 图片载荷的身份（2026-09-30 起，见 D16）。

    台账缺失该行时现场渲染并登记（新行首次登记的正常路径）；已登记则只读台账，
    绝不重渲染 —— 否则日后调整版式会把历史待核项误判成「载荷被篡改」。
    """
    business_date = row["评价时间"]
    entry = render_manifest.lookup(ROOT, business_date, row["记录键"])
    if entry is None:
        entry = render_manifest.ensure(ROOT, business_date, [row],
                                       item_id_for=item_id)[row["记录键"]]
    return entry["sha256"]


def notice_digest_matches(row: dict, value) -> bool:
    """载荷身份比对：正文摘要或图片摘要任一命中即认。

    先比正文（历史文本件、含 2026-09-26 已存人工审计的绑定），仅在不等时才去
    算图片摘要 —— 避免为纯文本历史行做无谓渲染。两种都是**精确字节比对**，
    判定强度与改动前完全一致。
    """
    if value == notice_text_digest(row):
        return True
    return value == notice_image_digest(row)


def _requests_for_day(business_date: str) -> list[tuple[Path, dict]]:
    found = []
    for path in sorted((ROOT / ".runtime").glob(f"delivery-{business_date}-*/request.json")):
        request = normalize(json.loads(path.read_text(encoding="utf-8")))
        if request["context"]["workflowId"] == "brand-negative-review-appeal-followup":
            found.append((path, request))
    return found


def _item_ledger(request: dict, item: dict) -> tuple[dict | None, bool]:
    work = WECHAT / ".runtime" / "events" / event_key(request) / item_key(request, item)
    delivery = read_json(work / "delivery.json")
    attempted_marker = any(work.rglob("attempt.json")) if work.exists() else False
    return delivery, attempted_marker


def _human_audit_path(business_date: str, target_item_id: str) -> Path:
    return ROOT / ".runtime" / "human-audits" / business_date / target_item_id / "audit.json"


def _load_human_audit(row: dict, requests: list[tuple[Path, dict]]) -> dict | None:
    path = _human_audit_path(row["评价时间"], item_id(row))
    if not path.is_file():
        return None
    audit = json.loads(path.read_text(encoding="utf-8"))
    exact = (audit.get("schemaVersion") == 1
             and audit.get("businessDate") == row["评价时间"]
             and audit.get("recordKey") == row["记录键"]
             and audit.get("itemId") == item_id(row)
             and audit.get("groupName") == GROUP
             and notice_digest_matches(row, audit.get("itemSha256"))
             and audit.get("confirmedDelivered") is True
             and isinstance(audit.get("auditId"), str)
             and isinstance(audit.get("requestDigest"), str)
             and isinstance(audit.get("eventId"), str))
    if not exact:
        raise ValueError("human-audit-binding-invalid")
    evidence = Path(str(audit.get("evidencePath") or ""))
    if (not evidence.is_file() or hashlib.sha256(evidence.read_bytes()).hexdigest()
            != audit.get("evidenceSha256")):
        raise ValueError("human-audit-evidence-mismatch")
    matches = []
    target = item_id(row)
    for _, request in requests:
        for item in request["items"]:
            if item["itemId"] == target:
                receipt, marker = _item_ledger(request, item)
                matches.append((request, item, receipt, marker))
    bound = [entry for entry in matches
             if entry[0]["context"]["eventId"] == audit["eventId"]
             and request_digest(entry[0]) == audit["requestDigest"]
             and entry[0]["groupName"] == audit["groupName"]
             and entry[1]["sha256"] == audit["itemSha256"]]
    # 2026-10-18 修复：调用方（_reconcile_existing）会按「单事件子集」反复调用
    # delivery_state；当子集里不含 audit 绑定的原事件（digest 不匹配）时，
    # 视为该子集无审计可应用，返回 None 而非报错——审计在全量事件视图下才校验。
    if len(bound) == 0 and not any(
            request_digest(entry[0]) == audit["requestDigest"] for entry in matches):
        return None
    if len(bound) != 1:
        raise ValueError("human-audit-event-binding-invalid")
    _, _, receipt, marker = bound[0]
    # 2026-10-18 人工代发通道：confirmationSource=user-confirmed-manual-send-* 表示
    # Windows 自动化卡死后由大同人工补发。该场景机器 sendAttempts 可能为 0
    # （动作前即被拒），attempt 证据=人工发送+群内可见，不要求机器痕迹。
    manual_send = str(audit.get("confirmationSource") or "").startswith("user-confirmed-manual-send-")
    if manual_send:
        if not receipt:
            raise ValueError("human-audit-attempt-not-proven")
        return audit
    if not marker or not receipt or receipt.get("status") not in {"unknown", "partial", "verified", "already_verified"}:
        raise ValueError("human-audit-attempt-not-proven")
    transport = receipt.get("transport") or {}
    if receipt.get("status") not in {"verified", "already_verified"} and transport.get("sendAttempts") != 1:
        raise ValueError("human-audit-send-attempt-not-proven")
    return audit


def delivery_state(row: dict, requests: list[tuple[Path, dict]]) -> tuple[str, dict | None]:
    """Return verified, unresolved, or untouched using the executor's item ledger."""
    matches = []
    target = item_id(row)
    for _, request in requests:
        for item in request["items"]:
            if item["itemId"] == target:
                receipt, marker = _item_ledger(request, item)
                if not notice_digest_matches(row, item.get("sha256")):
                    # 2026-09-29 大同授权「可修改任何门禁 优先确保今日工作完成」：
                    # 同日数据修订（申诉结果从「未申诉」/「未申诉（已开启自动申诉）」
                    # 推进为「申诉中/申诉成功/差评免责」）
                    # 会让同一记录键的通知正文变化。只有在历史载荷「确定从未尝试过
                    # 发送」时才允许被当前正文取代；一旦存在任何尝试痕迹（marker 或
                    # 非零 sendAttempts / attempted 类状态），仍然拒绝——绝不篡改
                    # 可能已经到达微信的载荷。
                    attempted = marker or (receipt is not None and (
                        receipt.get("status") in {"attempted", "unknown", "partial",
                                                  "verified", "already_verified"}
                        or not isinstance(receipt.get("sendAttempts"), int)
                        or receipt.get("sendAttempts") != 0))
                    if attempted:
                        raise ValueError("ledger-payload-digest-conflict")
                    continue
                matches.append((receipt, marker))
    if not matches:
        return "untouched", None
    verified = any(receipt and receipt.get("status") in {"verified", "already_verified"} for receipt, _ in matches)
    unresolved = False
    for receipt, marker in matches:
        if receipt and receipt.get("status") in {"verified", "already_verified"}:
            continue
        if marker or (receipt and (receipt.get("status") in {"attempted", "unknown", "partial"}
                                   or not isinstance(receipt.get("sendAttempts"), int)
                                   or receipt.get("sendAttempts") != 0)):
            unresolved = True
    if verified and unresolved:
        raise ValueError("item-ledger-conflict")
    if verified:
        return "verified", next(receipt for receipt, _ in matches if receipt and receipt.get("status") in {"verified", "already_verified"})
    audit = _load_human_audit(row, requests)
    if audit:
        return "human-confirmed-delivered", audit
    for receipt, marker in matches:
        if marker or not receipt:
            if marker:
                return "unresolved", receipt
            continue
        status, attempts = receipt.get("status"), receipt.get("sendAttempts")
        if status in {"attempted", "unknown", "partial"} or not isinstance(attempts, int) or attempts != 0:
            return "unresolved", receipt
    return "untouched", next((receipt for receipt, _ in matches if receipt), None)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.chmod(0o600)
    temp.replace(path)


def _same_frozen_items(left: dict, right: dict) -> bool:
    return (left.get("groupName") == right.get("groupName")
            and left.get("items") == right.get("items")
            and {key: value for key, value in left.get("context", {}).items() if key != "deadlineAt"}
                == {key: value for key, value in right.get("context", {}).items() if key != "deadlineAt"})


def prepare_next(*, now: int | None = None, business_date: str | None = None) -> dict:
    """Freeze only never-attempted items into a deterministic, idempotent event."""
    now = int(time.time()) if now is None else now
    business_date = business_date or yesterday_shanghai()
    rows = _daily_rows(business_date)
    prior_requests = _requests_for_day(business_date)
    states = {item_id(row): delivery_state(row, prior_requests) for row in rows}
    unresolved = [key for key, (state, _) in states.items() if state == "unresolved"]
    if unresolved:
        raise ValueError("prior-attempts-require-reconcile:" + ",".join(unresolved))
    pending = [row for row in rows if states[item_id(row)][0] == "untouched"]
    if not pending:
        return {"ok": True, "status": "complete", "records": 0, "sendAttempts": 0,
                "businessDate": business_date, "request": None, "authorization": None}
    if len(pending) > 20:
        raise ValueError("items-count-invalid")

    pending_ids = [item_id(row) for row in pending]
    # 先确保当天全部通知图片已渲染并登记（幂等）：台账是图片条目的身份来源。
    renders = render_manifest.ensure(ROOT, business_date, rows, item_id_for=item_id)

    # 复用判定的比较对象必须走**同一个 normalize**，不能手搓形状：
    # 手搓会漏掉 normalize 的路径归一（resolve）。macOS 临时目录是
    # /var → /private/var 的符号链接，两侧 path 不等 ⇒「同一载荷」判定永远为假
    # ⇒ 本可复用的续发请求被重复创建成新事件（同一行重复投递的风险）。
    def frozen_candidate(context: dict) -> dict:
        return normalize({"schemaVersion": 1, "operation": "send", "groupName": GROUP,
                          "items": [{"itemId": item_id(row), "type": "image",
                                     "path": renders[row["记录键"]]["path"]} for row in pending],
                          "context": context})

    # Reuse a previously frozen, still-unattempted request instead of creating a
    # second event when the controller is resumed before the first send.
    for prior_path, prior in reversed(prior_requests):
        if ([item["itemId"] for item in prior["items"]] == pending_ids
                and _same_frozen_items(prior, frozen_candidate(prior["context"]))):
            grant_path = prior_path.parent / "authorization.json"
            grant = json.loads(grant_path.read_text(encoding="utf-8"))
            if grant.get("expiresAt", 0) > now and prior["context"]["deadlineAt"] > now:
                return {"ok": True, "status": "reused", "businessDate": business_date,
                        "records": len(prior["items"]), "request": str(prior_path),
                        "authorization": str(grant_path), "requestDigest": request_digest(prior),
                        "eventId": prior["context"]["eventId"], "sendAttempts": 0}

    if prior_requests:
        parent_identity = "|".join(sorted(request_digest(request) for _, request in prior_requests))
        mode = "continuation"
        event_suffix = hashlib.sha256((business_date + "|" + parent_identity + "|" + "|".join(pending_ids)).encode()).hexdigest()[:16]
        event_id = f"brand-negative-appeal-{business_date}-all-outcomes-continuation-{event_suffix}"
        directory_suffix = f"continuation-{event_suffix}"
    else:
        mode = "initial"
        event_id = f"brand-negative-appeal-{business_date}-all-outcomes-v1"
        directory_suffix = "all-outcomes-v1"
    # D16：改以图片投递 —— Windows 驱动逐字键盘注入敲不进 `\n`，文本多行必被压平。
    items = [{"itemId": item_id(row), "type": "image",
              "path": renders[row["记录键"]]["path"]} for row in pending]
    request = normalize({
        "schemaVersion": 1, "operation": "send", "groupName": GROUP, "items": items,
        "context": {"workflowId": "brand-negative-review-appeal-followup", "eventId": event_id,
                    "accountAlias": "main-wechat", "channel": "desktop",
                    "deadlineAt": now + GRANT_SCOPE_SECONDS,
                    "searchGroupName": SEARCH},
    })
    digest = request_digest(request)
    out = ROOT / ".runtime" / f"delivery-{business_date}-{directory_suffix}"
    request_path, authorization_path = out / "request.json", out / "authorization.json"
    if out.exists():
        saved = normalize(json.loads(request_path.read_text(encoding="utf-8")))
        if not _same_frozen_items(saved, request):
            raise ValueError("continuation-event-payload-conflict")
        grant = json.loads(authorization_path.read_text(encoding="utf-8"))
        if grant.get("expiresAt", 0) <= now or saved["context"]["deadlineAt"] <= now:
            raise ValueError("continuation-event-expired")
        return {"ok": True, "status": "reused", "businessDate": business_date,
                "records": len(items), "request": str(request_path),
                "authorization": str(authorization_path), "requestDigest": request_digest(saved),
                "eventId": event_id, "sendAttempts": 0}
    out.mkdir(parents=True, exist_ok=False, mode=0o700)
    raw = {"schemaVersion": 1, "operation": "send", "groupName": GROUP, "items": items,
           "context": request["context"]}
    grant = {"schemaVersion": 1, "requestDigest": digest, "accountAlias": "main-wechat",
             "groupName": GROUP, "channel": "desktop", "expiresAt": now + GRANT_SCOPE_SECONDS,
             "authorizationRef": AUTH_REF}
    _atomic_json(request_path, raw)
    _atomic_json(authorization_path, grant)
    check = normalize(json.loads(request_path.read_text(encoding="utf-8")))
    if request_digest(check) != digest or json.loads(authorization_path.read_text(encoding="utf-8")) != grant:
        raise ValueError("frozen-request-readback-mismatch")
    return {"ok": True, "status": "prepared", "businessDate": business_date,
            "records": len(items), "request": str(request_path),
            "authorization": str(authorization_path), "requestDigest": digest,
            "eventId": event_id, "sendAttempts": 0}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        if item_id({"记录键": "a" * 64}) != "appeal-" + "a" * 20:
            raise SystemExit("self-test-failed")
        print(json.dumps({"ok": True, "runtimeModelDecisions": 0}))
        return 0
    try:
        result = prepare_next()
    except Exception as error:
        result = {"ok": False, "status": "blocked", "reason": str(error),
                  "sendAttempts": 0, "runtimeModelDecisions": 0}
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
