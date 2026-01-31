from pathlib import Path

import pytest

from takopi.config import ConfigError
from takopi.settings import HeartbeatSettings, TakopiSettings, validate_settings_data


def test_settings_strips_and_expands_transport_config(tmp_path: Path) -> None:
    settings = TakopiSettings.model_validate(
        {
            "transport": " telegram ",
            "plugins": {"enabled": [" foo "]},
            "transports": {"telegram": {"bot_token": "  token  ", "chat_id": 123}},
        }
    )

    assert settings.transport == "telegram"
    assert settings.plugins.enabled == ["foo"]
    assert settings.transports.telegram.bot_token == "token"


def test_settings_rejects_bool_chat_id(tmp_path: Path) -> None:
    data = {
        "transport": "telegram",
        "transports": {"telegram": {"bot_token": "token", "chat_id": True}},
    }

    with pytest.raises(ConfigError, match="chat_id"):
        validate_settings_data(data, config_path=tmp_path / "takopi.toml")


class TestHeartbeatSettings:
    """Tests for HeartbeatSettings model."""

    def test_inline_prompt(self) -> None:
        hb = HeartbeatSettings(prompt="Hello world")
        assert hb.prompt == "Hello world"
        assert hb.prompt_file is None

    def test_file_prompt(self) -> None:
        hb = HeartbeatSettings(prompt_file="~/prompts/test.md")
        assert hb.prompt_file == "~/prompts/test.md"
        assert hb.prompt is None

    def test_requires_prompt_source(self) -> None:
        with pytest.raises(ValueError, match="Either 'prompt' or 'prompt_file'"):
            HeartbeatSettings()

    def test_rejects_both_prompt_sources(self) -> None:
        with pytest.raises(ValueError, match="Cannot specify both"):
            HeartbeatSettings(prompt="inline", prompt_file="~/file.md")

    def test_defaults(self) -> None:
        hb = HeartbeatSettings(prompt="test")
        assert hb.cwd is None
        assert hb.model is None
        assert hb.allowed_tools is None
        assert hb.dangerously_skip_permissions is False
        assert hb.notify is True
        assert hb.notify_on_success is True
        assert hb.notify_on_failure is True
        assert hb.schedule is None

    def test_full_config(self) -> None:
        hb = HeartbeatSettings(
            prompt="test",
            cwd="~/dev",
            model="opus",
            allowed_tools=["Bash", "Read"],
            dangerously_skip_permissions=True,
            notify=False,
            schedule="0 */4 * * *",
        )
        assert hb.cwd == "~/dev"
        assert hb.model == "opus"
        assert hb.allowed_tools == ["Bash", "Read"]
        assert hb.dangerously_skip_permissions is True
        assert hb.notify is False
        assert hb.schedule == "0 */4 * * *"

    def test_strips_whitespace(self) -> None:
        hb = HeartbeatSettings(prompt="  test  ")
        assert hb.prompt == "test"

    def test_rejects_empty_prompt(self) -> None:
        with pytest.raises(ValueError):
            HeartbeatSettings(prompt="   ")

    def test_rejects_extra_fields(self) -> None:
        with pytest.raises(ValueError, match="extra"):
            HeartbeatSettings(prompt="test", unknown_field="value")


class TestHeartbeatsInSettings:
    """Tests for heartbeats in TakopiSettings."""

    def test_empty_heartbeats(self) -> None:
        settings = TakopiSettings.model_validate(
            {
                "transport": "telegram",
                "transports": {"telegram": {"bot_token": "token", "chat_id": 123}},
            }
        )
        assert settings.heartbeats == {}

    def test_single_heartbeat(self) -> None:
        settings = TakopiSettings.model_validate(
            {
                "transport": "telegram",
                "transports": {"telegram": {"bot_token": "token", "chat_id": 123}},
                "heartbeats": {
                    "research": {"prompt": "Do research"},
                },
            }
        )
        assert "research" in settings.heartbeats
        assert settings.heartbeats["research"].prompt == "Do research"

    def test_multiple_heartbeats(self) -> None:
        settings = TakopiSettings.model_validate(
            {
                "transport": "telegram",
                "transports": {"telegram": {"bot_token": "token", "chat_id": 123}},
                "heartbeats": {
                    "research": {"prompt": "Research task"},
                    "trading": {"prompt_file": "~/trading.md", "model": "opus"},
                },
            }
        )
        assert len(settings.heartbeats) == 2
        assert settings.heartbeats["research"].prompt == "Research task"
        assert settings.heartbeats["trading"].prompt_file == "~/trading.md"
        assert settings.heartbeats["trading"].model == "opus"
