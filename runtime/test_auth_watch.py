import unittest

import auth_watch


class AuthWatchStateTests(unittest.TestCase):
    def test_sealed_manifest_ignores_acceptance_window_history(self):
        value = {
            "status": "SEALED",
            "unsealedAcceptance": {"expiresAt": "2026-10-27T06:00:00+08:00"},
            "lastUnsealedAcceptance": {"expiresAt": "2026-10-26T06:00:00+08:00"},
        }
        self.assertEqual([], auth_watch._extract_expiries(value))

    def test_unsealed_manifest_still_monitors_current_window(self):
        value = {
            "status": "UNSEALED_ACCEPTANCE",
            "unsealedAcceptance": {"expiresAt": "2026-10-27T06:00:00+08:00"},
            "lastUnsealedAcceptance": {"expiresAt": "2026-10-26T06:00:00+08:00"},
        }
        self.assertEqual([("/unsealedAcceptance", 1793052000.0)], auth_watch._extract_expiries(value))

    def test_unrelated_active_expiry_is_not_suppressed(self):
        value = {"status": "SEALED", "lease": {"expiresAt": 1793052000}}
        self.assertEqual([("/lease", 1793052000.0)], auth_watch._extract_expiries(value))


if __name__ == "__main__":
    unittest.main()
