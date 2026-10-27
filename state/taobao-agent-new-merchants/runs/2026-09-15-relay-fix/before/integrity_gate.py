#!/usr/bin/env python3
"""Fail closed when the sealed merchant workflow executor drifts."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path


SKILL_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = SKILL_ROOT / "executor-lock.json"
SHARED_WECHAT_ROOT = Path(
    "/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts"
)
RUNTIME_FILES = {
    "workflow_executor": SKILL_ROOT / "scripts/workflow_executor.py",
    "integrity_gate": SKILL_ROOT / "scripts/executor_integrity.py",
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
    return {
        "ok": True,
        "status": "SEALED",
        "manifestSha256": hashlib.sha256(raw).hexdigest(),
        "fileCount": len(checked),
        "acceptanceMerchantId": acceptance["merchantId"],
        "acceptanceMessageSha256": acceptance["messageSha256"],
        "runtimeModelDecisions": 0,
        "maintenanceAcceptance": "desktop-wechat-shared-preflight",
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
    _validate_maintenance_acceptance(manifest)
    return {
        "ok": True,
        "status": "UNSEALED_ACCEPTANCE",
        "manifestSha256": hashlib.sha256(raw).hexdigest(),
        "fileCount": len(checked),
        "authorization": authorization,
        "runtimeModelDecisions": 0,
        "maintenanceAcceptance": "desktop-wechat-shared-preflight",
    }
