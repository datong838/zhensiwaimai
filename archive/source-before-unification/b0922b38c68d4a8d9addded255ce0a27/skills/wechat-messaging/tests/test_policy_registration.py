import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import policy_registration as registration
from contract import normalize, request_digest


class PolicyRegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.request = self.root / "request.json"
        self.grant = self.root / "grant.json"
        self.policy = self.root / "policy.json"
        self.policy.write_text(json.dumps({"mode": "offline", "deviceHash": "keep"}))
        self.original = registration.POLICY
        registration.POLICY = self.policy

    def tearDown(self):
        registration.POLICY = self.original
        self.tmp.cleanup()

    def write_scope(self, *, expiry=None, deadline=None):
        now = time.time()
        request = {"schemaVersion": 1, "groupName": "目标群", "items": [
            {"itemId": "one", "type": "text", "text": "正文"}],
            "context": {"workflowId": "wf", "eventId": "event", "accountAlias": "main-wechat",
                        "channel": "desktop", "deadlineAt": deadline or now + 60}}
        expiry = expiry or now + 120
        grant = {"schemaVersion": 1, "requestDigest": request_digest(normalize(request)), "accountAlias": "main-wechat",
                 "groupName": "目标群", "channel": "desktop", "expiresAt": expiry, "authorizationRef": "user-ref"}
        self.request.write_text(json.dumps(request, ensure_ascii=False))
        self.grant.write_text(json.dumps(grant, ensure_ascii=False))

    def test_prepares_exact_short_lived_scope_without_sending(self):
        self.write_scope()
        result = registration.prepare(self.request, self.grant, self.root / "out")
        policy = json.loads(self.policy.read_text())
        self.assertTrue(result["ok"])
        self.assertEqual(result["sendAttempts"], 0)
        self.assertEqual(policy["groupName"], "目标群")
        self.assertEqual(len(policy["requestDigests"]), 1)
        self.assertEqual(policy["deviceHash"], "keep")

    def test_rejects_scope_that_outlives_authorization(self):
        now = time.time()
        self.write_scope(expiry=now + 60, deadline=now + 120)
        result = registration.prepare(self.request, self.grant, self.root / "out")
        self.assertFalse(result["ok"])
        self.assertEqual(result["sendAttempts"], 0)
        self.assertEqual(json.loads(self.policy.read_text())["mode"], "offline")


if __name__ == "__main__":
    unittest.main()
