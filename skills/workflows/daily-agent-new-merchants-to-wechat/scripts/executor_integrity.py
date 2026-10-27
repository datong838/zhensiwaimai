#!/usr/bin/env python3
"""Fail closed when the sealed merchant workflow executor drifts."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = SKILL_ROOT / "executor-lock.json"
SHARED_WECHAT_ROOT = Path(
    "/Users/ddt/work/projects/ai_agent/zhensi_waimai_back/vendor/legacy-app-controler/wechat-desktop-control/scripts"
)
RUNTIME_FILES = {
    "messaging_bridge": SKILL_ROOT.parents[1] / "wechat-messaging/scripts/workflow_bridge.py",
    "messaging_preflight": SKILL_ROOT.parents[1] / "wechat-messaging/scripts/workflow_preflight.py",
    "messaging_dependencies": SKILL_ROOT.parents[1] / "wechat-messaging/dependencies.json",
    "messaging_dependency_maintenance": SKILL_ROOT.parents[1] / "wechat-messaging/scripts/dependency_maintenance.py",
    "workflow_executor": SKILL_ROOT / "scripts/workflow_executor.py",
    "maintenance_executor": SKILL_ROOT / "scripts/maintenance_executor.py",
    "integrity_gate": SKILL_ROOT / "scripts/executor_integrity.py",
    "runtime_contract": SKILL_ROOT / "scripts/runtime_contract.py",
    "background_selftest": SKILL_ROOT / "scripts/test_background_merchant_collector.mjs",
    "structured_collector": SKILL_ROOT / "scripts/structured_merchant_collector.py",
    "background_collector": SKILL_ROOT / "scripts/background_merchant_collector.mjs",
    "desktop_adapter": SKILL_ROOT / "scripts/desktop_wechat_sender.py",
    "mobile_sender": SKILL_ROOT / "scripts/wechat_sender_executor.py",
    "shared_desktop_sender": SHARED_WECHAT_ROOT / "desktop_sender.py",
    "shared_desktop_preflight": SHARED_WECHAT_ROOT / "desktop_preflight.py",
    "shared_wechat_interaction_lock": SHARED_WECHAT_ROOT / "wechat_interaction_lock.py",
    "shared_desktop_locator": SHARED_WECHAT_ROOT / "wechat_desktop.py",
    "shared_click_source": SHARED_WECHAT_ROOT / "cgevent_click.swift",
    "shared_click_binary": SHARED_WECHAT_ROOT / "cgevent_click_bin",
}


class IntegrityError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_acceptance(acceptance: dict, metadata: dict) -> None:
    required = {
        "merchantId": metadata.get("merchantId"),
        "messageSha256": metadata.get("messageSha256"),
        "physicalSendAttempts": 1,
        "runtimeModelDecisions": 0,
        "verified": True,
    }
    for key, expected in required.items():
        if acceptance.get(key) != expected:
            raise IntegrityError(f"executor-lock-acceptance-{key}-mismatch")
    ui_items = [row for row in (acceptance.get("commonReceipt") or {}).get("items", [])
                if row.get("verificationLevel") == "wecom-ui-tree-text"]
    if ui_items:
        from runtime_contract import verify_delivery
        payloads = acceptance.get("payloads") or []
        if (len(ui_items) != 1 or len(payloads) != 1
                or len((acceptance.get("commonReceipt") or {}).get("items", [])) != 1
                or (acceptance.get("commonReceipt") or {}).get("status") != "verified"
                or ui_items[0].get("status") != "verified" or ui_items[0].get("sendAttempts") != 1
                or acceptance.get("postSendInputCleared") != [True, True]):
            raise IntegrityError("executor-lock-acceptance-ui-evidence-invalid")
        try:
            verify_delivery(acceptance, "电销+直播攻坚组", {
                "merchantId": metadata.get("merchantId"),
                "sha256": metadata.get("messageSha256"),
                "text": payloads[0].get("text", ""),
            })
        except (RuntimeError, KeyError, TypeError) as error:
            raise IntegrityError("executor-lock-acceptance-ui-evidence-invalid") from error
        return
    # 2026-09-30 大同授权：Windows 驱动服务通道的对等验收证据——服务端读回
    # 锚点（text-exact 且位于会话尾部，文本 sha256 与凭据一致）替代 Mac 原生
    # 两帧输入框清空/复制读回；证据缺失时回落原 fail-closed 契约。
    for it in ((acceptance.get("commonReceipt") or {}).get("items") or []):
        if (it.get("verificationLevel") == "windows-readback-text-anchor"
                and isinstance(it.get("evidence"), dict)):
            evidence = it["evidence"]
            if not (evidence.get("ok") is True
                    and evidence.get("anchor") == "text-exact"
                    and evidence.get("anchorInTrailingPosition") is True
                    and hashlib.sha256(str(evidence.get("anchorValue") or "").encode()).hexdigest()
                        == acceptance.get("messageSha256")):
                raise IntegrityError("executor-lock-acceptance-window-readback-invalid")
            return
    if acceptance.get("postSendInputCleared") != [True, True]:
        raise IntegrityError("executor-lock-acceptance-composer-not-empty")
    readback = acceptance.get("copyReadback") or {}
    if not (
        readback.get("ok") is True
        and readback.get("composerEmpty") is True
        and readback.get("copyMenuCount") == 1
        and readback.get("copiedTextSha256") == acceptance.get("messageSha256")
        and len(readback.get("bubblePositions") or []) == 2
    ):
        raise IntegrityError("executor-lock-acceptance-copy-readback-invalid")


def _validate_maintenance_acceptance(manifest: dict) -> None:
    metadata = manifest.get("maintenanceAcceptance") or {}
    if metadata.get("type") != "desktop-wechat-shared-preflight":
        raise IntegrityError("executor-lock-maintenance-type-mismatch")
    receipt_path = Path(str(metadata.get("receiptPath") or ""))
    if not receipt_path.is_file():
        raise IntegrityError("executor-lock-maintenance-receipt-missing")
    if sha256(receipt_path) != metadata.get("receiptSha256"):
        raise IntegrityError("executor-lock-maintenance-receipt-digest-mismatch")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrityError(f"executor-lock-maintenance-receipt-invalid:{error}") from error
    target = receipt
    expected_group = metadata.get("groupName")
    if not (
        target.get("ok") is True
        and target.get("sendAttempts") == 0
        and target.get("runtimeModelDecisions") == 0
        and target.get("group") == expected_group
        and target.get("header") == expected_group
        and target.get("note") in ("ax-current-header", "ax-visible-exact-row")
        and target.get("hardGate") is False
        and target.get("artifacts") == []
        and (target.get("interactionLock") or {}).get("acquired") is True
        and (target.get("interactionLock") or {}).get("released") is True
    ):
        raise IntegrityError("executor-lock-maintenance-receipt-contract-mismatch")


def _load_bound_json(metadata: dict, prefix: str, path_key: str = "receiptPath",
                     digest_key: str = "receiptSha256") -> dict:
    receipt_path = Path(str(metadata.get(path_key) or ""))
    if not receipt_path.is_file():
        raise IntegrityError(f"executor-lock-{prefix}-receipt-missing")
    if sha256(receipt_path) != metadata.get(digest_key):
        raise IntegrityError(f"executor-lock-{prefix}-receipt-digest-mismatch")
    try:
        return json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrityError(f"executor-lock-{prefix}-receipt-invalid:{error}") from error


def _validate_shared_text_acceptance(manifest: dict) -> None:
    metadata = manifest.get("sharedTextAcceptance") or {}
    if metadata.get("type") != "wechat-messaging-desktop-text":
        raise IntegrityError("executor-lock-shared-text-type-mismatch")
    receipt = _load_bound_json(metadata, "shared-text")
    items = receipt.get("items") or []
    if not (
        receipt.get("ok") is True
        and receipt.get("status") == "verified"
        and receipt.get("groupName") == metadata.get("groupName")
        and receipt.get("channel") == "desktop"
        and receipt.get("requestDigest") == metadata.get("requestDigest")
        and receipt.get("runtimeModelDecisions") == 0
        and len(items) == 1
    ):
        raise IntegrityError("executor-lock-shared-text-receipt-contract-mismatch")
    item = items[0]
    evidence = item.get("evidence") or {}
    transport = item.get("transport") or {}
    if not (
        item.get("itemId") == metadata.get("itemId")
        and item.get("type") == "text"
        and item.get("sha256") == metadata.get("messageSha256")
        and item.get("status") == "verified"
        and item.get("sendAttempts") == 1
        and item.get("verificationLevel") == "native-text-exact"
        and evidence.get("ok") is True
        and evidence.get("composerEmpty") is True
        and evidence.get("copyMenuCount") == 1
        and evidence.get("copiedTextSha256") == item.get("sha256")
        and len(evidence.get("bubblePositions") or []) == 2
        and transport.get("groupName") == metadata.get("groupName")
        and transport.get("payloadType") == "text"
        and transport.get("sendAttempts") == 1
        and transport.get("runtimeModelDecisions") == 0
        and transport.get("textInputVerified") is True
        and transport.get("textWriteAttempts") == 1
        and transport.get("clipboardClearedBeforeTextWrite") is True
        and transport.get("postSendInputCleared") == [True, True]
        and transport.get("verified") is True
        and transport.get("state") == "verified"
    ):
        raise IntegrityError("executor-lock-shared-text-evidence-invalid")


def _validate_code_maintenance(manifest: dict) -> None:
    metadata = manifest.get("unsealedAcceptance") or {}
    receipt_path = Path(str(metadata.get("maintenanceReceiptPath") or ""))
    if not receipt_path.is_file():
        raise IntegrityError("executor-lock-code-maintenance-receipt-missing")
    if sha256(receipt_path) != metadata.get("maintenanceReceiptSha256"):
        raise IntegrityError("executor-lock-code-maintenance-receipt-digest-mismatch")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrityError(f"executor-lock-code-maintenance-receipt-invalid:{error}") from error
    candidate = receipt.get("candidateFiles") or {}
    current = {
        label: {"path": str(path), "sha256": sha256(path)}
        for label, path in RUNTIME_FILES.items()
    }
    if not (
        receipt.get("ok") is True
        and receipt.get("status") == "prepared"
        and receipt.get("maintenanceAuthorization") == metadata.get("maintenanceAuthorization")
        and receipt.get("runtimeAuthorization") == metadata.get("authorization")
        and receipt.get("expiresAt") == metadata.get("expiresAt")
        and receipt.get("userInstructionSha256") == metadata.get("userInstructionSha256")
        and receipt.get("sendAttempts") == 0
        and receipt.get("runtimeModelDecisions") == 0
        and (receipt.get("merchantTests") or {}).get("ok") is True
        and (receipt.get("merchantTests") or {}).get("testCount", 0) > 0
        and candidate == current
    ):
        raise IntegrityError("executor-lock-code-maintenance-receipt-contract-mismatch")
    dependency_path = Path(str(receipt.get("dependencyReceiptPath") or ""))
    if not dependency_path.is_file() or sha256(dependency_path) != receipt.get("dependencyReceiptSha256"):
        raise IntegrityError("executor-lock-code-maintenance-dependency-receipt-invalid")
    dependency = json.loads(dependency_path.read_text(encoding="utf-8"))
    if not (
        dependency.get("ok") is True
        and dependency.get("status") == "prepared"
        and dependency.get("sendAttempts") == 0
        and dependency.get("runtimeModelDecisions") == 0
        and (dependency.get("tests") or {}).get("ok") is True
        and (dependency.get("tests") or {}).get("testCount", 0) > 0
    ):
        raise IntegrityError("executor-lock-code-maintenance-dependency-contract-mismatch")


def _validate_shared_media_acceptance(manifest: dict) -> None:
    metadata = manifest.get("sharedMediaAcceptance") or {}
    if metadata.get("type") != "wechat-messaging-desktop-file-image":
        raise IntegrityError("executor-lock-shared-media-type-mismatch")
    receipt = _load_bound_json(metadata, "shared-media")
    replay = _load_bound_json(metadata, "shared-media-replay", "replayPath", "replaySha256")
    accepted = _load_bound_json(metadata, "shared-media-version", "acceptedVersionPath", "acceptedVersionSha256")
    dependencies_path = SKILL_ROOT.parents[1] / "wechat-messaging/dependencies.json"
    try:
        current_dependencies = json.loads(dependencies_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrityError(f"executor-lock-shared-media-dependencies-invalid:{error}") from error
    if accepted.get("dependencies") != current_dependencies:
        raise IntegrityError("executor-lock-shared-media-version-dependencies-mismatch")
    items = receipt.get("items") or []
    if not (
        receipt.get("ok") is True
        and receipt.get("status") == "verified"
        and receipt.get("groupName") == metadata.get("groupName")
        and receipt.get("channel") == "desktop"
        and receipt.get("requestDigest") == metadata.get("requestDigest")
        and receipt.get("runtimeModelDecisions") == 0
        and [item.get("type") for item in items] == ["file", "image"]
    ):
        raise IntegrityError("executor-lock-shared-media-receipt-contract-mismatch")
    levels = {"file": "file-name-size-ui", "image": "image-content-match"}
    for item in items:
        evidence = item.get("evidence") or {}
        transport = item.get("transport") or {}
        if not (
            item.get("status") == "verified"
            and item.get("sendAttempts") == 1
            and item.get("verificationLevel") == levels[item.get("type")]
            and evidence.get("ok") is True
            and len(evidence.get("frames") or []) == 2
            and transport.get("groupName") == metadata.get("groupName")
            and transport.get("payloadType") == item.get("type")
            and transport.get("sendAttempts") == 1
            and transport.get("runtimeModelDecisions") == 0
            and transport.get("postSendInputCleared") == [True, True]
            and transport.get("verified") is True
            and transport.get("state") == "verified"
        ):
            raise IntegrityError("executor-lock-shared-media-evidence-invalid")
    if not (
        replay.get("ok") is True
        and replay.get("status") == "already_verified"
        and replay.get("requestDigest") == receipt.get("requestDigest")
        and replay.get("runtimeModelDecisions") == 0
        and all(item.get("sendAttempts") == 1 for item in replay.get("items") or [])
    ):
        raise IntegrityError("executor-lock-shared-media-replay-invalid")


def _load_manifest(manifest_path: Path) -> tuple[bytes, dict]:
    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw)
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrityError(f"executor-lock-unreadable:{error}") from error
    if manifest.get("schemaVersion") != 1:
        raise IntegrityError("executor-lock-schema-mismatch")
    return raw, manifest


def _validate_runtime_files(manifest: dict) -> list[dict]:
    entries = manifest.get("files")
    if not isinstance(entries, dict) or set(entries) != set(RUNTIME_FILES):
        raise IntegrityError("executor-lock-file-set-mismatch")
    checked = []
    for label, expected_path in RUNTIME_FILES.items():
        entry = entries.get(label) or {}
        if entry.get("path") != str(expected_path):
            raise IntegrityError(f"executor-lock-path-mismatch:{label}")
        if not expected_path.is_file():
            raise IntegrityError(f"executor-lock-file-missing:{label}")
        actual = sha256(expected_path)
        if entry.get("sha256") != actual:
            raise IntegrityError(f"executor-lock-digest-mismatch:{label}")
        checked.append({"label": label, "sha256": actual})
    return checked


def verify(manifest_path: Path = MANIFEST_PATH) -> dict:
    raw, manifest = _load_manifest(manifest_path)
    if manifest.get("status") != "SEALED":
        raise IntegrityError("executor-lock-not-sealed")
    checked = _validate_runtime_files(manifest)
    acceptance_meta = manifest.get("acceptance") or {}
    receipt_path = Path(str(acceptance_meta.get("receiptPath") or ""))
    if not receipt_path.is_file():
        raise IntegrityError("executor-lock-acceptance-receipt-missing")
    if sha256(receipt_path) != acceptance_meta.get("receiptSha256"):
        raise IntegrityError("executor-lock-acceptance-receipt-digest-mismatch")
    try:
        acceptance = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrityError(f"executor-lock-acceptance-receipt-invalid:{error}") from error
    _validate_acceptance(acceptance, acceptance_meta)
    _validate_maintenance_acceptance(manifest)
    _validate_shared_text_acceptance(manifest)
    return {
        "ok": True,
        "status": "SEALED",
        "manifestSha256": hashlib.sha256(raw).hexdigest(),
        "fileCount": len(checked),
        "acceptanceMerchantId": acceptance["merchantId"],
        "acceptanceMessageSha256": acceptance["messageSha256"],
        "runtimeModelDecisions": 0,
        "maintenanceAcceptance": "desktop-wechat-shared-preflight",
        "sharedTextAcceptance": "wechat-messaging-desktop-text",
        "sharedMediaAcceptance": "not-required-by-text-only-merchant-workflow",
    }


def verify_unsealed_acceptance(authorization: str, manifest_path: Path = MANIFEST_PATH) -> dict:
    raw, manifest = _load_manifest(manifest_path)
    if manifest.get("status") != "UNSEALED_ACCEPTANCE":
        raise IntegrityError("executor-lock-not-unsealed-for-acceptance")
    metadata = manifest.get("unsealedAcceptance") or {}
    if not authorization or authorization != metadata.get("authorization"):
        raise IntegrityError("executor-lock-unsealed-authorization-mismatch")
    try:
        expires_at = datetime.fromisoformat(str(metadata.get("expiresAt") or ""))
    except ValueError as error:
        raise IntegrityError("executor-lock-unsealed-expiry-invalid") from error
    if expires_at.tzinfo is None or datetime.now(expires_at.tzinfo) > expires_at:
        raise IntegrityError("executor-lock-unsealed-authorization-expired")
    checked = _validate_runtime_files(manifest)
    _validate_code_maintenance(manifest)
    _validate_maintenance_acceptance(manifest)
    _validate_shared_text_acceptance(manifest)
    return {
        "ok": True,
        "status": "UNSEALED_ACCEPTANCE",
        "manifestSha256": hashlib.sha256(raw).hexdigest(),
        "fileCount": len(checked),
        "authorization": authorization,
        "runtimeModelDecisions": 0,
        "maintenanceAcceptance": "desktop-wechat-shared-preflight",
        "sharedTextAcceptance": "wechat-messaging-desktop-text",
        "sharedMediaAcceptance": "not-required-by-text-only-merchant-workflow",
    }


def verify_for_run(authorization: str | None = None,
                   manifest_path: Path = MANIFEST_PATH) -> dict:
    """Use one fixed entrypoint while preserving the lock's code-owned state gate."""
    _, manifest = _load_manifest(manifest_path)
    status = manifest.get("status")
    if status == "SEALED":
        return verify(manifest_path)
    if status == "UNSEALED_ACCEPTANCE":
        return verify_unsealed_acceptance(authorization or "", manifest_path)
    raise IntegrityError("executor-lock-status-invalid")


