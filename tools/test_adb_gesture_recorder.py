import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adb_gesture_recorder import (
    GestureRecorder,
    ScreenStateObserver,
    parse_display_size,
    parse_event_line,
    parse_input_devices,
)


class ADBGestureRecorderTests(unittest.TestCase):
    SAMPLE_DEVICES = """add device 1: /dev/input/event0
  name:     "gpio-keys"
  events:
    KEY (0001): 0072 KEY_HOME
add device 2: /dev/input/event2
  name:     "goodix-touchscreen"
  events:
    KEY (0001): 014a BTN_TOUCH
    ABS (0003): 0035 ABS_MT_POSITION_X : value 0, min 0, max 100
                0036 ABS_MT_POSITION_Y : value 0, min 0, max 100
                0039 ABS_MT_TRACKING_ID : value -1, min 0, max 65535
                0002 ABS_MT_SLOT : value 0, min 0, max 9
"""

    def setUp(self):
        self.device = parse_input_devices(self.SAMPLE_DEVICES)[0]

    def test_detects_touchscreen_and_axis_ranges(self):
        self.assertEqual(self.device.path, "/dev/input/event2")
        self.assertEqual(self.device.x_min, 0)
        self.assertEqual(self.device.x_max, 100)
        self.assertEqual(self.device.y_max, 100)

    def test_parses_hex_getevent_line(self):
        event = parse_event_line("[ 123.456789] /dev/input/event2: EV_ABS ABS_MT_POSITION_X 00000032")
        self.assertEqual(event, (123.456789, "/dev/input/event2", "EV_ABS", "ABS_MT_POSITION_X", 50))

    def test_parses_getevent_line_without_device_prefix(self):
        event = parse_event_line("[ 130436.126528] EV_ABS ABS_MT_POSITION_X 000006a6")
        self.assertEqual(event, (130436.126528, None, "EV_ABS", "ABS_MT_POSITION_X", 0x06A6))
        key_event = parse_event_line("[ 130436.126528] EV_KEY BTN_TOUCH DOWN")
        self.assertEqual(key_event, (130436.126528, None, "EV_KEY", "BTN_TOUCH", 1))
        release_event = parse_event_line("[ 130436.126528] EV_KEY BTN_TOUCH UP")
        self.assertEqual(release_event, (130436.126528, None, "EV_KEY", "BTN_TOUCH", 0))

    def test_parses_display_size(self):
        self.assertEqual(parse_display_size("Physical size: 1080x2400"), (1080, 2400))
        self.assertEqual(parse_display_size("Physical size: 1080x2400\nOverride size: 720x1600"), (720, 1600))

    def test_records_a_tap(self):
        recorder = GestureRecorder(self.device, 101, 101, 0, 1_700_000_000_000)
        lines = [
            "[ 1.000000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID 00000001",
            "[ 1.010000] /dev/input/event2: EV_ABS ABS_MT_POSITION_X 00000032",
            "[ 1.020000] /dev/input/event2: EV_ABS ABS_MT_POSITION_Y 00000032",
            "[ 1.030000] /dev/input/event2: EV_SYN SYN_REPORT 00000000",
            "[ 1.100000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID ffffffff",
        ]
        for line in lines:
            recorder.feed(line)
        self.assertEqual(len(recorder.actions), 1)
        self.assertEqual(recorder.actions[0]["gestureKind"], "TAP")
        self.assertEqual(recorder.actions[0]["gestureStartX"], 5000)
        self.assertEqual(recorder.actions[0]["gestureStartY"], 5000)

    def test_records_device_prefix_free_touch_events(self):
        recorder = GestureRecorder(self.device, 101, 101, 0, 1_700_000_000_000)
        lines = [
            "[ 1.000000] EV_ABS ABS_MT_TRACKING_ID 00000001",
            "[ 1.010000] EV_KEY BTN_TOUCH DOWN",
            "[ 1.020000] EV_ABS ABS_MT_POSITION_X 00000032",
            "[ 1.030000] EV_ABS ABS_MT_POSITION_Y 00000032",
            "[ 1.100000] EV_ABS ABS_MT_TRACKING_ID ffffffff",
            "[ 1.100000] EV_KEY BTN_TOUCH UP",
        ]
        for line in lines:
            recorder.feed(line)
        self.assertEqual(len(recorder.actions), 1)
        self.assertEqual(recorder.actions[0]["gestureKind"], "TAP")

    def test_records_a_swipe(self):
        recorder = GestureRecorder(self.device, 101, 101, 0, 1_700_000_000_000)
        lines = [
            "[ 1.000000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID 00000001",
            "[ 1.010000] /dev/input/event2: EV_ABS ABS_MT_POSITION_X 00000032",
            "[ 1.020000] /dev/input/event2: EV_ABS ABS_MT_POSITION_Y 00000050",
            "[ 1.030000] /dev/input/event2: EV_SYN SYN_REPORT 00000000",
            "[ 1.100000] /dev/input/event2: EV_ABS ABS_MT_POSITION_Y 00000020",
            "[ 1.110000] /dev/input/event2: EV_SYN SYN_REPORT 00000000",
            "[ 1.200000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID ffffffff",
        ]
        for line in lines:
            recorder.feed(line)
        self.assertEqual(len(recorder.actions), 1)
        self.assertEqual(recorder.actions[0]["gestureKind"], "SWIPE")
        self.assertNotEqual(recorder.actions[0]["gestureStartY"], recorder.actions[0]["gestureEndY"])


    def test_records_normalized_gesture_path_samples(self):
        recorder = GestureRecorder(self.device, 101, 101, 0, 1_700_000_000_000)
        lines = [
            "[ 1.000000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID 00000001",
            "[ 1.010000] /dev/input/event2: EV_ABS ABS_MT_POSITION_X 00000010",
            "[ 1.020000] /dev/input/event2: EV_ABS ABS_MT_POSITION_Y 00000010",
            "[ 1.040000] /dev/input/event2: EV_ABS ABS_MT_POSITION_X 00000032",
            "[ 1.050000] /dev/input/event2: EV_ABS ABS_MT_POSITION_Y 00000032",
            "[ 1.100000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID ffffffff",
        ]
        for line in lines:
            recorder.feed(line)
        points = recorder.actions[0]["gesturePoints"]
        self.assertGreaterEqual(len(points), 2)
        self.assertTrue(all(0 <= p["x"] <= 10000 and 0 <= p["y"] <= 10000 for p in points))
        self.assertTrue(all(points[i]["tMs"] <= points[i + 1]["tMs"] for i in range(len(points) - 1)))

    def test_records_gap_before_each_gesture(self):
        recorder = GestureRecorder(self.device, 101, 101, 0, 1_700_000_000_000)
        lines = [
            "[ 1.000000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID 00000001",
            "[ 1.010000] /dev/input/event2: EV_ABS ABS_MT_POSITION_X 00000032",
            "[ 1.020000] /dev/input/event2: EV_ABS ABS_MT_POSITION_Y 00000032",
            "[ 1.100000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID ffffffff",
            "[ 6.100000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID 00000002",
            "[ 6.110000] /dev/input/event2: EV_ABS ABS_MT_POSITION_X 00000040",
            "[ 6.120000] /dev/input/event2: EV_ABS ABS_MT_POSITION_Y 00000040",
            "[ 6.200000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID ffffffff",
        ]
        for line in lines:
            recorder.feed(line)
        self.assertEqual(len(recorder.actions), 2)
        self.assertEqual(recorder.actions[0]["gapBeforeMs"], 0)
        self.assertEqual(recorder.actions[1]["gapBeforeMs"], 5_000)
        self.assertLess(recorder.actions[1]["startTimestamp"], recorder.actions[1]["timestamp"])

    def test_snapshot_before_uses_host_monotonic_time_and_ui_history(self):
        observer = ScreenStateObserver(None, capture_ui_hierarchy=True)
        observer.history = [{
            "foregroundPackage": "com.example",
            "foregroundActivity": "com.example.Main",
            "focusedWindowPackage": "com.example",
            "focusedWindow": "com.example.Main",
            "sampledAtHostMonotonicMs": 1000,
            "visibleTexts": [],
            "uiSnapshotReliable": False,
        }]
        observer.ui_history = [{
            "visibleTexts": ["Continue", "Settings"],
            "uiCapturedHostMonotonicMs": 1200,
            "uiSnapshotReliable": True,
        }]
        snapshot = observer.snapshot_before(1500)
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["foregroundPackage"], "com.example")
        self.assertTrue(snapshot["stateSnapshotReliable"])
        self.assertTrue(snapshot["uiSnapshotReliable"])
        self.assertEqual(snapshot["visibleTexts"], ["Continue", "Settings"])

    def test_snapshot_before_does_not_use_future_state(self):
        observer = ScreenStateObserver(None)
        observer.history = [{
            "foregroundPackage": "com.example",
            "focusedWindowPackage": "com.example",
            "sampledAtHostMonotonicMs": 2000,
        }]
        self.assertIsNone(observer.snapshot_before(1500))

    def test_attaches_pre_touch_state_snapshot(self):
        recorder = GestureRecorder(self.device, 101, 101, 0, 1_700_000_000_000)
        recorder.state_provider = lambda uptime: {
            "foregroundPackage": "com.example",
            "deviceUptimeMs": uptime - 100,
            "stateSnapshotReliable": True,
        }
        lines = [
            "[ 1.000000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID 00000001",
            "[ 1.010000] /dev/input/event2: EV_ABS ABS_MT_POSITION_X 00000032",
            "[ 1.020000] /dev/input/event2: EV_ABS ABS_MT_POSITION_Y 00000032",
            "[ 1.100000] /dev/input/event2: EV_ABS ABS_MT_TRACKING_ID ffffffff",
        ]
        for line in lines:
            recorder.feed(line)
        self.assertEqual(recorder.actions[0]["screenStateBefore"]["foregroundPackage"], "com.example")

if __name__ == "__main__":
    unittest.main()
