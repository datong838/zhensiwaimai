import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import ApplicationServices as AX_RUNTIME

SHARED = Path("/Users/ddt/work/projects/ai_agent/skills/skills/app-controler/wechat-desktop-control/scripts")
sys.path.insert(0, str(SHARED))
import desktop_sender


class TextWriteReadbackTests(unittest.TestCase):
    """AX write/readback contract (the AppleScript channel was removed 2026-09-29).

    The intent is unchanged from the osascript era: a transport that reports an
    error is only accepted when an independent, exact native readback proves the
    composer holds the target text; otherwise the failure and its diagnostics
    are retained.
    """

    @staticmethod
    def _ax_attributes():
        def fake_attribute(ax, element, attribute, default=None):
            if attribute == AX_RUNTIME.kAXFocusedUIElementAttribute:
                return object()
            if attribute == AX_RUNTIME.kAXRoleAttribute:
                return "AXTextArea"
            return default
        return fake_attribute

    def _patches(self, write_error, readback):
        fake_readback = (patch.object(desktop_sender, "focused_text_value", side_effect=readback)
                         if isinstance(readback, BaseException)
                         else patch.object(desktop_sender, "focused_text_value", return_value=readback))
        return (
            patch.object(desktop_sender.wd, "wechat_ax_application", return_value=object()),
            patch.object(desktop_sender.wd, "ax_attribute", side_effect=self._ax_attributes()),
            patch.object(desktop_sender, "_ax_set", return_value=write_error),
            fake_readback,
        )

    def test_write_error_is_accepted_only_after_exact_native_readback(self):
        patches = self._patches(AX_RUNTIME.kAXErrorIllegalArgument, "target text")
        with patches[0], patches[1], patches[2], patches[3]:
            self.assertIsNone(desktop_sender.set_focused_text("target text"))

    def test_write_error_readback_mismatch_retains_failure_and_diagnostics(self):
        patches = self._patches(AX_RUNTIME.kAXErrorIllegalArgument, "partial")
        with patches[0], patches[1], patches[2], patches[3]:
            with self.assertRaisesRegex(desktop_sender.StopRun, "desktop-text-input-write-failed") as caught:
                desktop_sender.set_focused_text("target text")
        self.assertEqual(caught.exception.diagnostics, {"axError": AX_RUNTIME.kAXErrorIllegalArgument})

    def test_successful_write_needs_no_readback(self):
        patches = self._patches(AX_RUNTIME.kAXErrorSuccess, "whatever")
        patches[3].stop()
        with patches[0], patches[1], patches[2]:
            self.assertIsNone(desktop_sender.set_focused_text("target text"))

    def test_missing_text_area_is_rejected_without_writing(self):
        def no_text_area(ax, element, attribute, default=None):
            if attribute == AX_RUNTIME.kAXFocusedUIElementAttribute:
                return object()
            if attribute == AX_RUNTIME.kAXRoleAttribute:
                return "AXButton"
            return default
        with patch.object(desktop_sender.wd, "wechat_ax_application", return_value=object()), \
             patch.object(desktop_sender.wd, "ax_attribute", side_effect=no_text_area), \
             patch.object(desktop_sender, "_ax_set") as ax_set:
            with self.assertRaisesRegex(desktop_sender.StopRun, "desktop-text-input-write-failed") as caught:
                desktop_sender.set_focused_text("target text")
            ax_set.assert_not_called()
        self.assertEqual(caught.exception.diagnostics, {"reason": "focused-element-not-text-area"})


if __name__ == "__main__":
    unittest.main()
