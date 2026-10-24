import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from reconcile_predispatch import reconcile


class PredispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.marker = self.root / 'event.json'
        self.source = self.root / 'receipt.json'
        self.event = self.root / '.wechat-messaging' / 'events' / ('a' * 64)
        self.event.mkdir(parents=True)
        self.payload = dict(path='/f/report.xlsx', name='report.xlsx', size=12, sha256='b' * 64)
        self.claim = dict(bridgeVersion=1, state='attempted', groupName='g', payloadType='file',
                          payloads=[self.payload], sendAttempts=None, verified=False)
        self.receipt = {**self.claim, 'state': 'blocked', 'sendAttempts': 0,
                        'attemptMarker': str(self.marker),
                        'commonReceipt': {'eventKey': 'a' * 64, 'status': 'blocked', 'items': []}}
        binding = dict(groupName='g', accountAlias='main-wechat',
                       items=[dict(itemId='0', type='file', name='report.xlsx', size=12, sha256='b' * 64)])
        self.write(self.event / 'binding.json', {'digest': hashlib.sha256(json.dumps(
            binding, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()})
        self.write(self.marker, self.claim)
        self.write(self.source, self.receipt)

    def write(self, path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))

    def run_reconcile(self, mode='interrupted-preflight', apply=False):
        return reconcile(self.marker, self.source, mode, apply=apply, root=self.root)

    def test_dry_run_is_read_only(self):
        before = self.marker.read_bytes()
        self.assertTrue(self.run_reconcile()['ok'])
        self.assertEqual(before, self.marker.read_bytes())

    def test_initial_claim_with_no_dispatch_can_be_concluded(self):
        proof = self.run_reconcile(apply=True)
        self.assertEqual(json.loads(self.marker.read_text())['sendAttempts'], 0)
        self.assertEqual(json.loads(self.marker.read_text())['state'], 'blocked')
        self.assertEqual(json.loads(Path(proof['proof']).with_name('original-marker.json').read_text()), self.claim)

    def test_any_dispatch_journal_blocks_initial_claim_recovery(self):
        self.write(self.event / 'item' / 'delivery.json', {'status': 'attempted', 'sendAttempts': None})
        with self.assertRaisesRegex(ValueError, 'dispatch-evidence'):
            self.run_reconcile(apply=True)
        self.assertEqual(json.loads(self.marker.read_text()), self.claim)

    def test_unknown_claim_is_never_reclassified(self):
        self.write(self.marker, {**self.claim, 'state': 'unknown'})
        with self.assertRaisesRegex(ValueError, 'not-initial'):
            self.run_reconcile()

    def test_stale_binding_is_refused(self):
        self.write(self.event / 'binding.json', {'digest': 'c' * 64})
        with self.assertRaisesRegex(ValueError, 'event-binding'):
            self.run_reconcile()

    def test_zero_blocked_snapshot_is_archived_not_deleted(self):
        self.write(self.marker, self.receipt)
        item = self.event / 'item'
        self.write(item / 'delivery.json', {'status': 'blocked', 'sendAttempts': 0,
                                           'transport': {'sent': False, 'sendAttempts': 0}})
        (item / 'payload').mkdir()
        (item / 'payload' / 'report.xlsx').write_bytes(b'original')
        proof = self.run_reconcile('blocked-zero-refreeze', apply=True)
        self.assertFalse(item.exists())
        self.assertEqual((Path(proof['proof']).parent / 'item' / 'payload' / 'report.xlsx').read_bytes(), b'original')

    def test_unknown_transport_never_archives_payload(self):
        self.write(self.marker, self.receipt)
        item = self.event / 'item'
        self.write(item / 'delivery.json', {'status': 'blocked', 'sendAttempts': 0,
                                           'transport': {'sent': False, 'sendAttempts': None}})
        with self.assertRaisesRegex(ValueError, 'unknown-item'):
            self.run_reconcile('blocked-zero-refreeze', apply=True)
        self.assertTrue(item.exists())

    def test_send_key_evidence_is_quarantined_and_never_refrozen(self):
        self.write(self.marker, self.receipt)
        item = self.event / 'item'
        self.write(item / 'delivery.json', {'status': 'blocked', 'sendAttempts': 0,
            'transport': {'sent': False, 'sendAttempts': 0, 'receipt': {
                'steps': [{'send_attempts': [{'try': 'enter', 'input_clean': False}]}]}}})
        with self.assertRaisesRegex(ValueError, 'send-keys-already'):
            self.run_reconcile('blocked-zero-refreeze', apply=True)
        proof = self.run_reconcile('post-send-unknown', apply=True)
        self.assertTrue(item.exists())
        self.assertEqual(json.loads(self.marker.read_text())['state'], 'unknown')
        self.assertEqual(json.loads((item / 'delivery.json').read_text())['sendAttempts'], 1)
        self.assertTrue(Path(proof['proof']).exists())


if __name__ == '__main__':
    unittest.main()
