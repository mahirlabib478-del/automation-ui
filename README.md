# Automation UI — Android Record & Replay

A native Android MVP for recording accessibility-visible UI actions and replaying supported actions on the same device.

## Stack
- Kotlin + Android Studio
- Jetpack Compose
- Android AccessibilityService
- SharedPreferences for local workflow storage

## Build
1. Open this repository in Android Studio and sync Gradle.
2. Run the `app` configuration on an Android device (min SDK 26).
3. In the app, tap **Enable Accessibility Service** and enable **Automation UI**.
4. Tap **Record**, perform a short test in a non-sensitive app, tap **Stop**, then **Replay**.

## MVP limitations
Android does not let a regular app reliably capture every raw touch across all apps. This version records accessibility-visible click, text-change, scroll and window events; replay currently supports matching click events by accessible text or resource ID. It is not full-fidelity coordinate-based recording. Some system screens, secure windows, permission dialogs and OEM-specific UI may be unavailable.

## Privacy
Workflow data stays locally on the device. Avoid recording passwords, OTPs, banking details or other sensitive content. Replay can interact with other apps; test carefully and stop if the UI differs from the recorded sequence.
