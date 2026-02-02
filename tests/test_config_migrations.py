"""Tests for config migrations module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from takopi.config import ConfigError
from takopi.config_migrations import (
    _ensure_subtable,
    _migrate_legacy_telegram,
    _migrate_topics_scope,
    migrate_config,
    migrate_config_file,
)


class TestEnsureSubtable:
    """Tests for _ensure_subtable helper."""

    def test_returns_none_when_missing(self, tmp_path: Path) -> None:
        parent: dict = {}
        result = _ensure_subtable(
            parent, "key", config_path=tmp_path / "config.toml", label="test.key"
        )
        assert result is None

    def test_returns_dict_when_present(self, tmp_path: Path) -> None:
        parent: dict = {"key": {"nested": "value"}}
        result = _ensure_subtable(
            parent, "key", config_path=tmp_path / "config.toml", label="test.key"
        )
        assert result == {"nested": "value"}

    def test_raises_when_not_dict(self, tmp_path: Path) -> None:
        parent: dict = {"key": "not a dict"}
        with pytest.raises(ConfigError, match="expected a table"):
            _ensure_subtable(
                parent, "key", config_path=tmp_path / "config.toml", label="test.key"
            )


class TestMigrateLegacyTelegram:
    """Tests for _migrate_legacy_telegram."""

    def test_no_legacy_keys_returns_false(self, tmp_path: Path) -> None:
        config: dict = {"transport": "telegram"}
        result = _migrate_legacy_telegram(config, config_path=tmp_path / "config.toml")
        assert result is False

    def test_migrates_bot_token(self, tmp_path: Path) -> None:
        config: dict = {"bot_token": "123:ABC"}
        result = _migrate_legacy_telegram(config, config_path=tmp_path / "config.toml")
        assert result is True
        assert "bot_token" not in config
        assert config["transports"]["telegram"]["bot_token"] == "123:ABC"
        assert config["transport"] == "telegram"

    def test_migrates_chat_id(self, tmp_path: Path) -> None:
        config: dict = {"chat_id": 12345}
        result = _migrate_legacy_telegram(config, config_path=tmp_path / "config.toml")
        assert result is True
        assert "chat_id" not in config
        assert config["transports"]["telegram"]["chat_id"] == 12345

    def test_preserves_existing_telegram_config(self, tmp_path: Path) -> None:
        config: dict = {
            "bot_token": "legacy-token",
            "transports": {"telegram": {"bot_token": "existing-token"}},
        }
        result = _migrate_legacy_telegram(config, config_path=tmp_path / "config.toml")
        assert result is True
        # Existing token should be preserved, legacy removed
        assert config["transports"]["telegram"]["bot_token"] == "existing-token"
        assert "bot_token" not in config


class TestMigrateTopicsScope:
    """Tests for _migrate_topics_scope."""

    def test_no_transports_returns_false(self, tmp_path: Path) -> None:
        config: dict = {}
        result = _migrate_topics_scope(config, config_path=tmp_path / "config.toml")
        assert result is False

    def test_no_telegram_returns_false(self, tmp_path: Path) -> None:
        config: dict = {"transports": {}}
        result = _migrate_topics_scope(config, config_path=tmp_path / "config.toml")
        assert result is False

    def test_no_topics_returns_false(self, tmp_path: Path) -> None:
        config: dict = {"transports": {"telegram": {}}}
        result = _migrate_topics_scope(config, config_path=tmp_path / "config.toml")
        assert result is False

    def test_no_mode_returns_false(self, tmp_path: Path) -> None:
        config: dict = {"transports": {"telegram": {"topics": {}}}}
        result = _migrate_topics_scope(config, config_path=tmp_path / "config.toml")
        assert result is False

    def test_already_has_scope_removes_mode(self, tmp_path: Path) -> None:
        config: dict = {
            "transports": {
                "telegram": {"topics": {"mode": "multi_project_chat", "scope": "main"}}
            }
        }
        result = _migrate_topics_scope(config, config_path=tmp_path / "config.toml")
        assert result is True
        assert "mode" not in config["transports"]["telegram"]["topics"]
        assert config["transports"]["telegram"]["topics"]["scope"] == "main"

    def test_migrates_multi_project_chat_to_main(self, tmp_path: Path) -> None:
        config: dict = {
            "transports": {"telegram": {"topics": {"mode": "multi_project_chat"}}}
        }
        result = _migrate_topics_scope(config, config_path=tmp_path / "config.toml")
        assert result is True
        assert config["transports"]["telegram"]["topics"]["scope"] == "main"
        assert "mode" not in config["transports"]["telegram"]["topics"]

    def test_migrates_per_project_chat_to_projects(self, tmp_path: Path) -> None:
        config: dict = {
            "transports": {"telegram": {"topics": {"mode": "per_project_chat"}}}
        }
        result = _migrate_topics_scope(config, config_path=tmp_path / "config.toml")
        assert result is True
        assert config["transports"]["telegram"]["topics"]["scope"] == "projects"
        assert "mode" not in config["transports"]["telegram"]["topics"]

    def test_invalid_mode_type_raises(self, tmp_path: Path) -> None:
        config: dict = {"transports": {"telegram": {"topics": {"mode": 123}}}}
        with pytest.raises(ConfigError, match="expected a string"):
            _migrate_topics_scope(config, config_path=tmp_path / "config.toml")

    def test_invalid_mode_value_raises(self, tmp_path: Path) -> None:
        config: dict = {"transports": {"telegram": {"topics": {"mode": "unknown_mode"}}}}
        with pytest.raises(ConfigError, match="expected 'multi_project_chat'"):
            _migrate_topics_scope(config, config_path=tmp_path / "config.toml")


class TestMigrateConfig:
    """Tests for migrate_config function."""

    def test_no_migrations_needed(self, tmp_path: Path) -> None:
        config: dict = {}
        applied = migrate_config(config, config_path=tmp_path / "config.toml")
        assert applied == []

    def test_applies_legacy_telegram(self, tmp_path: Path) -> None:
        config: dict = {"bot_token": "123:ABC"}
        applied = migrate_config(config, config_path=tmp_path / "config.toml")
        assert "legacy-telegram" in applied

    def test_applies_topics_scope(self, tmp_path: Path) -> None:
        config: dict = {
            "transports": {"telegram": {"topics": {"mode": "multi_project_chat"}}}
        }
        applied = migrate_config(config, config_path=tmp_path / "config.toml")
        assert "topics-scope" in applied

    def test_applies_both_migrations(self, tmp_path: Path) -> None:
        config: dict = {
            "bot_token": "123:ABC",
            "transports": {"telegram": {"topics": {"mode": "per_project_chat"}}},
        }
        applied = migrate_config(config, config_path=tmp_path / "config.toml")
        assert "legacy-telegram" in applied
        assert "topics-scope" in applied


class TestMigrateConfigFile:
    """Tests for migrate_config_file function."""

    def test_no_migrations_does_not_write(self, tmp_path: Path) -> None:
        config_path = tmp_path / "takopi.toml"
        config_path.write_text('[transports.telegram]\nbot_token = "x"')

        with patch("takopi.config_migrations.write_config") as mock_write:
            applied = migrate_config_file(config_path)

        assert applied == []
        mock_write.assert_not_called()

    def test_migrations_applied_and_written(self, tmp_path: Path) -> None:
        config_path = tmp_path / "takopi.toml"
        config_path.write_text('bot_token = "123:ABC"')

        with patch("takopi.config_migrations.write_config") as mock_write:
            applied = migrate_config_file(config_path)

        assert "legacy-telegram" in applied
        mock_write.assert_called_once()
