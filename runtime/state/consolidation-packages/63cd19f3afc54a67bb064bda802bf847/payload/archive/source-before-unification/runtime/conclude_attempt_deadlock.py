#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""A2b-② · attempted 死结「读回取证 + 授权结论化」桥外独立工具（**零封印影响**）

方案：docs/solutions/20261006-A2方案-attempted死结检测与根治.md §3（A2b-②，大同 2026-10-06 裁决）

背景
----
桥对「已存在 marker」的四条出口中，`attempted` 且**无收据**（`sendAttempts=null`）只回
`existing-attempt-reconcile-only`：**既不发也不前进** ⇒ 游标永久阻塞（2026-10-06 旨寿司实证）。
代码层三条复核路径（sealed `legacy_text_reconcile` / `WindowsAdapter.reconcile` / 重新 `--execute`）
**全部要求收据齐全** ⇒ 零自愈。当时只能用**人工方案 A**（改写 marker 为 verified）解开。

本工具把「方案 A」交给机器，但保留同级人工闸门：
  1) 对 A2a 扫出的死结做**纯只读读回**取证
     （目标会话标题当前 + 载荷精确文本位于会话尾部，判据与 `WindowsAdapter._verify_sent` 同级）；
  2) **仅在 `--apply` + 每例唯一授权串**下把 marker 结论化为 `verified`
     （落盘形状与人工方案 A **逐字段一致**，确保下游消费者认账）；
  3) 写受控结论化登记 + 备份 + 审计。

纪律
----
* **绝不发送**、绝不改公共桥 `workflow_bridge.py`、绝不碰任何封印件（`python` 层只读 import）。
* **fail-closed**：读不到证据 / 形状不认识 / 授权串不符 ⇒ 只报告，**绝不改 marker**。
* 结论化前必须取桥同一把 `.bridge.lock`（防与 daemon/桥并发）。
* `--apply` 写后**回读校验**：`verified/state` 到位且 `payloads` 逐字节不变，否则用备份回滚。
* 默认 `dry-run`（不加 `--apply` 绝不写任何文件）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent          # repo root
RUNTIME = ROOT / "runtime"
if str(RUNTIME) not in sys.path:
    sys.path.insert(0, str(RUNTIME))

import scan_attempt_deadlocks as a2a                   # noqa: E402  (A2a 死结体检器，复用其判据)

CN = timezone(timedelta(hours=8))
AUDIT_PATH = RUNTIME / "state" / "attempt_conclusion_audit.jsonl"
MERCHANTS_STATE_HINT = "taobao-agent-new-merchants"    # 该流的消费者额外要求 merchantId
DEFAULT_ACTOR = "WorkBuddy 监理"
NO_RESEND = "本次结论化不触发任何发送；流程复用该 verified 收据后仅提交成功历史与游标。"
HONESTY = ("本记录不伪造 transport/attemptReviews：本工具只做只读读回取证，"
           "不复现桥的真实发送收据。")


# ------------------------------------------------------------------ 小工具

def _now() -> datetime:
    return datetime.now(CN)


def _stamp(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).strftime("%Y%m%d-%H%M%S")


def _iso(ts: Optional[float] = None) -> str:
    dt = datetime.fromtimestamp(ts, CN) if ts is not None else _now()
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def format_authorize_token(marker_path: Path, payload_sha: str) -> str:
    """每例唯一授权串：绑定「这一个 marker + 这一个载荷」，不可跨案例复用。"""
    seed = "%s\n%s" % (Path(marker_path).resolve(), payload_sha)
    return "conclude:" + _sha256_text(seed)[:12]


# ------------------------------------------------------------------ marker 绑定

class Refused(Exception):
    """形状不认识 / 证据不足 / 授权不符 —— 一律 fail-closed。"""


def load_marker(path: Path) -> dict:
    try:
        obj = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Refused("marker-unreadable:%s" % error)
    if not isinstance(obj, dict):
        raise Refused("marker-not-an-object")
    return obj


def marker_binding(prior: dict) -> Tuple[str, str, List[dict]]:
    """校验并抽出 (group, payload_type, payloads)。只为**死结形状**放行。"""
    if prior.get("bridgeVersion") != 1:
        raise Refused("marker-not-bridge-v1")
    state = prior.get("state")
    if state == "verified" and prior.get("verified") is True:
        raise Refused("marker-already-verified")
    if state != "attempted":
        raise Refused("marker-not-attempted:%s" % state)
    if prior.get("sendAttempts") not in (None, 0):
        raise Refused("marker-has-receipt:use-reconcile")
    group = str(prior.get("groupName") or "").strip()
    if not group:
        raise Refused("marker-without-group")
    payload_type = str(prior.get("payloadType") or "").strip()
    payloads = prior.get("payloads")
    if not isinstance(payloads, list) or len(payloads) != 1 or not isinstance(payloads[0], dict):
        raise Refused("marker-payload-shape-unsupported")
    return group, payload_type, payloads


