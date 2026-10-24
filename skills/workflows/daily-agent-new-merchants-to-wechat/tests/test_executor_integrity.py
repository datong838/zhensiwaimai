import copy
import hashlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import executor_integrity as integrity


class SharedAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads(integrity.MANIFEST_PATH.read_text(encoding="utf-8"))

    def _candidate(self, manifest):
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "executor-lock.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return directory, path

    def _mutated_receipt(self, metadata, mutation):
        source = Path(metadata["receiptPath"])
        receipt = json.loads(source.read_text(encoding="utf-8"))
        mutation(receipt)
        directory = tempfile.TemporaryDirectory()
        path = Path(directory.name) / "receipt.json"
        path.write_text(json.dumps(receipt), encoding="utf-8")
        changed = copy.deepcopy(metadata)
        changed["receiptPath"] = str(path)
        changed["receiptSha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        return directory, changed

    def test_current_shared_acceptances_pass(self):
        integrity._validate_shared_text_acceptance(self.manifest)

    def test_text_receipt_digest_is_bound(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["sharedTextAcceptance"]["receiptSha256"] = "0" * 64
        with self.assertRaisesRegex(integrity.IntegrityError, "shared-text-receipt-digest-mismatch"):
            integrity._validate_shared_text_acceptance(manifest)

    def test_text_requires_one_physical_send(self):
        directory, metadata = self._mutated_receipt(
            self.manifest["sharedTextAcceptance"],
            lambda receipt: receipt["items"][0].update(sendAttempts=0),
        )
        self.addCleanup(directory.cleanup)
        manifest = copy.deepcopy(self.manifest)
        manifest["sharedTextAcceptance"] = metadata
        with self.assertRaisesRegex(integrity.IntegrityError, "shared-text-evidence-invalid"):
            integrity._validate_shared_text_acceptance(manifest)

    def test_text_requires_exact_copy_hash(self):
        directory, metadata = self._mutated_receipt(
            self.manifest["sharedTextAcceptance"],
            lambda receipt: receipt["items"][0]["evidence"].update(copiedTextSha256="wrong"),
        )
        self.addCleanup(directory.cleanup)
        manifest = copy.deepcopy(self.manifest)
        manifest["sharedTextAcceptance"] = metadata
        with self.assertRaisesRegex(integrity.IntegrityError, "shared-text-evidence-invalid"):
            integrity._validate_shared_text_acceptance(manifest)

    def test_text_only_merchant_gate_does_not_require_media_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "executor-lock.json"
            expires = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
            manifest = {"schemaVersion": 1, "status": "UNSEALED_ACCEPTANCE", "files": {},
                        "unsealedAcceptance": {"authorization": "accepted", "expiresAt": expires},
                        "sharedMediaAcceptance": {"receiptSha256": "stale-media-version"}}
            path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch.object(integrity, "_validate_runtime_files", return_value=[]), \
                 patch.object(integrity, "_validate_code_maintenance"), \
                 patch.object(integrity, "_validate_maintenance_acceptance"), \
                 patch.object(integrity, "_validate_shared_text_acceptance"):
                result = integrity.verify_unsealed_acceptance("accepted", path)
        self.assertEqual(result["status"], "UNSEALED_ACCEPTANCE")
        self.assertEqual(result["sharedMediaAcceptance"], "not-required-by-text-only-merchant-workflow")

    def test_unsealed_code_maintenance_receipt_is_bound(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dependency = root / "dependency.json"
            dependency.write_text(json.dumps({"ok": True, "status": "prepared", "sendAttempts": 0,
                "runtimeModelDecisions": 0, "tests": {"ok": True, "testCount": 1}}))
            receipt = root / "maintenance.json"
            value = {"ok": True, "status": "prepared", "maintenanceAuthorization": "maint",
                "runtimeAuthorization": "runtime", "expiresAt": "future", "userInstructionSha256": "instruction",
                "sendAttempts": 0, "runtimeModelDecisions": 0, "merchantTests": {"ok": True, "testCount": 1},
                "candidateFiles": {}, "dependencyReceiptPath": str(dependency),
                "dependencyReceiptSha256": hashlib.sha256(dependency.read_bytes()).hexdigest()}
            receipt.write_text(json.dumps(value))
            manifest = {"unsealedAcceptance": {"maintenanceAuthorization": "maint", "authorization": "runtime",
                "expiresAt": "future", "userInstructionSha256": "instruction", "maintenanceReceiptPath": str(receipt),
                "maintenanceReceiptSha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}}
            with patch.object(integrity, "RUNTIME_FILES", {}):
                integrity._validate_code_maintenance(manifest)
                value["sendAttempts"] = 1; receipt.write_text(json.dumps(value))
                manifest["unsealedAcceptance"]["maintenanceReceiptSha256"] = hashlib.sha256(receipt.read_bytes()).hexdigest()
                with self.assertRaisesRegex(integrity.IntegrityError, "receipt-contract-mismatch"):
                    integrity._validate_code_maintenance(manifest)

    def test_fixed_hourly_entry_uses_sealed_gate_after_automatic_reseal(self):
        with patch.object(integrity, "_load_manifest", return_value=(b"{}", {"status": "SEALED"})), \
             patch.object(integrity, "verify", return_value={"ok": True, "status": "SEALED"}) as verify:
            result = integrity.verify_for_run("old-unsealed-authorization", Path("lock.json"))
        self.assertEqual(result["status"], "SEALED")
        verify.assert_called_once_with(Path("lock.json"))

    def _reseal_fixture(self, directory):
        root = Path(directory)
        manifest_path = root / "executor-lock.json"
        manifest_path.write_text(json.dumps({"schemaVersion": 1, "status": "UNSEALED_ACCEPTANCE",
            "files": {}, "unsealedAcceptance": {"authorization": "accepted"}}), encoding="utf-8")
        receipt_dir = root / "run/desktop-wechat/12345678"
        receipt_dir.mkdir(parents=True)
        digest = hashlib.sha256("城市\n联系人\n商家\n地址".encode()).hexdigest()
        receipt = {"merchantId": "12345678", "messageSha256": digest,
                   "physicalSendAttempts": 1, "runtimeModelDecisions": 0, "verified": True,
                   "postSendInputCleared": [True, True],
                   "copyReadback": {"ok": True, "composerEmpty": True, "copyMenuCount": 1,
                                    "copiedTextSha256": digest, "bubblePositions": [[1, 2], [1, 2]]}}
        (receipt_dir / "acceptance-receipt.json").write_text(json.dumps(receipt), encoding="utf-8")
        result = {"executorIntegrity": {"status": "UNSEALED_ACCEPTANCE"},
                  "finalCursor": {"verified": True, "merchantId": "12345678"},
                  "wechat": {"items": [{"merchantId": "12345678", "review": [
                      {"stage": "定位、输入与单次发送", "status": "PASS"},
                      {"stage": "成功历史与原子游标提交", "status": "PASS"}]}]}}
        return manifest_path, root / "run", result

    def test_reseal_requires_real_new_send_not_reconcile_or_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, output, result = self._reseal_fixture(directory)
            for items in ([], [{"merchantId": "12345678", "review": [
                    {"stage": "已有attempt只读复核", "status": "PASS"},
                    {"stage": "成功历史与原子游标提交", "status": "PASS"}]}]):
                candidate = copy.deepcopy(result); candidate["wechat"]["items"] = items
                with self.subTest(items=items), self.assertRaisesRegex(
                        integrity.IntegrityError, "nonempty-send-required"):
                    integrity.seal_from_nonempty_acceptance(candidate, output, manifest)

    def test_reseal_atomically_records_current_real_acceptance(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, output, result = self._reseal_fixture(directory)
            with patch.object(integrity, "RUNTIME_FILES", {}), \
                 patch.object(integrity, "verify", return_value={"ok": True, "status": "SEALED"}):
                sealed = integrity.seal_from_nonempty_acceptance(result, output, manifest)
            stored = json.loads(manifest.read_text())
        self.assertTrue(sealed["resealed"])
        self.assertEqual(stored["status"], "SEALED")
        self.assertEqual(stored["acceptance"]["merchantId"], "12345678")
        self.assertNotIn("unsealedAcceptance", stored)


if __name__ == "__main__":
    unittest.main()
