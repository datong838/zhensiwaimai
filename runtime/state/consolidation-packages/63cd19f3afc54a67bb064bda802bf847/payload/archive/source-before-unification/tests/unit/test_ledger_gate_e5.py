# -*- coding: utf-8 -*-
"""ledger_gate E5 成功等价判据单测（2026-10-06，stdlib unittest，不依赖 pytest）。

正负对照（防"成功但内容错"）:
  - SUCCESS 直接过；
  - SKIPPED_IDEMPOTENT + 当日 verified marker（收据时刻）→ 算成功；
  - SKIPPED_IDEMPOTENT + 跨日 marker → 不算（默认拒绝）；
  - SKIPPED_IDEMPOTENT + marker 无收据时刻、文件 mtime 为当日 → 算成功（mtime 兜底）；
  - SKIPPED_IDEMPOTENT + marker 未 verified / 缺失 / JSON 坏 → 不算；
  - 其他 status/category → 不算。
只测判定函数，不碰真实状态文件。
"""
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "runtime"))

import ledger_gate  # noqa: E402

NOW_EPOCH = datetime.now().timestamp()
YDAY_EPOCH = (datetime.now() - timedelta(days=1)).timestamp()


class TestE5SuccessEquivalent(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = self._tmp.name
        self.today = datetime.now().strftime("%Y-%m-%d")

    def tearDown(self):
        self._tmp.cleanup()

    def _marker(self, state="verified", verified=True, readback_at=NOW_EPOCH, claimed_at=NOW_EPOCH):
        p = os.path.join(self.dir, "marker.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({
                "state": state,
                "verified": verified,
                "commonReceipt": {"items": [{"readbackAt": readback_at, "claimedAt": claimed_at}]},
            }, f)
        return p

    def _record(self, status, category, marker=None):
        fs = {"idempotent_evidence": marker} if marker is not None else {}
        return {"status": status, "category": category, "fail_signal": fs}

    # ---------- 正对照 ----------

    def test_success_passes(self):
        self.assertTrue(ledger_gate._is_success_equivalent({"status": "SUCCESS"}, self.today))

    def test_skipped_idempotent_with_today_verified_marker(self):
        m = self._marker()
        self.assertTrue(ledger_gate._is_success_equivalent(
            self._record("SKIPPED", "SKIPPED_IDEMPOTENT", m), self.today))

    def test_mtime_fallback_today(self):
        m = self._marker(readback_at=None, claimed_at=None)
        self.assertTrue(ledger_gate._is_success_equivalent(
            self._record("SKIPPED", "SKIPPED_IDEMPOTENT", m), self.today))

    # ---------- 负对照 ----------

    def test_skipped_idempotent_with_yesterday_marker_rejected(self):
        m = self._marker(readback_at=YDAY_EPOCH, claimed_at=YDAY_EPOCH)
        self.assertFalse(ledger_gate._is_success_equivalent(
            self._record("SKIPPED", "SKIPPED_IDEMPOTENT", m), self.today))

    def test_skipped_idempotent_marker_not_verified_rejected(self):
        m = self._marker(state="pending", verified=False)
        verified_flag = ledger_gate._is_success_equivalent(
            self._record("SKIPPED", "SKIPPED_IDEMPOTENT", m), self.today)
        self.assertFalse(verified_flag)

    def test_skipped_idempotent_marker_missing_rejected(self):
        self.assertFalse(ledger_gate._is_success_equivalent(
            selfrecord := self._record("SKIPPED", "SKIPPED_IDEMPOTENT", os.path.join(self.dir, "nope.json")), self.today))
        _ = selfrecord

    def test_skipped_idempotent_marker_bad_json_rejected(self):
        bad = os.path.join(self.dir, "bad.json")
        with open(bad, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertFalse(ledger_gate._is_success_equivalent(
            self._record("SKIPPED", "SKIPPED_IDEMPOTENT", bad), self.today))

    def test_skipped_idempotent_no_evidence_path_rejected(self):
        self.assertFalse(ledger_gate._is_success_equivalent(
            self._record("SKIPPED", "SKIPPED_IDEMPOTENT", None), self.today))

    def test_failed_not_success(self):
        self.assertFalse(ledger_gate._is_success_equivalent(
            {"status": "FAILED", "category": "CAT_FAILED"}, self.today))

    def test_mtime_fallback_yesterday_rejected(self):
        p = os.path.join(self.dir, "old.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"state": "verified", "verified": True, "commonReceipt": {"items": [{}]}}, f)
        old = datetime.now() - timedelta(days=1)
        os.utime(p, (old.timestamp(), old.timestamp()))
        self.assertFalse(ledger_gate._is_success_equivalent(
            self._record("SKIPPED", "SKIPPED_IDEMPOTENT", p), self.today))


if __name__ == "__main__":
    unittest.main()
