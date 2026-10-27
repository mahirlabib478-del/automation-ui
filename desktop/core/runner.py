from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _worker_prefix(worker_name: str) -> list[str]:
    """Resolve the recorder/replayer entry point for source and packaged builds."""
    if getattr(sys, "frozen", False):
        executable_name = f"adb-flow-studio-{worker_name}.exe" if os.name == "nt" else f"adb-flow-studio-{worker_name}"
        worker_executable = Path(sys.executable).resolve().with_name(executable_name)
        if not worker_executable.is_file():
            raise FileNotFoundError(
                f"Required helper was not found: {worker_executable}. Rebuild the complete desktop package."
            )
        return [str(worker_executable)]

    script_name = {
        "recorder": "adb_gesture_recorder.py",
        "replayer": "adb_gesture_replayer.py",
    }.get(worker_name)
    if not script_name:
        raise ValueError(f"Unknown worker: {worker_name}")
    script = PROJECT_ROOT / "tools" / script_name
    if not script.is_file():
        raise FileNotFoundError(f"ADB helper script was not found: {script}")
    return [sys.executable, "-u", str(script)]


def build_capture_command(
    output_path: str | Path,
    serial: str | None = None,
    capture_state: bool = True,
    capture_ui_hierarchy: bool = False,
) -> list[str]:
    command = _worker_prefix("recorder") + ["--output", str(Path(output_path).expanduser())]
    if serial:
        command += ["--serial", serial]
    if not capture_state:
        command.append("--no-state-capture")
    if capture_ui_hierarchy:
        command.append("--capture-ui-hierarchy")
    return command


def build_replay_command(
    input_path: str | Path,
    log_path: str | Path,
    serial: str | None = None,
    verify_state: bool = False,
    dry_run: bool = False,
) -> list[str]:
    command = _worker_prefix("replayer") + [
        "--input", str(Path(input_path).expanduser()),
        "--log", str(Path(log_path).expanduser()),
        "--no-verify-state" if not verify_state else "--verify-state",
    ]
    if serial:
        command += ["--serial", serial]
    if dry_run:
        command.append("--dry-run")
    return command


def build_child_environment(adb_path: str | Path | None = None) -> dict[str, str]:
    """Make a selected adb.exe discoverable by the existing helper scripts."""
    env = os.environ.copy()
    if not adb_path:
        return env
    executable = Path(adb_path).expanduser()
    if executable.is_dir():
        executable = executable / ("adb.exe" if os.name == "nt" else "adb")
    if executable.is_file():
        env["PATH"] = str(executable.parent) + os.pathsep + env.get("PATH", "")
        env["ADB_PATH"] = str(executable)
    return env


def with_run_log(command: Sequence[str], run_index: int, total_runs: int) -> list[str]:
    """Give repeated replay cycles independent log files instead of overwriting one log."""
    result = list(command)
    if total_runs <= 1 or "--log" not in result:
        return result
    index = result.index("--log")
    if index + 1 >= len(result):
        return result
    path = Path(result[index + 1])
    result[index + 1] = str(path.with_name(f"{path.stem}-run-{run_index:03d}{path.suffix}"))
    return result
