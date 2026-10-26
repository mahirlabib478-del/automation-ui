import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adb_gesture_replayer import (
    action_coordinates,
    load_actions,
    recorded_gap_ms,
    state_matches,
    dispatch_action,
)


class ADBGgestureReplayerTests(unittest.TestCase):
    def test_loads_adb_capture_payload(self):
        payload = {"format": "adb-gesture-capture", "screen": {"width": 720, "height": 1600},
                   "actions": [{"type": "GESTURE", "gestureKind": "TAP"}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workflow.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            actions, loaded = load_actions(path)
        self.assertEqual(len(actions), 1)
        self.assertEqual(loaded["screen"]["width"], 720)

    def test_exact_gap_is_used(self):
        self.assertEqual(recorded_gap_ms({"gapBeforeMs": 5000}, {"timestamp": 1000}), 5000)

    def test_legacy_gap_subtracts_current_gesture_duration(self):
        previous = {"timestamp": 1000}
        current = {"timestamp": 6200, "gestureDurationMs": 200}
        self.assertEqual(recorded_gap_ms(current, previous), 5000)

    def test_normalized_coordinates_scale_to_current_screen(self):
        action = {"gestureStartX": 5000, "gestureStartY": 5000,
                  "gestureEndX": 10000, "gestureEndY": 10000}
        self.assertEqual(action_coordinates(action, 720, 1600, 360, 800),
                         (180, 400, 359, 799))

    def test_state_mismatch_detects_wrong_package(self):
        matched, reason = state_matches(
            {"foregroundPackage": "com.example"},
            {"foregroundPackage": "com.android.settings"}
        )
        self.assertFalse(matched)
        self.assertIn("foreground app differs", reason)

    def test_state_mismatch_detects_missing_current_identity(self):
        matched, reason = state_matches(
            {"foregroundPackage": "com.example"},
            {"foregroundPackage": None, "focusedWindowPackage": None}
        )
        self.assertFalse(matched)
        self.assertIn("cannot verify foreground app", reason)

    def test_ui_only_snapshot_can_verify_visible_text(self):
        matched, _ = state_matches(
            {"uiSnapshotReliable": True, "visibleTexts": ["Continue", "Settings"],
             "uiForegroundPackage": "com.example"},
            {"visibleTexts": ["Continue", "Settings"], "uiSnapshotReliable": True,
             "uiForegroundPackage": "com.example"}
        )
        self.assertTrue(matched)

    def test_ui_snapshot_from_different_app_does_not_match(self):
        matched, reason = state_matches(
            {"uiSnapshotReliable": True, "visibleTexts": ["Continue", "Settings"],
             "uiForegroundPackage": "com.example"},
            {"visibleTexts": ["Continue", "Settings"], "uiSnapshotReliable": True,
             "uiForegroundPackage": "com.example.other"}
        )
        self.assertFalse(matched)
        self.assertIn("different app", reason)

    def test_unstable_current_ui_snapshot_is_not_used(self):
        matched, reason = state_matches(
            {"uiSnapshotReliable": True, "visibleTexts": ["Continue", "Settings"]},
            {"visibleTexts": ["Continue", "Settings"], "uiSnapshotReliable": False}
        )
        self.assertFalse(matched)
        self.assertIn("not reliable", reason)

    def test_ui_snapshot_fails_if_current_hierarchy_unavailable(self):
        matched, reason = state_matches(
            {"uiSnapshotReliable": True, "visibleTexts": ["Continue", "Settings"]},
            {"visibleTexts": []}
        )
        self.assertFalse(matched)
        self.assertIn("hierarchy is unavailable", reason)

    def test_focused_window_match_overrides_transient_resumed_activity_mismatch(self):
        matched, reason = state_matches(
            {"foregroundPackage": "com.instagram.android",
             "focusedWindowPackage": "com.instagram.android"},
            {"foregroundPackage": "com.google.android.gms",
             "focusedWindowPackage": "com.instagram.android"}
        )
        self.assertTrue(matched)
        self.assertIn("screen state matches", reason)

    def test_focused_window_mismatch_still_stops_when_foreground_matches(self):
        matched, reason = state_matches(
            {"foregroundPackage": "com.instagram.android",
             "focusedWindowPackage": "com.instagram.android"},
            {"foregroundPackage": "com.instagram.android",
             "focusedWindowPackage": "com.transsion.hilauncher"}
        )
        self.assertFalse(matched)
        self.assertIn("focused window differs", reason)

    def test_ui_focused_window_match_overrides_transient_ui_activity_mismatch(self):
        matched, reason = state_matches(
            {"foregroundPackage": "com.instagram.android",
             "focusedWindowPackage": "com.instagram.android",
             "uiSnapshotReliable": True,
             "uiForegroundPackage": "com.instagram.android",
             "uiFocusedWindowPackage": "com.instagram.android",
             "visibleTexts": ["Home", "Search", "Profile"]},
            {"foregroundPackage": "com.google.android.gms",
             "focusedWindowPackage": "com.instagram.android",
             "uiSnapshotReliable": True,
             "uiForegroundPackage": "com.google.android.gms",
             "uiFocusedWindowPackage": "com.instagram.android",
             "visibleTexts": ["Home", "Search", "Profile"]}
        )
        self.assertTrue(matched)
        self.assertIn("screen state matches", reason)

    def test_transient_foreground_mismatch_is_tolerated_when_stable_ui_window_matches(self):
        matched, reason = state_matches(
            {"foregroundPackage": "com.instagram.android",
             "stateSnapshotReliable": True,
             "uiSnapshotReliable": False,
             "visibleTexts": []},
            {"foregroundPackage": "com.google.android.gms",
             "focusedWindowPackage": None,
             "uiIdentityStable": True,
             "uiFocusedWindowPackage": "com.instagram.android",
             "uiForegroundPackage": "com.google.android.gms",
             "uiSnapshotReliable": False,
             "visibleTexts": []}
        )
        self.assertTrue(matched)
        self.assertIn("screen state matches", reason)

    def test_foreground_mismatch_still_fails_without_corroborating_ui_identity(self):
        matched, reason = state_matches(
            {"foregroundPackage": "com.instagram.android"},
            {"foregroundPackage": "com.google.android.gms",
             "focusedWindowPackage": None,
             "uiIdentityStable": False}
        )
        self.assertFalse(matched)
        self.assertIn("foreground app differs", reason)

    def test_known_focused_window_mismatch_remains_a_hard_stop(self):
        matched, reason = state_matches(
            {"foregroundPackage": "com.instagram.android",
             "focusedWindowPackage": "com.instagram.android"},
            {"foregroundPackage": "com.google.android.gms",
             "focusedWindowPackage": "com.transsion.hilauncher",
             "uiIdentityStable": True,
             "uiFocusedWindowPackage": "com.instagram.android"}
        )
        self.assertFalse(matched)
        self.assertIn("focused window differs", reason)

    def test_state_matches_same_package(self):
        matched, _ = state_matches(
            {"foregroundPackage": "com.example", "focusedWindowPackage": "com.example"},
            {"foregroundPackage": "com.example", "focusedWindowPackage": "com.example"}
        )
        self.assertTrue(matched)

    def test_tap_dry_run_does_not_need_device(self):
        action = {"type": "GESTURE", "gestureKind": "TAP", "gestureStartX": 5000,
                  "gestureStartY": 5000, "gestureEndX": 5000, "gestureEndY": 5000,
                  "gestureDurationMs": 80}
        command = dispatch_action(None, action, 360, 800, 720, 1600, True)
        self.assertEqual(command, "shell input tap 180 400")

    def test_swipe_preserves_recorded_duration(self):
        action = {"type": "GESTURE", "gestureKind": "SWIPE", "gestureStartX": 1000,
                  "gestureStartY": 8000, "gestureEndX": 1000, "gestureEndY": 2000,
                  "gestureDurationMs": 777}
        command = dispatch_action(None, action, 360, 800, 720, 1600, True)
        self.assertEqual(command, "shell input swipe 36 639 36 160 777")


if __name__ == "__main__":
    unittest.main()
