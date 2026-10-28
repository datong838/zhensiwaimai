import contextlib
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import task_workflow as W


class PrecollectionGateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.events = self.root / 'events'
        self.events.mkdir()
        self.runs = self.root / 'runs'
        for key, value in [('EVENTS', self.events), ('RUNS', self.runs)]:
            p = patch.object(W, key, value)
            p.start()
            self.addCleanup(p.stop)
        self.day = W.datetime.now(W.LOCAL_TZ).date().isoformat()

    def marker(self, kind, base_state, **override):
        name = (f'{self.day}运营-店铺经营任务完成率明细.xlsx' if kind == 'detail'
                else f'{self.day}运营-店铺经营任务完成率.png')
        value = {'state': base_state, 'event': f'{self.day}-taobao-store-task-{kind}',
                 'name': name, 'groupName': W.GROUP,
                 'sha256': hashlib.sha256(kind.encode()).hexdigest(),
                 'sendAttempts': 0 if base_state == 'blocked' else 1, **override}
        # Wrong-event fixtures must still occupy the canonical path under test.
        file = self.events / f'{self.day}-taobao-store-task-{kind}.json'
        file.write_text(json.dumps(value))
        return value, file

    def invoke_main(self, expected_exit=None, **patches):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'argv', ['task_daily.py', '--execute']))
            calls = {name: stack.enter_context(patch.object(W, name, **kwargs))
                     for name, kwargs in patches.items()}
            out = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
            if expected_exit is not None:
                with self.assertRaises(SystemExit) as error:
                    W.main()
                self.assertEqual(error.exception.code, expected_exit)
            else:
                W.main()
        return json.loads(out.getvalue()), calls

    def test_pending_event_is_read_only_before_collect_or_build(self):
        for state in ('unknown', 'attempted'):
            _, file = self.marker('stats', state)
            before = file.read_bytes()
            result, calls = self.invoke_main(1, collect={}, build_report={}, deliver={})
            self.assertEqual(result['status'], 'unknown')
            self.assertTrue(result['collectionSkipped'])
            self.assertEqual(file.read_bytes(), before)
            self.assertFalse(self.runs.exists())
            for call in calls.values():
                call.assert_not_called()

    def test_both_verified_skip_all_business_actions(self):
        self.marker('detail', 'verified')
        self.marker('stats', 'verified')
        result, calls = self.invoke_main(collect={}, build_report={}, deliver={})
        self.assertEqual(result['status'], 'already_verified')
        self.assertFalse(self.runs.exists())
        for call in calls.values():
            call.assert_not_called()

    def test_bad_binding_state_and_unproven_zero_reject_without_collect(self):
        for override in [{'groupName': 'other'}, {'event': 'old-event'}, {'sha256': 'bad'},
                         {'state': 'bad'}, {'sendAttempts': 1}, {'sendAttempts': None},
                         {'sendAttempts': False}]:
            self.marker('detail', 'blocked', **override)
            result, calls = self.invoke_main(1, collect={}, build_report={}, deliver={})
            self.assertEqual(result['status'], 'blocked')
            for call in calls.values():
                call.assert_not_called()

    def test_malformed_marker_is_not_absent(self):
        _, file = self.marker('stats', 'unknown')
        for content in ('{partial', '[]'):
            file.write_text(content)
            self.assertEqual(W.inspect_day_delivery(self.day)['status'], 'blocked')
        self.assertFalse(self.runs.exists())

    def frozen(self, suffix, image=b'stats'):
        run = self.runs / f'{self.day}-{suffix}'
        run.mkdir(parents=True)
        detail = run / f'{self.day}运营-店铺经营任务完成率明细.xlsx'
        stats = run / f'{self.day}运营-店铺经营任务完成率.png'
        detail.write_bytes(b'detail')
        stats.write_bytes(image)
        report = {'day': self.day, 'rows': 1, 'matched': 1, 'unmatched': 0,
                  'reportPath': str(detail), 'statsPath': str(stats), 'path': str(detail),
                  'name': detail.name, 'statsName': stats.name, 'stats': []}
        (run / 'summary.json').write_text(json.dumps(report))
        return run, report

    def test_partial_verified_resumes_original_pair_without_overwriting_summary(self):
        self.marker('detail', 'verified')
        run, report = self.frozen('001')
        original = (run / 'summary.json').read_bytes()
        result, calls = self.invoke_main(collect={}, build_report={'return_value': report},
                                        deliver={'return_value': {'status': 'verified', 'sendAttempts': 1}})
        self.assertEqual(result['mode'], 'resume-frozen')
        calls['collect'].assert_not_called()
        calls['build_report'].assert_called_once_with(run, self.day)
        self.assertEqual(calls['deliver'].call_args.args[1], run)
        self.assertEqual((run / 'summary.json').read_bytes(), original)
        self.assertEqual(len(list(run.glob('resume-*.json'))), 1)
        self.assertEqual(list(self.runs.iterdir()), [run])

    def test_missing_or_conflicting_frozen_pair_does_not_recollect(self):
        marker, _ = self.marker('detail', 'verified')
        result, calls = self.invoke_main(1, collect={}, build_report={}, deliver={})
        self.assertEqual(result['reason'], 'original-frozen-pair-unavailable')
        calls['collect'].assert_not_called()
        one, _ = self.frozen('001')
        two, _ = self.frozen('002', b'different-image')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            W.frozen_day_run(self.day, {'detail': marker})
        (two / f'{self.day}运营-店铺经营任务完成率.png').write_bytes(b'stats')
        self.assertEqual(W.frozen_day_run(self.day, {'detail': marker}), one)

    def test_no_original_event_keeps_normal_first_run(self):
        self.assertIsNone(W.inspect_day_delivery(self.day))

    def test_reliable_zero_still_requires_original_pair_and_wrong_order_blocks(self):
        self.marker('detail', 'blocked', sendAttempts=0)
        self.assertEqual(W.inspect_day_delivery(self.day)['status'], 'resume-frozen')
        self.marker('stats', 'verified')
        self.assertEqual(W.inspect_day_delivery(self.day)['reason'], 'original-order-evidence-conflict')


if __name__ == '__main__':
    unittest.main()
