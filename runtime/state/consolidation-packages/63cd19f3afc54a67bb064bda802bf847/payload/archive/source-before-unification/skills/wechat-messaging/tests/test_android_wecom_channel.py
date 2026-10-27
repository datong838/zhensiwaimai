import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from android_wecom_channel import AndroidWeComAdapter, PACKAGE
from contract import Rejected
from executor import verify_dependencies


class AndroidWeComChannelTests(unittest.TestCase):
    def test_adapter_is_separate_from_personal_wechat(self):
        self.assertEqual(PACKAGE, "com.tencent.wework")
        self.assertEqual(AndroidWeComAdapter.channel, "mobile-wecom")
        self.assertEqual(AndroidWeComAdapter.supported, {"text", "image", "file"})

    def test_adapter_requires_a_physical_device(self):
        for serial in (None, "emulator-5554"):
            with self.assertRaisesRegex(Rejected, "physical-device-required"):
                AndroidWeComAdapter(serial)

    def test_mobile_wecom_verifies_only_its_local_runtime_chain(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            names = (
                "scripts/executor.py", "scripts/contract.py", "scripts/ledger.py",
                "scripts/dependency_maintenance.py", "scripts/android_wecom_channel.py",
                "scripts/android_wecom_acceptance.py",
            )
            manifest = {}
            for index, name in enumerate(names):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                payload = f"local-{index}".encode()
                path.write_bytes(payload)
                manifest[name] = hashlib.sha256(payload).hexdigest()
            manifest["/missing/legacy-desktop-sender.py"] = "0" * 64
            with patch("executor.ROOT", root), patch("executor.read_json", return_value={"files": manifest}):
                self.assertTrue(verify_dependencies("mobile-wecom"))
                with self.assertRaisesRegex(Rejected, "dependency-drift"):
                    verify_dependencies("desktop")

    def test_mobile_wecom_requires_complete_local_registration(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("executor.ROOT", Path(directory)), patch(
                "executor.read_json", return_value={"files": {"scripts/executor.py": "0" * 64}}
            ):
                with self.assertRaisesRegex(Rejected, "mobile-wecom-dependency-registration-incomplete"):
                    verify_dependencies("mobile-wecom")

    def test_file_card_readback_accepts_only_event_prefix_and_xlsx_suffix(self):
        adapter = AndroidWeComAdapter("usb-test-device")
        adapter.device = object()
        name = "wcom_b19db6101f_wecom_RUN1026003901_excel.xlsx"
        nodes = [
            {"text": "wcom_b19db6101f_we\ncom_RUN10260...l.xlsx"},
            {"text": "wcom_cafe123456_other.xlsx"},
        ]
        with patch("android_wecom_channel.ui.nodes", return_value=nodes):
            self.assertEqual(adapter._sent_file_cards(name), ["wcom_b19db6101f_wecom_RUN10260...l.xlsx"])


if __name__ == "__main__":
    unittest.main()