def payload_sha(prior: dict, payload_type: str) -> str:
    payload = (prior.get("payloads") or [{}])[0]
    if payload_type == "text":
        text = str(payload.get("text") or "")
        if not text:
            raise Refused("marker-empty-text")
        return _sha256_text(text)
    return str(payload.get("sha256") or "").strip()


# ------------------------------------------------------------------ 只读读回取证

def _wa():
    """惰性 import 适配器（借其判据函数；不实例化、不发送）。"""
    if str(ROOT / "skills" / "wechat-messaging" / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "skills" / "wechat-messaging" / "scripts"))
    import windows_adapter as wa
    return wa


def readback(adapter, group: str, payload: dict, *, payload_type: str = "text",
             search_group: Optional[str] = None,
             window_seconds: float = 12.0, poll_seconds: float = 2.0
             ) -> Tuple[bool, dict, List, Optional[str]]:
    """纯只读读回取证。返回 (ok, evidence, tail_messages, reason)。

    判据与 `WindowsAdapter._verify_sent` 同级：标题当前 **且** 载荷锚点位于会话尾部。

    ⚠ 前置条件（驱动契约所限）：`client.py` **没有「只打开会话不发送」的 action**，
    故读回只在目标群**恰是 Windows 微信当前会话**时成立。这恰是死结事故的现场状态
    （进程死在「已发出」之后，Windows 侧会话仍停在目标群；2026-10-06 方案 A 即据此成立）。
    标题不符时只做**有界轮询**（等驱动导航落定），**绝不为了取证去打开会话**——打开会话
    属驱动导航，不予代做；轮询超时即如实报 `windows-current-session-title-mismatch`。
    锚点不在尾部的判定是**决定性否定**，立即返回、不轮询（fail-closed）。
    """
    wa = _wa()
    try:
        resolved, strategy = adapter.resolve_group(group, search_group)
    except Exception as error:                      # noqa: BLE001 - 任何异常都只报告
        return False, {"strategy": None, "resolvedGroup": None}, [], "resolve-failed:%s" % error
    resolved = resolved or group
    end = time.time() + max(0.0, float(window_seconds))
    last: dict = {"ok": False, "resolvedGroup": resolved, "strategy": strategy}
    while True:
        try:
            current = adapter.client.current()
        except Exception as error:                  # noqa: BLE001
            return False, {"resolvedGroup": resolved}, [], "windows-current-unavailable:%s" % error
        title = wa._normalize_title((current.get("data") or {}).get("title"))
        if not wa._title_compatible(title, resolved):
            last = {"ok": False, "titleProven": False, "resolvedGroup": resolved,
                    "currentTitle": title, "strategy": strategy}
            reason = "windows-current-session-title-mismatch"
        else:
            try:
                read = adapter.client.read()
            except Exception as error:              # noqa: BLE001
                return False, {"ok": False, "resolvedGroup": resolved, "currentTitle": title}, \
                    [], "windows-read-empty:%s" % error
            messages = wa._read_messages(read)
            if messages:
                base = {"ok": False, "titleProven": True, "resolvedGroup": resolved,
                        "currentTitle": title, "messageCount": len(messages),
                        "strategy": strategy}
                if payload_type == "text":
                    anchors = [("text-exact", str(payload.get("text") or ""))]
                else:
                    anchors = [("file-card", marker) for marker in wa.FILE_CARD_MARKERS]
                for level, anchor in anchors:
                    if anchor and wa._anchor_newness(messages, anchor):
                        evidence = {"ok": True, "resolvedGroup": resolved, "currentTitle": title,
                                    "messageCount": len(messages), "anchor": level,
                                    "anchorValue": anchor, "anchorInTrailingPosition": True,
                                    "readbackAt": time.time(), "strategy": strategy}
                        return True, evidence, messages[-4:], None
                # 决定性否定：载荷不在尾部 ⇒ 立即返回，不轮询
                return False, base, messages[-4:], "windows-readback-anchor-not-trailing"
            last = {"ok": False, "titleProven": True, "resolvedGroup": resolved,
                    "currentTitle": title, "messageCount": 0, "strategy": strategy}
            reason = "windows-readback-empty"
        if time.time() >= end:
            return False, last, [], reason
        time.sleep(max(0.0, float(poll_seconds)))


# ------------------------------------------------------------------ 结论化

