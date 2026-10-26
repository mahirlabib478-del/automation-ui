#!/usr/bin/env python3
"""Replay ADB-captured Android gestures with timing and best-effort screen checks.

Examples:
  python adb_gesture_replayer.py --input adb-gestures.json --dry-run
  python adb_gesture_replayer.py --input adb-gestures.json
  python adb_gesture_replayer.py --input adb-gestures.json --no-verify-state

This uses Android's shell input commands through an authorized ADB connection.
It does not require the Automation UI app to remain in the foreground.
"""
from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

from adb_gesture_recorder import (
    capture_foreground_state,
    capture_visible_ui_texts,
    parse_display_size,
    parse_rotation,
    run_adb,
)


def load_actions(path: Path) -> tuple[list[dict], dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload, {}
    if not isinstance(payload, dict) or not isinstance(payload.get("actions"), list):
        raise ValueError("JSON must be an array of actions or an object containing an actions array.")
    if payload.get("format") not in (None, "", "adb-gesture-capture", "automation-ui-workflow"):
        raise ValueError(f"Unsupported workflow format: {payload.get('format')}")
    return payload["actions"], payload


def get_display(serial: Optional[str], rotation_override: Optional[int] = None) -> tuple[int, int, Optional[int]]:
    raw_size = run_adb(serial, "shell", "wm", "size")
    width, height = parse_display_size(raw_size)
    rotation_text = run_adb(serial, "shell", "dumpsys", "input")
    try:
        rotation_text += "\n" + run_adb(serial, "shell", "dumpsys", "window", "displays")
    except (OSError, subprocess.SubprocessError):
        pass
    detected_rotation = parse_rotation(rotation_text)
    rotation = rotation_override if rotation_override is not None else detected_rotation
    if rotation in (1, 3):
        width, height = height, width
    return width, height, rotation


def normalized_coordinate(value: Any, size: int) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if 0 <= number <= 10_000:
        return int(round(number / 10_000 * max(0, size - 1)))
    return None


def rotate_normalized_point(x: float, y: float, from_rotation: Optional[int],
                            to_rotation: Optional[int]) -> tuple[float, float]:
    """Transform normalized screen coordinates through natural orientation."""
    if from_rotation is None or to_rotation is None or from_rotation == to_rotation:
        return x, y

    # Invert the recorder's natural-to-current orientation transform.
    if from_rotation == 1:
        natural_x, natural_y = 1.0 - y, x
    elif from_rotation == 2:
        natural_x, natural_y = 1.0 - x, 1.0 - y
    elif from_rotation == 3:
        natural_x, natural_y = y, 1.0 - x
    else:
        natural_x, natural_y = x, y

    # Apply the current display orientation.
    if to_rotation == 1:
        return natural_y, 1.0 - natural_x
    if to_rotation == 2:
        return 1.0 - natural_x, 1.0 - natural_y
    if to_rotation == 3:
        return 1.0 - natural_y, natural_x
    return natural_x, natural_y


def _normalized_pair(x_value: Any, y_value: Any) -> Optional[tuple[float, float]]:
    try:
        x = int(x_value)
        y = int(y_value)
    except (TypeError, ValueError):
        return None
    if not (0 <= x <= 10_000 and 0 <= y <= 10_000):
        return None
    return x / 10_000.0, y / 10_000.0


def action_coordinates(action: dict, recorded_width: int, recorded_height: int,
                       current_width: int, current_height: int,
                       recorded_rotation: Optional[int] = None,
                       current_rotation: Optional[int] = None) -> tuple[int, int, int, int]:
    keys = ("gestureStartX", "gestureStartY", "gestureEndX", "gestureEndY")
    has_normalized_fields = any(key in action for key in keys)
    points = action.get("gesturePoints") or []
    kind = str(action.get("gestureKind") or "").upper()

    if all(key in action for key in keys):
        start = _normalized_pair(action.get("gestureStartX"), action.get("gestureStartY"))
        end = _normalized_pair(action.get("gestureEndX"), action.get("gestureEndY"))
        if start is None or end is None:
            raise ValueError("Gesture has invalid normalized coordinates; refusing to guess a touch location.")
    elif has_normalized_fields:
        raise ValueError("Gesture has incomplete normalized coordinates; refusing to guess a touch location.")
    else:
        path_points = []
        if isinstance(points, list):
            for point in points:
                if not isinstance(point, dict):
                    continue
                pair = _normalized_pair(point.get("x"), point.get("y"))
                if pair is not None:
                    path_points.append(pair)

        if path_points:
            start = path_points[0]
            end = path_points[-1] if kind == "SWIPE" else start
        else:
            if kind == "SWIPE":
                raise ValueError(
                    "SWIPE has no start/end coordinates or usable path points. "
                    "Its bounding box does not preserve swipe direction; record this workflow again."
                )
            if not all(key in action for key in ("left", "top", "right", "bottom")):
                raise ValueError("Gesture has no usable coordinates or legacy bounds; refusing to touch.")
            try:
                old_w = max(1, int(action.get("screenWidth") or recorded_width or current_width))
                old_h = max(1, int(action.get("screenHeight") or recorded_height or current_height))
                left, top = int(action["left"]), int(action["top"])
                right, bottom = int(action["right"]), int(action["bottom"])
            except (TypeError, ValueError, KeyError):
                raise ValueError("Gesture has invalid legacy bounds; refusing to guess a touch location.")
            x_fraction = ((left + right) / 2.0) / max(1, old_w - 1)
            y_fraction = ((top + bottom) / 2.0) / max(1, old_h - 1)
            start = (
                max(0.0, min(1.0, x_fraction)),
                max(0.0, min(1.0, y_fraction)),
            )
            end = start

    sxn, syn = start
    exn, eyn = end
    sxn, syn = rotate_normalized_point(sxn, syn, recorded_rotation, current_rotation)
    exn, eyn = rotate_normalized_point(exn, eyn, recorded_rotation, current_rotation)

    def to_pixel(value: float, size: int) -> int:
        return int(round(max(0.0, min(1.0, value)) * max(0, size - 1)))

    return (
        to_pixel(sxn, current_width),
        to_pixel(syn, current_height),
        to_pixel(exn, current_width),
        to_pixel(eyn, current_height),
    )


def require_gesture_actions(actions: list[Any]) -> list[dict]:
    """Reject mixed semantic workflows instead of silently skipping steps."""
    if not isinstance(actions, list):
        raise ValueError("Workflow actions must be a JSON array.")
    for index, action in enumerate(actions, start=1):
        if not isinstance(action, dict):
            raise ValueError(f"Action {index} is not a JSON object; refusing to skip it.")
        action_type = str(action.get("type") or "").upper()
        if action_type != "GESTURE":
            raise ValueError(
                f"Action {index} has type {action_type or '(missing)'}. "
                "This ADB-only replayer supports raw GESTURE actions only and refuses to "
                "skip other action types, because skipping steps can make later touches land on the wrong screen."
            )
    return actions


def swipe_path_deviation_px(action: dict, width: int, height: int,
                            recorded_rotation: Optional[int] = None,
                            current_rotation: Optional[int] = None) -> Optional[float]:
    """Return maximum deviation of recorded path samples from the straight ADB swipe."""
    points = action.get("gesturePoints")
    if not isinstance(points, list) or len(points) < 3:
        return None
    normalized = []
    for point in points:
        if not isinstance(point, dict):
            continue
        pair = _normalized_pair(point.get("x"), point.get("y"))
        if pair is None:
            continue
        x, y = rotate_normalized_point(pair[0], pair[1], recorded_rotation, current_rotation)
        normalized.append((x * max(0, width - 1), y * max(0, height - 1)))
    if len(normalized) < 3:
        return None
    x1, y1 = normalized[0]
    x2, y2 = normalized[-1]
    dx, dy = x2 - x1, y2 - y1
    length_sq = dx * dx + dy * dy
    maximum = 0.0
    for x, y in normalized[1:-1]:
        if length_sq <= 1e-9:
            distance = math.hypot(x - x1, y - y1)
        else:
            t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / length_sq))
            projection_x, projection_y = x1 + t * dx, y1 + t * dy
            distance = math.hypot(x - projection_x, y - projection_y)
        maximum = max(maximum, distance)
    return maximum


