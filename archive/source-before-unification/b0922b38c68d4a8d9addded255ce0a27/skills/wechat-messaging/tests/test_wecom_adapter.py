import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from wecom_adapter import WeComAdapter, PY, SENDER, target_preflight_verified


def result(**data):
    return subprocess.CompletedProcess([], 0, json.dumps(data), '')


class WeComRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        # Legacy-transport unit tests must not consume the live UI-only policy.
        policy_root = patch('wecom_adapter.ROOT', Path(self.tmp.name))
        policy_root.start()
        self.addCleanup(policy_root.stop)
        self.image = Path(self.tmp.name) / 'business.png'
        self.image.write_bytes(b'image fixture')
        self.adapter = WeComAdapter()
        self.request = {'groupName': '指定业务群'}
        self.inactive = dict(result='not-frontmost', axTrusted=True, pid=42,
                             windowFound=True, isActive=False)

    def file_item(self):
        import hashlib
        path=Path(self.tmp.name)/'report.xlsx'
        data=b'real-business-fixture'
        path.write_bytes(data)
        return {'type':'file','path':str(path),'name':path.name,'size':len(data),
                'sha256':hashlib.sha256(data).hexdigest()}

    def test_direct_file_call_gets_identity_before_send_and_persists_outcome(self):
        item=self.file_item()
        proof={'result':'verified','resolvedGroup':'指定业务群',
               'item':{k:item[k] for k in ('name','size','sha256')},
               'frames':[{'verified':True},{'verified':True}]}
        with patch('egress_policy.check',return_value={'allow':True}), \
             patch.object(self.adapter,'_run_sender',side_effect=[result(result='sent-tail-unconfirmed'),result(**proof)]):
            outcome=self.adapter.send_one(self.request,{'type':'file','path':item['path']},self.tmp.name,None,float('inf'))
        self.assertEqual(outcome['status'],'verified')
        saved=json.loads((Path(self.tmp.name)/'transport/delivery-receipt.json').read_text())
        self.assertEqual(saved,outcome)
        with patch.object(self.adapter,'_run_sender') as sender:
            outcome=self.adapter.send_one(self.request,item|{'sha256':'wrong'},self.tmp.name,None,float('inf'))
        self.assertEqual(outcome['sendAttempts'],0)
        sender.assert_not_called()

    def test_activation_requires_fresh_probe_before_navigation(self):
        replies = [result(**self.inactive), result(result='frontmost-ok'),
                   result(result='dry-run-ok', resolvedGroup='指定业务群')]
        with patch.object(self.adapter, '_run_sender', side_effect=replies) as sender, \
                patch('wecom_adapter.subprocess.run') as activate:
            receipt = self.adapter.preflight(self.request, self.tmp.name)
        self.assertTrue(receipt['ok'])
        activate.assert_called_once()
        self.assertEqual(sender.call_args_list[0].args[0], ['frontmost'])
        self.assertEqual(sender.call_args_list[1].args[0], ['frontmost'])
        self.assertEqual(receipt['sendAttempts'], 0)
        self.assertFalse(receipt['sessionListVerified'])
        self.assertFalse(any(c.args[0][0] == 'locate' for c in sender.call_args_list))

    def test_persistent_focus_failure_never_navigates(self):
        with patch.object(self.adapter, '_run_sender', return_value=result(**self.inactive)) as sender, \
                patch('wecom_adapter.subprocess.run') as activate, \
                patch('wecom_adapter.time.sleep'):
            receipt = self.adapter.preflight(self.request, self.tmp.name)
        self.assertFalse(receipt['ok'])
        activate.assert_called_once()
        self.assertTrue(all(c.args[0] == ['frontmost'] for c in sender.call_args_list))

    def test_missing_permission_does_not_activate(self):
        with patch.object(self.adapter, '_run_sender', return_value=result(**{**self.inactive, 'axTrusted': False})), \
                patch('wecom_adapter.subprocess.run') as activate:
            self.assertFalse(self.adapter.preflight(self.request, self.tmp.name)['ok'])
        activate.assert_not_called()

    def test_single_command_and_unknown_is_not_retried(self):
        with patch('egress_policy.check', return_value={'allow': True}), \
                patch.object(self.adapter, '_run_sender', return_value=result(result='sent-tail-unconfirmed')) as sender:
            receipt = self.adapter.send_one(self.request, {'type': 'image', 'path': str(self.image)},
                                            self.tmp.name, None, float('inf'))
        sender.assert_called_once()
        self.assertEqual(sender.call_args.args[0], ['send-image', '--image', str(self.image), '--group', '指定业务群'])
        self.assertEqual(receipt['status'], 'unknown')
        self.assertEqual(receipt['sendAttempts'], 1)

    def test_file_has_one_send_followed_only_by_strong_readback(self):
        item=self.file_item()
        proof={'result':'verified','resolvedGroup':'指定业务群',
               'item':{key:item[key] for key in ('name','size','sha256')},
               'frames':[{'verified':True},{'verified':True}]}
        with patch('egress_policy.check',return_value={'allow':True}), \
             patch.object(self.adapter,'_run_sender',side_effect=[result(result='sent-tail-unconfirmed'),result(**proof)]) as sender:
            receipt=self.adapter.send_one(self.request,item,self.tmp.name,None,float('inf'))
        self.assertEqual(receipt['status'],'verified')
        self.assertEqual(receipt['verificationLevel'],'file-name-size-ui')
        self.assertEqual([call.args[0][0] for call in sender.call_args_list],['send-file','verify-file'])
        self.assertEqual(receipt['sendAttempts'],1)
        with patch('egress_policy.check',return_value={'allow':True}), \
             patch.object(self.adapter,'_run_sender',side_effect=[result(result='sent-tail-unconfirmed'),result(**(proof|{'resolvedGroup':'别的群'}))]) as sender:
            receipt=self.adapter.send_one(self.request,item,self.tmp.name,None,float('inf'))
        self.assertEqual(receipt['status'],'unknown')
        self.assertEqual([call.args[0][0] for call in sender.call_args_list],['send-file','verify-file'])

    def test_office_choice_is_unknown_even_without_return_key(self):
        item=self.file_item()
        choice=result(result='focus-not-on-input-before-enter',steps=[{'office_choice_attempted':True}])
        with patch('egress_policy.check',return_value={'allow':True}), \
             patch.object(self.adapter,'_run_sender',side_effect=[choice,result(result='not-verified')]) as sender:
            receipt=self.adapter.send_one(self.request,item,self.tmp.name,None,float('inf'))
        self.assertEqual(receipt['status'],'unknown')
        self.assertIsNone(receipt['transport']['sent'])
        self.assertEqual(receipt['sendAttempts'],1)
        self.assertEqual([call.args[0][0] for call in sender.call_args_list],['send-file','verify-file'])

    def test_reconcile_unknown_file_only_reads_and_rejects_wrong_identity(self):
        item=self.file_item();prior={'state':'unknown','name':item['name'],'sha256':item['sha256'],
                                    'groupName':'指定业务群','sendAttempts':1}
        preflight={'ok':True,'resolvedGroup':'指定业务群','sessionListVerified':True}
        proof={'result':'verified','resolvedGroup':'指定业务群',
               'item':{k:item[k] for k in ('name','size','sha256')},
               'frames':[{'verified':True},{'verified':True}]}
        with patch.object(self.adapter,'preflight',return_value=preflight), \
             patch.object(self.adapter,'_run_sender',return_value=result(**proof)) as sender, \
             patch.object(self.adapter,'send_one') as send:
            outcome=self.adapter.reconcile(self.request,item,self.tmp.name,prior)
        self.assertEqual(outcome['status'],'verified')
        self.assertEqual(outcome['newSendAttempts'],0)
        self.assertEqual(sender.call_args.args[0][0],'verify-file')
        send.assert_not_called()
        with patch.object(self.adapter,'_run_sender') as sender:
            with self.assertRaisesRegex(Exception,'binding-mismatch'):
                self.adapter.reconcile(self.request,item,self.tmp.name,prior|{'sha256':'wrong'})
        sender.assert_not_called()

    def test_runner_prefixes_interpreter_once(self):
        with patch('wecom_adapter.subprocess.run', return_value=result(result='verified')) as run:
            self.adapter._run_sender(['send-image', '--image', '/tmp/business.png'])
        self.assertEqual(run.call_args.args[0], [PY, str(SENDER), 'send-image', '--image', '/tmp/business.png'])

    def test_exact_search_proof_works_without_list_membership(self):
        proof = dict(ok=True, resolvedGroup='指定业务群', sessionListVerified=False,
                     candidateStrategy='wecom-prefix-search', targetIdentityVerified=True,
                     groupTypeProof='wecom-search-open-title-evidence')
        self.assertTrue(target_preflight_verified(proof, '指定业务群'))
        self.assertFalse(target_preflight_verified(proof, '别的群'))
        self.assertFalse(target_preflight_verified({**proof, 'targetIdentityVerified': False}, '指定业务群'))

    def test_send_failure_after_enter_is_unknown_not_zero(self):
        failed = result(result='send-fail', steps=[{'send_attempts': [{'try': 'enter', 'input_clean': False}]}])
        with patch('egress_policy.check', return_value={'allow': True}), \
                patch.object(self.adapter, '_run_sender', return_value=failed) as sender:
            receipt = self.adapter.send_one(self.request, {'type': 'image', 'path': str(self.image)},
                                            self.tmp.name, None, float('inf'))
        sender.assert_called_once()
        self.assertEqual(receipt['status'], 'unknown')
        self.assertEqual(receipt['sendAttempts'], 1)


if __name__ == '__main__':
    unittest.main()