def build_conclusion(prior: dict, evidence: dict, *, merchant_id: Optional[str],
                     actor: str, authorized_by: str, note: Optional[str]) -> dict:
    """产出结论化 marker（**逐字段对齐人工方案 A**，见 docs §3 与 2026-10-06 旨寿司实证）。"""
    payload_type = str(prior.get("payloadType") or "text")
    payload = (prior.get("payloads") or [{}])[0]
    sha = payload_sha(prior, payload_type)
    now = time.time()
    common_item = {
        "itemId": "0",
        "sha256": sha,
        "type": payload_type,
        "status": "verified",
        "claimedAt": now,
        "sendAttempts": 1,
        "verificationLevel": "windows-readback-text-anchor",
        "evidence": evidence,
    }
    out = dict(prior)
    out.update({
        "bridgeVersion": 1,
        "ok": True,
        "verified": True,
        "payloadType": payload_type,
        "state": "verified",
        "sendAttempts": 1,
        "physicalSendAttempts": 1,
        "messageSha256": sha,
        "runtimeModelDecisions": 0,
        "reason": None,
        "commonReceipt": {"ok": True, "status": "verified", "groupName": prior.get("groupName"),
                          "channel": "desktop", "runtimeModelDecisions": 0, "items": [common_item]},
        # 我们的真实证据（不复制桥的 copyReadback/transport —— 那两款本工具并未产生）
        "readbackEvidence": evidence,
        "verificationMethod": "windows-driver-readback-anchor",
        "completionProvenance": {
            "decision": "controlled-verified-from-driver-readback",
            "tool": "runtime/conclude_attempt_deadlock.py (A2b-②)",
            "authorizedBy": authorized_by,
            "recordedAt": _iso(now),
            "recordedBy": actor,
            "replacedState": prior.get("state"),
            "evidenceObservedAt": _iso(evidence.get("readbackAt")),
            "evidenceBasis": ("驱动只读回读：目标会话标题当前，且载荷精确文本位于会话尾部"
                              "（anchor=%s）。" % evidence.get("anchor")),
            "noResendGuarantee": NO_RESEND,
            "note": HONESTY + ("；%s" % note if note else ""),
        },
    })
    if merchant_id:
        out["merchantId"] = merchant_id
    return out


def _registry_dir_for(marker: Path) -> Path:
    """与人工方案 A 同级落位：`<flow-state>/controlled-verifications/`。"""
    parent = Path(marker).resolve().parent
    if parent.name in ("send-attempts", "wechat-attempts", "send-ledger") or "attempts" in parent.name:
        candidate = parent.parent / "controlled-verifications"
    else:
        candidate = RUNTIME / "state" / "controlled-verifications"
    return candidate


