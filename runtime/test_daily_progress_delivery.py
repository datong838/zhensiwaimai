import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import daily_progress as P

DAY = '2026-10-28'
GROUP = '完整目标群'


class StructuredDeliveryTests(unittest.TestCase):
    def proof(self):
        return {'status': 'verified', 'groupName': GROUP,
                'verificationLevel': 'wecom-ui-tree-file-name-size', 'sendAttempts': 1}

    def check(self, value):
        return P._structured_delivery(value, DAY, GROUP)

    def test_unknown_field_or_success_string_never_proves_delivery(self):
        for value in [{'state': 'unknown', 'verified': False, 'verificationLevel': 'wecom-ui-tree-file-name-size'},
                      {'verificationLevel': 'windows-readback-text-anchor'},
                      {'reason': '"status":"verified" windows-readback'},
                      {'selftest': self.proof()}, {'authorization': self.proof()},
                      {'collection': self.proof()}, {'acceptance': self.proof()}]:
            self.assertFalse(self.check(value))

    def test_native_proof_requires_verified_group_and_delivery_level(self):
        self.assertTrue(self.check(self.proof()))
        for mutation in [{'groupName': 'wrong'}, {'resolvedGroup': 'wrong'}, {'status': 'unknown'},
                         {'state': 'attempted'}, {'ok': False}, {'verificationLevel': 'wecom-ui-tree-target'},
                         {'verificationLevel': 'wecom-ui-tree-image-pending'}]:
            self.assertFalse(self.check({**self.proof(), **mutation}))

    def test_nested_common_receipt_inherits_exact_group_only(self):
        child = self.proof()
        del child['groupName']
        self.assertTrue(self.check({'commonReceipt': {'groupName': GROUP, 'items': [child]}}))
        self.assertFalse(self.check({'commonReceipt': {'groupName': 'wrong', 'items': [child]}}))
        self.assertFalse(self.check({'selftest': {'commonReceipt': {'groupName': GROUP, 'items': [child]}}}))

    def test_original_canonical_verified_marker_needs_day_group_sha(self):
        marker = {'state': 'verified', 'event': DAY + '-event', 'sha256': 'a' * 64, 'groupName': GROUP}
        self.assertTrue(self.check(marker))
        for mutation in [{'event': '2026-10-27-event'}, {'sha256': 'bad'}, {'groupName': 'wrong'}, {'state': 'unknown'}]:
            self.assertFalse(self.check({**marker, **mutation}))

    def test_json_parser_handles_warnings_and_pretty_receipts_without_parsing_strings(self):
        text = 'warning: not receipt\n' + json.dumps(self.proof(), indent=2) + '\n' + json.dumps({'status': 'unknown'})
        self.assertEqual(len(list(P._json_receipts(text))), 2)
        self.assertEqual(list(P._json_receipts('arbitrary prefix ' + json.dumps(self.proof()))), [])
        obj = {'reason': json.dumps(self.proof())}
        self.assertFalse(any(self.check(x) for x in P._json_receipts(json.dumps(obj))))

    def test_business_report_explicit_double_delivery_contract(self):
        proof = {'runId': 'jinsha-business-production-20261028-01', 'ok': True, 'stage': 'verified',
                 'groupName': GROUP, 'deliveryTarget': GROUP, 'businessCompleted': True,
                 'sent': [{'platform': 'meituan'}, {'platform': 'taobao'}]}
        self.assertTrue(self.check(proof))
        for mutation in [{'stage': 'prepared'}, {'runId': 'jinsha-business-production-20261027-01'},
                         {'deliveryTarget': 'wrong'}, {'sent': [{'platform': 'meituan'}]}, {'businessCompleted': False}]:
            self.assertFalse(self.check({**proof, **mutation}))

    def test_merchant_final_cursor_contract_not_historical_selftest(self):
        proof = {'stage': 'complete', 'ok': True, 'dayDispatch': {'groupName': GROUP, 'businessDate': DAY},
                 'finalCursor': {'verified': True}, 'wechat': {'verified': True, 'sent': 1}}
        self.assertTrue(self.check(proof))
        for mutation in [{'stage': 'executor_integrity'}, {'dayDispatch': {'groupName': GROUP, 'businessDate': '2026-10-27'}},
                         {'finalCursor': None}, {'wechat': {'verified': True, 'sent': 0}}]:
            self.assertFalse(self.check({**proof, **mutation}))

    def test_actual_file_gate_respects_manifest_target_and_read_only_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            file = Path(t) / 'receipt.json'
            manifest = {'skills': [{'name': 'fixture', 'target_group': GROUP}]}
            with patch.object(P, '_load', return_value=manifest), patch.object(P, '_evidence_files', return_value=[file]):
                file.write_text(json.dumps({'state': 'unknown', 'verificationLevel': 'wecom-ui-tree-image-pending'}))
                before = file.read_bytes()
                self.assertFalse(P._has_delivery_evidence('fixture', DAY))
                self.assertEqual(file.read_bytes(), before)
                file.write_text(json.dumps(self.proof()))
                self.assertTrue(P._has_delivery_evidence('fixture', DAY))


if __name__ == '__main__':
    unittest.main()
