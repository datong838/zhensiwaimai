import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import native_ui_acceptance as acceptance


class NativeUiAcceptanceScopeTests(unittest.TestCase):
    NOW = datetime(2026, 10, 26, 2, 0, tzinfo=ZoneInfo('Asia/Shanghai'))

    def request(self, workflow='native-ui-acceptance-20261026', group=acceptance.GROUP):
        return {
            'groupName': group,
            'context': {'workflowId': workflow},
            'items': [{'itemId': 'synthetic-text', 'type': 'text', 'text': '合成测试'}],
        }

    def write_manifest(self, root, request):
        scope = root / 'runtime/state/native-ui-acceptance-2026-10-26'
        scope.mkdir(parents=True)
        (scope / 'manifest.json').write_text(json.dumps({
            'request': request,
            'grant': {'groupName': acceptance.GROUP},
        }, ensure_ascii=False), encoding='utf-8')

    def test_exact_current_day_manifest_is_enabled(self):
        with tempfile.TemporaryDirectory() as td, patch.object(acceptance, 'ROOT', Path(td)):
            request = self.request()
            self.write_manifest(Path(td), request)
            self.assertTrue(acceptance.request_enabled(request, now=self.NOW))

    def test_old_day_workflow_is_rejected(self):
        with tempfile.TemporaryDirectory() as td, patch.object(acceptance, 'ROOT', Path(td)):
            request = self.request('native-ui-acceptance-20261025')
            self.write_manifest(Path(td), request)
            self.assertFalse(acceptance.request_enabled(request, now=self.NOW))

    def test_wrong_group_is_rejected(self):
        with tempfile.TemporaryDirectory() as td, patch.object(acceptance, 'ROOT', Path(td)):
            request = self.request(group='其他群')
            self.write_manifest(Path(td), request)
            self.assertFalse(acceptance.request_enabled(request, now=self.NOW))

    def test_manifest_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as td, patch.object(acceptance, 'ROOT', Path(td)):
            frozen = self.request()
            self.write_manifest(Path(td), frozen)
            changed = json.loads(json.dumps(frozen, ensure_ascii=False))
            changed['items'][0]['text'] = '已变化'
            self.assertFalse(acceptance.request_enabled(changed, now=self.NOW))


if __name__ == '__main__':
    unittest.main()
