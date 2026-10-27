from __future__ import annotations

import unittest

from tools import adb_gesture_replayer


class ReplayerImportTests(unittest.TestCase):
    def test_replayer_imports_recorder_helpers_through_package(self) -> None:
        self.assertTrue(callable(adb_gesture_replayer.run_adb))
        self.assertTrue(callable(adb_gesture_replayer.load_actions))
        self.assertTrue(callable(adb_gesture_replayer.dispatch_action))


if __name__ == "__main__":
    unittest.main()
