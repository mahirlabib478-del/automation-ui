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


def get_display(serial: Optional[str]) -> tuple[int, int, Optional[int]]:
    raw_size = run_adb(serial, "shell", "wm", "size")
    width, height = parse_display_size(raw_size)
    rotation_text = run_adb(serial, "shell", "dumpsys", "input")
    try:
        rotation_text += "\n" + run_adb(serial, "shell", "dumpsys", "window", "displays")
    except (OSError, subprocess.SubprocessError):
        pass
    rotation = parse_rotation(rotation_text)
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


def action_coordinates(action: dict, recorded_width: int, recorded_height: int,
                       current_width: int, current_height: int) -> tuple[int, int, int, int]:
    sx = normalized_coordinate(action.get("gestureStartX"), current_width)
    sy = normalized_coordinate(action.get("gestureStartY"), current_height)
    ex = normalized_coordinate(action.get("gestureEndX"), current_width)
    ey = normalized_coordinate(action.get("gestureEndY"), current_height)
    if None not in (sx, sy, ex, ey):
        return int(sx), int(sy), int(ex), int(ey)

    # Compatibility fallback for older JSON files with only pixel bounds.
    old_w = max(1, int(action.get("screenWidth") or recorded_width or current_width))
    old_h = max(1, int(action.get("screenHeight") or recorded_height or current_height))
    left, top = int(action.get("left") or 0), int(action.get("top") or 0)
    right, bottom = int(action.get("right") or left), int(action.get("bottom") or top)
    x1 = int(round(((left + right) / 2) / old_w * max(0, current_width - 1)))
    y1 = int(round(((top + bottom) / 2) / old_h * max(0, current_height - 1)))
    return x1, y1, x1, y1


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
    for key, label in (
        ("foregroundPackage", "foreground app"),
        ("focusedWindowPackage", "focused window"),
    ):
        wanted = expected.get(key)
        got = actual.get(key)
        if wanted and got and wanted != got:
            return False, f"{label} differs (recorded={wanted}, current={got})"

    expected_texts = expected.get("visibleTexts") or []
    actual_texts = actual.get("visibleTexts") or []
    if verify_ui and expected.get("uiSnapshotReliable") and len(expected_texts) >= 2 and actual_texts:
        wanted = {normalize_text(str(x)) for x in expected_texts if str(x).strip()}
        got = {normalize_text(str(x)) for x in actual_texts if str(x).strip()}
        overlap = len(wanted & got)
        required = max(1, min(3, math.ceil(min(len(wanted), 8) * 0.25)))
        if overlap < required:
            return False, f"visible UI text differs (matched {overlap}, need {required})"
    return True, "screen state matches"


def wait_for_expected_state(serial: Optional[str], action: dict, timeout_ms: int,
                            verify_ui: bool, dry_run: bool) -> tuple[bool, str]:
    expected = action.get("screenStateBefore")
    reliable = bool(action.get("stateSnapshotReliable") or (
        isinstance(expected, dict) and expected.get("stateSnapshotReliable")
    ))
    if not isinstance(expected, dict) or not reliable:
        return True, "no fresh pre-touch state snapshot; state verification skipped"
    if dry_run:
        return True, "dry-run; state verification not performed"

    deadline = time.monotonic() + max(0, timeout_ms) / 1000
    last_reason = "state unavailable"
    while True:
        try:
            actual = capture_foreground_state(
                serial,
                capture_ui_hierarchy=verify_ui and bool(expected.get("uiSnapshotReliable")),
            )
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
                    recorded_width: int, recorded_height: int, dry_run: bool) -> str:
    kind = str(action.get("gestureKind") or "").upper()
    if str(action.get("type", "")).upper() != "GESTURE":
        raise ValueError(f"Action type {action.get('type')!r} is not a raw ADB gesture.")
    x1, y1, x2, y2 = action_coordinates(
        action, recorded_width, recorded_height, width, height
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
    parser.add_argument("--verify-timeout-ms", type=int, default=10_000,
                        help="How long to wait for a recorded pre-touch screen state")
    parser.add_argument("--no-verify-state", action="store_true",
                        help="Disable foreground/window checks before actions")
    parser.add_argument("--no-verify-ui", action="store_true",
                        help="Do not compare visible text even when a UI hierarchy snapshot exists")
    parser.add_argument("--allow-rotation-change", action="store_true",
                        help="Allow replay if display orientation differs from the recording")
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
        actions = [a for a in actions if isinstance(a, dict) and str(a.get("type", "")).upper() == "GESTURE"]
        if args.limit > 0:
            actions = actions[:args.limit]
        if not actions:
            raise ValueError("No GESTURE actions found in this JSON file.")

        width, height, rotation = get_display(args.serial)
        recorded_screen = payload.get("screen", {}) if isinstance(payload, dict) else {}
        recorded_rotation = recorded_screen.get("rotation")
        if rotation is not None and recorded_rotation is not None and rotation != int(recorded_rotation):
            message = f"Display rotation differs (recorded={recorded_rotation}, current={rotation})."
            if not args.allow_rotation_change:
                raise RuntimeError(message + " Rotate the phone back to the recording orientation, or pass --allow-rotation-change.")
            print("WARNING: " + message + " Normalized coordinates will be scaled to the current display.")

        recorded_width = int(recorded_screen.get("width") or actions[0].get("screenWidth") or width)
        recorded_height = int(recorded_screen.get("height") or actions[0].get("screenHeight") or height)
        print(f"Device ready. Display={width}x{height}, rotation={rotation}; actions={len(actions)}")
        print("Replay uses ADB shell input. Keep the phone unlocked and do not touch it during replay.")
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

                if not args.no_verify_state:
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
                    print(f"    NOTE: {len(points)} path samples were recorded; standard ADB shell input replays this as a straight swipe between endpoints.")
                command = dispatch_action(
                    args.serial, action, width, height,
                    recorded_width, recorded_height, args.dry_run
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
