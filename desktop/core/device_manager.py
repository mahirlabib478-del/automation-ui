from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class AndroidDevice:
    serial: str
    state: str
    details: str = ""

    @property
    def display_name(self) -> str:
        detail = self.details.strip()
        return f"{self.serial}  ·  {self.state}" + (f"  ·  {detail}" if detail else "")


def _candidate_paths(configured_path: str | os.PathLike[str] | None = None) -> Iterable[Path]:
    if configured_path:
        configured = Path(configured_path).expanduser()
        if configured.is_dir():
            yield configured / ("adb.exe" if os.name == "nt" else "adb")
        else:
            yield configured

    env_path = os.environ.get("ADB_PATH")
    if env_path:
        yield Path(env_path).expanduser()

    found = shutil.which("adb")
    if found:
        yield Path(found)

    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if android_home:
        yield Path(android_home).expanduser() / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")

    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        yield Path(local_app_data) / "Android" / "Sdk" / "platform-tools" / "adb.exe"

    root = Path(__file__).resolve().parents[2]
    yield root / "platform-tools" / ("adb.exe" if os.name == "nt" else "adb")
    yield root / "tools" / ("adb.exe" if os.name == "nt" else "adb")


def resolve_adb(configured_path: str | os.PathLike[str] | None = None) -> Path | None:
    """Return a valid adb executable path, or None if it cannot be found."""
    seen: set[str] = set()
    for candidate in _candidate_paths(configured_path):
        key = os.path.normcase(str(candidate))
        if key in seen:
            continue
        seen.add(key)
        try:
            if candidate.is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def list_devices(adb_path: str | os.PathLike[str], timeout: float = 12.0) -> list[AndroidDevice]:
    """Run adb devices -l and parse connected, unauthorized, and offline devices."""
    result = subprocess.run(
        [str(adb_path), "devices", "-l"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=True,
    )
    devices: list[AndroidDevice] = []
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.lower().startswith("list of devices attached"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        details = " ".join(parts[2:])
        devices.append(AndroidDevice(serial=serial, state=state, details=details))
    return devices
