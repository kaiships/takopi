"""Tests for heartbeat executor module."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from takopi.heartbeat.executor import (
    HeartbeatResult,
    expand_env_vars,
    load_prompt,
    run_heartbeat,
)
from takopi.heartbeat.state import HeartbeatState
from takopi.model import CompletedEvent, ResumeToken, StartedEvent
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

    def test_file_prompt_expands_tilde(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
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


class TestRunHeartbeat:
    """Tests for async run_heartbeat function."""

    @pytest.fixture
    def mock_state(self) -> HeartbeatState:
        """Create a fresh heartbeat state."""
        return HeartbeatState(name="test-heartbeat", session_id=None, runs=[])

    @pytest.fixture
    def mock_state_with_session(self) -> HeartbeatState:
        """Create a heartbeat state with existing session."""
        return HeartbeatState(
            name="test-heartbeat",
            session_id="existing-session-123",
            runs=[],
        )

    @pytest.mark.anyio
    async def test_successful_run(self, mock_state: HeartbeatState) -> None:
        """Test a successful heartbeat execution."""
        settings = HeartbeatSettings(prompt="Test prompt")

        # Mock events that runner will yield
        async def mock_run(*args, **kwargs):
            yield StartedEvent(
                engine="claude",
                resume=ResumeToken(engine="claude", value="new-session-456"),
            )
            yield CompletedEvent(
                engine="claude",
                ok=True,
                answer="Task completed!",
                resume=ResumeToken(engine="claude", value="new-session-456"),
                usage={"total_cost_usd": 0.02},
            )

        with (
            patch("takopi.heartbeat.executor.load_state", return_value=mock_state),
            patch("takopi.heartbeat.executor.save_state") as mock_save,
            patch("takopi.heartbeat.executor.ClaudeRunner") as mock_runner_class,
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            mock_runner = MagicMock()
            mock_runner.run = mock_run
            mock_runner_class.return_value = mock_runner

            result = await run_heartbeat("test-heartbeat", settings)

        assert result.ok is True
        assert result.answer == "Task completed!"
        assert result.session_id == "new-session-456"
        assert result.usage == {"total_cost_usd": 0.02}
        assert result.error is None
        assert result.duration_ms >= 0

        # Verify state was saved
        mock_save.assert_called_once()
        saved_state = mock_save.call_args[0][0]
        assert saved_state.session_id == "new-session-456"
        assert len(saved_state.runs) == 1
        assert saved_state.runs[0].ok is True

    @pytest.mark.anyio
    async def test_failed_run(self, mock_state: HeartbeatState) -> None:
        """Test a failed heartbeat execution."""
        settings = HeartbeatSettings(prompt="Test prompt")

        async def mock_run(*args, **kwargs):
            yield StartedEvent(
                engine="claude",
                resume=ResumeToken(engine="claude", value="session-789"),
            )
            yield CompletedEvent(
                engine="claude",
                ok=False,
                answer="",
                error="Model refused task",
            )

        with (
            patch("takopi.heartbeat.executor.load_state", return_value=mock_state),
            patch("takopi.heartbeat.executor.save_state") as mock_save,
            patch("takopi.heartbeat.executor.ClaudeRunner") as mock_runner_class,
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            mock_runner = MagicMock()
            mock_runner.run = mock_run
            mock_runner_class.return_value = mock_runner

            result = await run_heartbeat("test-heartbeat", settings)

        assert result.ok is False
        assert result.error == "Model refused task"
        assert result.answer == ""

        # State still saved on failure
        mock_save.assert_called_once()
        saved_state = mock_save.call_args[0][0]
        assert saved_state.runs[0].ok is False
        assert saved_state.runs[0].error == "Model refused task"

    @pytest.mark.anyio
    async def test_resume_from_existing_session(
        self, mock_state_with_session: HeartbeatState
    ) -> None:
        """Test resuming from an existing session."""
        settings = HeartbeatSettings(prompt="Continue task")

        async def mock_run(prompt, resume_token):
            # Verify resume token was passed
            assert resume_token is not None
            assert resume_token.value == "existing-session-123"
            yield CompletedEvent(
                engine="claude",
                ok=True,
                answer="Continued!",
                resume=ResumeToken(engine="claude", value="existing-session-123"),
            )

        with (
            patch(
                "takopi.heartbeat.executor.load_state",
                return_value=mock_state_with_session,
            ),
            patch("takopi.heartbeat.executor.save_state"),
            patch("takopi.heartbeat.executor.ClaudeRunner") as mock_runner_class,
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            mock_runner = MagicMock()
            mock_runner.run = mock_run
            mock_runner_class.return_value = mock_runner

            result = await run_heartbeat("test-heartbeat", settings, resume=True)

        assert result.ok is True
        assert result.answer == "Continued!"

    @pytest.mark.anyio
    async def test_no_resume_flag(
        self, mock_state_with_session: HeartbeatState
    ) -> None:
        """Test that resume=False starts a fresh session."""
        settings = HeartbeatSettings(prompt="Fresh start")

        async def mock_run(prompt, resume_token):
            # Verify no resume token when resume=False
            assert resume_token is None
            yield CompletedEvent(
                engine="claude",
                ok=True,
                answer="Fresh!",
                resume=ResumeToken(engine="claude", value="brand-new-session"),
            )

        with (
            patch(
                "takopi.heartbeat.executor.load_state",
                return_value=mock_state_with_session,
            ),
            patch("takopi.heartbeat.executor.save_state"),
            patch("takopi.heartbeat.executor.ClaudeRunner") as mock_runner_class,
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            mock_runner = MagicMock()
            mock_runner.run = mock_run
            mock_runner_class.return_value = mock_runner

            result = await run_heartbeat("test-heartbeat", settings, resume=False)

        assert result.ok is True
        assert result.session_id == "brand-new-session"

    @pytest.mark.anyio
    async def test_exception_during_run(self, mock_state: HeartbeatState) -> None:
        """Test handling of exceptions during heartbeat execution."""
        settings = HeartbeatSettings(prompt="Will fail")

        async def mock_run(*args, **kwargs):
            yield StartedEvent(
                engine="claude",
                resume=ResumeToken(engine="claude", value="session-error"),
            )
            raise RuntimeError("Connection lost")

        with (
            patch("takopi.heartbeat.executor.load_state", return_value=mock_state),
            patch("takopi.heartbeat.executor.save_state") as mock_save,
            patch("takopi.heartbeat.executor.ClaudeRunner") as mock_runner_class,
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            mock_runner = MagicMock()
            mock_runner.run = mock_run
            mock_runner_class.return_value = mock_runner

            result = await run_heartbeat("test-heartbeat", settings)

        assert result.ok is False
        assert result.error == "Connection lost"
        # Session ID should be captured from StartedEvent before error
        assert result.session_id == "session-error"

        # State should still be saved with error
        mock_save.assert_called_once()
        saved_state = mock_save.call_args[0][0]
        assert saved_state.runs[0].ok is False
        assert saved_state.runs[0].error == "Connection lost"

    @pytest.mark.anyio
    async def test_cwd_changes_during_run(
        self, mock_state: HeartbeatState, tmp_path: Path
    ) -> None:
        """Test that working directory changes and restores correctly."""
        settings = HeartbeatSettings(prompt="Test", cwd=str(tmp_path))
        original_cwd = os.getcwd()

        captured_cwd = None

        async def mock_run(*args, **kwargs):
            nonlocal captured_cwd
            captured_cwd = os.getcwd()
            yield CompletedEvent(engine="claude", ok=True, answer="Done")

        with (
            patch("takopi.heartbeat.executor.load_state", return_value=mock_state),
            patch("takopi.heartbeat.executor.save_state"),
            patch("takopi.heartbeat.executor.ClaudeRunner") as mock_runner_class,
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            mock_runner = MagicMock()
            mock_runner.run = mock_run
            mock_runner_class.return_value = mock_runner

            await run_heartbeat("test-heartbeat", settings)

        # During run, cwd should have been tmp_path
        assert captured_cwd == str(tmp_path)
        # After run, cwd should be restored
        assert os.getcwd() == original_cwd

    @pytest.mark.anyio
    async def test_cwd_missing_directory(self, mock_state: HeartbeatState) -> None:
        """Test handling of non-existent cwd."""
        settings = HeartbeatSettings(
            prompt="Test", cwd="/nonexistent/path/that/does/not/exist"
        )
        original_cwd = os.getcwd()

        async def mock_run(*args, **kwargs):
            yield CompletedEvent(engine="claude", ok=True, answer="Done")

        with (
            patch("takopi.heartbeat.executor.load_state", return_value=mock_state),
            patch("takopi.heartbeat.executor.save_state"),
            patch("takopi.heartbeat.executor.ClaudeRunner") as mock_runner_class,
            patch("shutil.which", return_value="/usr/bin/claude"),
        ):
            mock_runner = MagicMock()
            mock_runner.run = mock_run
            mock_runner_class.return_value = mock_runner

            # Should not raise, just log warning and continue
            result = await run_heartbeat("test-heartbeat", settings)

        assert result.ok is True
        # cwd should remain unchanged
        assert os.getcwd() == original_cwd

    @pytest.mark.anyio
    async def test_runner_configuration(self, mock_state: HeartbeatState) -> None:
        """Test that ClaudeRunner is configured with correct settings."""
        settings = HeartbeatSettings(
            prompt="Test",
            model="claude-sonnet-4-20250514",
            allowed_tools=["Read", "Write", "Bash"],
            dangerously_skip_permissions=True,
        )

        async def mock_run(*args, **kwargs):
            yield CompletedEvent(engine="claude", ok=True, answer="Done")

        with (
            patch("takopi.heartbeat.executor.load_state", return_value=mock_state),
            patch("takopi.heartbeat.executor.save_state"),
            patch("takopi.heartbeat.executor.ClaudeRunner") as mock_runner_class,
            patch("shutil.which", return_value="/opt/claude/bin/claude"),
        ):
            mock_runner = MagicMock()
            mock_runner.run = mock_run
            mock_runner_class.return_value = mock_runner

            await run_heartbeat("test-heartbeat", settings)

        # Verify runner was constructed with correct args
        mock_runner_class.assert_called_once_with(
            claude_cmd="/opt/claude/bin/claude",
            model="claude-sonnet-4-20250514",
            allowed_tools=["Read", "Write", "Bash"],
            dangerously_skip_permissions=True,
            session_title="test-heartbeat",
        )
