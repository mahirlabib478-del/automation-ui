from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class WorkflowSummary:
    path: Path
    action_count: int
    tap_count: int
    swipe_count: int
    long_press_count: int
    display_width: int | None = None
    display_height: int | None = None
    rotation: int | None = None


def load_actions(path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    workflow_path = Path(path).expanduser()
    if not workflow_path.is_file():
        raise FileNotFoundError(f"Workflow file not found: {workflow_path}")
    try:
        payload = json.loads(workflow_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read workflow JSON: {exc}") from exc

    if isinstance(payload, list):
        actions = payload
        metadata: dict[str, Any] = {}
    elif isinstance(payload, dict):
        actions = payload.get("actions", [])
        metadata = payload
    else:
        raise ValueError("Workflow JSON must be an object containing actions or a list of actions.")

    if not isinstance(actions, list):
        raise ValueError("Workflow JSON field 'actions' must be a list.")
    if not all(isinstance(action, dict) for action in actions):
        raise ValueError("Every workflow action must be a JSON object.")
    return actions, metadata


def summarize_workflow(path: str | Path) -> WorkflowSummary:
    workflow_path = Path(path).expanduser()
    actions, payload = load_actions(workflow_path)
    counts = {"TAP": 0, "SWIPE": 0, "LONG_PRESS": 0}
    for action in actions:
        kind = str(action.get("gestureKind", action.get("type", ""))).upper()
        if kind in counts:
            counts[kind] += 1

    screen = payload.get("screen", {}) if isinstance(payload, dict) else {}
    if not isinstance(screen, dict):
        screen = {}
    return WorkflowSummary(
        path=workflow_path.resolve(),
        action_count=len(actions),
        tap_count=counts["TAP"],
        swipe_count=counts["SWIPE"],
        long_press_count=counts["LONG_PRESS"],
        display_width=_optional_int(screen.get("width")),
        display_height=_optional_int(screen.get("height")),
        rotation=_optional_int(screen.get("rotation")),
    )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def list_workflows(directory: str | Path) -> list[Path]:
    folder = Path(directory)
    if not folder.exists():
        return []
    return sorted(
        (path for path in folder.glob("*.json") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
