from __future__ import annotations

import os
import re
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Sequence

from PySide6.QtCore import QThread, Signal

from desktop.core.runner import with_run_log


class CommandWorker(QThread):
    """Run one ADB helper, or repeat a replay workflow, without blocking the UI."""

    output = Signal(str)
    run_progress = Signal(int, int)
    action_progress = Signal(int, int, int)
    operation_finished = Signal(bool, str)

    def __init__(
        self,
        command: Sequence[str],
        working_dir: str | Path,
        env: dict[str, str] | None = None,
        repeat_count: int = 1,
        delay_between_runs: float = 0.0,
        operation_name: str = "operation",
    ) -> None:
        super().__init__()
        self.command = list(command)
        self.working_dir = str(working_dir)
        self.env = env
        self.repeat_count = max(1, int(repeat_count))
        self.delay_between_runs = max(0.0, float(delay_between_runs))
        self.operation_name = operation_name
        self._stop_event = threading.Event()
        self._process: subprocess.Popen[str] | None = None
        self._process_lock = threading.Lock()

    def stop(self) -> None:
        self._stop_event.set()
        with self._process_lock:
            process = self._process
        if process is not None and process.poll() is None:
            threading.Thread(
                target=self._terminate_process_tree,
                args=(process,),
                name="adb-flow-stop-process",
                daemon=True,
            ).start()

    def _start_process(self, command: list[str]) -> subprocess.Popen[str]:
        kwargs: dict[str, object] = {
            "cwd": self.working_dir,
            "env": self.env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "bufsize": 1,
        }
        if os.name == "nt":
            kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                | getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            )
            startup_info = subprocess.STARTUPINFO()
            startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup_info.wShowWindow = subprocess.SW_HIDE
            kwargs["startupinfo"] = startup_info
        else:
            kwargs["start_new_session"] = True
        return subprocess.Popen(command, **kwargs)  # type: ignore[arg-type]

    @staticmethod
    def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
        if process.poll() is not None:
            return
        if os.name == "nt":
            try:
                process.send_signal(signal.CTRL_BREAK_EVENT)
            except (OSError, ValueError, AttributeError):
                pass
            deadline = time.monotonic() + 2.0
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.08)
            if process.poll() is None:
                try:
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        check=False,
                    )
                except (OSError, subprocess.SubprocessError):
                    pass
        else:
            try:
                os.killpg(process.pid, signal.SIGINT)
            except (OSError, ProcessLookupError):
                pass
            deadline = time.monotonic() + 1.5
            while process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.08)
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    try:
                        process.kill()
                    except OSError:
                        pass

    def run(self) -> None:
        stopped = False
        failure = ""
        completed_runs = 0
        for run_index in range(1, self.repeat_count + 1):
            if self._stop_event.is_set():
                stopped = True
                break

            command = with_run_log(self.command, run_index, self.repeat_count)
            self.run_progress.emit(run_index, self.repeat_count)
            if self.repeat_count > 1:
                self.output.emit(f"--- {self.operation_name.title()} run {run_index}/{self.repeat_count} ---")

            try:
                process = self._start_process(command)
                with self._process_lock:
                    self._process = process
                if self._stop_event.is_set():
                    threading.Thread(
                        target=self._terminate_process_tree,
                        args=(process,),
                        name="adb-flow-stop-process",
                        daemon=True,
                    ).start()

                if process.stdout is not None:
                    for raw_line in process.stdout:
                        line = raw_line.rstrip()
                        if not line:
                            continue
                        self.output.emit(line)
                        match = re.search(r"\[(\d+)/(\d+)\]", line)
                        if match:
                            self.action_progress.emit(
                                run_index, int(match.group(1)), int(match.group(2))
                            )
                return_code = process.wait()
            except (OSError, subprocess.SubprocessError) as exc:
                failure = f"Could not start {self.operation_name}: {exc}"
                self.output.emit(f"ERROR: {failure}")
                break
            finally:
                with self._process_lock:
                    self._process = None

            if self._stop_event.is_set():
                stopped = True
                break
            if return_code != 0:
                failure = f"{self.operation_name.title()} exited with code {return_code}."
                break

            completed_runs += 1
            if run_index < self.repeat_count and self.delay_between_runs > 0:
                self.output.emit(
                    f"Waiting {self.delay_between_runs:g} second(s) before the next run..."
                )
                if self._stop_event.wait(self.delay_between_runs):
                    stopped = True
                    break

        if stopped or self._stop_event.is_set():
            self.operation_finished.emit(False, f"Stopped by user. Completed {completed_runs} run(s).")
        elif failure:
            self.operation_finished.emit(False, failure)
        else:
            self.operation_finished.emit(
                True, f"Completed {completed_runs} run(s) successfully."
            )
