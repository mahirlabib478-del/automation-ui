#!/usr/bin/env bash
set -euo pipefail

APK_PATH="${1:-}"
PACKAGE="com.automationui"
OUT_DIR="${2:-adb-smoke-output}"
mkdir -p "$OUT_DIR"

command -v adb >/dev/null 2>&1 || { echo "ERROR: adb not found. Install Android Platform Tools."; exit 2; }
adb get-state >/dev/null 2>&1 || { echo "ERROR: No authorized Android device. Enable USB debugging and accept the RSA prompt."; exit 3; }

echo "Device: $(adb shell getprop ro.product.manufacturer) $(adb shell getprop ro.product.model)"
echo "Android API: $(adb shell getprop ro.build.version.sdk)"
adb shell getprop ro.build.version.release > "$OUT_DIR/android-version.txt"
adb shell dumpsys accessibility > "$OUT_DIR/accessibility.txt"
adb shell settings get secure enabled_accessibility_services > "$OUT_DIR/enabled-accessibility-services.txt"

if [[ -n "$APK_PATH" ]]; then
  [[ -f "$APK_PATH" ]] || { echo "ERROR: APK not found: $APK_PATH"; exit 4; }
  adb install -r "$APK_PATH"
fi

adb shell pm path "$PACKAGE" > "$OUT_DIR/installed-package.txt" || true
adb shell am force-stop "$PACKAGE" || true
adb shell monkey -p "$PACKAGE" 1 >/dev/null
sleep 2
adb shell screencap -p /sdcard/automation-ui-smoke.png
adb pull /sdcard/automation-ui-smoke.png "$OUT_DIR/automation-ui-smoke.png" >/dev/null
adb shell rm -f /sdcard/automation-ui-smoke.png
adb logcat -d -t 4000 -s AutomationAccessibilityService AndroidRuntime System.err > "$OUT_DIR/logcat.txt" || true

echo
echo "Smoke diagnostics saved in: $OUT_DIR"
echo "Check enabled-accessibility-services.txt and logcat.txt. A successful install/launch is not proof that Record & Replay passed on-device."
