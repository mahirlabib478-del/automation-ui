#!/usr/bin/env python3
"""Capture touchscreen gestures over ADB and export Automation UI workflow JSON.

Run this on a computer with Python 3 and Android Platform Tools installed:
    python tools/adb_gesture_recorder.py --output adb-gestures.json

Start Accessibility recording in Automation UI first. Start this script, use the
phone, then press Ctrl+C on the computer and import/merge the JSON in the app.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


DEVICE_HEADER = re.compile(r"^add device \d+:\s*(/dev/input/\S+)", re.MULTILINE)
EVENT_LINE = re.compile(
    r"^\[\s*(?P<time>\d+(?:\.\d+)?)\]\s+"
    r"(?:(?P<device>/dev/input/\S+):\s+)?"
    r"(?P<event>\S+)\s+(?P<code>\S+)\s+(?P<value>[0-9a-fA-F-]+)"
)


def parse_value(raw: str) -> int:
    if raw.startswith("-"):
        return int(raw, 10)
    value = int(raw, 16)
    return value - (1 << 32) if value >= (1 << 31) else value


def parse_axis_range(block: str, axis_name: str) -> Optional[tuple[int, int]]:
    for line in block.splitlines():
        if axis_name not in line:
            continue
        match = re.search(r"min\s+(-?\d+),\s*max\s+(-?\d+)", line)
        if match:
            minimum, maximum = int(match.group(1)), int(match.group(2))
            if maximum > minimum:
                return minimum, maximum
    return None


@dataclass(frozen=True)
class InputDevice:
    path: str
    name: str
    x_code: str
    y_code: str
    x_min: int
    x_max: int
    y_min: int
    y_max: int
    tracking_code: str
    touch_code: str
    slot_code: str


def parse_input_devices(output: str) -> list[InputDevice]:
    blocks = re.split(r"(?=^add device \d+:)", output, flags=re.MULTILINE)
    devices: list[tuple[int, InputDevice]] = []
    for block in blocks:
        header = DEVICE_HEADER.search(block)
        if not header:
            continue
        path = header.group(1)
        name_match = re.search(r'^\s*name:\s*"([^"]+)"', block, re.MULTILINE)
        name = name_match.group(1) if name_match else path
        mt_x = parse_axis_range(block, "ABS_MT_POSITION_X")
        mt_y = parse_axis_range(block, "ABS_MT_POSITION_Y")
        single_x = parse_axis_range(block, "ABS_X")
        single_y = parse_axis_range(block, "ABS_Y")
        if mt_x and mt_y:
            x_code, y_code, xr, yr = "ABS_MT_POSITION_X", "ABS_MT_POSITION_Y", mt_x, mt_y
        elif single_x and single_y:
            x_code, y_code, xr, yr = "ABS_X", "ABS_Y", single_x, single_y
        else:
            continue
        tracking = "ABS_MT_TRACKING_ID" if "ABS_MT_TRACKING_ID" in block else ""
        touch = "BTN_TOUCH" if "BTN_TOUCH" in block else ("BTN_TOOL_FINGER" if "BTN_TOOL_FINGER" in block else "")
        slot = "ABS_MT_SLOT" if "ABS_MT_SLOT" in block else ""
        if not tracking and not touch:
            continue
        score = 0
        lowered = name.lower()
        if "touch" in lowered or "digitizer" in lowered or "screen" in lowered:
            score += 10
        if tracking:
            score += 2
        if touch:
            score += 1
        device = InputDevice(path, name, x_code, y_code, xr[0], xr[1], yr[0], yr[1], tracking, touch, slot)
        devices.append((score, device))
    return [device for _, device in sorted(devices, key=lambda item: item[0], reverse=True)]


def parse_event_line(line: str):
    match = EVENT_LINE.match(line.strip())
    if not match:
        return None
    return (
        float(match.group("time")),
        match.group("device") or None,
        match.group("event"),
        match.group("code"),
        parse_value(match.group("value")),
    )


def parse_display_size(output: str) -> tuple[int, int]:
    matches = re.findall(r"(?:Physical|Override) size:\s*(\d+)x(\d+)", output)
    if not matches:
        matches = re.findall(r"(\d+)x(\d+)", output)
    if not matches:
        raise RuntimeError("Could not determine Android display size from adb shell wm size.")
    width, height = map(int, matches[-1])
    return width, height


def parse_rotation(output: str) -> Optional[int]:
    patterns = [
        r"SurfaceOrientation:\s*([0-3])",
        r"surfaceOrientation\s*[=:]\s*([0-3])",
        r"mCurrentOrientation\s*[=:]\s*([0-3])",
        r"mDisplayRotation\s*[=:]\s*ROTATION_(0|90|180|270)",
        r"ROTATION_(0|90|180|270)",
    ]
    for pattern in patterns:
        match = re.search(pattern, output)
        if match:
            value = match.group(1)
            if value.isdigit() and int(value) <= 3:
                return int(value)
            return {"0": 0, "90": 1, "180": 2, "270": 3}[value]
    return None


def resolve_adb_executable() -> str:
    """Find adb even when it is installed outside Windows PATH."""
    found = shutil.which("adb")
    if found:
        return found
    candidates = [
        Path(__file__).resolve().parent / "adb.exe",
        Path(__file__).resolve().parent / "platform-tools" / "adb.exe",
        Path(r"C:\platform-tools\adb.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    # Preserve the usual error message if adb is not installed or discoverable.
    return "adb"


def adb_command(serial: Optional[str], *args: str) -> list[str]:
    command = [resolve_adb_executable()]
    if serial:
        command += ["-s", serial]
    command += list(args)
    return command


def run_adb(serial: Optional[str], *args: str) -> str:
    result = subprocess.run(
        adb_command(serial, *args),
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=15,
    )
    return result.stdout.strip()


def normalize_pixel(value: float, size: int) -> int:
    if size <= 1:
        return 0
    return int(round(max(0.0, min(float(size - 1), value)) / float(size - 1) * 10_000))


class GestureRecorder:
    def __init__(
        self,
        device: InputDevice,
        physical_width: int,
        physical_height: int,
        rotation: int,
        epoch_offset_ms: float,
        min_swipe_px: float = 35.0,
        long_press_ms: int = 650,
    ):
        self.device = device
        self.physical_width = physical_width
        self.physical_height = physical_height
        self.rotation = rotation
        self.width = physical_height if rotation in (1, 3) else physical_width
        self.height = physical_width if rotation in (1, 3) else physical_height
        self.epoch_offset_ms = epoch_offset_ms
        self.min_swipe_px = min_swipe_px
        self.long_press_ms = long_press_ms
        self.actions: list[dict] = []
        self.active = False
        self.invalid_multitouch = False
        self.active_slot: Optional[int] = None
        self.current_slot = 0
        self.start_time: Optional[float] = None
        self.start_point: Optional[tuple[float, float]] = None
        self.last_point: Optional[tuple[float, float]] = None
        self.raw_x: Optional[int] = None
        self.raw_y: Optional[int] = None

    def _map_point(self) -> Optional[tuple[float, float]]:
        if self.raw_x is None or self.raw_y is None:
            return None
        dx = (self.raw_x - self.device.x_min) / (self.device.x_max - self.device.x_min)
        dy = (self.raw_y - self.device.y_min) / (self.device.y_max - self.device.y_min)
        nx = max(0.0, min(1.0, dx)) * (self.physical_width - 1)
        ny = max(0.0, min(1.0, dy)) * (self.physical_height - 1)
        if self.rotation == 0:
            return nx, ny
        if self.rotation == 1:
            return ny, (self.physical_width - 1) - nx
        if self.rotation == 2:
            return (self.physical_width - 1) - nx, (self.physical_height - 1) - ny
        return (self.physical_height - 1) - ny, nx

    def _start(self, timestamp: float):
        if self.active:
            return
        self.active = True
        self.invalid_multitouch = False
        self.active_slot = self.current_slot
        self.start_time = timestamp
        self.start_point = None
        self.last_point = None
        self.raw_x = None
        self.raw_y = None

    def _update_point(self):
        point = self._map_point()
        if point is None or not self.active:
            return
        if self.start_point is None:
            self.start_point = point
        self.last_point = point

    def _finish(self, timestamp: float):
        if not self.active:
            return
        if (
            not self.invalid_multitouch
            and self.start_point is not None
            and self.last_point is not None
            and self.start_time is not None
        ):
            sx, sy = self.start_point
            ex, ey = self.last_point
            distance = math.hypot(ex - sx, ey - sy)
            duration_ms = max(50, min(5000, int(round((timestamp - self.start_time) * 1000))))
            if distance >= self.min_swipe_px:
                kind = "SWIPE"
            elif duration_ms >= self.long_press_ms:
                kind = "LONG_PRESS"
            else:
                kind = "TAP"
            self.actions.append(self._action(kind, sx, sy, ex, ey, duration_ms, timestamp))
        self.active = False
        self.invalid_multitouch = False
        self.active_slot = None
        self.start_time = None
        self.start_point = None
        self.last_point = None
        self.raw_x = None
        self.raw_y = None

    def _action(
        self, kind: str, sx: float, sy: float, ex: float, ey: float,
        duration_ms: int, end_time: float
    ) -> dict:
        width, height = self.width, self.height
        sx_i, sy_i = int(round(sx)), int(round(sy))
        ex_i, ey_i = int(round(ex)), int(round(ey))
        timestamp = int(round((end_time * 1000) + self.epoch_offset_ms))
        return {
            "type": "GESTURE",
            "packageName": None,
            "text": "ADB captured " + kind,
            "viewId": None,
            "contentDescription": None,
            "className": None,
            "left": min(sx_i, ex_i),
            "top": min(sy_i, ey_i),
            "right": max(sx_i, ex_i),
            "bottom": max(sy_i, ey_i),
            "screenWidth": width,
            "screenHeight": height,
            "scrollDeltaY": ey_i - sy_i,
            "timestamp": timestamp,
            "inputValue": None,
            "hintText": None,
            "displayRotation": self.rotation,
            "schemaVersion": 2,
            "gestureKind": kind,
            "gestureStartX": normalize_pixel(sx, width),
            "gestureStartY": normalize_pixel(sy, height),
            "gestureEndX": normalize_pixel(ex, width),
            "gestureEndY": normalize_pixel(ey, height),
            "gestureDurationMs": duration_ms,
        }

    def feed(self, line: str):
        parsed = parse_event_line(line)
        if parsed is None:
            return
        timestamp, path, event_type, code, value = parsed
        # getevent omits the device prefix when a single event node is specified.
        # If a prefix is present, still reject events from other input devices.
        if path is not None and path != self.device.path:
            return
        if code == self.device.slot_code and event_type == "EV_ABS":
            self.current_slot = value
            if self.active and self.active_slot is not None and self.current_slot != self.active_slot:
                self.invalid_multitouch = True
            return
        if code == self.device.tracking_code and event_type == "EV_ABS":
            if value >= 0:
                if not self.active:
                    self._start(timestamp)
                elif self.active_slot != self.current_slot:
                    self.invalid_multitouch = True
            else:
                self._finish(timestamp)
            return
        if code == self.device.touch_code and event_type == "EV_KEY":
            if value == 1:
                self._start(timestamp)
            elif value == 0:
                self._finish(timestamp)
            return
        if not self.active:
            return
        if self.device.slot_code and self.current_slot != self.active_slot:
            return
        if event_type == "EV_ABS" and code == self.device.x_code:
            self.raw_x = value
            self._update_point()
        elif event_type == "EV_ABS" and code == self.device.y_code:
            self.raw_y = value
            self._update_point()


def workflow_payload(actions: list[dict], device: InputDevice, width: int, height: int, rotation: int) -> dict:
    return {
        "format": "adb-gesture-capture",
        "schemaVersion": 2,
        "source": "adb-getevent",
        "inputDevice": {"path": device.path, "name": device.name},
        "screen": {"width": width, "height": height, "rotation": rotation},
        "exportedAt": int(time.time() * 1000),
        "actions": actions,
    }


def atomic_write(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Record Android touchscreen gestures over ADB.")
    parser.add_argument("--serial", help="ADB device serial when more than one device is connected")
    parser.add_argument("--event", help="Touchscreen event node, e.g. /dev/input/event2")
    parser.add_argument("--output", default="adb-gestures.json", help="Output JSON path")
    parser.add_argument("--min-swipe-px", type=float, default=35.0, help="Minimum movement to classify a swipe")
    parser.add_argument("--long-press-ms", type=int, default=650, help="Minimum low-motion duration for long press")
    parser.add_argument("--rotation", type=int, choices=(0, 1, 2, 3), help="Override rotation if detection is unavailable")
    args = parser.parse_args(argv)

    try:
        state = run_adb(args.serial, "get-state")
        if state.strip() != "device":
            raise RuntimeError("ADB device is not ready. Authorize USB debugging on the phone.")
        device_list = parse_input_devices(run_adb(args.serial, "shell", "getevent", "-lp"))
        if args.event:
            device_list = [device for device in device_list if device.path == args.event]
            if not device_list:
                raise RuntimeError(f"{args.event} was not found as a readable touchscreen in getevent -lp.")
        if not device_list:
            raise RuntimeError("No touchscreen event node found. The device may block shell access to getevent.")
        device = device_list[0]
        physical_width, physical_height = parse_display_size(run_adb(args.serial, "shell", "wm", "size"))
        rotation_output = run_adb(args.serial, "shell", "dumpsys", "input")
        if args.rotation is None:
            rotation_output += "\n" + run_adb(args.serial, "shell", "dumpsys", "window", "displays")
        rotation = args.rotation if args.rotation is not None else parse_rotation(rotation_output)
        if rotation is None:
            raise RuntimeError("Could not detect display rotation. Re-run with --rotation 0, 1, 2, or 3 after checking phone orientation.")
        uptime = float(run_adb(args.serial, "shell", "cat", "/proc/uptime").split()[0])
        epoch_seconds = float(run_adb(args.serial, "shell", "date", "+%s"))
        epoch_offset_ms = epoch_seconds * 1000 - uptime * 1000

        recorder = GestureRecorder(
            device, physical_width, physical_height, rotation, epoch_offset_ms,
            min_swipe_px=args.min_swipe_px,
            long_press_ms=args.long_press_ms,
        )
        output_path = Path(args.output)
        print(f"Device: {device.name} ({device.path})")
        print(f"Display: {recorder.width}x{recorder.height}, rotation={rotation}")
        print(f"Recording raw touch gestures to {output_path}. Use the phone; press Ctrl+C here to stop.")
        process = subprocess.Popen(
            adb_command(args.serial, "shell", "getevent", "-lt", device.path),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if "permission denied" in line.lower() or "could not open" in line.lower():
                    raise RuntimeError(line.strip())
                before = len(recorder.actions)
                recorder.feed(line)
                if len(recorder.actions) > before:
                    action = recorder.actions[-1]
                    atomic_write(output_path, workflow_payload(
                        recorder.actions, device, recorder.width, recorder.height, rotation
                    ))
                    print("Captured " + action["gestureKind"] + " (" +
                          str(action["gestureDurationMs"]) + " ms), total=" +
                          str(len(recorder.actions)))
            code = process.wait()
            if code != 0:
                raise RuntimeError(f"getevent exited with status {code}; check shell access permissions.")
        except KeyboardInterrupt:
            print("\nStopping capture…")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        atomic_write(output_path, workflow_payload(
            recorder.actions, device, recorder.width, recorder.height, rotation
        ))
        print(f"Saved {len(recorder.actions)} gestures to {output_path.resolve()}")
        if not recorder.actions:
            print("No gestures were captured. Check the selected event node and device permissions.", file=sys.stderr)
            return 5
        return 0
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        print("Confirm USB debugging is enabled, the device is authorized, and adb shell getevent -lp can read touchscreen events.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
