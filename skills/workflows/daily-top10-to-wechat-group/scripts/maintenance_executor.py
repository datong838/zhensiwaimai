#!/usr/bin/env python3
"""Zero-send, receipt-bound refresh of the shared WeChat manifest pin."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import runtime_guard


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT.parents[2]
POLICY = ROOT / "runtime-policy.json"
SHARED_ROOT = ROOT.parents[1] / "wechat-messaging"
SHARED_MANIFEST = SHARED_ROOT / "dependencies.json"
AUTHORIZATION = "user-20261028-ui-execution-closure"
INSTRUCTION_SHA256 = "ad3ab4f8a8bd21f9a84a2c17242733036a90c489ba95eaf5b7208e4d60e33ce3"
EXPECTED_CHANGE_PATHS = {
    "scripts/dependency_maintenance.py",
    "scripts/file_size_policy.py",
    "scripts/native_ui_tree.py",
    "scripts/presentation_policy.py",
    "scripts/registered_ui_routes.py",
    "scripts/wecom_adapter.py",
    "scripts/wecom_ui_queue.py",
    "config/ui-execution-policy.json",
    "config/native-ui-selectors.json",
    "scripts/native_ui_tree.jxa",
}
EXPECTED_AFTER = {
    "scripts/file_size_policy.py": "bbee1269d339bd21583b626451ef4772a1d5a4222ca5abb892bd4ab0f9173299",
    "scripts/native_ui_tree.py": "89d6e21e6f3303eca512154994ae03ffc7716908ffd1f4b3476a45b5dd4b66a7",
    "scripts/presentation_policy.py": "cea830bd3ac88a90a34932e1b3c80a1557de5c63c3724cdf9f56111d5129c507",
    "scripts/registered_ui_routes.py": "154fa6fb7dba37822f39c6b2d23920403ba635bbb46b9d365757b26dd3a9c010",
    "scripts/wecom_adapter.py": "d14448385606c83a58b96f640300049a4001db693e6a3d3a4a5884f6bb6aebd1",
    "scripts/wecom_ui_queue.py": "5ceb7ae15972a4b2564471c72eac6a94fb8d41bcc51adfffa9e14e9cdbc1e9ba",
    "config/ui-execution-policy.json": "5332b773fbf5c1044f47da9867e08c58ab122908e66582219734bf4171017351",
    "config/native-ui-selectors.json": "04d0bf97e3e1a6a743400dd8c82a06171ab921824ee7f598f6891dbf118747f9",
    "scripts/native_ui_tree.jxa": "bba531ba0fed9b84f82f57146dae4dee70afea75b30f1d467c0a359fe2d9b8e6",
}


class MaintenanceError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_json(path: Path, value: dict) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("xb") as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def validate_receipt(receipt: dict, policy: dict, now: datetime) -> dict:
    checks = (
        receipt.get("ok") is True,
        receipt.get("action") == "prepare",
        receipt.get("status") == "prepared",
        receipt.get("authorization") == AUTHORIZATION,
        receipt.get("userInstructionSha256") == INSTRUCTION_SHA256,
        receipt.get("sendAttempts") == 0,
        receipt.get("runtimeModelDecisions") == 0,
        (receipt.get("tests") or {}).get("ok") is True,
        int((receipt.get("tests") or {}).get("testCount") or 0) > 0,
        (receipt.get("capabilityCheck") or {}).get("ok") is True,
    )
    if not all(checks):
        raise MaintenanceError("top10-public-resync-receipt-invalid")
    try:
        expiry = datetime.fromisoformat(str(receipt.get("expiresAt")))
    except ValueError as error:
        raise MaintenanceError("top10-public-resync-expiry-invalid") from error
    if expiry.tzinfo is None or now.astimezone(expiry.tzinfo) >= expiry:
        raise MaintenanceError("top10-public-resync-receipt-expired")
    current_entry = (policy.get("files") or {}).get("messaging_dependencies") or {}
    if (receipt.get("dependencyManifestPath") != str(SHARED_MANIFEST)
            or receipt.get("dependencyManifestBeforeSha256") != current_entry.get("sha256")
            or receipt.get("dependencyManifestAfterSha256") != sha256(SHARED_MANIFEST)):
        raise MaintenanceError("top10-public-resync-receipt-binding")
    changes = receipt.get("changes")
    if not isinstance(changes, list) or {item.get("path") for item in changes} != EXPECTED_CHANGE_PATHS:
        raise MaintenanceError("top10-public-resync-change-scope")
    for item in changes:
        path = item.get("path")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("before") or "")):
            raise MaintenanceError("top10-public-resync-before-invalid")
        if path != "scripts/dependency_maintenance.py" and item.get("after") != EXPECTED_AFTER.get(path):
            raise MaintenanceError("top10-public-resync-unreviewed-bytes")
    return receipt


def refresh(receipt_path: Path, output_dir: Path, now: datetime | None = None,
            policy_path: Path = POLICY, validator=runtime_guard.validate_runtime_policy) -> dict:
    now = now or datetime.now().astimezone()
    output_dir.mkdir(parents=True, exist_ok=False, mode=0o700)
    original = policy_path.read_bytes()
    result = {"ok": False, "action": "refresh-public-dependency", "status": "blocked",
              "sendAttempts": 0, "runtimeModelDecisions": 0}
    lock_path = policy_path.with_suffix(policy_path.suffix + ".ui-closure.lock")
    lock_fd = None
    wrote = False
    try:
        if any((PROJECT / "runtime/state/live_steps").iterdir()):
            raise MaintenanceError("top10-public-resync-director-busy")
        lock_fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        policy = json.loads(original)
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        validate_receipt(receipt, policy, now)
        for label, expected_path in runtime_guard.EXPECTED_POLICY_FILES.items():
            if label == "messaging_dependencies":
                continue
            entry = policy["files"].get(label) or {}
            if entry.get("path") != str(expected_path) or sha256(expected_path) != entry.get("sha256"):
                raise MaintenanceError(f"top10-public-resync-local-drift:{label}")
        candidate = json.loads(json.dumps(policy))
        candidate["files"]["messaging_dependencies"]["sha256"] = sha256(SHARED_MANIFEST)
        if policy_path.read_bytes() != original:
            raise MaintenanceError("top10-public-resync-concurrent-maintenance")
        (output_dir / "original-runtime-policy.json").write_bytes(original)
        atomic_json(policy_path, candidate); wrote = True
        validator(policy_path)
        result.update(ok=True, status="SEALED", receiptSha256=sha256(receipt_path),
                      policyBeforeSha256=hashlib.sha256(original).hexdigest(),
                      policyAfterSha256=sha256(policy_path),
                      messagingDependenciesSha256=sha256(SHARED_MANIFEST))
    except Exception as error:
        result["reason"] = str(error)
        if wrote:
            policy_path.write_bytes(original)
            result["rollback"] = "restored"
    finally:
        if lock_fd is not None:
            os.close(lock_fd)
            lock_path.unlink(missing_ok=True)
        result["observedAt"] = datetime.now().astimezone().isoformat()
        atomic_json(output_dir / "receipt.json", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("refresh-public-dependency",))
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    result = refresh(Path(args.receipt), Path(args.output_dir))
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
