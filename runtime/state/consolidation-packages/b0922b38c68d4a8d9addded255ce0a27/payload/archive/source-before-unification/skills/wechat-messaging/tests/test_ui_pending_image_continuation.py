"""Synthetic receipts only: continue a batch without repeating a submitted image."""
import tempfile
import unittest
from pathlib import Path
from PIL import Image
from test_runtime import Fake, sample, grant
from contract import normalize
from executor import deliver


class OwnerFake(Fake):
    owner_lifetime = True


class PendingImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        raw = sample()
        raw['items'] = []
        for name in ('first', 'second'):
            path = self.root / (name + '.png')
            Image.new('RGB', (8, 8), 'red' if name == 'first' else 'blue').save(path)
            raw['items'].append({'itemId': name, 'type': 'image', 'path': str(path)})
        self.request = normalize(raw)
        self.authorization = grant(self.request)

    def tearDown(self):
        self.tmp.cleanup()

    def pending(self, **overrides):
        return dict(status='unknown', sendAttempts=1,
                    resolvedGroup=self.request['groupName'], inputEmpty=True,
                    backend='system-events-ui-tree',
                    reason='native-ui-inline-image-not-exposed') | overrides

    def run_batch(self, adapter, **kwargs):
        return deliver(self.request, self.authorization, self.root / 'ledger', adapter, **kwargs)

    def test_first_pending_does_not_stop_second_and_reentry_has_zero_ui(self):
        adapter = OwnerFake([self.pending()])
        result = self.run_batch(adapter)
        self.assertEqual(adapter.sent, ['first', 'second'])
        self.assertFalse(result['ok'])
        self.assertTrue(result['executionComplete'])
        self.assertEqual(result['verificationPending'], ['first'])
        opened = adapter.opened
        again = self.run_batch(adapter)
        self.assertEqual(adapter.sent, ['first', 'second'])
        self.assertEqual(adapter.opened, opened)
        self.assertTrue(again['executionComplete'])
        self.assertEqual(again['items'][0]['status'], 'unknown')

    def test_reentry_resumes_only_unattempted_item(self):
        old = Fake([self.pending()])
        self.run_batch(old)
        self.assertEqual(old.sent, ['first'])
        resumed = OwnerFake()
        result = self.run_batch(resumed)
        self.assertEqual(resumed.sent, ['second'])
        self.assertEqual(result['verificationPending'], ['first'])

    def test_legacy_adapter_retains_no_retry_behavior(self):
        adapter = Fake([self.pending()])
        self.run_batch(adapter)
        self.run_batch(adapter)
        self.assertEqual(adapter.sent, ['first'])

    def test_unsafe_unknown_stops_remaining(self):
        cases = [{'resolvedGroup': 'wrong'}, {'inputEmpty': False},
                 {'sendAttempts': None}, {'backend': 'other'}, {'reason': 'lost-response'}]
        for index, change in enumerate(cases):
            with self.subTest(change=change):
                self.request['context']['eventId'] = 'unsafe-' + str(index)
                self.authorization = grant(self.request)
                adapter = OwnerFake([self.pending(**change)])
                result = self.run_batch(adapter)
                self.assertEqual(adapter.sent, ['first'])
                self.assertFalse(result.get('executionComplete', False))

    def test_reconcile_never_sends(self):
        adapter = OwnerFake([self.pending(), self.pending()])
        self.run_batch(adapter)
        count = len(adapter.sent)
        self.run_batch(adapter, reconcile=True)
        self.assertEqual(len(adapter.sent), count)

    def test_payload_drift_rejected_before_ui(self):
        self.run_batch(OwnerFake([self.pending()]))
        self.request['items'][1]['sha256'] = 'f' * 64
        self.authorization = grant(self.request)
        adapter = OwnerFake()
        result = self.run_batch(adapter)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(adapter.opened, 0)
        self.assertEqual(adapter.sent, [])


if __name__ == '__main__':
    unittest.main()
