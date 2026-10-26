# Automation UI

An Android Accessibility-based Record & Replay prototype. It records actions exposed by Android Accessibility and replays supported UI actions on the same device.

## Architecture

- Recorder: accessible click events, opt-in non-password text changes, scroll events, package, element selectors, clickable-parent bounds, display size and rotation.
- Workflow model: versioned JSON actions persisted locally; older records remain readable.
- Replay policy: ranks visible/enabled UI nodes using resource ID, text, content description, hint, class, editability, scrollability and normalized screen position.
- Replay controller: prefers Accessibility actions, waits for targets, applies bounded retries, and logs fallback/skip reasons.
- Verification: each replay action and failure is recorded in Replay diagnostics.

## Build and tests

Run `gradle --no-daemon testDebugUnitTest` and `gradle --no-daemon assembleDebug`.

GitHub Actions runs unit tests before building the debug APK.

## ADB device smoke test

With Android Platform Tools installed and USB debugging authorized, run:

    bash tools/adb-device-smoke.sh app/build/outputs/apk/debug/app-debug.apk

The script captures Android version, Accessibility diagnostics, logcat and a screenshot. A successful install/launch is not proof that arbitrary workflows passed; those still require repeatable on-device tests.

## Platform limits

A normal Android app cannot universally observe every raw touch in every other app. Accessibility exposes semantic clicks and some scroll events, but arbitrary gestures, notification shade interactions, secure screens and OEM-specific system UI may be unavailable. ADB improves diagnostics and some test flows, but is not a permanent privileged API for the installed app. MediaProjection-based visual verification and a separately permissioned ADB touch-capture companion remain follow-up work, not features claimed as implemented here.

Text recording is opt-in and password fields are excluded. Do not use workflows to bypass authentication or protected system controls.