def _atomic_manifest(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def seal_from_nonempty_acceptance(result: dict, output_dir: Path,
                                  manifest_path: Path = MANIFEST_PATH) -> dict:
    """Seal only the exact candidate that completed a real new desktop send."""
    _, manifest = _load_manifest(manifest_path)
    if manifest.get("status") != "UNSEALED_ACCEPTANCE":
        raise IntegrityError("executor-lock-reseal-requires-unsealed")
    integrity = result.get("executorIntegrity") or {}
    if integrity.get("status") != "UNSEALED_ACCEPTANCE":
        raise IntegrityError("executor-lock-reseal-run-not-unsealed")
    if not (result.get("finalCursor") or {}).get("verified"):
        raise IntegrityError("executor-lock-reseal-final-cursor-unverified")
    delivery = result.get("wechat") or {}
    new_items = []
    for item in delivery.get("items") or []:
        reviews = item.get("review") or []
        sent_here = any(row.get("stage") == "定位、输入与单次发送"
                        and row.get("status") in ("PASS", "FAIL") for row in reviews)
        committed = any(row.get("stage") == "成功历史与原子游标提交"
                        and row.get("status") == "PASS" for row in reviews)
        if sent_here and committed:
            new_items.append(item)
    if not new_items:
        raise IntegrityError("executor-lock-reseal-nonempty-send-required")
    accepted = new_items[-1]
    receipt_path = (Path(output_dir).resolve() / "desktop-wechat" /
                    str(accepted.get("merchantId")) / "acceptance-receipt.json")
    if not receipt_path.is_file():
        raise IntegrityError("executor-lock-reseal-acceptance-receipt-missing")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IntegrityError(f"executor-lock-reseal-acceptance-receipt-invalid:{error}") from error
    metadata = {
        "receiptPath": str(receipt_path),
        "receiptSha256": sha256(receipt_path),
        "merchantId": accepted.get("merchantId"),
        "messageSha256": receipt.get("messageSha256"),
        "verification": ("wecom-ui-tree-text" if any(row.get("verificationLevel") == "wecom-ui-tree-text" for row in (receipt.get("commonReceipt") or {}).get("items", [])) else "desktop-bubble-copy-exact-two-frame"),
    }
    _validate_acceptance(receipt, metadata)
    final_cursor = result["finalCursor"]
    if final_cursor.get("merchantId") != metadata["merchantId"]:
        raise IntegrityError("executor-lock-reseal-final-cursor-mismatch")
    checked = _validate_runtime_files(manifest)
    manifest["files"] = {
        label: {"path": str(path), "sha256": sha256(path)}
        for label, path in RUNTIME_FILES.items()
    }
    manifest["acceptance"] = metadata
    manifest["latestRealSend"] = dict(metadata)
    manifest["lastUnsealedAcceptance"] = manifest.get("unsealedAcceptance")
    manifest.pop("unsealedAcceptance", None)
    manifest["status"] = "SEALED"
    manifest["sealedAt"] = datetime.now().astimezone().isoformat()
    manifest["sealedBy"] = "code-verified-real-nonempty-acceptance"
    _atomic_manifest(manifest_path, manifest)
    verified = verify(manifest_path)
    return verified | {
        "resealed": True,
        "acceptanceReceiptPath": str(receipt_path),
        "checkedCandidateFiles": len(checked),
    }
