"""Persist heartbeat state: resume tokens, run history."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.json_state import atomic_write_json

HEARTBEAT_STATE_DIR = Path.home() / ".takopi" / "heartbeats"


@dataclass(slots=True)
class HeartbeatRun:
    """Record of a single heartbeat execution."""

    started_at: str
    completed_at: str | None = None
    ok: bool = False
    duration_ms: int | None = None
    usage: dict[str, Any] | None = None
    error: str | None = None


@dataclass(slots=True)
class HeartbeatState:
    """Persistent state for a heartbeat."""

    name: str
    session_id: str | None = None
    last_run_at: str | None = None
    runs: list[HeartbeatRun] = field(default_factory=list)
    max_runs: int = 50


def load_state(name: str) -> HeartbeatState:
    """Load heartbeat state from disk."""
    path = HEARTBEAT_STATE_DIR / f"{name}.json"
    if not path.exists():
        return HeartbeatState(name=name)

    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    runs = [
        HeartbeatRun(
            started_at=r.get("started_at", ""),
            completed_at=r.get("completed_at"),
            ok=r.get("ok", False),
            duration_ms=r.get("duration_ms"),
            usage=r.get("usage"),
            error=r.get("error"),
        )
        for r in data.get("runs", [])
    ]

    return HeartbeatState(
        name=name,
        session_id=data.get("session_id"),
        last_run_at=data.get("last_run_at"),
        runs=runs,
    )


def save_state(state: HeartbeatState) -> None:
    """Save heartbeat state to disk."""
    # Trim runs to max
    if len(state.runs) > state.max_runs:
        state.runs = state.runs[-state.max_runs :]

    payload = {
        "session_id": state.session_id,
        "last_run_at": state.last_run_at,
        "runs": [
            {
                "started_at": r.started_at,
                "completed_at": r.completed_at,
                "ok": r.ok,
                "duration_ms": r.duration_ms,
                "usage": r.usage,
                "error": r.error,
            }
            for r in state.runs
        ],
    }

    path = HEARTBEAT_STATE_DIR / f"{state.name}.json"
    atomic_write_json(path, payload)
