#!/usr/bin/env python3
import unittest
import importlib.util
import sys
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import desktop_preflight as preflight
import wechat_desktop as wd


class SharedDesktopPreflightTests(unittest.TestCase):
    def test_activation_is_ax_bounded_before_cross_space_fallback(self):
        import types
        process = SimpleNamespace(processIdentifier=lambda: 1,
                                  activateWithOptions_=mock.Mock())
        appkit = types.SimpleNamespace(
            NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(runningApplications=lambda: [process])),
            NSApplicationActivateAllWindows=2,
            NSApplicationActivateIgnoringOtherApps=1,
        )
        ax = types.SimpleNamespace(kAXErrorSuccess=0, kAXRaiseAction="AXRaise")
        with mock.patch.dict(sys.modules, {"AppKit": appkit, "ApplicationServices": ax}), \
             mock.patch.object(wd, "ensure_window_size"), \
             mock.patch.object(wd, "unique_wechat_application", return_value=process), \
             mock.patch.object(wd, "wechat_ax_application", return_value="app"), \
             mock.patch.object(wd, "set_ax_messaging_timeout") as bounded, \
             mock.patch.object(wd, "ax_windows", return_value=[]), \
             mock.patch.object(wd, "ax_main_window",
                               side_effect=RuntimeError("wechat-main-window-count-not-one")):
            with self.assertRaisesRegex(RuntimeError, "wechat-main-window-count-not-one"):
                wd.activate_wechat()
        bounded.assert_called_once()
        process.activateWithOptions_.assert_called_once()
        source = Path(wd.__file__).read_text(encoding="utf-8")
        activate = source.split("def activate_wechat() -> None:", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn("System Events", activate)

    def test_activation_requires_successful_raise_of_verified_main_window(self):
        import types
        process = SimpleNamespace(processIdentifier=lambda: 1,
                                  activateWithOptions_=mock.Mock())
        appkit = types.SimpleNamespace(
            NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(runningApplications=lambda: [process])),
            NSApplicationActivateIgnoringOtherApps=1,
            NSApplicationActivateAllWindows=2,
        )
        ax = SimpleNamespace(kAXErrorSuccess=0, kAXRaiseAction="AXRaise",
                             AXUIElementSetAttributeValue=mock.Mock(return_value=0),
                             AXUIElementPerformAction=mock.Mock(return_value=0))
        main = object()
        with mock.patch.dict(sys.modules, {"AppKit": appkit, "ApplicationServices": ax}), \
             mock.patch.object(wd, "ensure_window_size"), \
             mock.patch.object(wd, "unique_wechat_application", return_value=process), \
             mock.patch.object(wd, "wechat_ax_application", return_value="app"), \
             mock.patch.object(wd, "set_ax_messaging_timeout"), \
             mock.patch.object(wd, "ax_windows", return_value=[main]), \
             mock.patch.object(wd, "ax_main_window", return_value=(main, (1000, 700))), \
             mock.patch.object(wd, "wechat_window_unobstructed", return_value=True), \
             mock.patch.object(wd, "wechat_frontmost", return_value=True), \
             mock.patch.object(wd, "wechat_menu_bar_frontmost", return_value=True), \
             mock.patch.object(wd.time, "sleep"):
            wd.activate_wechat()
        ax.AXUIElementPerformAction.assert_called_once_with(main, "AXRaise")
        process.activateWithOptions_.assert_called_once_with(3)

    def test_activation_waits_for_obstruction_to_clear_without_synthetic_clicks(self):
        import types
        process = SimpleNamespace(processIdentifier=lambda: 1,
                                  activateWithOptions_=mock.Mock())
        appkit = types.SimpleNamespace(
            NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(runningApplications=lambda: [process])),
            NSApplicationActivateIgnoringOtherApps=1,
            NSApplicationActivateAllWindows=2,
        )
        ax = SimpleNamespace(kAXErrorSuccess=0, kAXRaiseAction="AXRaise",
                             AXUIElementSetAttributeValue=mock.Mock(return_value=0),
                             AXUIElementPerformAction=mock.Mock(return_value=0))
        main = object()
        with mock.patch.dict(sys.modules, {"AppKit": appkit, "ApplicationServices": ax}), \
             mock.patch.object(wd, "ensure_window_size"), \
             mock.patch.object(wd, "unique_wechat_application", return_value=process), \
             mock.patch.object(wd, "wechat_ax_application", return_value="app"), \
             mock.patch.object(wd, "set_ax_messaging_timeout"), \
             mock.patch.object(wd, "ax_windows", return_value=[main]), \
             mock.patch.object(wd, "ax_main_window", return_value=(main, (1000, 700))), \
             mock.patch.object(wd, "wechat_window_unobstructed", side_effect=[False, False, True]), \
             mock.patch.object(wd, "wechat_frontmost", return_value=True), \
             mock.patch.object(wd, "wechat_menu_bar_frontmost", return_value=True), \
             mock.patch.object(wd, "run_preflight_control", return_value=SimpleNamespace(returncode=0)) as switch, \
             mock.patch.object(wd, "click") as click, \
             mock.patch.object(wd.time, "sleep"):
            wd.activate_wechat()
        click.assert_not_called()
        self.assertEqual(process.activateWithOptions_.call_count, 3)
        self.assertEqual(ax.AXUIElementPerformAction.call_count, 3)
        switch.assert_called_once()

    def test_activation_fails_closed_when_main_window_stays_obstructed(self):
        import types
        process = SimpleNamespace(processIdentifier=lambda: 1,
                                  activateWithOptions_=mock.Mock())
        appkit = types.SimpleNamespace(
            NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(runningApplications=lambda: [process])),
            NSApplicationActivateIgnoringOtherApps=1,
            NSApplicationActivateAllWindows=2,
        )
        ax = SimpleNamespace(kAXErrorSuccess=0, kAXRaiseAction="AXRaise",
                             AXUIElementSetAttributeValue=mock.Mock(return_value=0),
                             AXUIElementPerformAction=mock.Mock(return_value=0))
        main = object()
        with mock.patch.dict(sys.modules, {"AppKit": appkit, "ApplicationServices": ax}), \
             mock.patch.object(wd, "ensure_window_size"), \
             mock.patch.object(wd, "unique_wechat_application", return_value=process), \
             mock.patch.object(wd, "wechat_ax_application", return_value="app"), \
             mock.patch.object(wd, "set_ax_messaging_timeout"), \
             mock.patch.object(wd, "ax_windows", return_value=[main]), \
             mock.patch.object(wd, "ax_main_window", return_value=(main, (1000, 700))), \
             mock.patch.object(wd, "wechat_window_unobstructed", return_value=False), \
             mock.patch.object(wd, "wechat_frontmost", return_value=True), \
             mock.patch.object(wd, "run_preflight_control", return_value=SimpleNamespace(returncode=0)) as switch, \
             mock.patch.object(wd, "click"), \
             mock.patch.object(wd.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "wechat-window-obstructed"):
                wd.activate_wechat()
        self.assertEqual(process.activateWithOptions_.call_count, 9)
        self.assertEqual(ax.AXUIElementPerformAction.call_count, 9)
        switch.assert_called_once()

    def test_activation_fails_closed_if_cross_space_switch_fails(self):
        process = SimpleNamespace(processIdentifier=lambda: 1, activateWithOptions_=mock.Mock())
        appkit = SimpleNamespace(
            NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(runningApplications=lambda: [process])),
            NSApplicationActivateIgnoringOtherApps=1, NSApplicationActivateAllWindows=2)
        ax = SimpleNamespace(kAXErrorSuccess=0, kAXRaiseAction="AXRaise",
                             AXUIElementSetAttributeValue=mock.Mock(return_value=0),
                             AXUIElementPerformAction=mock.Mock(return_value=0))
        main = object()
        with mock.patch.dict(sys.modules, {"AppKit": appkit, "ApplicationServices": ax}), \
             mock.patch.object(wd, "ensure_window_size"), \
             mock.patch.object(wd, "unique_wechat_application", return_value=process), \
             mock.patch.object(wd, "wechat_ax_application", return_value="app"), \
             mock.patch.object(wd, "set_ax_messaging_timeout"), \
             mock.patch.object(wd, "ax_windows", return_value=[main]), \
             mock.patch.object(wd, "ax_main_window", return_value=(main, (1000, 700))), \
             mock.patch.object(wd, "wechat_window_unobstructed", return_value=False), \
             mock.patch.object(wd, "run_preflight_control", return_value=SimpleNamespace(returncode=1)), \
             mock.patch.object(wd.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "wechat-application-activation-failed"):
                wd.activate_wechat()

    def test_activation_wait_does_not_enter_keyboard_or_mouse_controls(self):
        source = Path(wd.__file__).read_text(encoding="utf-8")
        activate = source.split("def activate_wechat() -> None:", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("NSApplicationActivateAllWindows", activate)
        self.assertIn("wechat_window_unobstructed()", activate)
        self.assertNotIn("click(", activate)
        self.assertNotIn("post_key(", activate)

    def test_activation_fails_closed_when_main_window_raise_fails(self):
        import types
        process = SimpleNamespace(processIdentifier=lambda: 1,
                                  activateWithOptions_=mock.Mock())
        appkit = types.SimpleNamespace(
            NSWorkspace=SimpleNamespace(sharedWorkspace=lambda: SimpleNamespace(runningApplications=lambda: [process])),
            NSApplicationActivateIgnoringOtherApps=1,
            NSApplicationActivateAllWindows=2,
        )
        ax = SimpleNamespace(kAXErrorSuccess=0, kAXRaiseAction="AXRaise",
                             AXUIElementSetAttributeValue=mock.Mock(return_value=0),
                             AXUIElementPerformAction=mock.Mock(return_value=1))
        main = object()
        with mock.patch.dict(sys.modules, {"AppKit": appkit, "ApplicationServices": ax}), \
             mock.patch.object(wd, "ensure_window_size"), \
             mock.patch.object(wd, "unique_wechat_application", return_value=process), \
             mock.patch.object(wd, "wechat_ax_application", return_value="app"), \
             mock.patch.object(wd, "set_ax_messaging_timeout"), \
             mock.patch.object(wd, "ax_windows", return_value=[main]), \
             mock.patch.object(wd, "ax_main_window", return_value=(main, (1000, 700))), \
             mock.patch.object(wd.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "wechat-main-window-raise-failed"):
                wd.activate_wechat()
        ax.AXUIElementPerformAction.assert_called_once_with(main, "AXRaise")

    def test_ax_read_subprocess_timeout_is_bounded_and_stage_specific(self):
        with mock.patch.object(wd, "run_preflight_control",
                               side_effect=RuntimeError("wechat-ax-read-timeout")) as run:
            with self.assertRaisesRegex(RuntimeError, "wechat-ax-read-timeout"):
                wd.wechat_ax_state()
        self.assertEqual(run.call_args.kwargs["timeout_code"], "wechat-ax-read-timeout")
        self.assertIn("AXUIElementSetMessagingTimeout(element,5.0)", run.call_args.args[0][2])

    def test_ax_message_timeout_configuration_is_checked(self):
        ax = SimpleNamespace(kAXErrorSuccess=0,
                             AXUIElementSetMessagingTimeout=mock.Mock(return_value=0))
        wd.set_ax_messaging_timeout(ax, "app-element", 5.0)
        ax.AXUIElementSetMessagingTimeout.assert_called_once_with("app-element", 5.0)
        ax.AXUIElementSetMessagingTimeout.return_value = 1
        with self.assertRaisesRegex(RuntimeError, "wechat-ax-timeout-configuration-failed"):
            wd.set_ax_messaging_timeout(ax, "window-element", 5.0)

    def test_preflight_helper_kills_timed_out_child_with_specific_reason(self):
        with mock.patch.object(wd.subprocess, "run",
                               side_effect=subprocess.TimeoutExpired(["osascript"], 20)) as run:
            with self.assertRaisesRegex(RuntimeError, "wechat-ax-read-timeout"):
                wd.run_preflight_control(["osascript"], timeout_code="wechat-ax-read-timeout")
        self.assertEqual(run.call_args.kwargs["timeout"], 20)

    def test_preflight_normalizer_preserves_bounded_timeout_causes(self):
        self.assertEqual(preflight.normalize_failure("wechat-window-activation-timeout"),
                         "wechat-window-activation-timeout")
        self.assertEqual(preflight.normalize_failure("wechat-ax-read-timeout"),
                         "wechat-ax-read-timeout")

    def test_window_recovery_geometry_is_capped_and_usable(self):
        frame = SimpleNamespace(size=SimpleNamespace(height=1440))
        visible = SimpleNamespace(origin=SimpleNamespace(x=0, y=0),
                                  size=SimpleNamespace(width=2560, height=1440))
        self.assertEqual(wd.bounded_window_geometry(frame, visible), (24, 24, 1000, 700))

    def test_window_recovery_geometry_respects_available_screen_area(self):
        frame = SimpleNamespace(size=SimpleNamespace(height=800))
        visible = SimpleNamespace(origin=SimpleNamespace(x=-100, y=20),
                                  size=SimpleNamespace(width=950, height=620))
        self.assertEqual(wd.bounded_window_geometry(frame, visible), (-76, 184, 902, 572))

    def test_window_recovery_rejects_screen_below_minimum(self):
        frame = SimpleNamespace(size=SimpleNamespace(height=700))
        visible = SimpleNamespace(origin=SimpleNamespace(x=0, y=0),
                                  size=SimpleNamespace(width=900, height=580))
        with self.assertRaisesRegex(RuntimeError, "wechat-visible-screen-too-small"):
            wd.bounded_window_geometry(frame, visible)

    def test_window_recovery_script_sets_only_unique_window_without_swallowed_errors(self):
        script = wd.window_geometry_script((24, 24), (1000, 700))
        self.assertIn('if (count of namedMains) is not 1 then error "wechat-main-window-count-not-one"', script)
        self.assertIn("set position of w to {24, 24}", script)
        self.assertIn("set size of w to {1000, 700}", script)
        self.assertNotIn("try", script)
        self.assertIn('return "resize-requested"', script)
        self.assertNotIn("return (item 1", script)

    def test_window_size_readback_requires_exact_expected_dimensions(self):
        wd.verify_window_size_readback((1000, 700), (1000, 700))
        with self.assertRaisesRegex(RuntimeError, "wechat-main-window-size-readback-mismatch"):
            wd.verify_window_size_readback((280, 380), (1000, 700))

    def test_window_size_readback_waits_for_async_ax_update_without_resizing_again(self):
        values = iter([(280, 380), (1000, 700)])
        read_size = mock.Mock(side_effect=lambda: next(values))
        with mock.patch.object(wd.time, "monotonic", side_effect=[0.0, 0.0, 0.1]), \
             mock.patch.object(wd.time, "sleep") as sleep:
            wd.wait_for_window_size_readback(read_size, (1000, 700), timeout_seconds=2.0,
                                             poll_interval=0.1)
        self.assertEqual(read_size.call_count, 2)
        sleep.assert_called_once()

    def test_window_size_readback_stays_closed_after_bounded_wait(self):
        read_size = mock.Mock(return_value=(280, 380))
        with mock.patch.object(wd.time, "monotonic", side_effect=[0.0, 0.0, 0.1, 2.0]), \
             mock.patch.object(wd.time, "sleep") as sleep:
            with self.assertRaisesRegex(RuntimeError, "wechat-main-window-size-readback-mismatch"):
                wd.wait_for_window_size_readback(read_size, (1000, 700), timeout_seconds=1.0,
                                                 poll_interval=0.1)
        self.assertEqual(read_size.call_count, 2)
        sleep.assert_called_once()

    def test_wechat_process_selection_requires_unique_live_bundle(self):
        live = SimpleNamespace(bundleIdentifier=lambda: "com.tencent.xinWeChat",
                               isTerminated=lambda: False)
        self.assertIs(wd.unique_wechat_application([live]), live)
        other = SimpleNamespace(bundleIdentifier=lambda: "com.example.other",
                                isTerminated=lambda: False)
        with self.assertRaisesRegex(RuntimeError, "wechat-process-count-not-one"):
            wd.unique_wechat_application([live, live, other])
        terminated = SimpleNamespace(bundleIdentifier=lambda: "com.tencent.xinWeChat",
                                     isTerminated=lambda: True)
        with self.assertRaisesRegex(RuntimeError, "wechat-process-identity-mismatch"):
            wd.unique_wechat_application([terminated])

    def test_capture_window_must_belong_to_exact_wechat_process_pid(self):
        window = {
            "kCGWindowOwnerPID": 321,
            "kCGWindowOwnerName": "WeChat",
            "kCGWindowLayer": 0,
            "kCGWindowName": "微信",
            "kCGWindowBounds": {"Width": 1000, "Height": 700},
            "kCGWindowNumber": 77,
        }
        self.assertTrue(wd.wechat_window_info_matches(window, 321))
        self.assertFalse(wd.wechat_window_info_matches(window, 654))
        window["kCGWindowOwnerPID"] = "invalid"
        self.assertFalse(wd.wechat_window_info_matches(window, 321))

    def test_module_can_be_loaded_by_business_adapter_from_absolute_path(self):
        module_path = Path(preflight.__file__).resolve()
        spec = importlib.util.spec_from_file_location("absolute_shared_preflight_test", module_path)
        self.assertIsNotNone(spec)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        self.assertTrue(callable(module.run_exact_group_preflight))

    def test_receipt_is_parameterized_and_never_sends(self):
        locator = SimpleNamespace(open_group=mock.Mock(return_value=wd.Receipt(
            ok=True, action="open-group", group="任意完整群名", header="任意完整群名（3）",
            note="ax-current-header", artifacts=[])))
        receipt = preflight.run_exact_group_preflight("任意完整群名", "/tmp/wechat-preflight-test", locator=locator)
        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["group"], "任意完整群名")
        self.assertEqual(receipt["sendAttempts"], 0)
        self.assertEqual(receipt["runtimeModelDecisions"], 0)
        self.assertTrue(receipt["interactionLock"]["released"])
        locator.open_group.assert_called_once_with(
            "任意完整群名", Path("/tmp/wechat-preflight-test").resolve(),
            exact=True, search_name=None,
        )

    def test_capture_failure_is_a_hard_gate(self):
        locator = SimpleNamespace(open_group=mock.Mock(side_effect=RuntimeError(
            "wechat-window-capture-failed:could not create image from window")))
        receipt = preflight.run_exact_group_preflight("目标群", locator=locator)
        self.assertFalse(receipt["ok"])
        self.assertEqual(receipt["reason"], "wechat-window-capture-failed")
        self.assertTrue(receipt["hardGate"])

    def test_multiple_candidates_are_a_hard_gate(self):
        locator = SimpleNamespace(open_group=mock.Mock(return_value=wd.Receipt(
            ok=False, action="open-group", group="目标群", note="exact-group-result-count:2")))
        receipt = preflight.run_exact_group_preflight("目标群", locator=locator)
        self.assertFalse(receipt["ok"])
        self.assertTrue(receipt["hardGate"])

    def test_current_ax_header_does_not_touch_window_or_screenshot(self):
        expected = wd.Receipt(ok=True, action="open-group", group="目标群",
                              header="目标群（8）", note="ax-current-header")
        with mock.patch.object(wd, "wechat_running", return_value=True), \
             mock.patch.object(wd, "open_group_exact_ax_visible", return_value=expected), \
             mock.patch.object(wd, "ensure_window_size") as resize, \
             mock.patch.object(wd, "screenshot_search_region") as screenshot:
            receipt = wd.open_group("目标群", Path("/tmp/wechat-preflight-test"), exact=True)
        self.assertTrue(receipt.ok)
        resize.assert_not_called()
        screenshot.assert_not_called()


