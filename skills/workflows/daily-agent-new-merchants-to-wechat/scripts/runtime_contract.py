"""Executable runtime policy and receipt-derived reviews; no UI actions here."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

PRODUCTION_AUTHORIZATION = "user-20260915-production-hourly"
STAGES = {
    "executor_integrity": "封板完整性",
    "runtime_policy": "授权、群与通道门禁",
    "offline_selftest": "离线自测",
    "collection": "商家采集",
    "audit": "采集合同审计",
    "day_dispatch": "当日派发与历史待核隔离",
    "empty_notice": "半小时无新增意向商家通知",
    "desktop_wechat_preflight": "桌面微信预检",
    "desktop_wechat": "逐条通知",
    "phone": "手机通知",
    "final_cursor_check": "最终账本与游标复核",
    "reseal": "真实非空验收重封",
}
TRANSIENT_NAVIGATION = frozenset({"agent-menu-count:0", "intention-list-not-open",
                                 "customer-menu-not-ready", "service-shell-not-ready"})


def collection_label(phase):
    names = {"background_preflight": "后台浏览器预检", "task_page": "建立独立任务页",
             "navigation": "进入意向商户列表", "date_filter": "日期设置与双帧回读"}
    if phase in names:
        return names[phase]
    page = re.fullmatch(r"page_(\d+)_(read|next)", phase)
    if page:
        return f"第{page[1]}页" + ("采集与稳定核验" if page[2] == "read" else "翻页")
    return "商家详情核验 " + phase[7:] if phase.startswith("detail_") else phase


def validate_policy(args, sender):
    if args.group != sender.PRODUCTION_GROUP:
        raise RuntimeError("production-only-target-required")
    expected = {sender.PRODUCTION_GROUP: PRODUCTION_AUTHORIZATION,
                sender.TEST_GROUP: sender.TEST_AUTHORIZATION}
    if args.group not in expected or args.standing_authorization != expected[args.group]:
        raise RuntimeError("runtime-authorization-group-mismatch")
    if args.group == sender.PRODUCTION_GROUP and args.wechat_channel != "desktop":
        raise RuntimeError("production-channel-must-be-desktop")
    for value, minimum, maximum in [(args.wechat_contention_wait_seconds, 0, 900),
                                     (args.wechat_contention_poll_seconds, 1, 5)]:
        if not math.isfinite(value) or not minimum <= value <= maximum:
            raise RuntimeError("runtime-contention-budget-invalid")
    return {"ok": True, "group": args.group, "channel": args.wechat_channel,
            "cursorFile": str(sender.cursor_file(args.group)), "maxCollectionAttempts": 2,
            "collectionBudgetSeconds": 180}


def offline_selftest(sender, collector, attempts: int = 2):
    """离线自检（只读、幂等）。

    2026-10-23 19:10：daemon 内出现**间歇性** `browser-selftest-invalid-receipt`
    （19:01:28 elapsedMs=214、19:09:12 elapsedMs=168，而本机跑同一份只需 408ms 且稳定
    通过 ⇒ 子进程根本没起来，不是断言失败）。因为该自检是幂等只读操作，失败一次就
    整档失败会把一轮真实增量白白丢掉（当天实测连续 4 档空转）。
    ⇒ 未拿到合法回执时重试一次，并把每次的 rc/stdout/stderr 尾巴拼进异常消息，
    下次复发即可直接定位（无需再加探针）。
    """
    local = sender.self_test()
    if local.get("ok") is not True:
        raise RuntimeError("sender-selftest-failed")
    failures = []
    for attempt in range(1, max(1, attempts) + 1):
        completed = subprocess.run(
            [collector.NODE, str(Path(__file__).with_name("test_background_merchant_collector.mjs"))],
            capture_output=True, text=True, timeout=30)
        try:
            browser = json.loads(completed.stdout.strip().splitlines()[-1])
        except (ValueError, IndexError):
            failures.append({"attempt": attempt, "rc": completed.returncode,
                             "out": (completed.stdout or "")[-200:],
                             "err": (completed.stderr or "")[-200:]})
            if attempt < attempts:
                time.sleep(1.0)
            continue
        if completed.returncode or browser.get("ok") is not True:
            raise RuntimeError("browser-selftest-failed")
        return {"ok": True, "senderTests": local["tests"], "browserTests": browser["tests"],
                "selftestAttempts": attempt}
    raise RuntimeError("browser-selftest-invalid-receipt:"
                       + json.dumps(failures, ensure_ascii=False)[:320])


def may_retry_collection(receipt, attempt, remaining_seconds):
    return (attempt == 1 and remaining_seconds > 1 and receipt.get("ok") is False
            and receipt.get("stageResults", {}).get("navigation") == "FAIL"
            and receipt.get("error") in TRANSIENT_NAVIGATION)


def verify_delivery(receipt, group, item):

    # UI-post evidence is explicit and separately labeled; never reinterpret the old wrong tail.
    ui = receipt.get('uiPostReadback')
    if ui is None:
        for row in (receipt.get('commonReceipt') or {}).get('items', []):
            if row.get('verificationLevel') == 'wecom-ui-tree-text':
                ui = row.get('evidence'); break
    if ui is not None:
        frames = ui.get('observations', [])
        payloads = receipt.get('payloads') or []
        if not (receipt.get('ok') is True and receipt.get('verified') is True
                and receipt.get('state') == 'verified' and receipt.get('groupName') == group
                and receipt.get('sendAttempts') == 1 and receipt.get('physicalSendAttempts') == 1
                and receipt.get('merchantId') == item['merchantId']
                and receipt.get('messageSha256') == item['sha256']
                and len(payloads) == 1 and payloads[0].get('text') == item['text']
                and payloads[0].get('sha256') == item['sha256']
                and hashlib.sha256(item['text'].encode()).hexdigest() == item['sha256']
                and ui.get('method') == 'wecom-ui-tree-text' and ui.get('resolvedGroup') == group
                and ui.get('sha256') == item['sha256'] and len(frames) == 2
                and all(f.get('groupName') == group and f.get('inputEmpty') is True
                        and f.get('newMessageVisible') is True and f.get('visibleTextSha256') == item['sha256'] for f in frames)):
            raise RuntimeError('delivery-ui-post-evidence-incomplete')
        return {'ok':True,'merchantId':item['merchantId'],'physicalSendAttempts':1,
                'verificationLevel':'wecom-ui-tree-text'}
    """Do not commit a merchant merely because a subprocess says verified."""
    # 2026-09-30 大同授权：Mac 桌面微信停用后，⑪ 通知走 Windows 驱动服务，
    # 对等证据是服务端读回锚点（windows-readback-text-anchor）：目标会话标题
    # 当前且 payload 精确文本位于会话尾部。存在该级证据时按 Windows 契约校验。
    win = None
    for it in ((receipt.get("commonReceipt") or {}).get("items") or []):
        if (it.get("verificationLevel") == "windows-readback-text-anchor"
                and isinstance(it.get("evidence"), dict)):
            win = it
            break
    if win is not None:
        evidence = win["evidence"]
        payloads = receipt.get("payloads") or []
        if not (receipt.get("ok") is True and receipt.get("verified") is True
                and receipt.get("state") == "verified" and receipt.get("groupName") == group
                # 2026-10-10 大同授权「发现卡了立即解决」：本函数(=最终账本复核)与
                # desktop_wechat_sender._verify_delivery_evidence(=提交前门禁)是同一
                # windows-readback 判据的两份副本，此前只在后者放宽了复用路径，前者仍硬
                # 卡 sendAttempts==1 ⇒ 已 verified 的复用收据（继承历史 sendAttempts>1）
                # 在最终复核被误判 delivery-evidence-incomplete。此处与 _verify_delivery_evidence
                # 对齐：新发送仍要求恰好 1 次物理发送，复用收据（reusedExisting=True，本调用
                # 0 新发送）凭已读回验证的证据放行。
                and (receipt.get("sendAttempts") == 1 or receipt.get("reusedExisting") is True)
                and receipt.get("merchantId") == item["merchantId"]
                and receipt.get("messageSha256") == item["sha256"]
                and len(payloads) == 1 and payloads[0].get("text") == item["text"]
                and payloads[0].get("sha256") == item["sha256"]
                and hashlib.sha256(item["text"].encode()).hexdigest() == item["sha256"]
                and evidence.get("ok") is True and evidence.get("anchor") == "text-exact"
                and evidence.get("anchorValue") == item["text"]
                and evidence.get("resolvedGroup") == group
                and evidence.get("anchorInTrailingPosition") is True):
            raise RuntimeError("delivery-evidence-incomplete")
        return {"ok": True, "merchantId": item["merchantId"],
                "physicalSendAttempts": receipt.get("sendAttempts")}
    copy = receipt.get("copyReadback") or {}
    payloads = receipt.get("payloads") or []
    reconciled_unknown = (receipt.get("reconciledWithoutSend") is True
                          and receipt.get("sendAttempts") is None
                          and receipt.get("physicalSendAttempts") is None)
    if not (receipt.get("ok") is True and receipt.get("verified") is True
            and receipt.get("state") == "verified" and receipt.get("groupName") == group
            and (reconciled_unknown or (receipt.get("sendAttempts") == 1
                                        and receipt.get("physicalSendAttempts") == 1))
            and receipt.get("merchantId") == item["merchantId"]
            and receipt.get("messageSha256") == item["sha256"]
            and len(payloads) == 1 and payloads[0].get("text") == item["text"]
            and payloads[0].get("sha256") == item["sha256"]
            and hashlib.sha256(item["text"].encode()).hexdigest() == item["sha256"]
            and copy.get("ok") is True and copy.get("composerEmpty") is True
            and copy.get("copyMenuCount") == 1 and len(copy.get("bubblePositions") or []) == 2
            and copy.get("copiedTextSha256") == item["sha256"]):
        raise RuntimeError("delivery-evidence-incomplete")
    # A successful deterministic reconcile can supply the two fresh empty-composer
    # observations when the original post-send verification failed prematurely.
    if receipt.get("postSendInputCleared") != [True, True] and not (
        receipt.get("reconciledWithoutSend") is True
        and len(copy.get("frameAnchors") or []) == 2
    ):
        raise RuntimeError("delivery-composer-evidence-incomplete")
    return {"ok": True, "merchantId": item["merchantId"],
            "physicalSendAttempts": receipt.get("physicalSendAttempts")}


def audit_final(sender, group, collection, channel, reconciliation_only=False,
                dispatch_plan=None, collection_path=None):
    current = json.loads(sender.cursor_file(group).read_text())
    if current.get("groupName") != group or current.get("verified") is not True:
        raise RuntimeError("final-cursor-unverified")
    messages = collection["messages"]
    if dispatch_plan is not None:
        validate_day_dispatch(sender, group, collection, collection_path, dispatch_plan)
        eligible = set(dispatch_plan['eligibleIdentities'])
        messages = [item for item in messages if sender.send_identity(group, item) in eligible]
    checked_messages = messages[:1] if reconciliation_only else messages
    if checked_messages and any(current.get(k) != checked_messages[-1][k]
                        for k in ("merchantId", "recommendTime", "tableOrder")):
        raise RuntimeError("final-cursor-mismatch")
    if not messages and any(current.get(k) != collection["cursor"].get(k)
                            for k in ("merchantId", "recommendTime", "tableOrder")):
        raise RuntimeError("noop-cursor-changed")
    if channel == "desktop" and checked_messages:
        history = [json.loads(line) for line in sender.HISTORY_FILE.read_text().splitlines() if line]
        for item in checked_messages:
            identity = sender.send_identity(group, item)
            matched = [row for row in history if row.get("groupName") == group
                       and sender.send_identity(group, row) == identity and row.get("verified") is True]
            if len(matched) != 1 or matched[0].get("messageSha256") != item["sha256"]:
                raise RuntimeError("final-history-not-unique-or-hash-mismatch")
            marker = sender.STATE_DIR / "send-attempts" / (identity + ".json")
            verify_delivery(json.loads(marker.read_text()), group, item)
    return {"verified": True, "merchantId": current["merchantId"],
            "recommendTime": current["recommendTime"], "checkedDeliveries": len(checked_messages),
            "reconciliationOnly": reconciliation_only,
            "historicalDeferred": len((dispatch_plan or {}).get('historicalDeferred', []))}


def delivery_counts(delivery):
    counts = {"verifiedNewSends": 0, "verifiedExisting": 0, "unresolvedItems": 0}
    for item in delivery.get("items", []):
        phases = item.get("review", [])
        committed = any(
            phase.get("stage") == "成功历史与原子游标提交" and phase.get("status") == "PASS"
            for phase in phases
        )
        entered_send = any(
            phase.get("stage") == "定位、输入与单次发送" and phase.get("status") in ("PASS", "FAIL")
            for phase in phases
        )
        key = ("verifiedNewSends" if entered_send else "verifiedExisting") if committed else "unresolvedItems"
        counts[key] += 1
    return counts


USER_ACTION_TOKENS = ("login", "登录", "captcha", "验证码", "slider", "滑块", "account-risk", "账号风险")


def completion_state(result):
    """Classify the next legal action from receipts, never from prose."""
    counts = delivery_counts(result.get("wechat", {}))
    delivery = result.get("wechat", {})
    entered_send = any(
        phase.get("stage") == "定位、输入与单次发送"
        for item in delivery.get("items", [])
        for phase in item.get("review", [])
    )
    preflight_attempts = (result.get("desktopWechatPreflight") or {}).get("sendAttempts", 0)
    recorded_attempts = delivery.get("sendAttempts", 0)
    def has_unknown_marker(value):
        if isinstance(value, dict):
            if (value.get("state") in ("attempted", "unknown")
                    or value.get("status") == "unknown") and "sendAttempts" in value:
                return True
            return any(has_unknown_marker(child) for child in value.values())
        if isinstance(value, list):
            return any(has_unknown_marker(child) for child in value)
        return False
    unknown_marker = has_unknown_marker(delivery)
    nonzero_evidence = (counts["verifiedNewSends"] > 0 or counts["verifiedExisting"] > 0
                        or entered_send or preflight_attempts or recorded_attempts or unknown_marker)
    reason = str(result.get("error") or delivery.get("reason") or "")
    lowered = reason.lower()
    if result.get("ok") is True and counts["unresolvedItems"] == 0:
        return {"state": "COMPLETE", "nextAction": "none", "automaticRecoveryAllowed": False,
                "recoveryAttemptBudget": 0, "reason": "final-cursor-and-history-verified"}
    if any(token.lower() in lowered for token in USER_ACTION_TOKENS):
        return {"state": "USER_ACTION_REQUIRED", "nextAction": "request-login-or-challenge-resolution",
                "automaticRecoveryAllowed": False, "recoveryAttemptBudget": 0,
                "reason": reason or "interactive-authentication-required"}
    if nonzero_evidence:
        return {"state": "RECONCILE_ONLY", "nextAction": "native-copy-read-only-reconcile-no-resend",
                "automaticRecoveryAllowed": True, "recoveryAttemptBudget": 1,
                "reason": reason or "send-or-existing-attempt-evidence-present"}
    return {"state": "RECOVERABLE_NO_SEND", "nextAction": "diagnose-repair-test-maintain-retry-once",
            "automaticRecoveryAllowed": True, "recoveryAttemptBudget": 1,
            "reason": reason or "zero-send-failure"}


def build_review(result):
    rows = []
    def add(stage, label, elapsed, status, pitfalls=(), parent=None):
        if elapsed is not None and (not isinstance(elapsed, int) or elapsed < 0):
            raise RuntimeError("review-invalid-elapsed-time")
        rows.append({"item": len(rows) + 1, "stage": stage, "label": label,
                     "elapsedMs": elapsed, "status": status, "pitfalls": list(pitfalls), "parent": parent})
    channel = result.get("wechatChannel", "desktop")
    order = [key for key in STAGES if key != ("phone" if channel == "desktop" else "desktop_wechat")]
    if result.get("stage") == "lock":
        add("lock", "流程互斥锁", result.get("elapsedMs"), "FAIL", [result.get("error", "lock-failed")])
    for key in order:
        elapsed = result.get("stageMs", {}).get(key)
        status = result.get("stageResults", {}).get(key, "SKIPPED")
        pitfalls = [result["error"]] if status == "FAIL" and result.get("error") else []
        if key == "desktop_wechat_preflight":
            if status == "SKIPPED" and result.get("desktopWechatPreflight", {}).get("reason") == "no-pending-merchants":
                status = "NOOP"
                pitfalls = ["无待发商家，代码跳过微信预检"]
            pitfalls += [e["reason"] for e in result.get("desktopWechatPreflight", {}).get("contentionEvents", [])]
        if key == "reseal" and status == "SKIPPED":
            reason = result.get("resealReason")
            status = "NOOP"
            pitfalls = ["已封板运行，无需重封" if reason == "already-sealed" else "无真实新增发送，保持未封板"]
        if key == "desktop_wechat" and status == "PASS" and result.get("wechat", {}).get("mode") == "execute-noop":
            status = "NOOP"
            pitfalls = ["无待发商家，未触发发送"]
        add(key, STAGES[key], elapsed, status, pitfalls)
        if key == "desktop_wechat_preflight":
            preflight = result.get("desktopWechatPreflight", {})
            for attempt in preflight.get("attemptReviews", []):
                add(f"preflight.{attempt['attempt']}", f"群定位第{attempt['attempt']}次",
                    attempt["elapsedMs"], "PASS" if attempt["ok"] else "FAIL",
                    [attempt["reason"]] if attempt.get("reason") else [], key)
            for event in preflight.get("contentionEvents", []):
                add(f"preflight.wait.{event['attempt']}", f"群定位第{event['attempt']}次退避等待",
                    event.get("observedWaitMs"), "PASS", [event["reason"]], key)
        if key == "collection":
            for attempt in result.get("collectionAttempts", []):
                for phase, ms in attempt.get("stageMs", {}).items():
                    failed = attempt.get("stageResults", {}).get(phase) == "FAIL"
                    add(f"collection.{attempt['attempt']}.{phase}", f"采集第{attempt['attempt']}次 · {collection_label(phase)}",
                        ms, "FAIL" if failed else "PASS", [attempt["error"]] if failed else [], key)
        if key == "desktop_wechat":
            for item in result.get("wechat", {}).get("items", []):
                for row in item.get("review", []):
                    add(f"merchant.{item['merchantId']}.{row['stage']}",
                        item["merchantName"] + " · " + row["stage"], row["elapsedMs"],
                        row["status"], row.get("pitfalls", []), key)
                    for detail in row.get("details", []):
                        add(f"merchant.{item['merchantId']}.{detail['stage']}",
                            item["merchantName"] + " · " + detail["label"], detail["elapsedMs"],
                            "PASS" if detail["status"] == "completed" else "FAIL",
                            [p["reason"] for p in detail.get("pitfalls", [])], row["stage"])
    add("total", "整轮总耗时（含子阶段，不重复相加）", result["elapsedMs"],
        "PASS" if result.get("ok") else "FAIL")
    counts = delivery_counts(result.get("wechat", {}))
    completion = result.get("completion") or completion_state(result)
    review = {"schemaVersion": 1, "runId": result["runId"], "ok": result.get("ok") is True,
              "sent": counts["verifiedNewSends"], **counts, "completion": completion, "rows": rows}
    if result.get('dayDispatch') is not None:
        review['historicalDeferred'] = result['dayDispatch']['historicalDeferred']
    return review


def render_review(review):
    def safe(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    lines = ["# 每轮执行复盘", "", "| 项目 | 耗时 | 结果 | 踩坑点 |", "|---|---:|---|---|"]
    labels = {"PASS": "通过", "FAIL": "失败", "SKIPPED": "未执行", "NOOP": "无待发"}
    for row in review["rows"]:
        elapsed = "—" if row["elapsedMs"] is None else ("<0.001秒" if row["elapsedMs"] == 0 else f"{row['elapsedMs']/1000:.3f}秒")
        pitfalls = "；".join(row["pitfalls"]) or ("前置门禁未通过" if row["status"] == "SKIPPED" else "无")
        lines.append(f"| {safe(row['label'])} | {elapsed} | {labels[row['status']]} | {safe(pitfalls)} |")
    completion = review.get("completion") or {}
    lines += ["", "父阶段包含子阶段耗时，不能把所有行重复相加。", "",
              "## 机器决定的下一动作", "",
              f"- 状态：`{completion.get('state', 'UNKNOWN')}`",
              f"- 下一动作：`{completion.get('nextAction', 'unknown')}`",
              f"- 自动恢复：`{str(completion.get('automaticRecoveryAllowed', False)).lower()}`",
              f"- 恢复预算：`{completion.get('recoveryAttemptBudget', 0)}`",
              f"- 原因：`{completion.get('reason', 'unknown')}`"]
    historical = review.get('historicalDeferred') or []
    if historical:
        lines += ['', '## 历史待核（未重发、未改为已核验）', '',
                  f'本轮当前项之外另保留 {len(historical)} 项，原标记与独立登记均保留。']
        for item in historical:
            lines.append(f"- `{safe(item['identity'])}`：旧日 {safe(item['attemptBusinessDate'])}，仍待只读核验。")
    return "\n".join(lines) + "\n"


# Mechanism metadata is separate from immutable send markers and the success cursor.
def _dispatch_now():
    return datetime.now(ZoneInfo('Asia/Shanghai'))


def _dispatch_path(sender, *parts):
    root = sender.STATE_DIR.resolve()
    path = root.joinpath(*parts)
    if path.resolve() != path or not path.is_relative_to(root):
        raise RuntimeError('dispatch-state-symlink-or-escape')
    return path


def _dispatch_read(path, default=None):
    path = Path(path)
    if path.is_symlink():
        raise RuntimeError('dispatch-state-symlink')
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError) as error:
        raise RuntimeError('dispatch-state-invalid') from error


def _dispatch_day(value):
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None:
            raise ValueError('timezone-required')
        return stamp.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    except (ValueError, TypeError, AttributeError) as error:
        raise RuntimeError('dispatch-date-proof-invalid') from error


def _dispatch_source(collection, path, group, now):
    raw = Path(path).read_bytes()
    if (json.loads(raw) != collection or collection.get('ok') is not True
            or not isinstance(collection.get('messages'), list) or collection.get('groupName') != group
            or collection.get('businessDate') != now.strftime('%Y-%m-%d')):
        raise RuntimeError('dispatch-source-binding-invalid')
    return hashlib.sha256(raw).hexdigest()


def _marker_payload_sha(marker):
    if marker.get('payloadType') not in (None, 'text'):
        raise RuntimeError('dispatch-old-payload-kind-invalid')
    payloads = marker.get('payloads') or []
    digest = marker.get('messageSha256')
    if payloads:
        if (len(payloads) != 1 or not isinstance(payloads[0].get('text'), str)
                or hashlib.sha256(payloads[0]['text'].encode()).hexdigest() != payloads[0].get('sha256')
                or (digest is not None and digest != payloads[0]['sha256'])):
            raise RuntimeError('dispatch-old-payload-binding-invalid')
        digest = payloads[0]['sha256']
    if not isinstance(digest, str) or not re.fullmatch(r'[a-f0-9]{64}', digest):
        return None
    return digest


def record_dispatch_origin(sender, group, item, collection, collection_path,
                           zero_send_verified=False, now=None):
    """Record preparation, never an attempt or delivery; unknown cannot be redated."""
    now = now or _dispatch_now()
    source_sha = _dispatch_source(collection, collection_path, group, now)
    identity = sender.send_identity(group, item)
    marker_path = _dispatch_path(sender, 'send-attempts', identity + '.json')
    prior = _dispatch_read(marker_path)
    if prior is not None and not (zero_send_verified and prior.get('state') == 'blocked'
                                 and prior.get('sendAttempts') == 0
                                 and prior.get('groupName') == group):
        raise RuntimeError('dispatch-origin-existing-attempt')
    path = _dispatch_path(sender, 'dispatch-origins', identity + '.json')
    data = _dispatch_read(path, {'schemaVersion': 1, 'preparations': []})
    if data.get('schemaVersion') != 1 or not isinstance(data.get('preparations'), list):
        raise RuntimeError('dispatch-origin-invalid')
    row = {'identity': identity, 'groupName': group, 'messageSha256': item['sha256'],
           'businessDate': collection['businessDate'], 'preparedAt': now.isoformat(),
           'sourceSha256': source_sha}
    data['preparations'].append(row)
    sender.atomic_write_json(path, data)
    return row


def _historical_proof(sender, group, identity, marker, marker_sha, observations, day):
    if marker.get('groupName') != group:
        raise RuntimeError('dispatch-marker-group-mismatch')
    payload_sha = _marker_payload_sha(marker)
    if payload_sha is None:
        return None
    origin = _dispatch_read(_dispatch_path(sender, 'dispatch-origins', identity + '.json'))
    if origin is not None:
        preparations = origin.get('preparations')
        if origin.get('schemaVersion') != 1 or not isinstance(preparations, list) or not preparations:
            raise RuntimeError('dispatch-origin-invalid')
        latest = preparations[-1]
        if (latest.get('identity') != identity or latest.get('groupName') != group
                or latest.get('messageSha256') != payload_sha
                or _dispatch_day(latest.get('preparedAt')) != latest.get('businessDate')):
            raise RuntimeError('dispatch-origin-binding-invalid')
        # The latest preparation wins, even if an old marker happened to have identical bytes.
        if latest['businessDate'] >= day:
            return None
        return {'kind': 'original-dispatch-origin', 'businessDate': latest['businessDate'],
                'payloadSha256': payload_sha}
    matches = [row for row in observations.get(identity, [])
               if row.get('groupName') == group and row.get('markerSha256') == marker_sha]
    days = [_dispatch_day(row.get('firstObservedAt')) for row in matches]
    if not days or min(days) >= day:
        return None
    return {'kind': 'prior-day-exact-marker-observation', 'businessDate': min(days),
            'payloadSha256': payload_sha}


def day_dispatch(sender, group, collection, collection_path, *, register=False, now=None):
    """Partition only proved historical attempts; leave the original collection untouched."""
    now = now or _dispatch_now()
    source_sha = _dispatch_source(collection, collection_path, group, now)
    day = collection['businessDate']
    observation_path = _dispatch_path(sender, 'attempt-observations-v1.json')
    observed = _dispatch_read(observation_path, {'schemaVersion': 1, 'entries': {}})
    if observed.get('schemaVersion') != 1 or not isinstance(observed.get('entries'), dict):
        raise RuntimeError('dispatch-observations-invalid')
    markers = {}; changed = False
    for item in collection['messages']:
        identity = sender.send_identity(group, item)
        if identity in markers:
            raise RuntimeError('dispatch-duplicate-identity')
        path = _dispatch_path(sender, 'send-attempts', identity + '.json')
        marker = _dispatch_read(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest() if marker is not None else None
        markers[identity] = (marker, digest)
        if marker is None or marker.get('state') not in ('unknown', 'attempted'):
            continue
        if marker.get('groupName') is None:
            # An incomplete legacy marker can only use the original read-only
            # reconciliation path; it cannot acquire historical skip permission.
            continue
        if marker.get('groupName') != group:
            raise RuntimeError('dispatch-marker-group-mismatch')
        rows = observed['entries'].setdefault(identity, [])
        if not isinstance(rows, list):
            raise RuntimeError('dispatch-observations-invalid')
        if register and not any(row.get('markerSha256') == digest and row.get('groupName') == group for row in rows):
            rows.append({'markerSha256': digest, 'groupName': group, 'firstObservedAt': now.isoformat()})
            changed = True
    if changed:
        sender.atomic_write_json(observation_path, observed)
    plan = {'schemaVersion': 1, 'groupName': group, 'businessDate': day,
            'sourceSha256': source_sha, 'eligibleIdentities': [], 'historicalDeferred': []}
    for item in collection['messages']:
        identity = sender.send_identity(group, item); marker, digest = markers[identity]
        proof = (_historical_proof(sender, group, identity, marker, digest, observed['entries'], day)
                 if marker is not None and marker.get('state') in ('unknown', 'attempted')
                 and marker.get('groupName') is not None else None)
        if proof is None:
            plan['eligibleIdentities'].append(identity)
            continue
        if item['recommendTime'][:10] > proof['businessDate']:
            raise RuntimeError('dispatch-recommendation-after-old-attempt')
        stable = {'schemaVersion': 1, 'identity': identity, 'groupName': group,
                  'merchantId': item['merchantId'], 'recommendTime': item['recommendTime'],
                  'currentPayloadSha256': item['sha256'],
                  'originalMarkerSha256': digest, 'attemptBusinessDate': proof['businessDate'],
                  'proofKind': proof['kind'], 'originalPayloadSha256': proof['payloadSha256']}
        record_path = _dispatch_path(sender, 'historical-pending', identity, digest + '-' + item['sha256'] + '.json')
        record = _dispatch_read(record_path)
        if record is None and register:
            record = stable | {'registeredAt': now.isoformat(), 'sourceSha256': source_sha,
                               'itemSnapshot': item, 'originalMarkerSnapshot': marker,
                               'observedState': marker['state'], 'resolved': False}
            sender.atomic_write_json(record_path, record)
        snapshot = (record or {}).get('itemSnapshot') or {}
        if (record is None or any(record.get(k) != value for k, value in stable.items())
                or record.get('originalMarkerSnapshot') != marker
                or snapshot.get('merchantId') != item['merchantId']
                or snapshot.get('recommendTime') != item['recommendTime']
                or snapshot.get('text') != item['text'] or snapshot.get('sha256') != item['sha256']):
            raise RuntimeError('dispatch-historical-registration-invalid')
        plan['historicalDeferred'].append({'identity': identity, 'attemptBusinessDate': proof['businessDate'],
            'originalMarkerSha256': digest, 'recordPath': str(record_path),
            'recordSha256': hashlib.sha256(record_path.read_bytes()).hexdigest(),
            'payloadConflict': proof['payloadSha256'] != item['sha256']})
    return plan


def validate_day_dispatch(sender, group, collection, collection_path, plan, now=None):
    expected = day_dispatch(sender, group, collection, collection_path, now=now)
    if plan != expected:
        raise RuntimeError('dispatch-plan-binding-invalid')
    return True
