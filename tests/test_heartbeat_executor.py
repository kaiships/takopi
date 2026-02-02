"""Tests for heartbeat executor module."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from takopi.heartbeat.executor import (
    HeartbeatResult,
    expand_env_vars,
    load_prompt,
)
from takopi.settings import HeartbeatSettings


class TestExpandEnvVars:
    """Tests for expand_env_vars function."""

    def test_no_vars(self) -> None:
        text = "Hello, world!"
        assert expand_env_vars(text) == "Hello, world!"

    def test_today_builtin(self) -> None:
        text = "Date: ${TODAY}"
        result = expand_env_vars(text)
        # Should be YYYY-MM-DD format
        assert result.startswith("Date: ")
        date_part = result.replace("Date: ", "")
        # Verify it's a valid date
        datetime.strptime(date_part, "%Y-%m-%d")

    def test_now_builtin(self) -> None:
        text = "Time: ${NOW}"
        result = expand_env_vars(text)
        # Should be HH:MM format
        assert result.startswith("Time: ")
        time_part = result.replace("Time: ", "")
        datetime.strptime(time_part, "%H:%M")

    def test_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR", "test_value")
        text = "Value: ${TEST_VAR}"
        assert expand_env_vars(text) == "Value: test_value"

    def test_missing_env_var_unchanged(self) -> None:
        text = "Value: ${NONEXISTENT_VAR_12345}"
        assert expand_env_vars(text) == "Value: ${NONEXISTENT_VAR_12345}"

    def test_multiple_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("NAME", "Kai")
        text = "Hello ${NAME}! Today is ${TODAY}."
        result = expand_env_vars(text)
        assert "Hello Kai!" in result
        assert "Today is " in result
        # TODAY should be expanded
        assert "${TODAY}" not in result

    def test_builtin_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Even if TODAY is set as env var, builtin should be used
        monkeypatch.setenv("TODAY", "WRONG")
        text = "${TODAY}"
        result = expand_env_vars(text)
        assert result != "WRONG"
        # Should be a date
        datetime.strptime(result, "%Y-%m-%d")


class TestLoadPrompt:
    """Tests for load_prompt function."""

    def test_inline_prompt(self) -> None:
        settings = HeartbeatSettings(prompt="Hello, world!")
        assert load_prompt(settings) == "Hello, world!"

    def test_inline_prompt_with_vars(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GREETING", "Hello")
        settings = HeartbeatSettings(prompt="${GREETING}, world!")
        assert load_prompt(settings) == "Hello, world!"

    def test_file_prompt(self, tmp_path: Path) -> None:
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("This is a test prompt.")
        settings = HeartbeatSettings(prompt_file=str(prompt_file))
        assert load_prompt(settings) == "This is a test prompt."

    def test_file_prompt_with_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NAME", "Kai")
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Hello, ${NAME}!")
        settings = HeartbeatSettings(prompt_file=str(prompt_file))
        assert load_prompt(settings) == "Hello, Kai!"

    def test_file_prompt_not_found(self) -> None:
        settings = HeartbeatSettings(prompt_file="/nonexistent/path/prompt.md")
        with pytest.raises(FileNotFoundError, match="Prompt file not found"):
            load_prompt(settings)

    def test_file_prompt_expands_tilde(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Create a temp file and reference it with ~
        prompt_file = tmp_path / "prompt.md"
        prompt_file.write_text("Tilde test")
        # Mock expanduser to return our temp path
        with patch.object(Path, "expanduser", return_value=prompt_file):
            settings = HeartbeatSettings(prompt_file="~/prompt.md")
            assert load_prompt(settings) == "Tilde test"


class TestHeartbeatResult:
    """Tests for HeartbeatResult dataclass."""

    def test_success_result(self) -> None:
        result = HeartbeatResult(
            ok=True,
            answer="Task completed successfully",
            session_id="session-123",
            duration_ms=5000,
            usage={"total_cost_usd": 0.05},
            error=None,
        )
        assert result.ok is True
        assert result.answer == "Task completed successfully"
        assert result.session_id == "session-123"
        assert result.duration_ms == 5000
        assert result.usage == {"total_cost_usd": 0.05}
        assert result.error is None

    def test_failure_result(self) -> None:
        result = HeartbeatResult(
            ok=False,
            answer="",
            session_id=None,
            duration_ms=1000,
            usage=None,
            error="Connection timeout",
        )
        assert result.ok is False
        assert result.answer == ""
        assert result.session_id is None
        assert result.error == "Connection timeout"

    def test_partial_result(self) -> None:
        result = HeartbeatResult(
            ok=False,
            answer="Partial output...",
            session_id="session-456",
            duration_ms=30000,
            usage={"total_cost_usd": 0.10},
            error="Interrupted",
        )
        # Can have both answer and error if interrupted mid-execution
        assert result.ok is False
        assert result.answer == "Partial output..."
        assert result.error == "Interrupted"
