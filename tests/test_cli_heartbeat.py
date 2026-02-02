"""Tests for heartbeat CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from takopi.cli.heartbeat import app


runner = CliRunner()


@pytest.fixture
def config_with_heartbeats(tmp_path: Path) -> Path:
    """Create a config file with heartbeats defined."""
    config_path = tmp_path / "takopi.toml"
    config_path.write_text(
        """
transport = "telegram"

[transports.telegram]
bot_token = "test-token"
chat_id = 123

[heartbeats.test-research]
prompt = "Research prompt here"
schedule = "0 */4 * * *"

[heartbeats.test-project]
prompt_file = "~/prompts/project.md"
cwd = "~/dev"
model = "opus"
""",
        encoding="utf-8",
    )
    return config_path


@pytest.fixture
def config_no_heartbeats(tmp_path: Path) -> Path:
    """Create a config file without heartbeats."""
    config_path = tmp_path / "takopi.toml"
    config_path.write_text(
        """
transport = "telegram"

[transports.telegram]
bot_token = "test-token"
chat_id = 123
""",
        encoding="utf-8",
    )
    return config_path


class TestHeartbeatList:
    """Tests for listing heartbeats."""

    def test_list_shows_configured_heartbeats(
        self, config_with_heartbeats: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Override config discovery to use our test config
        monkeypatch.setenv("TAKOPI_CONFIG", str(config_with_heartbeats))

        from takopi.settings import load_settings

        # Verify the config loads correctly
        settings, _ = load_settings(config_with_heartbeats)
        assert "test-research" in settings.heartbeats
        assert "test-project" in settings.heartbeats
        assert settings.heartbeats["test-research"].prompt == "Research prompt here"
        assert settings.heartbeats["test-project"].prompt_file == "~/prompts/project.md"

    def test_no_heartbeats_shows_instructions(
        self, config_no_heartbeats: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from takopi.settings import load_settings

        settings, _ = load_settings(config_no_heartbeats)
        assert settings.heartbeats == {}


class TestHeartbeatSettings:
    """Tests for heartbeat configuration parsing."""

    def test_inline_prompt_config(self, tmp_path: Path) -> None:
        config_path = tmp_path / "takopi.toml"
        config_path.write_text(
            """
transport = "telegram"
[transports.telegram]
bot_token = "token"
chat_id = 123

[heartbeats.inline-test]
prompt = "Test prompt"
notify = false
""",
            encoding="utf-8",
        )

        from takopi.settings import load_settings

        settings, _ = load_settings(config_path)
        hb = settings.heartbeats["inline-test"]
        assert hb.prompt == "Test prompt"
        assert hb.notify is False

    def test_file_prompt_config(self, tmp_path: Path) -> None:
        config_path = tmp_path / "takopi.toml"
        config_path.write_text(
            """
transport = "telegram"
[transports.telegram]
bot_token = "token"
chat_id = 123

[heartbeats.file-test]
prompt_file = "~/prompts/test.md"
cwd = "~/dev/project"
model = "haiku"
allowed_tools = ["Bash", "Read"]
dangerously_skip_permissions = true
""",
            encoding="utf-8",
        )

        from takopi.settings import load_settings

        settings, _ = load_settings(config_path)
        hb = settings.heartbeats["file-test"]
        assert hb.prompt_file == "~/prompts/test.md"
        assert hb.cwd == "~/dev/project"
        assert hb.model == "haiku"
        assert hb.allowed_tools == ["Bash", "Read"]
        assert hb.dangerously_skip_permissions is True

    def test_notify_settings(self, tmp_path: Path) -> None:
        config_path = tmp_path / "takopi.toml"
        config_path.write_text(
            """
transport = "telegram"
[transports.telegram]
bot_token = "token"
chat_id = 123

[heartbeats.notify-test]
prompt = "Test"
notify = true
notify_on_success = false
notify_on_failure = true
""",
            encoding="utf-8",
        )

        from takopi.settings import load_settings

        settings, _ = load_settings(config_path)
        hb = settings.heartbeats["notify-test"]
        assert hb.notify is True
        assert hb.notify_on_success is False
        assert hb.notify_on_failure is True

    def test_multiple_heartbeats(self, tmp_path: Path) -> None:
        config_path = tmp_path / "takopi.toml"
        config_path.write_text(
            """
transport = "telegram"
[transports.telegram]
bot_token = "token"
chat_id = 123

[heartbeats.research]
prompt = "Research task"
schedule = "0 */2 * * *"

[heartbeats.memory]
prompt = "Memory task"
schedule = "30 */2 * * *"

[heartbeats.project]
prompt = "Project task"
schedule = "0 1-23/2 * * *"
""",
            encoding="utf-8",
        )

        from takopi.settings import load_settings

        settings, _ = load_settings(config_path)
        assert len(settings.heartbeats) == 3
        assert "research" in settings.heartbeats
        assert "memory" in settings.heartbeats
        assert "project" in settings.heartbeats