def _write_audit(row: dict) -> None:
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def conclude(marker: Path, *, adapter, authorize: Optional[str], actor: str = DEFAULT_ACTOR,
             note: Optional[str] = None, allow_weaker_file_anchor: bool = False,
             merchant_id: Optional[str] = None, apply: bool = False,
             search_group: Optional[str] = None, readback_window: float = 12.0) -> dict:
    """对单个死结 marker 做读回取证（+ 受控结论化）。**默认 dry-run**。"""
    marker = Path(marker).resolve()
    result: Dict = {"marker": str(marker), "applied": False, "decision": None}

    try:
        prior = load_marker(marker)
        group, payload_type, payloads = marker_binding(prior)
        sha = payload_sha(prior, payload_type)
    except Refused as error:
        result.update(decision="refused", reason=str(error))
        return result
    token = format_authorize_token(marker, sha)
    result.update(group=group, payloadType=payload_type, payloadSha256=sha,
                  authorizeToken=token, previousState=prior.get("state"),
                  previousSendAttempts=prior.get("sendAttempts"))

    if payload_type != "text" and not allow_weaker_file_anchor:
        result.update(decision="refused",
                      reason="file-payload-anchor-is-weaker:re-run-with--allow-weaker-file-anchor")
        return result

    ok, evidence, tail, reason = readback(adapter, group, payloads[0],
                                          payload_type=payload_type, search_group=search_group,
                                          window_seconds=readback_window)
    result.update(readbackOk=ok, readbackReason=reason, evidence=evidence,
                  tailMessages=tail)
    if not ok:
        result.update(decision="no-evidence",
                      reason=reason or "readback-failed")
        return result

    if not apply:
        result.update(decision="dry-run-evidence-ok",
                      wouldConclude=True,
                      hint=("取证通过。结论化执行："
                            "--apply --marker %s --authorize %s%s"
                            % (marker, token,
                               (" --merchant-id %s" % merchant_id) if merchant_id else "")))
        return result

    if not authorize or authorize.strip() != token:
        result.update(decision="refused", reason="authorize-token-mismatch")
        return result

    if merchant_id is None and MERCHANTS_STATE_HINT in str(marker):
        result.update(decision="refused",
                      reason="merchant-id-required-for-this-flow:pass--merchant-id")
        return result

    new = build_conclusion(prior, evidence, merchant_id=merchant_id, actor=actor,
                           authorized_by="授权串 %s（操作者：%s）" % (token, actor), note=note)

    backup = marker.with_name(marker.name + ".bak-controlled-verified-" + _stamp())
    before_bytes = marker.read_bytes()
    after = json.dumps(new, ensure_ascii=False, indent=1)

    lock_path = marker.with_suffix(".bridge.lock")
    import fcntl
    ledger = marker.parent
    try:
        fd = os.open(ledger, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
    with lock_path.open("a+") as lock:
        try:
            os.chmod(lock.name, 0o600)
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result.update(decision="refused", reason="bridge-lock-busy")
            return result
        try:
            # 取锁后再读一次：防取锁前一刻被桥改写
            _re = load_marker(marker)
            if _re.get("state") == "verified" or _re != prior:
                result.update(decision="refused", reason="marker-changed-under-lock")
                return result
            backup.write_bytes(before_bytes)
            os.chmod(backup, 0o600)
            tmp = marker.with_name(marker.name + ".tmp-%d" % os.getpid())
            tmp.write_text(after, encoding="utf-8")
            os.chmod(tmp, 0o600)
            os.replace(tmp, marker)
            # 写后回读校验
            check = load_marker(marker)
            binding_ok = (check.get("verified") is True and check.get("state") == "verified"
                          and check.get("payloads") == prior.get("payloads")
                          and check.get("groupName") == prior.get("groupName"))
            if not binding_ok:
                marker.write_bytes(before_bytes)
                result.update(decision="refused", reason="post-write-verify-failed:rolled-back")
                return result
        except Exception as error:                  # noqa: BLE001
            try:
                marker.write_bytes(before_bytes)
            except OSError:
                pass
            result.update(decision="refused", reason="write-failed:%s" % error)
            return result

    # 证据旁文件（命名含 evidence ⇒ A2a 扫描器不会误当 marker）
    sidecar = marker.with_name(marker.name + ".readback-evidence-" + _stamp() + ".json")
    try:
        sidecar.write_text(json.dumps({"marker": str(marker), "evidence": evidence,
                                       "tailMessages": tail, "authorizeToken": token,
                                       "recordedAt": _iso()},
                                      ensure_ascii=False, indent=1), encoding="utf-8")
        os.chmod(sidecar, 0o600)
    except OSError:
        sidecar = None

    # 受控结论化登记（与人工方案 A 同构）
    registry_dir = _registry_dir_for(marker)
    try:
        registry_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        stem = merchant_id or marker.stem[:12]
        record_path = registry_dir / ("%s-%s.json" % (stem, _stamp()))
        record_path.write_text(json.dumps({
            "schemaVersion": 1,
            "kind": "controlled-marker-verification",
            "authorizedBy": "授权串（操作者：%s）" % actor,
            "recordedAt": _iso(),
            "group": group,
            "merchantId": merchant_id,
            "marker": str(marker),
            "backup": str(backup),
            "evidenceSidecar": str(sidecar) if sidecar else None,
            "before": {"sha256": _sha256_bytes(before_bytes), "state": prior.get("state"),
                       "verified": prior.get("verified"),
                       "sendAttempts": prior.get("sendAttempts")},
            "after": {"sha256": _sha256_bytes(marker.read_bytes()), "state": "verified",
                      "verified": True, "sendAttempts": 1},
            "evidence": evidence,
            "provenance": new.get("completionProvenance"),
            "verifications": ["conclude_attempt_deadlock.readback-anchor"],
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        os.chmod(record_path, 0o600)
    except OSError as error:
        record_path = None
        result["registryWriteError"] = str(error)

    _write_audit({"ts": _iso(), "marker": str(marker), "group": group,
                  "payloadType": payload_type, "payloadSha256": sha,
                  "decision": "concluded-verified", "actor": actor,
                  "authorizeToken": token, "merchantId": merchant_id,
                  "backup": str(backup), "registry": str(record_path) if record_path else None,
                  "readbackAt": evidence.get("readbackAt")})
    result.update(applied=True, decision="concluded-verified", backup=str(backup),
                  registry=str(record_path) if record_path else None,
                  evidenceSidecar=str(sidecar) if sidecar else None)
    return result


# ------------------------------------------------------------------ 扫描 / 自动解算

def resolve_item_for_marker(marker: Path, group: str, sha: str,
                            *, state_root: Path) -> Optional[dict]:
    """由 marker 文件名反解真实 item（send_identity = sha256(group\\n merchantId\\n recommendTime)）。

    数据源：该流 runs 下的 collection 收据（只读）。不解算成功返回 None（不阻塞主流程）。
    """
    try:
        scripts = ROOT / "skills" / "workflows" / "daily-agent-new-merchants-to-wechat" / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import wechat_sender_executor as wse   # noqa: WPS433
    except Exception:                              # noqa: BLE001
        return None
    stem = marker.name[:-5] if marker.name.endswith(".json") else marker.name
    runs = state_root / "runs"
    if not runs.is_dir():
        return None
    seen = set()
    for pattern in ("*/collection*.json", "*/*/collection*.json"):
        for path in runs.glob(pattern):
            if path in seen:
                continue
            seen.add(path)
            try:
                obj = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for row in (obj.get("messages") or []):
                if not isinstance(row, dict) or row.get("groupName", group) != group:
                    continue
                try:
                    ident = wse.send_identity(group, row)
                except Exception:                  # noqa: BLE001
                    continue
                if ident == stem and _sha256_text(str(row.get("text") or "")) == sha:
                    return {"merchantId": row.get("merchantId"),
                            "merchantName": row.get("merchantName"),
                            "recommendTime": row.get("recommendTime"),
                            "source": str(path)}
    return None


def scan(roots: List[Path], *, adapter=None, state_root: Optional[Path] = None) -> List[dict]:
    """A2a 扫出的死结 → 逐个只读读回取证（**零写入**）。"""
    out = []
    for item in a2a.scan(roots):
        row = dict(item)
        marker = Path(item["path"])
        sha = None
        try:
            prior = load_marker(marker)
            group, payload_type, payloads = marker_binding(prior)
            sha = payload_sha(prior, payload_type)
            row.update(authorizeToken=format_authorize_token(marker, sha),
                       payloadType=payload_type)
            if state_root is not None:
                resolved = resolve_item_for_marker(marker, group, sha, state_root=state_root)
                if resolved:
                    row.update(merchantId=resolved.get("merchantId"),
                               merchantName=resolved.get("merchantName"),
                               resolveSource=resolved.get("source"))
            if adapter is None:
                row["readbackOk"] = None
                row["readbackReason"] = "adapter-unavailable"
            else:
                ok, evidence, _tail, reason = readback(adapter, group, payloads[0],
                                                       payload_type=payload_type)
                row.update(readbackOk=ok, readbackReason=reason, evidence=evidence)
        except Refused as error:
            row.update(readbackOk=False, readbackReason="not-concludable:%s" % error)
        out.append(row)
    return out


def _real_adapter():
    scripts = ROOT / "skills" / "wechat-messaging" / "scripts"
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    from windows_adapter import WindowsAdapter
    return WindowsAdapter()


# ------------------------------------------------------------------ CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="A2b-② attempted 死结读回取证 + 授权结论化（默认 dry-run，绝不发送）")
    ap.add_argument("--marker", help="单个死结 marker 路径（结论化必填）")
    ap.add_argument("--apply", action="store_true", help="真正写 marker（需 --marker + --authorize）")
    ap.add_argument("--authorize", help="每例唯一授权串（dry-run 会打印）")
    ap.add_argument("--merchant-id", help="该流消费者要求的商家号（merchants 流必填）")
    ap.add_argument("--actor", default=DEFAULT_ACTOR)
    ap.add_argument("--note", help="附带说明，写入 completionProvenance.note")
    ap.add_argument("--allow-weaker-file-anchor", action="store_true",
                    help="允许对 file/image 载荷用「卡片在尾部」这一较弱锚点结论化")
    ap.add_argument("--scan", action="store_true", help="扫描所有死结并逐个读回取证（只读）")
    ap.add_argument("--root", action="append", default=None, help="扫描根（默认 state/ 与 .local/state/）")
    ap.add_argument("--no-adapter", action="store_true", help="扫描时不做读回（纯 marker 清单）")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.apply:
        if not args.marker:
            print("conclude-attempt-deadlock: REFUSED --apply 需要 --marker")
            return 2
        if args.no_adapter:
            print("conclude-attempt-deadlock: REFUSED --apply 不能与 --no-adapter 同用")
            return 2
        try:
            adapter = _real_adapter()
        except Exception as error:                 # noqa: BLE001
            print("conclude-attempt-deadlock: REFUSED adapter-init-failed:%s" % error)
            return 2
        row = conclude(Path(args.marker), adapter=adapter, authorize=args.authorize,
                       actor=args.actor, note=args.note,
                       allow_weaker_file_anchor=args.allow_weaker_file_anchor,
                       merchant_id=args.merchant_id, apply=True)
        print(json.dumps(row, ensure_ascii=False, indent=1))
        if row.get("decision") == "concluded-verified":
            print("conclude-attempt-deadlock: CONCLUDED %s" % row["marker"])
            return 0
        print("conclude-attempt-deadlock: REFUSED %s (%s)"
              % (row.get("reason"), row.get("decision")))
        return 2

    if args.marker:
        try:
            adapter = None if args.no_adapter else _real_adapter()
        except Exception as error:                 # noqa: BLE001
            print("conclude-attempt-deadlock: adapter-init-failed:%s（退化为纯 marker 清单）" % error)
            adapter = None
        row = conclude(Path(args.marker), adapter=adapter, authorize=None, actor=args.actor,
                       allow_weaker_file_anchor=args.allow_weaker_file_anchor,
                       merchant_id=args.merchant_id, apply=False)
        print(json.dumps(row, ensure_ascii=False, indent=1))
        if row.get("decision") == "dry-run-evidence-ok":
            print("conclude-attempt-deadlock: EVIDENCE-OK %s" % row["marker"])
            return 0
        print("conclude-attempt-deadlock: NO-EVIDENCE %s (%s)"
              % (row.get("reason"), row.get("decision")))
        return 1

    # 默认：扫描模式
    roots = [Path(p) if Path(p).is_absolute() else ROOT / p
             for p in (args.root or ["state", ".local/state"])]
    adapter = None
    if not args.no_adapter:
        try:
            adapter = _real_adapter()
        except Exception as error:                 # noqa: BLE001
            print("conclude-attempt-deadlock: adapter-init-failed:%s（只列 marker，不做读回）" % error)
    state_root = ROOT / "state" / "taobao-agent-new-merchants"
    rows = scan(roots, adapter=adapter, state_root=state_root if state_root.is_dir() else None)
    print("conclude-attempt-deadlock: deadlocks=%d adapter=%s"
          % (len(rows), "on" if adapter else "off"))
    for row in rows:
        print("  [DEADLOCK] %s" % row["path"])
        print("      group=%s type=%s age=%sh merchantId=%s"
              % (row.get("group"), row.get("payloadType"), row.get("age_hours"),
                 row.get("merchantId")))
        print("      readback=%s (%s)" % (row.get("readbackOk"), row.get("readbackReason")))
        if row.get("authorizeToken"):
            hint = "--apply --marker %s --authorize %s" % (row["path"], row["authorizeToken"])
            if row.get("merchantId"):
                hint += " --merchant-id %s" % row["merchantId"]
            print("      conclude-cmd: %s" % hint)
    if rows:
        print("conclude-attempt-deadlock: FOUND %d" % len(rows))
        return 1
    print("conclude-attempt-deadlock: CLEAN")
    return 0


# ------------------------------------------------------------------ hermetic 自测

class _FakeClient:
    def __init__(self, title: str, messages: List):
        self.title = title
        self.messages = messages

    def current(self):
        return {"ok": True, "data": {"title": self.title}}

    def read(self):
        return {"ok": True, "data": {"messages": self.messages}}


class _FakeAdapter:
    def __init__(self, title: str, messages: List, resolve=None):
        self.client = _FakeClient(title, messages)
        self._resolve = resolve

    def resolve_group(self, group, search_group=None):
        if self._resolve is not None:
            return self._resolve
        return group, "exact"


def _selftest() -> int:
    import tempfile
    ok = True

    def chk(name, cond):
        nonlocal ok
        print("  [%s] %s" % ("OK" if cond else "FAIL", name))
        ok = ok and cond

    TEXT = "城市：南通市  ；  联系人：荆  ；  店铺：旨寿司"
    SHA = _sha256_text(TEXT)
    GROUP = "电销+直播攻坚组"

    # ---------- A. 读回判据（正/负对照） ----------
    hit = _FakeAdapter(GROUP, ["上一条别的消息", {"text": TEXT}, "14:01"])
    ok_a, ev_a, _t, why_a = readback(hit, GROUP, {"text": TEXT}, window_seconds=0)
    chk("A1 载荷在尾部 ⇒ 取证通过（anchor=text-exact, 尾部位置）",
        ok_a and ev_a.get("anchor") == "text-exact" and ev_a.get("anchorInTrailingPosition") is True
        and ev_a.get("resolvedGroup") == GROUP and ev_a.get("anchorValue") == TEXT and why_a is None)

    miss = _FakeAdapter(GROUP, ["别的消息", "又是别的"])
    ok_b, _ev_b, _t, why_b = readback(miss, GROUP, {"text": TEXT}, window_seconds=0)
    chk("A2 载荷不在会话 ⇒ 拒绝，判据=windows-readback-anchor-not-trailing",
        (not ok_b) and why_b == "windows-readback-anchor-not-trailing")

    wrong_title = _FakeAdapter("别的群", [{"text": TEXT}])
    ok_c, _ev_c, _t, why_c = readback(wrong_title, GROUP, {"text": TEXT}, window_seconds=0)
    chk("A3 标题不是目标群 ⇒ 拒绝，判据=windows-current-session-title-mismatch（不代开会话）",
        (not ok_c) and why_c == "windows-current-session-title-mismatch")

    not_tail = _FakeAdapter(GROUP, [{"text": TEXT}, "别人后来又说了一句"])
    ok_d, _ev_d, _t, why_d = readback(not_tail, GROUP, {"text": TEXT}, window_seconds=0)
    chk("A4 载荷出现在中间、后面还有非时间戳消息 ⇒ 不算尾部（新鲜性）",
        (not ok_d) and why_d == "windows-readback-anchor-not-trailing")

    # 多行载荷 + 驱动把换行压平（历史坑）：必须仍能命中
    ml_text = "城市：南通市\n联系人：荆\n店铺：旨寿司"
    ml_hit = _FakeAdapter(GROUP, [{"text": "城市：南通市联系人：荆店铺：旨寿司"}, "14:01"])
    ok_e, ev_e, _t, why_e = readback(ml_hit, GROUP, {"text": ml_text}, window_seconds=0)
    chk("A5 多行载荷 vs 驱动单行化回读 ⇒ 换行压平后仍能命中",
        ok_e and ev_e.get("anchor") == "text-exact" and why_e is None)

    # ---------- B. 结论化形状必须过「真闸门」 ----------
    try:
        scripts = ROOT / "skills" / "workflows" / "daily-agent-new-merchants-to-wechat" / "scripts"
        if str(scripts) not in sys.path:
            sys.path.insert(0, str(scripts))
        import runtime_contract as rc
        gate_ok = True
    except Exception as error:                     # noqa: BLE001
        print("  [SKIP] runtime_contract 不可导入：%r" % error)
        gate_ok = False

    prior_claim = {"bridgeVersion": 1, "state": "attempted", "groupName": GROUP,
                   "payloadType": "text", "payloads": [{"text": TEXT, "sha256": SHA}],
                   "sendAttempts": None, "verified": False}
    item = {"merchantId": "1332142200", "merchantName": "旨寿司", "text": TEXT, "sha256": SHA}
    conclusion = build_conclusion(prior_claim, ev_a, merchant_id="1332142200",
                                 actor="selftest", authorized_by="selftest", note=None)

    if gate_ok:
        try:
            rc.verify_delivery(conclusion, GROUP, item)
            chk("B1 结论化形状过 runtime_contract.verify_delivery（真闸门，正例）", True)
        except Exception as error:                 # noqa: BLE001
            chk("B1 结论化形状过 runtime_contract.verify_delivery（真闸门，正例）: %r" % error, False)

        broken = json.loads(json.dumps(conclusion))
        broken["commonReceipt"]["items"][0]["evidence"]["anchorInTrailingPosition"] = False
        try:
            rc.verify_delivery(broken, GROUP, item)
            chk("B2 负例对照：抽掉 anchorInTrailingPosition ⇒ 闸门必须拒绝", False)
        except Exception:
            chk("B2 负例对照：抽掉 anchorInTrailingPosition ⇒ 闸门必须拒绝", True)

        broken2 = json.loads(json.dumps(conclusion))
        broken2["sendAttempts"] = None
        try:
            rc.verify_delivery(broken2, GROUP, item)
            chk("B3 负例对照：sendAttempts=null ⇒ 闸门必须拒绝", False)
        except Exception:
            chk("B3 负例对照：sendAttempts=null ⇒ 闸门必须拒绝", True)

    chk("B4 payloads 与 sha256 逐字保留", conclusion["payloads"] == prior_claim["payloads"]
        and conclusion["messageSha256"] == SHA)

    def _has_key(obj, key):
        if isinstance(obj, dict):
            return key in obj or any(_has_key(v, key) for v in obj.values())
        if isinstance(obj, list):
            return any(_has_key(v, key) for v in obj)
        return False

    chk("B5 不伪造 copyReadback / transport 收据（按字段名判定，诚实性）",
        not _has_key(conclusion, "copyReadback") and not _has_key(conclusion, "transport")
        and conclusion.get("verificationMethod") == "windows-driver-readback-anchor")

    # ---------- C/D/E. 授权闸门 + 形状闸门 + 端到端 ----------
    with tempfile.TemporaryDirectory() as td:
        ledger = Path(td) / "flow" / "send-attempts"
        ledger.mkdir(parents=True)
        marker = ledger / "abc.json"

        def _conclude(mk, **kw):
            kw.setdefault("readback_window", 0.0)
            return conclude(mk, **kw)

        def fresh_marker(obj=None):
            marker.write_text(json.dumps(obj if obj is not None else prior_claim,
                                         ensure_ascii=False), encoding="utf-8")

        good = _FakeAdapter(GROUP, [{"text": TEXT}, "14:01"])
        token = format_authorize_token(marker, SHA)

        fresh_marker()
        r_wrong = _conclude(marker, adapter=good, authorize="conclude:deadbeef", apply=True)
        chk("C1 错授权串 ⇒ 拒绝且不写",
            r_wrong["decision"] == "refused" and r_wrong["reason"] == "authorize-token-mismatch"
            and json.loads(marker.read_text())["state"] == "attempted")

        fresh_marker()
        r_nomid = _conclude(marker, adapter=good, authorize=None, apply=False)
        chk("C2 无 --apply ⇒ 绝不写（dry-run 只给证据与命令）",
            r_nomid["decision"] == "dry-run-evidence-ok" and r_nomid.get("applied") is False
            and json.loads(marker.read_text())["state"] == "attempted")

        fresh_marker({"bridgeVersion": 1, "state": "verified", "verified": True,
                      "groupName": GROUP, "payloadType": "text",
                      "payloads": [{"text": TEXT, "sha256": SHA}], "sendAttempts": 1})
        r_done = _conclude(marker, adapter=good, authorize=token, apply=True)
        chk("D1 已 verified 的 marker ⇒ 拒绝（不是死结）",
            r_done["decision"] == "refused" and r_done["reason"] == "marker-already-verified")

        fresh_marker({"bridgeVersion": 1, "state": "attempted", "groupName": GROUP,
                      "payloadType": "text", "payloads": [{"text": TEXT, "sha256": SHA}],
                      "sendAttempts": 1})
        r_receipt = _conclude(marker, adapter=good, authorize=token, apply=True)
        chk("D2 已有收据（sendAttempts=1）⇒ 拒绝（应走 reconcile）",
            r_receipt["decision"] == "refused" and r_receipt["reason"] == "marker-has-receipt:use-reconcile")

        fresh_marker({"bridgeVersion": 2, "state": "attempted", "groupName": GROUP,
                      "payloadType": "text", "payloads": [{"text": TEXT, "sha256": SHA}],
                      "sendAttempts": None})
        r_ver = _conclude(marker, adapter=good, authorize=token, apply=True)
        chk("D3 未知形状（bridgeVersion!=1）⇒ 拒绝",
            r_ver["decision"] == "refused" and r_ver["reason"] == "marker-not-bridge-v1")

        fresh_marker({"bridgeVersion": 1, "state": "attempted", "groupName": GROUP,
                      "payloadType": "image", "payloads": [{"name": "a.png", "sha256": SHA}],
                      "sendAttempts": None})
        r_file = _conclude(marker, adapter=good, authorize=token, apply=True)
        chk("D4 file/image 未加 --allow-weaker-file-anchor ⇒ 拒绝",
            r_file["decision"] == "refused"
            and r_file["reason"].startswith("file-payload-anchor-is-weaker"))

        # 端到端：真写（临时台账内，零生产影响）
        fresh_marker()
        before = marker.read_bytes()
        r_apply = _conclude(marker, adapter=good, authorize=token, apply=True,
                           merchant_id="1332142200", actor="selftest", note="selftest-e2e")
        after_obj = json.loads(marker.read_text())
        backups = list(ledger.glob("abc.json.bak-controlled-verified-*"))
        records = list((Path(td) / "flow" / "controlled-verifications").glob("*.json"))
        sidecars = list(ledger.glob("abc.json.readback-evidence-*.json"))
        chk("E1 --apply 后 marker=verified 且 payloads 不变",
            r_apply["decision"] == "concluded-verified" and r_apply["applied"] is True
            and after_obj["state"] == "verified" and after_obj["verified"] is True
            and after_obj["payloads"] == prior_claim["payloads"]
            and after_obj["sendAttempts"] == 1 and after_obj["merchantId"] == "1332142200")
        chk("E2 备份落盘且字节等于改前", len(backups) == 1 and backups[0].read_bytes() == before)
        chk("E3 受控结论化登记落盘", len(records) == 1)
        chk("E4 证据旁文件落盘（命名含 evidence ⇒ A2a 不会误当 marker）", len(sidecars) == 1)
        if gate_ok:
            try:
                rc.verify_delivery(after_obj, GROUP, item)
                chk("E5 落盘的 marker 过真闸门（端到端正例）", True)
            except Exception as error:             # noqa: BLE001
                chk("E5 落盘的 marker 过真闸门（端到端正例）: %r" % error, False)

        # 幂等/重复结论化 ⇒ 第二次拒绝
        r_again = _conclude(marker, adapter=good, authorize=token, apply=True)
        chk("E6 对已结论化的 marker 再来一次 ⇒ 拒绝（幂等保护）",
            r_again["decision"] == "refused" and r_again["reason"] == "marker-already-verified")

        # A2a 扫描器必须继续认为该目录 CLEAN（它的产物不自我污染）
        chk("E7 A2a 扫描器对本目录 CLEAN（产物不自我污染）", a2a.scan([Path(td) / "flow"]) == [])

        # 读回失败 ⇒ 绝不写
        marker.write_text(json.dumps(prior_claim, ensure_ascii=False), encoding="utf-8")
        r_noev = _conclude(marker, adapter=_FakeAdapter(GROUP, ["无关消息"]),
                          authorize=token, apply=True)
        chk("E8 取证失败 ⇒ 拒绝且 marker 保持 attempted",
            r_noev["decision"] == "no-evidence"
            and json.loads(marker.read_text())["state"] == "attempted")

    print("conclude-attempt-deadlock-selftest: %s" % ("ALL PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
