import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import maintenance_executor as maintenance


class MaintenanceExecutorTests(unittest.TestCase):
    def expiry(self):
        return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name)
        lock = root / "executor-lock.json"
        dependency = root / "dependencies.json"
        runtime = root / "runtime.py"; runtime.write_text("current", encoding="utf-8")
        manifest = {"schemaVersion": 1, "status": "SEALED", "files": {},
                    "acceptance": {}, "maintenanceAcceptance": {}, "sharedTextAcceptance": {}}
        raw = (json.dumps(manifest) + "\n").encode()
        lock.write_bytes(raw); dependency.write_text("old", encoding="utf-8")
        return directory, root, lock, dependency, runtime, manifest, raw

    def test_wrong_authorization_leaves_lock_untouched(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        result = maintenance.prepare("wrong", self.expiry(), root / "out", lock, dependency,
                                     run_command=lambda *_: self.fail("must not run"))
        self.assertFalse(result["ok"])
        self.assertEqual(lock.read_bytes(), raw)

    def test_shared_drift_requires_exact_dependency_binding(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        manifest["files"] = {"shared": {"path": str(runtime), "sha256": "0" * 64}}
        lock.write_text(json.dumps(manifest))
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {str(runtime): maintenance.sha256(runtime)}}))
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {
                 "shared": runtime,
                 "maintenance_executor": runtime,
                 "messaging_dependency_maintenance": runtime,
             }), patch.object(maintenance.executor_integrity, "_load_bound_json", return_value={}), \
             patch.object(maintenance.executor_integrity, "_validate_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_maintenance_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_shared_text_acceptance"):
            maintenance._load_sealed_baseline(lock, dependency)
            dependency.write_text(json.dumps({"schemaVersion": 1, "files": {str(runtime): "f" * 64}}))
            with self.assertRaisesRegex(maintenance.MaintenanceError, "unapproved-runtime-drift:shared"):
                maintenance._load_sealed_baseline(lock, dependency)

    def test_sealed_baseline_accepts_already_registered_maintenance_labels(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        files = {label: {"path": str(runtime), "sha256": maintenance.sha256(runtime)} for label in (
            "shared", "maintenance_executor", "messaging_dependency_maintenance")}
        manifest["files"] = files
        lock.write_text(json.dumps(manifest))
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {}}))
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {
                 "shared": runtime,
                 "maintenance_executor": runtime,
                 "messaging_dependency_maintenance": runtime,
             }), patch.object(maintenance.executor_integrity, "_load_bound_json", return_value={}), \
             patch.object(maintenance.executor_integrity, "_validate_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_maintenance_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_shared_text_acceptance"):
            maintenance._load_sealed_baseline(lock, dependency)

    def test_sealed_baseline_accepts_authorized_maintenance_executor_drift(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        files = {label: {"path": str(runtime), "sha256": maintenance.sha256(runtime)} for label in (
            "shared", "maintenance_executor", "messaging_dependency_maintenance")}
        files["maintenance_executor"]["sha256"] = "0" * 64
        manifest["files"] = files
        lock.write_text(json.dumps(manifest))
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {}}))
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {
                 "shared": runtime,
                 "maintenance_executor": runtime,
                 "messaging_dependency_maintenance": runtime,
             }), patch.object(maintenance.executor_integrity, "_load_bound_json", return_value={}), \
             patch.object(maintenance.executor_integrity, "_validate_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_maintenance_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_shared_text_acceptance"):
            maintenance._load_sealed_baseline(lock, dependency)

    def test_sealed_baseline_accepts_registered_shared_locator_drift(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        files = {label: {"path": str(runtime), "sha256": maintenance.sha256(runtime)} for label in (
            "shared_desktop_locator", "maintenance_executor", "messaging_dependency_maintenance")}
        files["shared_desktop_locator"]["sha256"] = "0" * 64
        manifest["files"] = files
        lock.write_text(json.dumps(manifest))
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {}}))
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {
                 "shared_desktop_locator": runtime,
                 "maintenance_executor": runtime,
                 "messaging_dependency_maintenance": runtime,
             }), patch.object(maintenance.executor_integrity, "_load_bound_json", return_value={}), \
             patch.object(maintenance.executor_integrity, "_validate_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_maintenance_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_shared_text_acceptance"):
            maintenance._load_sealed_baseline(lock, dependency)

    def test_allowed_pre_refresh_drift_includes_workflow_executor(self):
        self.assertIn("workflow_executor", maintenance.ALLOWED_EXISTING_DRIFT)
        self.assertIn("runtime_contract", maintenance.ALLOWED_EXISTING_DRIFT)

    def test_allowed_pre_refresh_drift_includes_dependency_maintenance(self):
        self.assertIn("messaging_dependency_maintenance", maintenance.ALLOWED_EXISTING_DRIFT)
        self.assertIn("desktop_adapter", maintenance.ALLOWED_EXISTING_DRIFT)

    def test_browser_repair_drift_requires_exact_candidate_sha256(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        manifest["files"] = {
            "background_collector": {"path": str(runtime), "sha256": "0" * 64},
            "maintenance_executor": {"path": str(runtime), "sha256": maintenance.sha256(runtime)},
            "messaging_dependency_maintenance": {"path": str(runtime), "sha256": maintenance.sha256(runtime)},
        }
        lock.write_text(json.dumps(manifest))
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {}}))
        shared = {"background_collector": runtime, "maintenance_executor": runtime,
                  "messaging_dependency_maintenance": runtime}
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", shared), \
             patch.object(maintenance, "AUTHORIZED_REPAIR_CANDIDATE_SHA256",
                          {"background_collector": maintenance.sha256(runtime)}), \
             patch.object(maintenance.executor_integrity, "_load_bound_json", return_value={}), \
             patch.object(maintenance.executor_integrity, "_validate_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_maintenance_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_shared_text_acceptance"):
            maintenance._load_sealed_baseline(lock, dependency)
            with patch.object(maintenance, "AUTHORIZED_REPAIR_CANDIDATE_SHA256",
                              {"background_collector": "f" * 64}):
                with self.assertRaisesRegex(maintenance.MaintenanceError,
                                            "maintenance-unapproved-runtime-drift:background_collector"):
                    maintenance._load_sealed_baseline(lock, dependency)

    def test_unsealed_refresh_requires_exact_browser_repair_candidates(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        locator = str(runtime); actual = maintenance.sha256(runtime)
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {locator: actual}}), encoding="utf-8")
        dependency_manifest_sha = maintenance.sha256(dependency)
        receipt = root / "maintenance-receipt.json"
        refresh_expiry = self.expiry()
        receipt.write_text(json.dumps({"sendAttempts": 0, "runtimeModelDecisions": 0,
                                       "status": "prepared",
                                       "maintenanceAuthorization": maintenance.MAINTENANCE_AUTHORIZATION,
                                       "runtimeAuthorization": maintenance.RUNTIME_ACCEPTANCE_AUTHORIZATION,
                                       "userInstructionSha256": maintenance.USER_INSTRUCTION_SHA256}),
                           encoding="utf-8")
        manifest.update(status="UNSEALED_ACCEPTANCE", unsealedAcceptance={
            "maintenanceAuthorization": maintenance.MAINTENANCE_AUTHORIZATION,
            "maintenanceReceiptPath": str(receipt),
            "maintenanceReceiptSha256": maintenance.sha256(receipt),
            "authorization": maintenance.RUNTIME_ACCEPTANCE_AUTHORIZATION,
            "expiresAt": refresh_expiry,
        })
        runtime_map = {
            "background_collector": runtime, "background_selftest": runtime,
            "shared_desktop_locator": runtime, "messaging_dependencies": dependency,
            "maintenance_executor": runtime,
            "messaging_dependency_maintenance": maintenance.DEPENDENCY_MAINTENANCE,
        }
        candidates = {label: {"path": str(path), "sha256": maintenance.sha256(path)}
                      for label, path in runtime_map.items()}
        manifest["files"] = {label: dict(entry) for label, entry in candidates.items()}
        manifest["files"]["background_collector"]["sha256"] = "0" * 64
        manifest["files"]["background_selftest"]["sha256"] = "0" * 64
        lock.write_text(json.dumps(manifest), encoding="utf-8")
        dependency_receipt = root / "clean-dependency-receipt.json"
        dependency_receipt.write_text(json.dumps({
            "action": "prepare", "status": "prepared",
            "authorization": maintenance.SHARED_DEPENDENCY_MAINTENANCE_AUTHORIZATION,
            "userInstructionSha256": maintenance.SHARED_DEPENDENCY_USER_INSTRUCTION_SHA256,
            "dependencyManifestPath": str(dependency),
            "dependencyManifestBeforeSha256": dependency_manifest_sha,
            "dependencyManifestAfterSha256": dependency_manifest_sha, "changes": [],
            "tests": {"ok": True, "testCount": 9}, "capabilityCheck": {"ok": True},
            "sendAttempts": 0, "runtimeModelDecisions": 0,
        }), encoding="utf-8")
        dependency_receipt_sha = maintenance.sha256(dependency_receipt)
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", runtime_map), \
             patch.object(maintenance, "AUTHORIZED_REPAIR_CANDIDATE_SHA256",
                          {"background_collector": candidates["background_collector"]["sha256"],
                           "background_selftest": candidates["background_selftest"]["sha256"]}), \
             patch.object(maintenance, "DEPENDENCY_MANIFEST", dependency), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_PATH", locator), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_SHA256", actual), \
             patch.object(maintenance, "_stable_runtime_candidate_files", return_value=candidates), \
             patch.object(maintenance.executor_integrity, "verify_unsealed_acceptance",
                          return_value={"ok": True, "status": "UNSEALED_ACCEPTANCE"}):
            result = maintenance.refresh_unsealed(maintenance.MAINTENANCE_AUTHORIZATION,
                                                   root / "refresh-ok", refresh_expiry, lock,
                                                   dependency_receipt, dependency_receipt_sha,
                                                   run_command=lambda *_: {"ok": True, "elapsedMs": 1,
                                                                           "testCount": 16})
        self.assertTrue(result["ok"], result)

        before_lock = lock.read_bytes(); before_receipt = receipt.read_bytes()
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", runtime_map), \
             patch.object(maintenance, "AUTHORIZED_REPAIR_CANDIDATE_SHA256",
                          {"background_collector": "f" * 64, "background_selftest": "f" * 64}), \
             patch.object(maintenance, "_stable_runtime_candidate_files", return_value=candidates):
            rejected = maintenance.refresh_unsealed(maintenance.MAINTENANCE_AUTHORIZATION,
                                                     root / "refresh-rejected", refresh_expiry, lock,
                                                     dependency_receipt, dependency_receipt_sha)
        self.assertFalse(rejected["ok"])
        self.assertEqual(rejected["reason"], "refresh-repair-candidate-digest-mismatch")
        self.assertEqual(lock.read_bytes(), before_lock)
        self.assertEqual(receipt.read_bytes(), before_receipt)

    def test_unsealed_refresh_accepts_only_receipted_registered_shared_locator(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        locator = str(runtime)
        actual = maintenance.sha256(runtime)
        dependency_before = json.dumps({"schemaVersion": 1, "files": {locator: "0" * 64}},
                                       sort_keys=True).encode()
        dependency_after = json.dumps({"schemaVersion": 1, "files": {locator: actual}},
                                      sort_keys=True).encode()
        dependency.write_bytes(dependency_after)
        maintenance_receipt = root / "maintenance-receipt.json"
        expires = self.expiry()
        maintenance_receipt.write_text(json.dumps({
            "schemaVersion": 1, "status": "prepared", "sendAttempts": 0,
            "runtimeModelDecisions": 0,
            "maintenanceAuthorization": maintenance.MAINTENANCE_AUTHORIZATION,
            "runtimeAuthorization": maintenance.RUNTIME_ACCEPTANCE_AUTHORIZATION,
            "userInstructionSha256": maintenance.USER_INSTRUCTION_SHA256,
        }), encoding="utf-8")
        lock_files = {
            "shared_desktop_locator": {"path": locator, "sha256": "0" * 64},
            "messaging_dependencies": {"path": str(dependency),
                                       "sha256": maintenance.hashlib.sha256(dependency_before).hexdigest()},
            "maintenance_executor": {"path": str(runtime), "sha256": actual},
            "messaging_dependency_maintenance": {"path": str(maintenance.DEPENDENCY_MAINTENANCE),
                                                  "sha256": maintenance.sha256(maintenance.DEPENDENCY_MAINTENANCE)},
        }
        lock_value = {"schemaVersion": 1, "status": "UNSEALED_ACCEPTANCE", "files": lock_files,
                      "unsealedAcceptance": {
                          "maintenanceAuthorization": maintenance.MAINTENANCE_AUTHORIZATION,
                          "maintenanceReceiptPath": str(maintenance_receipt),
                          "maintenanceReceiptSha256": maintenance.sha256(maintenance_receipt),
                          "authorization": maintenance.RUNTIME_ACCEPTANCE_AUTHORIZATION,
                          "expiresAt": expires,
                      }}
        lock.write_text(json.dumps(lock_value), encoding="utf-8")
        dependency_receipt = root / "shared-dependency-receipt.json"
        dependency_receipt.write_text(json.dumps({
            "action": "prepare", "status": "prepared",
            "authorization": maintenance.SHARED_DEPENDENCY_MAINTENANCE_AUTHORIZATION,
            "userInstructionSha256": maintenance.SHARED_DEPENDENCY_USER_INSTRUCTION_SHA256,
            "dependencyManifestBeforeSha256": maintenance.hashlib.sha256(dependency_before).hexdigest(),
            "dependencyManifestAfterSha256": maintenance.hashlib.sha256(dependency_after).hexdigest(),
            "changes": [{"path": locator, "before": "0" * 64, "after": actual}],
            "tests": {"ok": True, "testCount": 10},
            "capabilityCheck": {"ok": True}, "sendAttempts": 0,
            "runtimeModelDecisions": 0,
        }), encoding="utf-8")
        runtime_map = {label: Path(entry["path"]) for label, entry in lock_files.items()}
        receipt_digest = maintenance.sha256(dependency_receipt)
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", runtime_map), \
             patch.object(maintenance, "DEPENDENCY_MANIFEST", dependency), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_PATH", locator), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_SHA256", actual), \
             patch.object(maintenance.executor_integrity, "verify_unsealed_acceptance",
                          return_value={"ok": True, "status": "UNSEALED_ACCEPTANCE"}):
            result = maintenance.refresh_unsealed(
                maintenance.MAINTENANCE_AUTHORIZATION, root / "refresh", expires, lock,
                dependency_receipt, receipt_digest,
                run_command=lambda *_: {"ok": True, "elapsedMs": 1, "testCount": 16})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["repairType"], "registered-shared-desktop-locator")
        refreshed = json.loads(lock.read_text())
        self.assertEqual(refreshed["status"], "UNSEALED_ACCEPTANCE")
        self.assertEqual(refreshed["files"]["shared_desktop_locator"]["sha256"], actual)
        self.assertEqual(refreshed["unsealedAcceptance"]["maintenanceReceiptPath"],
                         str(Path(result["maintenanceReceiptPath"]).resolve()))
        self.assertEqual(json.loads(Path(result["maintenanceReceiptPath"]).read_text())[
            "dependencyReceiptSha256"], receipt_digest)

    def test_unsealed_refresh_rejects_shared_locator_receipt_with_unknown_send_count(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        locator = str(runtime)
        actual = maintenance.sha256(runtime)
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {locator: actual}}), encoding="utf-8")
        dependency_receipt = root / "dependency-receipt.json"
        dependency_receipt.write_text(json.dumps({"sendAttempts": None}), encoding="utf-8")
        lock_manifest = {"files": {
            "shared_desktop_locator": {"path": locator, "sha256": "0" * 64},
            "messaging_dependencies": {"path": str(dependency), "sha256": "old-manifest-hash"},
        }}
        with patch.object(maintenance, "DEPENDENCY_MANIFEST", dependency), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_PATH", locator), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_SHA256", actual), \
             patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {"shared_desktop_locator": runtime}):
            with self.assertRaisesRegex(maintenance.MaintenanceError,
                                        "refresh-dependency-receipt-contract-mismatch"):
                maintenance._validate_dependency_maintenance_receipt(
                    dependency_receipt, maintenance.sha256(dependency_receipt), lock_manifest,
                    {"shared_desktop_locator": {"path": locator, "sha256": actual}})

    def test_business_storage_bridge_receipt_is_exactly_scoped_and_zero_send(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = Path(directory.name); scripts = root / "scripts"; scripts.mkdir()
        locator = root / "desktop.py"; locator.write_text("locator")
        bridge = scripts / "workflow_bridge.py"; bridge.write_text("bridge")
        maint = scripts / "dependency_maintenance.py"; maint.write_text("maint")
        dependency = root / "dependencies.json"
        files = {
            str(locator): maintenance.sha256(locator),
            "scripts/workflow_bridge.py": maintenance.sha256(bridge),
            "scripts/dependency_maintenance.py": maintenance.sha256(maint),
            "../../runtime/business_storage.py": "3" * 64,
        }
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": files}))
        lock_manifest = {"files": {
            "shared_desktop_locator": {"path": str(locator), "sha256": maintenance.sha256(locator)},
            "messaging_dependencies": {"path": str(dependency.resolve()), "sha256": "1" * 64},
        }}
        receipt = root / "receipt.json"
        changes = [{"path": name, "before": "0" * 64, "after": digest}
                   for name, digest in files.items() if name != str(locator)]
        receipt.write_text(json.dumps({
            "action": "prepare", "status": "prepared",
            "authorization": maintenance.BUSINESS_STORAGE_BRIDGE_AUTHORIZATION,
            "userInstructionSha256": maintenance.BUSINESS_STORAGE_BRIDGE_INSTRUCTION_SHA256,
            "dependencyManifestPath": str(dependency.resolve()),
            "dependencyManifestBeforeSha256": "2" * 64,
            "dependencyManifestAfterSha256": maintenance.sha256(dependency),
            "changes": changes, "tests": {"ok": True, "testCount": 1},
            "capabilityCheck": {"ok": True}, "sendAttempts": 0,
            "runtimeModelDecisions": 0,
        }))
        candidate = {"shared_desktop_locator": {"path": str(locator),
                     "sha256": maintenance.sha256(locator)}}
        with patch.object(maintenance, "WECHAT_ROOT", root), \
             patch.object(maintenance, "DEPENDENCY_MANIFEST", dependency), \
             patch.object(maintenance, "DEPENDENCY_MAINTENANCE", maint), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_PATH", str(locator)), \
             patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {"shared_desktop_locator": locator}):
            verified = maintenance._validate_dependency_maintenance_receipt(
                receipt, maintenance.sha256(receipt), lock_manifest, candidate)
        self.assertEqual({row["path"] for row in verified["changes"]},
                         maintenance.BUSINESS_STORAGE_BRIDGE_ALLOWED_CHANGES)

    def test_zero_send_recovery_binds_clean_receipt_to_registered_manifest_path(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = Path(directory.name); locator = root / "desktop.py"; locator.write_text("current")
        dependency = root / "dependencies.json"
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {str(locator): maintenance.sha256(locator)}}))
        lock_manifest = {"files": {
            "shared_desktop_locator": {"path": str(locator), "sha256": maintenance.sha256(locator)},
            "messaging_dependencies": {"path": str(dependency.resolve()), "sha256": "0" * 64},
        }}
        receipt = root / "dependency-receipt.json"
        receipt.write_text(json.dumps({
            "action": "prepare", "status": "prepared",
            "authorization": maintenance.ZERO_SEND_DRAFT_AUTHORIZATION,
            "userInstructionSha256": maintenance.ZERO_SEND_DRAFT_INSTRUCTION_SHA256,
            "dependencyManifestPath": str(dependency.resolve()),
            "dependencyManifestBeforeSha256": maintenance.sha256(dependency),
            "dependencyManifestAfterSha256": maintenance.sha256(dependency),
            "changes": [], "tests": {"ok": True, "testCount": 1},
            "capabilityCheck": {"ok": True}, "sendAttempts": 0,
            "runtimeModelDecisions": 0,
        }))
        candidate = {"shared_desktop_locator": {"path": str(locator), "sha256": maintenance.sha256(locator)}}
        with patch.object(maintenance, "DEPENDENCY_MANIFEST", dependency), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_PATH", str(locator)), \
             patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {"shared_desktop_locator": locator}):
            result = maintenance._validate_dependency_maintenance_receipt(
                receipt, maintenance.sha256(receipt), lock_manifest, candidate, allow_clean=True)
            self.assertEqual(result["dependencyManifestPath"], str(dependency.resolve()))
            altered = json.loads(receipt.read_text()); altered["dependencyManifestPath"] = str(root / "other.json")
            receipt.write_text(json.dumps(altered))
            with self.assertRaisesRegex(maintenance.MaintenanceError, "zero-draft-manifest-binding-mismatch"):
                maintenance._validate_dependency_maintenance_receipt(
                    receipt, maintenance.sha256(receipt), lock_manifest, candidate, allow_clean=True)

    def test_zero_send_recovery_accepts_only_registered_adapter_dependency_change(self):
        directory = tempfile.TemporaryDirectory(); self.addCleanup(directory.cleanup)
        root = Path(directory.name); (root / "scripts").mkdir()
        locator = root / "desktop.py"; locator.write_text("locator")
        adapter = root / "scripts/desktop_adapter.py"; adapter.write_text("new adapter")
        dependency = root / "dependencies.json"
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {
            str(locator): maintenance.sha256(locator),
            "scripts/desktop_adapter.py": maintenance.sha256(adapter),
        }}))
        lock_manifest = {"files": {
            "shared_desktop_locator": {"path": str(locator), "sha256": maintenance.sha256(locator)},
            "desktop_adapter": {"path": str(adapter), "sha256": "0" * 64},
            "messaging_dependencies": {"path": str(dependency.resolve()), "sha256": "1" * 64},
        }}
        receipt = root / "dependency-receipt.json"
        receipt.write_text(json.dumps({
            "action": "prepare", "status": "prepared",
            "authorization": maintenance.ZERO_SEND_DRAFT_AUTHORIZATION,
            "userInstructionSha256": maintenance.ZERO_SEND_DRAFT_INSTRUCTION_SHA256,
            "dependencyManifestPath": str(dependency.resolve()),
            "dependencyManifestBeforeSha256": "2" * 64,
            "dependencyManifestAfterSha256": maintenance.sha256(dependency),
            "changes": [{"path": "scripts/desktop_adapter.py", "before": "0" * 64,
                         "after": maintenance.sha256(adapter)}],
            "tests": {"ok": True, "testCount": 1}, "capabilityCheck": {"ok": True},
            "sendAttempts": 0, "runtimeModelDecisions": 0,
        }))
        with patch.object(maintenance, "WECHAT_ROOT", root), \
             patch.object(maintenance, "DEPENDENCY_MANIFEST", dependency), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_PATH", str(locator)), \
             patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {"shared_desktop_locator": locator}):
            verified = maintenance._validate_dependency_maintenance_receipt(
                receipt, maintenance.sha256(receipt), lock_manifest,
                {"shared_desktop_locator": {"path": str(locator), "sha256": maintenance.sha256(locator)}})
        self.assertEqual(verified["changes"][0]["path"], "scripts/desktop_adapter.py")

    def test_unsealed_refresh_accepts_receipted_maintenance_code_only_drift(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        locator = str(runtime)
        locator_hash = maintenance.sha256(runtime)
        self_key = "scripts/dependency_maintenance.py"
        dependency_script_hash = maintenance.sha256(maintenance.DEPENDENCY_MAINTENANCE)
        dependency_before = json.dumps({"schemaVersion": 1, "files": {
            locator: locator_hash, self_key: "0" * 64,
        }}, sort_keys=True).encode()
        dependency_after = json.dumps({"schemaVersion": 1, "files": {
            locator: locator_hash, self_key: dependency_script_hash,
        }}, sort_keys=True).encode()
        dependency.write_bytes(dependency_after)
        expires = self.expiry()
        merchant_receipt = root / "old-maintenance-receipt.json"
        merchant_receipt.write_text(json.dumps({
            "schemaVersion": 1, "status": "prepared", "sendAttempts": 0,
            "runtimeModelDecisions": 0,
            "maintenanceAuthorization": maintenance.MAINTENANCE_AUTHORIZATION,
            "runtimeAuthorization": maintenance.RUNTIME_ACCEPTANCE_AUTHORIZATION,
            "userInstructionSha256": maintenance.USER_INSTRUCTION_SHA256,
        }), encoding="utf-8")
        runtime_map = {
            "shared_desktop_locator": runtime,
            "messaging_dependencies": dependency,
            "maintenance_executor": runtime,
            "messaging_dependency_maintenance": maintenance.DEPENDENCY_MAINTENANCE,
        }
        lock_files = {label: {"path": str(path), "sha256": maintenance.sha256(path)}
                      for label, path in runtime_map.items()}
        lock_files["messaging_dependencies"]["sha256"] = maintenance.hashlib.sha256(dependency_before).hexdigest()
        lock_value = {"schemaVersion": 1, "status": "UNSEALED_ACCEPTANCE", "files": lock_files,
                      "unsealedAcceptance": {
                          "maintenanceAuthorization": maintenance.MAINTENANCE_AUTHORIZATION,
                          "maintenanceReceiptPath": str(merchant_receipt),
                          "maintenanceReceiptSha256": maintenance.sha256(merchant_receipt),
                          "authorization": maintenance.RUNTIME_ACCEPTANCE_AUTHORIZATION,
                          "expiresAt": expires,
                      }}
        lock.write_text(json.dumps(lock_value), encoding="utf-8")
        dependency_receipt = root / "dependency-receipt.json"
        dependency_receipt.write_text(json.dumps({
            "action": "prepare", "status": "prepared",
            "authorization": maintenance.SHARED_DEPENDENCY_MAINTENANCE_AUTHORIZATION,
            "userInstructionSha256": maintenance.SHARED_DEPENDENCY_USER_INSTRUCTION_SHA256,
            "dependencyManifestBeforeSha256": maintenance.hashlib.sha256(dependency_before).hexdigest(),
            "dependencyManifestAfterSha256": maintenance.hashlib.sha256(dependency_after).hexdigest(),
            "changes": [{"path": self_key, "before": "0" * 64, "after": dependency_script_hash}],
            "tests": {"ok": True, "testCount": 9}, "capabilityCheck": {"ok": True},
            "sendAttempts": 0, "runtimeModelDecisions": 0,
        }), encoding="utf-8")
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", runtime_map), \
             patch.object(maintenance, "DEPENDENCY_MANIFEST", dependency), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_PATH", locator), \
             patch.object(maintenance, "AUTHORIZED_SHARED_LOCATOR_SHA256", locator_hash), \
             patch.object(maintenance.executor_integrity, "verify_unsealed_acceptance",
                          return_value={"ok": True, "status": "UNSEALED_ACCEPTANCE"}):
            result = maintenance.refresh_unsealed(
                maintenance.MAINTENANCE_AUTHORIZATION, root / "refresh-code-only", expires, lock,
                dependency_receipt, maintenance.sha256(dependency_receipt),
                run_command=lambda *_: {"ok": True, "elapsedMs": 1, "testCount": 17})
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["repairType"], "authorized-maintenance-code-only")
        refreshed = json.loads(lock.read_text())
        self.assertEqual(refreshed["files"]["shared_desktop_locator"]["sha256"], locator_hash)

    def test_sealed_baseline_accepts_pending_adapter_registration(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        files = {label: {"path": str(runtime), "sha256": maintenance.sha256(runtime)} for label in (
            "desktop_adapter", "maintenance_executor", "messaging_dependency_maintenance")}
        files["desktop_adapter"]["sha256"] = "0" * 64
        manifest["files"] = files
        lock.write_text(json.dumps(manifest))
        dependency.write_text(json.dumps({"schemaVersion": 1, "files": {}}))
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {
                 "desktop_adapter": runtime,
                 "maintenance_executor": runtime,
                 "messaging_dependency_maintenance": runtime,
             }), patch.object(maintenance.executor_integrity, "_load_bound_json", return_value={}), \
             patch.object(maintenance.executor_integrity, "_validate_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_maintenance_acceptance"), \
             patch.object(maintenance.executor_integrity, "_validate_shared_text_acceptance"):
            maintenance._load_sealed_baseline(lock, dependency)

    def test_runtime_candidate_stability_rejects_a_mid_refresh_change(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        def mutate(_seconds):
            runtime.write_text("changed-during-stability-check", encoding="utf-8")
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {"runtime": runtime}), \
             patch.object(maintenance.time, "sleep", side_effect=mutate):
            with self.assertRaisesRegex(maintenance.MaintenanceError, "maintenance-runtime-candidate-unstable"):
                maintenance._stable_runtime_candidate_files()

    def test_runtime_candidate_stability_accepts_unchanged_files(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        with patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {"runtime": runtime}), \
             patch.object(maintenance.time, "sleep"):
            candidate = maintenance._stable_runtime_candidate_files()
        self.assertEqual(candidate["runtime"]["sha256"], maintenance.sha256(runtime))

    def test_prepare_can_only_write_unsealed_acceptance(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        shared_receipt = root / "shared-receipt.json"
        shared_receipt.write_text("{}", encoding="utf-8")
        def runner(command, cwd=maintenance.WORKSPACE_ROOT):
            if str(maintenance.DEPENDENCY_MAINTENANCE) in command:
                return {"ok": True, "elapsedMs": 1, "testCount": None, "json": {
                    "ok": True, "status": "prepared", "receiptPath": str(shared_receipt),
                    "receiptSha256": maintenance.sha256(shared_receipt),
                }}
            return {"ok": True, "elapsedMs": 1, "testCount": 9, "json": None}
        with patch.object(maintenance, "_load_sealed_baseline", return_value=(raw, manifest)), \
             patch.object(maintenance.executor_integrity, "RUNTIME_FILES", {"runtime": runtime}), \
             patch.object(maintenance.executor_integrity, "verify_unsealed_acceptance",
                          return_value={"ok": True, "status": "UNSEALED_ACCEPTANCE"}):
            result = maintenance.prepare(maintenance.MAINTENANCE_AUTHORIZATION, self.expiry(),
                                         root / "out", lock, dependency, runner)
        stored = json.loads(lock.read_text())
        self.assertTrue(result["ok"])
        self.assertEqual(stored["status"], "UNSEALED_ACCEPTANCE")
        self.assertNotEqual(stored["status"], "SEALED")
        self.assertEqual(stored["unsealedAcceptance"]["authorization"],
                         maintenance.RUNTIME_ACCEPTANCE_AUTHORIZATION)

    def test_merchant_test_failure_rolls_back_dependency_change(self):
        directory, root, lock, dependency, runtime, manifest, raw = self.fixture(); self.addCleanup(directory.cleanup)
        before_dependency = dependency.read_bytes()
        shared_receipt = root / "shared-receipt.json"; shared_receipt.write_text("{}")
        calls = []
        def runner(command, cwd=maintenance.WORKSPACE_ROOT):
            calls.append(1)
            if len(calls) == 1:
                dependency.write_text("changed")
                return {"ok": True, "elapsedMs": 1, "testCount": None, "json": {
                    "ok": True, "status": "prepared", "receiptPath": str(shared_receipt),
                    "receiptSha256": maintenance.sha256(shared_receipt),
                }}
            raise maintenance.MaintenanceError("merchant-tests-failed")
        with patch.object(maintenance, "_load_sealed_baseline", return_value=(raw, manifest)):
            result = maintenance.prepare(maintenance.MAINTENANCE_AUTHORIZATION, self.expiry(),
                                         root / "out", lock, dependency, runner)
        self.assertFalse(result["ok"])
        self.assertEqual(dependency.read_bytes(), before_dependency)
        self.assertEqual(lock.read_bytes(), raw)


if __name__ == "__main__":
    unittest.main()
