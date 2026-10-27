from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from desktop.core.runner import (
    build_capture_command,
    build_child_environment,
    build_replay_command,
    with_run_log,
)
from desktop.core.workflow import load_actions, summarize_workflow


class WorkflowTests(unittest.TestCase):
    def test_summarize_workflow_counts_supported_gestures(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "sample.json"
            path.write_text(
                json.dumps(
                    {
                        "screen": {"width": 720, "height": 1600, "rotation": 0},
                        "actions": [
                            {"gestureKind": "TAP"},
                            {"gestureKind": "SWIPE"},
                            {"gestureKind": "LONG_PRESS"},
                            {"gestureKind": "TAP"},
                            {"gestureKind": "UNKNOWN"},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            summary = summarize_workflow(path)
            self.assertEqual(summary.action_count, 5)
            self.assertEqual(summary.tap_count, 2)
            self.assertEqual(summary.swipe_count, 1)
            self.assertEqual(summary.long_press_count, 1)
            self.assertEqual(summary.display_width, 720)
            self.assertEqual(summary.display_height, 1600)
            self.assertEqual(summary.rotation, 0)

    def test_load_actions_accepts_a_top_level_list(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "list.json"
            path.write_text(json.dumps([{"gestureKind": "TAP"}]), encoding="utf-8")
            actions, metadata = load_actions(path)
            self.assertEqual(len(actions), 1)
            self.assertEqual(metadata, {})

    def test_load_actions_rejects_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.json"
            path.write_text("{invalid", encoding="utf-8")
            with self.assertRaises(ValueError):
                load_actions(path)

    def test_load_actions_rejects_non_object_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad-actions.json"
            path.write_text(json.dumps({"actions": ["not-an-object"]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_actions(path)


class RunnerTests(unittest.TestCase):
    def test_capture_command_keeps_state_capture_and_can_enable_ui_text(self) -> None:
        command = build_capture_command(
            output_path="sample.json",
            serial="device-123",
            capture_state=True,
            capture_ui_hierarchy=True,
        )
        self.assertIn("--output", command)
        self.assertIn("sample.json", command)
        self.assertIn("--serial", command)
        self.assertIn("device-123", command)
        self.assertIn("--capture-ui-hierarchy", command)
        self.assertNotIn("--no-state-capture", command)

    def test_replay_defaults_to_verification_off(self) -> None:
        command = build_replay_command(
            input_path="sample.json",
            log_path="run.jsonl",
            serial="device-123",
            verify_state=False,
            dry_run=True,
        )
        self.assertIn("--no-verify-state", command)
        self.assertIn("--dry-run", command)
        self.assertIn("--serial", command)
        self.assertIn("device-123", command)

    def test_replay_can_enable_verification(self) -> None:
        command = build_replay_command(
            input_path="sample.json",
            log_path="run.jsonl",
            verify_state=True,
            dry_run=False,
        )
        self.assertIn("--verify-state", command)
        self.assertNotIn("--no-verify-state", command)
        self.assertNotIn("--dry-run", command)

    def test_repeated_runs_get_individual_log_files(self) -> None:
        command = ["python", "replayer.py", "--log", "logs/run.jsonl"]
        updated = with_run_log(command, 2, 4)
        self.assertEqual(updated[-1], str(Path("logs/run-run-002.jsonl")))
        self.assertEqual(command[-1], "logs/run.jsonl")

    def test_child_environment_adds_selected_adb_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            adb = Path(temp_dir) / ("adb.exe" if os.name == "nt" else "adb")
            adb.write_text("placeholder", encoding="utf-8")
            env = build_child_environment(adb)
            self.assertTrue(env["PATH"].startswith(str(adb.parent)))
            self.assertEqual(env["ADB_PATH"], str(adb))


if __name__ == "__main__":
    unittest.main()
