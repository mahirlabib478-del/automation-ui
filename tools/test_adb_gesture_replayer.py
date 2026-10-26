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
            {"uiSnapshotReliable": True, "visibleTexts": ["Continue", "Settings"]},
            {"visibleTexts": ["Continue", "Settings"]}
        )
        self.assertTrue(matched)

    def test_ui_snapshot_fails_if_current_hierarchy_unavailable(self):
        matched, reason = state_matches(
            {"uiSnapshotReliable": True, "visibleTexts": ["Continue", "Settings"]},
            {"visibleTexts": []}
        )
        self.assertFalse(matched)
        self.assertIn("hierarchy is unavailable", reason)

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
