from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from desktop.main import MainWindow


class GuiSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_constructs_with_no_connected_device(self) -> None:
        window = MainWindow()
        self.assertEqual(window.windowTitle(), "ADB Flow Studio")
        self.assertEqual(window.stack.count(), 5)
        self.assertTrue(window.dry_run_checkbox.isChecked())
        self.assertFalse(window.verify_state_checkbox.isChecked())
        window.close()


if __name__ == "__main__":
    unittest.main()
