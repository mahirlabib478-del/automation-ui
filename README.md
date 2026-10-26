# Automation UI

An Android Accessibility-based Record & Replay prototype. It records actions exposed by Android Accessibility and replays supported UI actions on the same device.

## Architecture

- Recorder: accessible click events, opt-in non-password text changes, scroll events, package, element selectors, clickable-parent bounds, display size and rotation.
- Workflow model: versioned JSON actions persisted locally; older records remain readable.
- Replay policy: ranks visible/enabled UI nodes using resource ID, text, content description, hint, class, editability, scrollability and normalized screen position.
- Replay controller: prefers Accessibility actions, waits for targets, applies bounded retries, and logs fallback/skip reasons.
- Verification: each replay action and failure is recorded in Replay diagnostics.

## Build and tests

Run `python3 -m unittest discover -s tools -p 'test_*.py' -v`, `gradle --no-daemon testDebugUnitTest`, and `gradle --no-daemon assembleDebug`.

GitHub Actions runs Python parser tests and Android unit tests before building the debug APK.

## Hybrid gesture recording over ADB (optional import workflow)

For users who want to import raw ADB gestures into the Android app's older hybrid workflow, run the recorder with Python 3 and Android Platform Tools:

    python tools/adb_gesture_recorder.py --output adb-gestures.json

Start Record in Automation UI first, run the companion, use the phone, then press Ctrl+C in the computer terminal. Stop app recording and import/merge adb-gestures.json. This hybrid import path is optional; the ADB-only workflow below does not require the Automation UI app to be open.

The companion discovers touchscreen axes with adb shell getevent -lp. Some production/OEM builds deny shell access to touch input; in that case it reports an error. Multi-touch gestures are intentionally ignored rather than approximated as a single finger.

## ADB device smoke test

With Android Platform Tools installed and USB debugging authorized, run:

    bash tools/adb-device-smoke.sh app/build/outputs/apk/debug/app-debug.apk

The script captures Android version, Accessibility diagnostics, logcat and a screenshot. A successful install/launch is not proof that arbitrary workflows passed; those still require repeatable on-device tests.

## Platform limits

A normal Android app cannot universally observe every raw touch in every other app. Accessibility exposes semantic clicks and some scroll events, but arbitrary gestures, notification shade interactions, secure screens and OEM-specific system UI may be unavailable. ADB improves diagnostics and some test flows, but is not a permanent privileged API for the installed app. MediaProjection-based visual verification and a separately permissioned ADB touch-capture companion remain follow-up work, not features claimed as implemented here.

Text recording is opt-in and password fields are excluded. Do not use workflows to bypass authentication or protected system controls.


## ADB-only record and replay

The companion recorder records raw single-finger tap, swipe, and long-press gestures through `adb shell getevent`, including gesture duration, start/end timestamps, and the exact idle gap before each touch. It also samples the foreground activity and focused window before touches; use `--capture-ui-hierarchy` to collect best-effort visible text snapshots for dialog/popup matching.

Record:
```bat
python adb_gesture_recorder.py --output adb-gestures.json --capture-ui-hierarchy
```

Preview without touching the device:
```bat
python adb_gesture_replayer.py --input adb-gestures.json --dry-run
```

Replay with ADB shell input (no Automation UI foreground required):
```bat
python adb_gesture_replayer.py --input adb-gestures.json
```

The replayer scales normalized coordinates to the current logical display, preserves recorded idle gaps and swipe duration, checks display rotation, and verifies the recorded pre-touch foreground/window state when a fresh snapshot is available. If a reliable screen state does not match within the timeout, replay stops rather than blindly tapping a different screen. UI text matching is best-effort and may be unavailable for secure or OEM-protected windows. Raw ADB capture is single-touch; multi-touch, protected system surfaces, and some hardware keys are not fully reproducible. Review workflows and logs before replay.
