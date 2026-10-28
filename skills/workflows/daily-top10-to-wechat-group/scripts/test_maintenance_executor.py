import hashlib
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import maintenance_executor as maintenance


class MaintenanceExecutorTests(unittest.TestCase):
    def test_candidate_refreshes_only_shared_manifest_pin(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = root / "runtime-policy.json"
            shared = root / "dependencies.json"
            receipt = root / "shared-receipt.json"
            live = root / "runtime/state/live_steps"; live.mkdir(parents=True)
            output = root / "out"
            shared.write_text('{"schemaVersion":1,"files":{}}\n', encoding="utf-8")
            old = "0" * 64
            policy.write_text(json.dumps({"files": {"messaging_dependencies": {
                "path": str(shared), "sha256": old}}}), encoding="utf-8")
            changes = [{"path": name, "before": "0" * 64,
                        "after": ("f" * 64 if name == "scripts/dependency_maintenance.py"
                                  else digest)}
                       for name, digest in ({"scripts/dependency_maintenance.py": "f" * 64}
                                            | maintenance.EXPECTED_AFTER).items()]
            receipt.write_text(json.dumps({
                "ok": True, "action": "prepare", "status": "prepared",
                "authorization": maintenance.AUTHORIZATION,
                "userInstructionSha256": maintenance.INSTRUCTION_SHA256,
                "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
                "sendAttempts": 0, "runtimeModelDecisions": 0,
                "tests": {"ok": True, "testCount": 1}, "capabilityCheck": {"ok": True},
                "dependencyManifestPath": str(shared),
                "dependencyManifestBeforeSha256": old,
                "dependencyManifestAfterSha256": hashlib.sha256(shared.read_bytes()).hexdigest(),
                "changes": changes,
            }), encoding="utf-8")
            with patch.object(maintenance, "PROJECT", root), \
                 patch.object(maintenance, "SHARED_MANIFEST", shared), \
                 patch.object(maintenance.runtime_guard, "EXPECTED_POLICY_FILES",
                              {"messaging_dependencies": shared}):
                result = maintenance.refresh(receipt, output, policy_path=policy,
                                             validator=lambda _: True)
            self.assertTrue(result["ok"], result)
            current = json.loads(policy.read_text(encoding="utf-8"))
            self.assertEqual(current["files"]["messaging_dependencies"]["sha256"],
                             hashlib.sha256(shared.read_bytes()).hexdigest())

    def test_unreviewed_change_is_rejected(self):
        policy = {"files": {"messaging_dependencies": {"sha256": "0" * 64}}}
        receipt = {
            "ok": True, "action": "prepare", "status": "prepared",
            "authorization": maintenance.AUTHORIZATION,
            "userInstructionSha256": maintenance.INSTRUCTION_SHA256,
            "expiresAt": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "sendAttempts": 0, "runtimeModelDecisions": 0,
            "tests": {"ok": True, "testCount": 1}, "capabilityCheck": {"ok": True},
            "changes": [{"path": "unexpected", "before": "0" * 64, "after": "f" * 64}],
        }
        with self.assertRaisesRegex(maintenance.MaintenanceError, "receipt-binding|change-scope"):
            maintenance.validate_receipt(receipt, policy, datetime.now(timezone.utc))


if __name__ == "__main__":
    unittest.main()
