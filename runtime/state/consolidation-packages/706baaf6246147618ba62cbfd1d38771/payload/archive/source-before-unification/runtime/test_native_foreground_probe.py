import sys
import unittest
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/wechat-messaging/scripts'))
import wechat_foreground_probe as probe
import native_ui_tree


class NativeForegroundProbeTests(unittest.TestCase):
    def test_native_policy_never_calls_old_capture_or_activation(self):
        with patch.object(native_ui_tree,'read_anchor',side_effect=[
            ({},{'role':'AXWindow','focused':False}),({},{'value':'test'}),({},{'value':''})]), \
             patch.object(probe,'snapshot',side_effect=AssertionError('capture forbidden')):
            result=probe.probe('test',activate=True)
        self.assertEqual(result['diagnosis'],'ok')
        self.assertFalse(result['activated'])
        self.assertFalse(result['screenCapture'])

    def test_native_read_failure_does_not_fallback(self):
        with patch.object(native_ui_tree,'read_anchor',side_effect=RuntimeError('no access')), \
             patch.object(probe,'snapshot',side_effect=AssertionError('capture forbidden')):
            result=probe.probe('test')
        self.assertTrue(result['contended'])
        self.assertIn('no access',result['diagnosis'])


if __name__=='__main__':unittest.main()
