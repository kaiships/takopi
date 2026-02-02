"""Tests for path utilities."""

from __future__ import annotations

from pathlib import Path

from takopi.utils.paths import (
    get_run_base_dir,
    relativize_command,
    relativize_path,
    reset_run_base_dir,
    set_run_base_dir,
)


# Original tests preserved
def test_relativize_command_rewrites_cwd_paths(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    base.mkdir()
    command = f'find {base}/tests -type f -name "*.py" | head -20'
    expected = 'find tests -type f -name "*.py" | head -20'
    assert relativize_command(command, base_dir=base) == expected


def test_relativize_command_rewrites_equals_paths(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    base.mkdir()
    command = f'rg -n --files -g "*.py" --path={base}/src'
    expected = 'rg -n --files -g "*.py" --path=src'
    assert relativize_command(command, base_dir=base) == expected


def test_relativize_path_ignores_sibling_prefix(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    base.mkdir()
    value = str(tmp_path / "repo2" / "file.txt")
    assert relativize_path(value, base_dir=base) == value


def test_relativize_path_inside_base(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    base.mkdir()
    value = str(base / "src" / "app.py")
    assert relativize_path(value, base_dir=base) == "src/app.py"


def test_relativize_path_uses_run_base_dir(tmp_path: Path) -> None:
    base = tmp_path / "repo"
    base.mkdir()
    token = set_run_base_dir(base)
    try:
        value = str(base / "src" / "app.py")
        assert relativize_path(value) == "src/app.py"
    finally:
        reset_run_base_dir(token)


# New tests for additional coverage
class TestRunBaseDir:
    """Tests for run base dir context variable."""

    def test_default_is_none(self) -> None:
        # Fresh context should return None (unless another test set it)
        token = set_run_base_dir(None)
        try:
            assert get_run_base_dir() is None
        finally:
            reset_run_base_dir(token)

    def test_set_and_get(self, tmp_path: Path) -> None:
        token = set_run_base_dir(tmp_path)
        try:
            assert get_run_base_dir() == tmp_path
        finally:
            reset_run_base_dir(token)

    def test_reset_restores_previous(self, tmp_path: Path) -> None:
        token1 = set_run_base_dir(tmp_path)
        token2 = set_run_base_dir(tmp_path / "nested")
        assert get_run_base_dir() == tmp_path / "nested"
        reset_run_base_dir(token2)
        assert get_run_base_dir() == tmp_path
        reset_run_base_dir(token1)


class TestRelativizePath:
    """Additional tests for relativize_path function."""

    def test_empty_value_returns_empty(self) -> None:
        assert relativize_path("") == ""

    def test_exact_match_returns_dot(self, tmp_path: Path) -> None:
        assert relativize_path(str(tmp_path), base_dir=tmp_path) == "."


class TestRelativizeCommand:
    """Additional tests for relativize_command function."""

    def test_no_change_without_prefix(self, tmp_path: Path) -> None:
        cmd = "python script.py"
        result = relativize_command(cmd, base_dir=tmp_path)
        assert result == "python script.py"