def recorded_gap_ms(action: dict, previous: Optional[dict]) -> int:
    if "gapBeforeMs" in action:
        try:
            return max(0, int(action.get("gapBeforeMs") or 0))
        except (TypeError, ValueError):
            return 0
    if previous is None:
        return 0
    try:
        elapsed = int(action.get("timestamp", 0)) - int(previous.get("timestamp", 0))
        current_duration = int(action.get("gestureDurationMs", 0) or 0)
        return max(0, elapsed - current_duration)
    except (TypeError, ValueError):
        return 0


def normalize_text(value: str) -> str:
    return " ".join(value.casefold().split())


def state_matches(expected: dict, actual: dict, verify_ui: bool = True) -> tuple[bool, str]:
    # Prefer the focused window as the visible touch target. Android can report a
    # transient/resumed service activity (for example Play services) while the
    # expected app still owns the focused window.
    expected_window = expected.get("focusedWindowPackage")
    actual_window = actual.get("focusedWindowPackage")
    expected_package = expected.get("foregroundPackage")
    actual_package = actual.get("foregroundPackage")

    if expected_window and actual_window:
        # A known different focused window is a hard mismatch. Do not override it
        # merely because a foreground/activity label or some text happens to match.
        if expected_window != actual_window:
            return False, f"focused window differs (recorded={expected_window}, current={actual_window})"
    else:
        identity_reason = None
        if expected_package and not actual_package:
            identity_reason = "cannot verify foreground app; current identity is unavailable"
        elif expected_package and actual_package and expected_package != actual_package:
            identity_reason = f"foreground app differs (recorded={expected_package}, current={actual_package})"
        elif expected_window and not actual_window and not actual_package:
            identity_reason = "cannot verify focused window or foreground app; current identity is unavailable"

        # A stable UI dump is a second source of evidence. This specifically handles
        # transient Android service/resumed-activity labels when the touchable app's
        # focused window is still the app that was recorded.
        ui_identity_stable = bool(actual.get("uiIdentityStable"))
        actual_ui_window = actual.get("uiFocusedWindowPackage")
        actual_ui_package = actual.get("uiForegroundPackage")
        expected_target = expected_window or expected_package
        ui_corroborates_expected = bool(
            verify_ui
            and ui_identity_stable
            and expected_target
            and (
                actual_ui_window == expected_target
                or (not actual_ui_window and actual_ui_package == expected_target)
            )
        )
        if identity_reason and not ui_corroborates_expected:
            return False, identity_reason

    expected_texts = expected.get("visibleTexts") or []
    actual_texts = actual.get("visibleTexts") or []
    identity_available = bool(
        expected_package or expected_window
        or (verify_ui and actual.get("uiIdentityStable") and
            (actual.get("uiFocusedWindowPackage") or actual.get("uiForegroundPackage")))
    )

    if verify_ui and expected.get("uiSnapshotReliable"):
        if len(expected_texts) < 2:
            if not identity_available:
                return False, "not enough recorded UI text to verify the screen without app/window identity"
        else:
            if not actual_texts:
                return False, "recorded UI text exists but current UI hierarchy is unavailable"
            if not actual.get("uiSnapshotReliable"):
                return False, "current UI hierarchy snapshot is not reliable; app/window may have changed during capture"
            expected_ui_window = expected.get("uiFocusedWindowPackage")
            actual_ui_window = actual.get("uiFocusedWindowPackage")
            if expected_ui_window and actual_ui_window:
                if expected_ui_window != actual_ui_window:
                    return False, f"UI hierarchy belongs to a different focused window (recorded={expected_ui_window}, current={actual_ui_window})"
            else:
                expected_ui_package = expected.get("uiForegroundPackage")
                actual_ui_package = actual.get("uiForegroundPackage")
                if expected_ui_package and actual_ui_package and expected_ui_package != actual_ui_package:
                    return False, f"UI hierarchy belongs to a different app (recorded={expected_ui_package}, current={actual_ui_package})"
            wanted = {normalize_text(str(x)) for x in expected_texts if str(x).strip()}
            got = {normalize_text(str(x)) for x in actual_texts if str(x).strip()}
            overlap = len(wanted & got)
            required = max(1, min(3, math.ceil(min(len(wanted), 8) * 0.25)))
            if overlap < required:
                return False, f"visible UI text differs (matched {overlap}, need {required})"

    if not identity_available and not (verify_ui and expected.get("uiSnapshotReliable") and len(expected_texts) >= 2):
        return False, "recorded screen has no verifiable app/window identity or sufficient UI text"
    return True, "screen state matches"


