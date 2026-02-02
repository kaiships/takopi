"""Tests for config module."""

from __future__ import annotations

from pathlib import Path

import pytest

from takopi.config import (
    ConfigError,
    ProjectConfig,
    ProjectsConfig,
    dump_toml,
    ensure_table,
    load_or_init_config,
    read_config,
    write_config,
)


class TestEnsureTable:
    """Tests for ensure_table function."""

    def test_creates_new_table(self, tmp_path: Path) -> None:
        config: dict = {}
        result = ensure_table(config, "new_key", config_path=tmp_path / "test.toml")
        assert result == {}
        assert config["new_key"] == {}

    def test_returns_existing_table(self, tmp_path: Path) -> None:
        config: dict = {"existing": {"key": "value"}}
        result = ensure_table(config, "existing", config_path=tmp_path / "test.toml")
        assert result == {"key": "value"}

    def test_raises_on_non_dict(self, tmp_path: Path) -> None:
        config: dict = {"bad_key": "not a dict"}
        with pytest.raises(ConfigError, match="expected a table"):
            ensure_table(config, "bad_key", config_path=tmp_path / "test.toml")

    def test_uses_label_in_error(self, tmp_path: Path) -> None:
        config: dict = {"key": "value"}
        with pytest.raises(ConfigError, match="custom.label"):
            ensure_table(
                config, "key", config_path=tmp_path / "test.toml", label="custom.label"
            )


class TestReadConfig:
    """Tests for read_config function."""

    def test_reads_valid_toml(self, tmp_path: Path) -> None:
        config_path = tmp_path / "config.toml"
        config_path.write_text('[section]\nkey = "value"')
        result = read_config(config_path)
        assert result == {"section": {"key": "value"}}

    def test_raises_on_directory(self, tmp_path: Path) -> None:
        # tmp_path is a directory
        with pytest.raises(ConfigError, match="not a file"):
            read_config(tmp_path)

    def test_raises_on_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="Missing config"):
            read_config(tmp_path / "nonexistent.toml")

    def test_raises_on_invalid_toml(self, tmp_path: Path) -> None:
        config_path = tmp_path / "bad.toml"
        config_path.write_text("not valid = toml [")
        with pytest.raises(ConfigError, match="Malformed TOML"):
            read_config(config_path)


class TestLoadOrInitConfig:
    """Tests for load_or_init_config function."""

    def test_returns_empty_for_new_file(self, tmp_path: Path) -> None:
        config_path = tmp_path / "new.toml"
        config, path = load_or_init_config(config_path)
        assert config == {}
        assert path == config_path

    def test_raises_on_directory(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="not a file"):
            load_or_init_config(tmp_path)


class TestProjectConfig:
    """Tests for ProjectConfig dataclass."""

    def test_worktrees_root_relative(self, tmp_path: Path) -> None:
        config = ProjectConfig(
            alias="test",
            path=tmp_path,
            worktrees_dir=Path(".worktrees"),
        )
        assert config.worktrees_root == tmp_path / ".worktrees"

    def test_worktrees_root_absolute(self, tmp_path: Path) -> None:
        abs_dir = tmp_path / "abs_worktrees"
        config = ProjectConfig(
            alias="test",
            path=tmp_path,
            worktrees_dir=abs_dir,
        )
        assert config.worktrees_root == abs_dir


class TestProjectsConfig:
    """Tests for ProjectsConfig dataclass."""

    @pytest.fixture
    def config(self, tmp_path: Path) -> ProjectsConfig:
        return ProjectsConfig(
            projects={
                "proj1": ProjectConfig(
                    alias="proj1", path=tmp_path, worktrees_dir=Path(".wt")
                ),
                "proj2": ProjectConfig(
                    alias="proj2", path=tmp_path, worktrees_dir=Path(".wt")
                ),
            },
            default_project="proj1",
            chat_map={123: "proj1", 456: "proj2"},
        )

    def test_resolve_alias(self, config: ProjectsConfig) -> None:
        result = config.resolve("proj2")
        assert result is not None
        assert result.alias == "proj2"

    def test_resolve_default(self, config: ProjectsConfig) -> None:
        result = config.resolve(None)
        assert result is not None
        assert result.alias == "proj1"

    def test_resolve_no_default(self, tmp_path: Path) -> None:
        config = ProjectsConfig(projects={}, default_project=None)
        assert config.resolve(None) is None

    def test_resolve_unknown(self, config: ProjectsConfig) -> None:
        assert config.resolve("unknown") is None


class TestDumpToml:
    """Tests for dump_toml function."""

    def test_dumps_valid_config(self) -> None:
        result = dump_toml({"key": "value"})
        assert 'key = "value"' in result

    def test_raises_on_unsupported_value(self) -> None:
        with pytest.raises(ConfigError, match="Unsupported config"):
            dump_toml({"bad": object()})
