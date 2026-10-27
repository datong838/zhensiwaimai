import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import dependency_maintenance as maintenance


class DependencyMaintenanceTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        root = Path(directory.name) / "wechat-messaging"
        (root / "scripts").mkdir(parents=True)
        (root / "tests").mkdir()
        (root / maintenance.SELF_KEY).write_text("maintenance", encoding="utf-8")
        (root / maintenance.HEARTBEAT_RECOVERY_KEY).write_text("recovery", encoding="utf-8")
        (root / maintenance.DESKTOP_ADAPTER_KEY).write_text("adapter", encoding="utf-8")
        (root / maintenance.POLICY_REGISTRATION_KEY).write_text("policy", encoding="utf-8")
        # 2026-09-30 出站闸门（egress_policy.py）也纳入摘要覆盖：夹具必须同步补齐，
        # 否则维护器会判 dependency-file-missing（测试要跟着封印范围走）。
        (root / maintenance.EGRESS_POLICY_KEY).write_text("egress", encoding="utf-8")
        target = root / "scripts/target.py"
        target.write_text("current", encoding="utf-8")
        manifest = root / "dependencies.json"
        manifest.write_text(json.dumps({"schemaVersion": 1, "files": {
            "scripts/target.py": "0" * 64,
        }}), encoding="utf-8")
        return directory, root, manifest

    def clean_merchant_fixture(self):
        directory, root, manifest = self.fixture()
        files = {"scripts/target.py": maintenance.sha256(root / "scripts/target.py")}
        for key in (maintenance.SELF_KEY, maintenance.HEARTBEAT_RECOVERY_KEY,
                    maintenance.DESKTOP_ADAPTER_KEY, maintenance.POLICY_REGISTRATION_KEY,
                    maintenance.EGRESS_POLICY_KEY):
            files[key] = maintenance.sha256(root / key)
        manifest.write_text(json.dumps({"schemaVersion": 1, "files": files},
                                       ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return directory, root, manifest

    def expiry(self):
        return (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()

    def test_inspect_is_read_only_and_reports_drift(self):
        directory, root, manifest = self.fixture(); self.addCleanup(directory.cleanup)
        before = manifest.read_bytes()
        result = maintenance.inspect(manifest, root)
        self.assertEqual(result["status"], "drift")
        self.assertEqual(manifest.read_bytes(), before)
        self.assertEqual({x["path"] for x in result["changes"]}, {
            "scripts/target.py", maintenance.SELF_KEY, maintenance.HEARTBEAT_RECOVERY_KEY, maintenance.DESKTOP_ADAPTER_KEY, maintenance.POLICY_REGISTRATION_KEY, maintenance.EGRESS_POLICY_KEY,
        })

    def test_code_consolidation_migrates_registered_key_and_rejects_collision(self):
        directory, root, manifest = self.clean_merchant_fixture(); self.addCleanup(directory.cleanup)
        old = root / "outside-old.py"; new = root / "inside-new.py"
        old.write_text("same", encoding="utf-8"); new.write_text("same", encoding="utf-8")
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["files"][str(old)] = maintenance.sha256(old)
        manifest.write_text(json.dumps(value), encoding="utf-8")
        with patch.object(maintenance, "CODE_CONSOLIDATION_KEY_MIGRATIONS",
                          {str(old): str(new)}):
            _, current = maintenance._read_manifest(manifest)
            candidate, changes = maintenance._candidate(current, root)
            self.assertNotIn(str(old), candidate["files"])
            self.assertEqual(candidate["files"][str(new)], maintenance.sha256(new))
            self.assertEqual(changes, [])
            current["files"][str(new)] = "f" * 64
            with self.assertRaisesRegex(maintenance.MaintenanceError,
                                        "code-consolidation-key-collision"):
                maintenance._candidate(current, root)

    def test_wrong_authorization_never_writes_manifest(self):
        directory, root, manifest = self.fixture(); self.addCleanup(directory.cleanup)
        before = manifest.read_bytes()
        result = maintenance.prepare("wrong", self.expiry(), root / "out", manifest, root,
                                     run_command=lambda *_: self.fail("tests must not run"))
        self.assertFalse(result["ok"])
        self.assertEqual(manifest.read_bytes(), before)

    def test_image_card_profile_binds_exact_native_file(self):
        profile=maintenance.MAINTENANCE_AUTHORIZATIONS[maintenance.NATIVE_IMAGE_CARD_AUTHORIZATION]
        self.assertEqual(profile['allowedChangePaths'],{maintenance.SELF_KEY,'scripts/native_ui_post.py'})
        self.assertEqual(profile['allowedAfterSha256']['scripts/native_ui_post.py'],
                         maintenance.sha256(maintenance.ROOT/'scripts/native_ui_post.py'))

    def test_image_card_prepare_accepts_only_reviewed_bytes_and_scope(self):
        for mode in ('reviewed','new-registration','unreviewed','extra-drift'):
            with self.subTest(mode=mode):
                directory,root,manifest=self.clean_merchant_fixture();self.addCleanup(directory.cleanup)
                native=root/'scripts/native_ui_post.py'
                native.write_bytes((maintenance.ROOT/'scripts/native_ui_post.py').read_bytes()
                                   if mode!='unreviewed' else b'unreviewed')
                current=json.loads(manifest.read_text())
                if mode!='new-registration':current['files']['scripts/native_ui_post.py']='0'*64
                manifest.write_text(json.dumps(current));before=manifest.read_bytes()
                if mode=='extra-drift':(root/'scripts/target.py').write_text('outside-authorized-scope')
                result=maintenance.prepare(maintenance.NATIVE_IMAGE_CARD_AUTHORIZATION,self.expiry(),
                    root/'out',manifest,root,run_command=lambda *_:{'ok':True,'testCount':1})
                self.assertEqual(result['ok'],mode in ('reviewed','new-registration'))
                self.assertEqual(result['sendAttempts'],0)
                if mode not in ('reviewed','new-registration'):self.assertEqual(manifest.read_bytes(),before)
                else:self.assertEqual(json.loads(manifest.read_text())['files']['scripts/native_ui_post.py'],maintenance.sha256(native))

    def test_success_updates_only_registered_files_and_self(self):
        directory, root, manifest = self.fixture(); self.addCleanup(directory.cleanup)
        calls = []
        def runner(*_):
            calls.append(1)
            return {"ok": True, "elapsedMs": 1, "testCount": 7}
        result = maintenance.prepare(maintenance.MAINTENANCE_AUTHORIZATION, self.expiry(),
                                     root / "out", manifest, root, runner)
        stored = json.loads(manifest.read_text())
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(maintenance.inspect(manifest, root)["status"], "clean")
        self.assertIn(maintenance.SELF_KEY, stored["files"])
        self.assertIn(maintenance.HEARTBEAT_RECOVERY_KEY, stored["files"])
        self.assertIn(maintenance.DESKTOP_ADAPTER_KEY, stored["files"])
        self.assertIn(maintenance.POLICY_REGISTRATION_KEY, stored["files"])
        self.assertIn(maintenance.EGRESS_POLICY_KEY, stored["files"])

    def test_merchant_authorization_only_prepares_clean_manifest(self):
        directory, root, manifest = self.clean_merchant_fixture(); self.addCleanup(directory.cleanup)
        before = manifest.read_bytes()
        calls = []
        def runner(*_):
            calls.append(1)
            return {"ok": True, "elapsedMs": 1, "testCount": 7}
        result = maintenance.prepare(maintenance.MERCHANT_MAINTENANCE_AUTHORIZATION,
                                     self.expiry(), root / "out", manifest, root, runner)
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["changes"], [])
        self.assertEqual(result["userInstructionSha256"],
                         maintenance.MERCHANT_MAINTENANCE_INSTRUCTION_SHA256)
        self.assertEqual(manifest.read_bytes(), before)

    def test_merchant_authorization_rejects_nonself_manifest_drift(self):
        directory, root, manifest = self.clean_merchant_fixture(); self.addCleanup(directory.cleanup)
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["files"]["scripts/target.py"] = "0" * 64
        manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        before = manifest.read_bytes()
        result = maintenance.prepare(maintenance.MERCHANT_MAINTENANCE_AUTHORIZATION,
                                     self.expiry(), root / "out", manifest, root,
                                     run_command=lambda *_: self.fail("out-of-scope changes must not run"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "maintenance-scope-disallows-dependency-changes")
        self.assertEqual(manifest.read_bytes(), before)

    def test_merchant_authorization_may_update_only_its_own_digest(self):
        directory, root, manifest = self.clean_merchant_fixture(); self.addCleanup(directory.cleanup)
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["files"][maintenance.SELF_KEY] = "0" * 64
        manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        calls = []
        def runner(*_):
            calls.append(1)
            return {"ok": True, "elapsedMs": 1, "testCount": 7}
        result = maintenance.prepare(maintenance.MERCHANT_MAINTENANCE_AUTHORIZATION,
                                     self.expiry(), root / "out", manifest, root, runner)
        stored = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 2)
        self.assertEqual([change["path"] for change in result["changes"]], [maintenance.SELF_KEY])
        self.assertEqual(stored["files"][maintenance.SELF_KEY],
                         maintenance.sha256(root / maintenance.SELF_KEY))

    def test_merchant_authorization_may_update_exact_registered_shared_locator(self):
        directory, root, manifest = self.clean_merchant_fixture(); self.addCleanup(directory.cleanup)
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["files"]["scripts/target.py"] = "0" * 64
        manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        actual = maintenance.sha256(root / "scripts/target.py")
        calls = []

        def runner(*_):
            calls.append(1)
            return {"ok": True, "elapsedMs": 1, "testCount": 7}

        with patch.object(maintenance, "MERCHANT_SHARED_LOCATOR_PATH", "scripts/target.py"), \
             patch.object(maintenance, "MERCHANT_SHARED_LOCATOR_SHA256", actual), \
             patch.dict(maintenance.MAINTENANCE_AUTHORIZATIONS, {
                 maintenance.MERCHANT_MAINTENANCE_AUTHORIZATION: {
                     "instructionSha256": maintenance.MERCHANT_MAINTENANCE_INSTRUCTION_SHA256,
                     "allowedChangePaths": {maintenance.SELF_KEY, "scripts/target.py"},
                 }
             }):
            result = maintenance.prepare(maintenance.MERCHANT_MAINTENANCE_AUTHORIZATION,
                                         self.expiry(), root / "out", manifest, root, runner)
        self.assertTrue(result["ok"])
        self.assertEqual([item["path"] for item in result["changes"]], ["scripts/target.py"])
        self.assertEqual(json.loads(manifest.read_text())["files"]["scripts/target.py"], actual)

    def test_merchant_authorization_rejects_different_shared_locator_bytes(self):
        directory, root, manifest = self.clean_merchant_fixture(); self.addCleanup(directory.cleanup)
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["files"]["scripts/target.py"] = "0" * 64
        manifest.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        before = manifest.read_bytes()
        with patch.object(maintenance, "MERCHANT_SHARED_LOCATOR_PATH", "scripts/target.py"), \
             patch.object(maintenance, "MERCHANT_SHARED_LOCATOR_SHA256", "f" * 64), \
             patch.dict(maintenance.MAINTENANCE_AUTHORIZATIONS, {
                 maintenance.MERCHANT_MAINTENANCE_AUTHORIZATION: {
                     "instructionSha256": maintenance.MERCHANT_MAINTENANCE_INSTRUCTION_SHA256,
                     "allowedChangePaths": {maintenance.SELF_KEY, "scripts/target.py"},
                 }
             }):
            result = maintenance.prepare(maintenance.MERCHANT_MAINTENANCE_AUTHORIZATION,
                                         self.expiry(), root / "out", manifest, root,
                                         run_command=lambda *_: self.fail("unreviewed bytes must not run tests"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "merchant-shared-locator-digest-not-authorized")
        self.assertEqual(manifest.read_bytes(), before)

    def test_new_stores_authorization_updates_only_reviewed_bytes(self):
        directory, root, manifest = self.clean_merchant_fixture(); self.addCleanup(directory.cleanup)
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["files"]["scripts/target.py"] = "0" * 64
        value["files"][maintenance.SELF_KEY] = "0" * 64
        manifest.write_text(json.dumps(value), encoding="utf-8")
        digest = maintenance.sha256(root / "scripts/target.py")
        profile = {"instructionSha256": maintenance.NEW_STORES_INSTRUCTION_SHA256,
                   "allowedChangePaths": {maintenance.SELF_KEY, "scripts/target.py"},
                   "allowedAfterSha256": {"scripts/target.py": digest}}
        with patch.dict(maintenance.MAINTENANCE_AUTHORIZATIONS,
                        {maintenance.NEW_STORES_AUTHORIZATION: profile}):
            result = maintenance.prepare(maintenance.NEW_STORES_AUTHORIZATION, self.expiry(),
                                         root / "out", manifest, root,
                                         run_command=lambda *_: {"ok": True, "testCount": 1})
        self.assertTrue(result["ok"])
        self.assertEqual(maintenance.inspect(manifest, root)["status"], "clean")
        self.assertEqual(result["userInstructionSha256"], maintenance.NEW_STORES_INSTRUCTION_SHA256)

    def test_new_stores_authorization_rejects_unreviewed_bytes_without_writing(self):
        directory, root, manifest = self.clean_merchant_fixture(); self.addCleanup(directory.cleanup)
        value = json.loads(manifest.read_text(encoding="utf-8"))
        value["files"]["scripts/target.py"] = "0" * 64
        manifest.write_text(json.dumps(value), encoding="utf-8")
        before = manifest.read_bytes()
        profile = {"instructionSha256": maintenance.NEW_STORES_INSTRUCTION_SHA256,
                   "allowedChangePaths": {maintenance.SELF_KEY, "scripts/target.py"},
                   "allowedAfterSha256": {"scripts/target.py": "f" * 64}}
        with patch.dict(maintenance.MAINTENANCE_AUTHORIZATIONS,
                        {maintenance.NEW_STORES_AUTHORIZATION: profile}):
            result = maintenance.prepare(maintenance.NEW_STORES_AUTHORIZATION, self.expiry(),
                                         root / "out", manifest, root,
                                         run_command=lambda *_: self.fail("unreviewed bytes must not run tests"))
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "new-stores-unreviewed-dependency-bytes")
        self.assertEqual(manifest.read_bytes(), before)

    def test_postwrite_failure_restores_original_manifest(self):
        directory, root, manifest = self.fixture(); self.addCleanup(directory.cleanup)
        before = manifest.read_bytes(); calls = []
        def runner(*_):
            calls.append(1)
            if len(calls) == 2:
                raise maintenance.MaintenanceError("capabilities-failed")
            return {"ok": True, "elapsedMs": 1, "testCount": 7}
        result = maintenance.prepare(maintenance.MAINTENANCE_AUTHORIZATION, self.expiry(),
                                     root / "out", manifest, root, runner)
        self.assertFalse(result["ok"])
        self.assertEqual(result.get("rollback"), "restored")
        self.assertEqual(manifest.read_bytes(), before)

    def test_business_storage_bridge_authorization_binds_reviewed_source_bytes(self):
        profile=maintenance.MAINTENANCE_AUTHORIZATIONS[maintenance.BUSINESS_STORAGE_BRIDGE_AUTHORIZATION]
        self.assertEqual(profile['instructionSha256'],
                         maintenance.BUSINESS_STORAGE_BRIDGE_INSTRUCTION_SHA256)
        for name,digest in maintenance.BUSINESS_STORAGE_BRIDGE_ALLOWED_AFTER.items():
            self.assertEqual(maintenance.sha256(maintenance._resolve(name)),digest)
            self.assertIn(name,profile['allowedChangePaths'])
        manifest={'schemaVersion':1,'files':{}}
        candidate,_=maintenance._candidate(manifest,include_business_storage=True)
        self.assertIn(maintenance.BUSINESS_STORAGE_KEY,candidate['files'])


if __name__ == "__main__":
    unittest.main()