if __name__ == "__main__":
    unittest.main()

class SingleWindowAppleScriptTests(unittest.TestCase):
    def test_main_window_binding_is_ax_only_and_never_front_window(self):
        source = Path(wd.__file__).read_text(encoding="utf-8")
        self.assertIn("kAXTitleAttribute", source)
        self.assertIn('== "微信"', source)
        self.assertIn("kAXSizeAttribute", source)
        self.assertIn("wechat-main-window-count-not-one", source)
        for name in ("activate_wechat", "window_bounds", "screenshot_search_region"):
            body = source.split("def %s(" % name, 1)[1].split("\ndef ", 1)[0]
            self.assertNotIn("front window", body)


class SearchCaptureForegroundIdentityTests(unittest.TestCase):
    def test_search_capture_refuses_non_wechat_foreground_before_screenshot(self):
        with mock.patch.object(wd, "activate_wechat"), \
             mock.patch.object(wd, "wechat_window_id", return_value=77), \
             mock.patch.object(wd, "wechat_frontmost", return_value=False), \
             mock.patch.object(wd, "wechat_window_unobstructed", return_value=True), \
             mock.patch.object(wd, "wechat_menu_bar_frontmost", return_value=True), \
             mock.patch.object(wd, "run") as capture, \
             mock.patch.object(wd.time, "sleep"):
            with self.assertRaisesRegex(RuntimeError, "wechat-search-region-contended"):
                wd.screenshot_search_region(Path("/tmp/not-wechat.png"))
        capture.assert_not_called()

    def test_search_capture_removes_frame_if_foreground_changes_during_capture(self):
        states = iter((True, False))
        def write_capture(command):
            Path(command[-1]).write_bytes(b"captured")
            return SimpleNamespace(returncode=0, stderr="", stdout="")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "search.png"
            with mock.patch.object(wd, "activate_wechat"), \
                 mock.patch.object(wd, "wechat_window_id", return_value=77), \
                 mock.patch.object(wd, "wechat_frontmost", side_effect=lambda: next(states)), \
                 mock.patch.object(wd, "wechat_window_unobstructed", return_value=True), \
                 mock.patch.object(wd, "wechat_menu_bar_frontmost", return_value=True), \
                 mock.patch.object(wd, "window_bounds", return_value=(0, 0, 1000, 700)), \
                 mock.patch.object(wd, "run", side_effect=write_capture), \
                 mock.patch.object(wd.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "wechat-search-region-contended"):
                    wd.screenshot_search_region(path)
            self.assertFalse(path.exists())


