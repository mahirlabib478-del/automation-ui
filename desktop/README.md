# ADB Flow Studio — Desktop MVP

ADB Flow Studio is the first Windows desktop interface for the existing ADB-only gesture recorder and replayer. This branch adds the desktop shell and connects it to the scripts in tools/adb_gesture_recorder.py and tools/adb_gesture_replayer.py.

## Current MVP features

- Dashboard with ADB/device status and saved workflow list.
- ADB executable auto-detection and a manual path setting.
- Capture page with output JSON selection, Stop and Save, optional foreground/window snapshots, and optional UI-text snapshots.
- Replay page with workflow selection, repeat count, delay between runs, progress, Stop, and per-run logs.
- Dry Run is enabled by default. Real replay requires a confirmation prompt.
- Screen-state verification is disabled by default to match the current ADB-only workflow. It can be enabled explicitly for a replay.
- Logs and workflow JSON files are stored in the user's Documents folder.

## Important status

**This MVP is not ready for commercial sale yet.** The License page is a placeholder. The digitally signed, PC-bound offline license system and final installer validation are planned for the next phase.

The desktop GUI does not remove the underlying ADB limitations: capture is single-finger; some Android/OEM builds block getevent; and ADB shell input approximates recorded curved swipes as straight swipes.

## Run from source on Windows

1. Install Python 3.11 or newer.
2. Install Android Platform Tools and make sure the phone is authorized for USB debugging.
3. From the repository root, run these commands:

    python -m pip install -r requirements-desktop.txt
    python desktop\main.py

4. If ADB is not detected, open Settings in the app and browse to adb.exe.
5. Capture workflows are saved by default under %USERPROFILE%\Documents\ADB Flow Studio\workflows.
6. Replay logs are saved under %USERPROFILE%\Documents\ADB Flow Studio\logs.

## Run tests

    python -m unittest discover -s desktop\tests -v
    python -m compileall -q desktop tools

## Build Windows executables

Run desktop\build_windows.bat from a Windows checkout. The script creates a local build environment and packages the GUI plus separate recorder/replayer worker executables. The complete dist folder must be kept together because the GUI launches the worker executables beside it.

Do not distribute this build commercially until offline license enforcement, signing-key handling, clean-machine installation, and end-to-end device tests have been completed.
