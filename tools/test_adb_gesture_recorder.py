import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from adb_gesture_recorder import (
    GestureRecorder,
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


if __name__ == "__main__":
    unittest.main()
