"""Packaged helper entry point for the ADB gesture recorder."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop.licensing.license_core import current_license_status
from tools.adb_gesture_recorder import main as recorder_main


def main() -> int:
    status = current_license_status()
    if status.enforcement_enabled and not status.activated:
        print("ERROR: A valid ADB Flow Studio license is required before capture.", file=sys.stderr)
        print(status.message, file=sys.stderr)
        return 6
    return recorder_main()


if __name__ == "__main__":
    raise SystemExit(main())