class WindowOcclusionDecisionTests(unittest.TestCase):
    def setUp(self):
        self.target = {
            "kCGWindowOwnerPID": 321, "kCGWindowOwnerName": "WeChat",
            "kCGWindowLayer": 0, "kCGWindowName": "微信", "kCGWindowNumber": 77,
            "kCGWindowBounds": {"X": 10, "Y": 20, "Width": 1000, "Height": 700},
            "kCGWindowAlpha": 1.0,
        }
        self.bounds = (10, 20, 1000, 700)

    def other(self, pid=654, bounds=None, alpha=1.0):
        return {"kCGWindowOwnerPID": pid, "kCGWindowOwnerName": "Other",
                "kCGWindowLayer": 0, "kCGWindowName": "Other", "kCGWindowNumber": 88,
                "kCGWindowBounds": bounds or {"X": 300, "Y": 200, "Width": 800, "Height": 500},
                "kCGWindowAlpha": alpha}

    def test_foreign_overlapping_window_above_target_blocks(self):
        decision = wd.window_occlusion_decision([self.other(), self.target], 77, 321, self.bounds)
        self.assertEqual(decision, "foreign-window-overlap")

    def test_foreign_window_below_target_does_not_block(self):
        decision = wd.window_occlusion_decision([self.target, self.other()], 77, 321, self.bounds)
        self.assertEqual(decision, "unobstructed")

    def test_same_process_transparent_zero_area_and_non_intersecting_windows_are_ignored(self):
        cases = [
            self.other(pid=321),
            self.other(bounds={"X": 20, "Y": 30, "Width": 0, "Height": 0}),
            self.other(bounds={"X": 1200, "Y": 900, "Width": 200, "Height": 100}),
            self.other(alpha=0.0),
        ]
        for candidate in cases:
            with self.subTest(candidate=candidate):
                self.assertEqual(wd.window_occlusion_decision(
                    [candidate, self.target], 77, 321, self.bounds), "unobstructed")

    def test_system_layer_windows_never_block(self):
        # Dock backdrop reports full-screen bounds but sits on a system layer.
        dock = dict(self.other(bounds={"X": 0, "Y": 0, "Width": 1312, "Height": 848}),
                    kCGWindowLayer=20, kCGWindowName="Dock")
        menubar = dict(self.other(bounds={"X": 0, "Y": 0, "Width": 1312, "Height": 26}),
                       kCGWindowLayer=24, kCGWindowName="Menubar")
        for overlay in (dock, menubar):
            with self.subTest(overlay=overlay["kCGWindowName"]):
                self.assertEqual(wd.window_occlusion_decision(
                    [overlay, self.target], 77, 321, self.bounds), "unobstructed")

    def test_missing_duplicate_or_mismatched_target_fails_closed(self):
        self.assertEqual(wd.window_occlusion_decision([], 77, 321, self.bounds),
                         "target-window-not-onscreen")
        self.assertEqual(wd.window_occlusion_decision([self.target, self.target], 77, 321, self.bounds),
                         "target-window-identity-not-unique")
        self.assertEqual(wd.window_occlusion_decision([self.target], 77, 654, self.bounds),
                         "target-window-not-onscreen")
        self.assertEqual(wd.window_occlusion_decision(
            [self.target], 77, 321, (10, 20, 1200, 700)), "target-window-geometry-mismatch")

    def test_unknown_foreign_window_geometry_fails_closed(self):
        unknown = self.other()
        del unknown["kCGWindowBounds"]["Height"]
        self.assertEqual(wd.window_occlusion_decision([unknown, self.target], 77, 321, self.bounds),
                         "window-occlusion-evidence-invalid")
