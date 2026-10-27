"""Isolated real-orchestrator next-day checks. Never connects to browser/UI."""
import contextlib
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
SKILL = 'skills/workflows/daily-meituan-income-top10-to-wechat'
spec = importlib.util.spec_from_file_location('top10_nextday_audit', ROOT/SKILL/'scripts/income_workflow.py')
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)
from registered_ui_routes import meituan_income_allowed


class FakeAdapter:
    def __init__(self, unknown=False):
        self.calls = []
        self.unknown = unknown
    def session(self, request):
        return contextlib.nullcontext()
    def preflight(self, request, folder):
        return {'ok': True, 'resolvedGroup': flow.GROUP, 'inputEmpty': True,
                'verificationLevel': 'wecom-ui-tree-target'}
    def send_one(self, request, item, *args):
        self.calls.append(item['type'])
        return {'status': 'unknown' if self.unknown and item['type'] == 'image' else 'verified', 'sendAttempts': 1}


def main():
    # This gate checks real current pins, without calling production run().
    flow.integrity()
    cases = []
    with tempfile.TemporaryDirectory(prefix='top10-nextday-audit-') as folder:
        root = Path(folder).resolve()
        state = root/SKILL/'.runtime'
        old = state/'days/2026-10-27/delivery.json'
        old.parent.mkdir(parents=True)
        old.write_text('{"state":"unknown","sendAttempts":2}')
        old_bytes = old.read_bytes()
        captures = []
        def capture(target):
            captures.append(str(target))
            target.mkdir(parents=True)
            image = target/'fixture.png'
            image.write_bytes(b'isolated-fixture')
            return {'ok': True, 'file': str(image), 'sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
                    'collectedAt': '2026-10-28T08:00:00+08:00', 'dataDate': '2026-10-27', 'browserPort': 9233}
        with patch.object(flow, 'STATE', state), patch.object(flow, 'day_now', return_value='2026-10-28'):
            adapter = FakeAdapter(unknown=True)
            result = flow.run(execute=True, collect=capture, adapter=adapter)
            assert adapter.calls == ['text', 'image'] and captures and old.read_bytes() == old_bytes
            assert result['ok'] is False and result['collection']['dataDate'] == '2026-10-27'
            cases.append('prior-day-unknown-does-not-block-new-day-source-or-event')
            current = state/'days/2026-10-28'
            assert json.loads((current/'delivery.json').read_text())['state'] == 'unknown'
            request = json.loads((current/'request.json').read_text())
            assert meituan_income_allowed(request, root=root, day='2026-10-28')
            assert not meituan_income_allowed(request, root=root, day='2026-10-29')
            cases.append('original-registered-route-binds-new-day-two-items-and-exact-group')
            before = (current/'delivery.json').read_bytes()
            replay = flow.run(execute=True, collect=capture, adapter=adapter)
            assert replay['status'] == 'unknown' and replay['sendAttempts'] == 0
            assert len(captures) == 1 and adapter.calls == ['text', 'image']
            assert before == (current/'delivery.json').read_bytes() and old.read_bytes() == old_bytes
            cases.append('current-unknown-does-not-recollect-or-repeat-caption-or-image')
            for n, change in enumerate([{'dataDate': '2026-10-26'},
                                       {'collectedAt': '2026-10-27T08:00:00+08:00'},
                                       {'collectedAt': '2026-10-29T08:00:00+08:00'}]):
                separate = root/f'rejected-{n}'
                separate.mkdir()
                try:
                    flow.frozen_item('2026-10-28', separate, lambda f: capture(f) | change)
                except ValueError as error:
                    assert 'source-date-invalid' in str(error)
                else:
                    raise AssertionError('invalid source date was accepted')
                assert not (separate/'frozen.json').exists()
            cases.append('wrong-data-day-old-collection-and-future-collection-rejected-before-freeze')
    print(json.dumps({'ok': True, 'cases': cases, 'realBrowserActions': 0, 'realSendAttempts': 0,
                      'productionStateWritten': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