def wait_for_expected_state(serial: Optional[str], action: dict, timeout_ms: int,
                            verify_ui: bool, dry_run: bool) -> tuple[bool, str]:
    expected = action.get("screenStateBefore")
    reliable = bool(
        isinstance(expected, dict)
        and (
            action.get("stateSnapshotReliable")
            or expected.get("stateSnapshotReliable")
            or action.get("uiSnapshotReliable")
            or expected.get("uiSnapshotReliable")
        )
    )
    if not isinstance(expected, dict) or not reliable:
        return True, "no fresh pre-touch state snapshot; state verification skipped"
    if dry_run:
        return True, "dry-run; state verification not performed"

    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    last_reason = "state unavailable"
    ui_fallback_attempted = False
    last_ui_capture = 0.0
    while True:
        try:
            actual = capture_foreground_state(serial)
            matched, reason = state_matches(expected, actual, verify_ui=verify_ui)

            # If the quick foreground/window check mismatches and the recording had
            # no reliable UI text, take one UI hierarchy sample as corroborating
            # evidence before stopping. Avoid repeatedly dumping the hierarchy every
            # 400 ms; it is relatively expensive on some Android devices.
            should_try_ui_fallback = (
                not matched
                and verify_ui
                and not ui_fallback_attempted
                and not expected.get("uiSnapshotReliable")
                and not reason.startswith("focused window differs")
            )
            if should_try_ui_fallback:
                ui_fallback_attempted = True
                actual.update(capture_visible_ui_texts(serial))
                matched, reason = state_matches(expected, actual, verify_ui=verify_ui)

            # When the recorded step includes reliable UI text, refresh that evidence
            # periodically rather than on every fast foreground poll.
            elif not matched and verify_ui and expected.get("uiSnapshotReliable"):
                now = time.monotonic()
                if last_ui_capture == 0.0 or now - last_ui_capture >= 1.2:
                    actual.update(capture_visible_ui_texts(serial))
                    last_ui_capture = time.monotonic()
                    matched, reason = state_matches(expected, actual, verify_ui=verify_ui)

            if matched:
                return True, reason
            last_reason = reason
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            last_reason = f"could not read current screen state: {exc}"
        if time.monotonic() >= deadline:
            return False, last_reason
        time.sleep(0.4)


