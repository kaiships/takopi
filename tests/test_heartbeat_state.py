"""Tests for heartbeat state persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from takopi.heartbeat.state import (
    HEARTBEAT_STATE_DIR,
    HeartbeatRun,
    HeartbeatState,
    load_state,
    save_state,
)


@pytest.fixture
def temp_heartbeat_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Override heartbeat state directory to temp path."""
    test_dir = tmp_path / "heartbeats"
    test_dir.mkdir()
    monkeypatch.setattr("takopi.heartbeat.state.HEARTBEAT_STATE_DIR", test_dir)
    return test_dir


class TestHeartbeatRun:
    """Tests for HeartbeatRun dataclass."""

    def test_defaults(self) -> None:
        run = HeartbeatRun(started_at="2026-02-01T12:00:00Z")
        assert run.started_at == "2026-02-01T12:00:00Z"
        assert run.completed_at is None
        assert run.ok is False
        assert run.duration_ms is None
        assert run.usage is None
        assert run.error is None

    def test_full_fields(self) -> None:
        run = HeartbeatRun(
            started_at="2026-02-01T12:00:00Z",
            completed_at="2026-02-01T12:01:00Z",
            ok=True,
            duration_ms=60000,
            usage={"total_cost_usd": 0.05},
            error=None,
        )
        assert run.ok is True
        assert run.duration_ms == 60000
        assert run.usage == {"total_cost_usd": 0.05}


class TestHeartbeatState:
    """Tests for HeartbeatState dataclass."""

    def test_defaults(self) -> None:
        state = HeartbeatState(name="test-heartbeat")
        assert state.name == "test-heartbeat"
        assert state.session_id is None
        assert state.last_run_at is None
        assert state.runs == []
        assert state.max_runs == 50

    def test_with_runs(self) -> None:
        runs = [
            HeartbeatRun(started_at="2026-02-01T12:00:00Z", ok=True),
            HeartbeatRun(started_at="2026-02-01T14:00:00Z", ok=False, error="timeout"),
        ]
        state = HeartbeatState(name="test", runs=runs)
        assert len(state.runs) == 2
        assert state.runs[0].ok is True
        assert state.runs[1].error == "timeout"


class TestLoadState:
    """Tests for load_state function."""

    def test_returns_empty_state_when_no_file(self, temp_heartbeat_dir: Path) -> None:
        state = load_state("nonexistent")
        assert state.name == "nonexistent"
        assert state.session_id is None
        assert state.runs == []

    def test_loads_existing_state(self, temp_heartbeat_dir: Path) -> None:
        # Write a state file
        state_file = temp_heartbeat_dir / "test-hb.json"
        state_file.write_text(
            json.dumps(
                {
                    "session_id": "abc123",
                    "last_run_at": "2026-02-01T12:00:00Z",
                    "runs": [
                        {
                            "started_at": "2026-02-01T11:00:00Z",
                            "completed_at": "2026-02-01T11:05:00Z",
                            "ok": True,
                            "duration_ms": 300000,
                            "usage": {"total_cost_usd": 0.10},
                            "error": None,
                        }
                    ],
                }
            )
        )

        state = load_state("test-hb")
        assert state.name == "test-hb"
        assert state.session_id == "abc123"
        assert state.last_run_at == "2026-02-01T12:00:00Z"
        assert len(state.runs) == 1
        assert state.runs[0].ok is True
        assert state.runs[0].duration_ms == 300000


class TestSaveState:
    """Tests for save_state function."""

    def test_saves_state(self, temp_heartbeat_dir: Path) -> None:
        state = HeartbeatState(
            name="save-test",
            session_id="xyz789",
            last_run_at="2026-02-01T15:00:00Z",
            runs=[HeartbeatRun(started_at="2026-02-01T15:00:00Z", ok=True)],
        )
        save_state(state)

        state_file = temp_heartbeat_dir / "save-test.json"
        assert state_file.exists()

        data = json.loads(state_file.read_text())
        assert data["session_id"] == "xyz789"
        assert data["last_run_at"] == "2026-02-01T15:00:00Z"
        assert len(data["runs"]) == 1

    def test_trims_runs_to_max(self, temp_heartbeat_dir: Path) -> None:
        # Create state with more runs than max
        runs = [HeartbeatRun(started_at=f"2026-02-01T{i:02d}:00:00Z") for i in range(60)]
        state = HeartbeatState(name="trim-test", runs=runs, max_runs=50)
        save_state(state)

        # Reload and verify trimmed
        loaded = load_state("trim-test")
        assert len(loaded.runs) == 50
        # Should keep the most recent (last 50)
        assert loaded.runs[0].started_at == "2026-02-01T10:00:00Z"
        assert loaded.runs[-1].started_at == "2026-02-01T59:00:00Z"

    def test_round_trip(self, temp_heartbeat_dir: Path) -> None:
        original = HeartbeatState(
            name="round-trip",
            session_id="session-123",
            last_run_at="2026-02-01T18:00:00Z",
            runs=[
                HeartbeatRun(
                    started_at="2026-02-01T18:00:00Z",
                    completed_at="2026-02-01T18:02:00Z",
                    ok=True,
                    duration_ms=120000,
                    usage={"input_tokens": 1000, "output_tokens": 500},
                ),
            ],
        )
        save_state(original)
        loaded = load_state("round-trip")

        assert loaded.name == original.name
        assert loaded.session_id == original.session_id
        assert loaded.last_run_at == original.last_run_at
        assert len(loaded.runs) == 1
        assert loaded.runs[0].started_at == original.runs[0].started_at
        assert loaded.runs[0].usage == original.runs[0].usage
