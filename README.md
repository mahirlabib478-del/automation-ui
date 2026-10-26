# Automation UI — Android Record & Replay

Native Android prototype for recording accessibility-visible UI actions and replaying supported actions on the same phone.

## Build status and APK

Every push to `main` runs the **Android APK Build** GitHub Actions workflow. When the workflow succeeds, it uploads `automation-ui-debug-apk` as an artifact.

1. Open [Actions → Android APK Build](https://github.com/mahirlabib478-del/automation-ui/actions/workflows/android-build.yml).
2. Open the latest successful run.
3. Download the `automation-ui-debug-apk` artifact and unzip it.
4. Install `app-debug.apk` on your Android phone. If Android asks, allow installation from the source you used.

## Open in Android Studio

- JDK 17
- Android SDK Platform 35
- Gradle 8.9 (the CI workflow installs this version)
- Android Studio with Kotlin and Jetpack Compose support

Open the repository folder in Android Studio and sync the project. The CI workflow builds with `gradle --no-daemon assembleDebug`.

## Enable and test

1. Install and open **Automation UI**.
2. Tap **Enable Accessibility Service** and enable Automation UI in Android Accessibility settings.
3. Return to the app and leave **Record text input** disabled unless you explicitly need text-field replay.
4. Tap **Record**, switch to a non-sensitive test app, and perform a short sequence of clicks and scrolls.
5. Return to Automation UI and tap **Stop**. Actions are stored locally on the device.
6. Return to the same initial screen and tap **Replay**. Use **Stop replay immediately** to cancel playback.

## Current capabilities

- Records accessibility-visible clicks and their UI selectors/bounds.
- Can record scroll events and replay by accessibility scroll actions or a coordinate swipe fallback.
- Can replay clicks using resource ID/text selectors with coordinate fallback.
- Can replay Home transitions observed through launcher window changes and selected system Back/Home buttons when Android exposes those events.
- Optional text-field recording is off by default and skips password fields.
- Local action storage and live action/status list.

## Limitations — read before use

This is an MVP, not a universal phone macro recorder. Android does not expose every raw touch from other apps to a normal application. Therefore arbitrary swipes, notification-shade gestures, every Back action, lock screens, protected windows, permission dialogs and some OEM-specific Settings screens may not be captured or replayable. Coordinate fallback depends on the same device layout and screen state. Some apps deliberately restrict accessibility access.

Use only on your own device and for permitted workflows. Do not record passwords, OTPs, banking details or private information. The optional text recording feature is disabled by default. Accessibility access is powerful; disable the service when you are not using the app.

## Technology

- Kotlin
- Jetpack Compose
- Android AccessibilityService / AccessibilityNodeInfo
- SharedPreferences JSON storage
- GitHub Actions debug APK build