def dispatch_action(serial: Optional[str], action: dict, width: int, height: int,
                    recorded_width: int, recorded_height: int, dry_run: bool,
                    recorded_rotation: Optional[int] = None,
                    current_rotation: Optional[int] = None) -> str:
    kind = str(action.get("gestureKind") or "").upper()
    if str(action.get("type", "")).upper() != "GESTURE":
        raise ValueError(f"Action type {action.get('type')!r} is not a raw ADB gesture.")
    x1, y1, x2, y2 = action_coordinates(
        action, recorded_width, recorded_height, width, height,
        recorded_rotation=recorded_rotation, current_rotation=current_rotation
    )
    duration = max(50, min(10_000, int(action.get("gestureDurationMs") or 350)))
    if kind == "TAP":
        command = ["shell", "input", "tap", str(x1), str(y1)]
    elif kind == "LONG_PRESS":
        command = ["shell", "input", "swipe", str(x1), str(y1), str(x1), str(y1), str(max(650, duration))]
    elif kind == "SWIPE":
        command = ["shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)]
    else:
        raise ValueError(f"Unsupported gesture kind {kind!r}; refusing to guess.")
    display = " ".join(command)
    if not dry_run:
        run_adb(serial, *command)
    return display


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replay ADB-recorded Android touch gestures.")
    parser.add_argument("--input", default="adb-gestures.json", help="Recorded JSON workflow")
    parser.add_argument("--serial", help="ADB device serial when multiple devices are connected")
    parser.add_argument("--max-gap-ms", type=int, default=300_000,
                        help="Maximum replay wait before any step (default 5 minutes)")
    parser.add_argument("--verify-timeout-ms", type=int, default=15_000,
                        help="How long to wait for a recorded pre-touch screen state (default 15 seconds)")
    verification = parser.add_mutually_exclusive_group()
    verification.add_argument("--verify-state", dest="verify_state", action="store_true",
                              help="Enable best-effort screen-state checks before actions (opt-in)")
    verification.add_argument("--no-verify-state", dest="verify_state", action="store_false",
                              help="Disable screen-state checks (default; kept for compatibility)")
    parser.set_defaults(verify_state=False)
    parser.add_argument("--no-verify-ui", action="store_true",
                        help="Do not compare visible text even when a UI hierarchy snapshot exists")
    parser.add_argument("--allow-rotation-change", action="store_true",
                        help="Allow a different display orientation and transform normalized coordinates")
    parser.add_argument("--rotation", type=int, choices=(0, 1, 2, 3),
                        help="Override current display rotation if auto-detection is unavailable or incorrect")
    parser.add_argument("--dry-run", action="store_true", help="Print planned waits/actions without touching the phone")
    parser.add_argument("--limit", type=int, default=0, help="Replay only the first N actions (0 means all)")
    parser.add_argument("--log", default="adb-replay-log.jsonl", help="Replay log output path")
    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"ERROR: workflow file not found: {input_path.resolve()}", file=sys.stderr)
        return 2

    try:
        device_state = run_adb(args.serial, "get-state").strip()
        if device_state != "device":
            raise RuntimeError("ADB device is not authorized. Check adb devices and accept the phone prompt.")
        actions, payload = load_actions(input_path)
        actions = require_gesture_actions(actions)
        if args.limit > 0:
            actions = actions[:args.limit]
        if not actions:
            raise ValueError("No GESTURE actions found in this JSON file.")

        width, height, rotation = get_display(args.serial, args.rotation)
        if rotation is None:
            raise RuntimeError(
                "Could not determine current display rotation. Refusing to replay because touch coordinates may be wrong. "
                "Check the phone orientation or pass --rotation 0, 1, 2, or 3."
            )
        recorded_screen = payload.get("screen", {}) if isinstance(payload, dict) else {}
        recorded_rotation_value = recorded_screen.get("rotation")
        if recorded_rotation_value is None:
            recorded_rotation_value = next(
                (action.get("displayRotation") for action in actions if action.get("displayRotation") is not None),
                None,
            )
        try:
            recorded_rotation = int(recorded_rotation_value) if recorded_rotation_value is not None else None
        except (TypeError, ValueError):
            recorded_rotation = None

        if recorded_rotation is not None and rotation != recorded_rotation:
            message = f"Display rotation differs (recorded={recorded_rotation}, current={rotation})."
            if not args.allow_rotation_change:
                raise RuntimeError(message + " Rotate the phone back to the recording orientation, or pass --allow-rotation-change.")
            print("WARNING: " + message + " Normalized coordinates will be transformed for the new orientation.")
        elif recorded_rotation is None:
            print("WARNING: recording has no rotation metadata; keep the phone in the same orientation used during capture.")

        recorded_width = int(recorded_screen.get("width") or actions[0].get("screenWidth") or width)
        recorded_height = int(recorded_screen.get("height") or actions[0].get("screenHeight") or height)
        print(f"Device ready. Display={width}x{height}, rotation={rotation}; actions={len(actions)}")
        print("Replay uses ADB shell input. Keep the phone unlocked and do not touch it during replay.")
        if args.verify_state:
            print("Screen-state verification: ON (best-effort; may stop on mismatches).")
        else:
            print("WARNING: screen-state verification is OFF; replay will not stop if the phone is on the wrong screen.")
        if args.dry_run:
            print("DRY RUN: no input will be sent to the phone.")

        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        previous: Optional[dict] = None
        with log_path.open("w", encoding="utf-8") as log:
            for index, action in enumerate(actions, start=1):
                gap = recorded_gap_ms(action, previous)
                if gap > args.max_gap_ms:
                    print(f"WARNING: step {index} gap capped from {gap} ms to {args.max_gap_ms} ms")
                    gap = args.max_gap_ms
                print(f"[{index}/{len(actions)}] waiting {gap} ms before {action.get('gestureKind')}")
                log.write(json.dumps({
                    "step": index, "event": "wait", "gapBeforeMs": gap,
                    "timestamp": int(time.time() * 1000)
                }) + "\n")
                log.flush()
                if gap and not args.dry_run:
                    time.sleep(gap / 1000)

                if args.verify_state:
                    matched, reason = wait_for_expected_state(
                        args.serial, action, args.verify_timeout_ms,
                        verify_ui=not args.no_verify_ui, dry_run=args.dry_run
                    )
                    print(f"    STATE: {reason}")
                    log.write(json.dumps({
                        "step": index, "event": "state-check", "matched": matched,
                        "reason": reason, "timestamp": int(time.time() * 1000)
                    }) + "\n")
                    log.flush()
                    if not matched:
                        print("STOP: recorded screen state did not match; refusing to tap a potentially wrong screen.", file=sys.stderr)
                        return 4

                points = action.get("gesturePoints") or []
                if str(action.get("gestureKind", "")).upper() == "SWIPE" and len(points) > 2:
                    deviation = swipe_path_deviation_px(
                        action, width, height, recorded_rotation, rotation
                    )
                    if deviation is None:
                        print(f"    NOTE: {len(points)} path samples were recorded; ADB shell input can replay only a straight swipe between endpoints.")
                    else:
                        print(
                            f"    NOTE: ADB shell input approximates {len(points)} recorded path samples as a straight swipe; "
                            f"maximum path deviation is about {deviation:.0f} px, so curved swipes may behave differently."
                        )
                command = dispatch_action(
                    args.serial, action, width, height,
                    recorded_width, recorded_height, args.dry_run,
                    recorded_rotation=recorded_rotation, current_rotation=rotation
                )
                print(f"    ADB: {command}")
                log.write(json.dumps({
                    "step": index, "event": "gesture", "kind": action.get("gestureKind"),
                    "command": command, "timestamp": int(time.time() * 1000)
                }) + "\n")
                log.flush()
                previous = action

        print(f"Replay finished. Log: {log_path.resolve()}")
        return 0
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
