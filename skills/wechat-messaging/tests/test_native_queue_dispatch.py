import json
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import wecom_ui_queue as queue


class NativeQueueDispatchTests(unittest.TestCase):
    def test_current_day_acceptance_route_uses_strict_validator(self):
        request = {'groupName': 'test', 'context': {'workflowId': 'native-ui-acceptance-20261026'}}
        validator = Mock(return_value=True)
        module = types.SimpleNamespace(request_enabled=validator)
        with patch.dict(sys.modules, {'native_ui_acceptance': module}):
            self.assertTrue(queue.enabled(request))
        validator.assert_called_once_with(request)

    def test_malformed_acceptance_workflow_is_not_routed_to_validator(self):
        request = {'groupName': 'test', 'context': {'workflowId': 'native-ui-acceptance-current'}}
        validator = Mock(return_value=True)
        module = types.SimpleNamespace(request_enabled=validator)
        with patch.dict(sys.modules, {'native_ui_acceptance': module}):
            self.assertFalse(queue.enabled(request))
        validator.assert_not_called()

    def test_production_owner_cannot_silently_wait_for_manual_consumer(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            with patch.object(queue,'QUEUE',root),patch.object(queue,'preflight_enabled',return_value=True), \
                 patch.object(queue,'native_dispatch_enabled',return_value=False),patch.object(queue,'dispatch_original_task') as dispatch:
                with self.assertRaisesRegex(ValueError,'native-dispatch-not-ready'):
                    queue.exchange('preflight',{'groupName':'test','context':{'deadlineAt':1}},queue=root,owner_lifetime=True)
            self.assertEqual(list(root.iterdir()),[])
            dispatch.assert_not_called()
    def test_owner_exchange_dispatches_same_frozen_task_without_poll_wait(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            def native(folder):
                task = json.loads((folder / 'task.json').read_text())
                self.assertEqual(task['lifetime'], 'owner-process')
                queue.atomic_json(folder / 'response.json', {
                    'taskId': task['taskId'], 'binding': task['binding'],
                    'result': {'ok': True, 'resolvedGroup': 'test', 'inputEmpty': True}})
            with patch.object(queue, 'QUEUE', root), patch.object(queue, 'preflight_enabled', return_value=True), \
                 patch.object(queue, 'process_identity', return_value='live'), \
                 patch.object(queue, 'native_dispatch_enabled', return_value=True), \
                 patch.object(queue, 'dispatch_original_task', side_effect=native) as dispatch, \
                 patch.object(queue.time, 'sleep', side_effect=AssertionError('no-handoff-wait')):
                result = queue.exchange('preflight', {'groupName': 'test', 'context': {'deadlineAt': 0}},
                                        queue=root, owner_lifetime=True)
            self.assertTrue(result['ok'])
            dispatch.assert_called_once()

    def test_exception_after_intent_stays_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            queue.atomic_json(folder / 'task.json', {'taskId': 'one', 'binding': 'bound',
                              'request': {'groupName': 'test'}})
            (folder / 'send-intent.json').write_text('{}')
            with patch('native_ui_post.dispatch', side_effect=RuntimeError('lost outcome')):
                queue.dispatch_original_task(folder)
            result = json.loads((folder / 'response.json').read_text())['result']
            self.assertEqual(result['status'], 'unknown')
            self.assertEqual(result['sendAttempts'], 1)

    def test_exception_before_intent_records_zero(self):
        with tempfile.TemporaryDirectory() as td:
            folder = Path(td)
            queue.atomic_json(folder / 'task.json', {'taskId': 'one', 'binding': 'bound',
                              'request': {'groupName': 'test'}})
            with patch('native_ui_post.dispatch', side_effect=RuntimeError('no control')):
                queue.dispatch_original_task(folder)
            result = json.loads((folder / 'response.json').read_text())['result']
            self.assertEqual(result['status'], 'blocked')
            self.assertEqual(result['sendAttempts'], 0)

    def test_policy_requires_native_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as td:
            policy = Path(td) / 'policy.json'
            with patch.object(queue, 'EXECUTION_POLICY', policy):
                self.assertFalse(queue.native_dispatch_enabled())
                policy.write_text(json.dumps({'nativeDispatch': True, 'transport': 'visible-ui-tree-only',
                                              'legacyInjectedSendAllowed': False}))
                self.assertTrue(queue.native_dispatch_enabled())
                policy.write_text('{')
                self.assertFalse(queue.native_dispatch_enabled())


if __name__ == '__main__':
    unittest.main()
