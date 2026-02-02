"""Tests for worktree management."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from takopi.config import ProjectConfig, ProjectsConfig
from takopi.context import RunContext
from takopi.worktrees import (
    WorktreeError,
    _ensure_within_root,
    _matches_project_branch,
    _sanitize_branch,
    ensure_worktree,
    resolve_run_cwd,
)


class TestSanitizeBranch:
    """Tests for _sanitize_branch function."""

    def test_valid_branch(self) -> None:
        assert _sanitize_branch("feature/test") == "feature/test"
        assert _sanitize_branch("main") == "main"
        assert _sanitize_branch("  main  ") == "main"

    def test_empty_branch_raises(self) -> None:
        with pytest.raises(WorktreeError, match="cannot be empty"):
            _sanitize_branch("")

    def test_whitespace_only_raises(self) -> None:
        with pytest.raises(WorktreeError, match="cannot be empty"):
            _sanitize_branch("   ")

    def test_starts_with_slash_raises(self) -> None:
        with pytest.raises(WorktreeError, match="cannot start with"):
            _sanitize_branch("/branch")

    def test_dotdot_raises(self) -> None:
        with pytest.raises(WorktreeError, match="cannot contain"):
            _sanitize_branch("../escape")

    def test_nested_dotdot_raises(self) -> None:
        with pytest.raises(WorktreeError, match="cannot contain"):
            _sanitize_branch("feature/../escape")


class TestEnsureWithinRoot:
    """Tests for _ensure_within_root function."""

    def test_valid_path(self, tmp_path: Path) -> None:
        root = tmp_path / "worktrees"
        path = root / "feature-branch"
        # Should not raise
        _ensure_within_root(root, path)

    def test_escape_raises(self, tmp_path: Path) -> None:
        root = tmp_path / "worktrees"
        escape_path = tmp_path / "outside"
        with pytest.raises(WorktreeError, match="escapes the worktrees directory"):
            _ensure_within_root(root, escape_path)


class TestMatchesProjectBranch:
    """Tests for _matches_project_branch function."""

    def test_matches(self, tmp_path: Path) -> None:
        with patch("takopi.worktrees.git_stdout", return_value="main"):
            assert _matches_project_branch(tmp_path, "main") is True

    def test_does_not_match(self, tmp_path: Path) -> None:
        with patch("takopi.worktrees.git_stdout", return_value="develop"):
            assert _matches_project_branch(tmp_path, "main") is False

    def test_no_current_branch(self, tmp_path: Path) -> None:
        with patch("takopi.worktrees.git_stdout", return_value=None):
            assert _matches_project_branch(tmp_path, "main") is False


class TestResolveRunCwd:
    """Tests for resolve_run_cwd function."""

    @pytest.fixture
    def projects_config(self, tmp_path: Path) -> ProjectsConfig:
        project_path = tmp_path / "myproject"
        project_path.mkdir()
        return ProjectsConfig(
            projects={
                "myproject": ProjectConfig(
                    alias="myproject",
                    path=project_path,
                    worktrees_dir=Path(".worktrees"),
                )
            }
        )

    def test_none_context(self, projects_config: ProjectsConfig) -> None:
        assert resolve_run_cwd(None, projects=projects_config) is None

    def test_no_project(self, projects_config: ProjectsConfig) -> None:
        context = RunContext(project=None, branch=None)
        assert resolve_run_cwd(context, projects=projects_config) is None

    def test_unknown_project(self, projects_config: ProjectsConfig) -> None:
        context = RunContext(project="unknown", branch=None)
        with pytest.raises(WorktreeError, match="unknown project"):
            resolve_run_cwd(context, projects=projects_config)

    def test_no_branch(self, projects_config: ProjectsConfig) -> None:
        context = RunContext(project="myproject", branch=None)
        result = resolve_run_cwd(context, projects=projects_config)
        assert result == projects_config.projects["myproject"].path

    def test_current_branch_matches(
        self, projects_config: ProjectsConfig, tmp_path: Path
    ) -> None:
        context = RunContext(project="myproject", branch="main")
        with patch("takopi.worktrees._matches_project_branch", return_value=True):
            result = resolve_run_cwd(context, projects=projects_config)
        assert result == projects_config.projects["myproject"].path


class TestEnsureWorktree:
    """Tests for ensure_worktree function."""

    @pytest.fixture
    def project(self, tmp_path: Path) -> ProjectConfig:
        project_path = tmp_path / "project"
        project_path.mkdir()
        return ProjectConfig(
            alias="test",
            path=project_path,
            worktrees_dir=Path(".worktrees"),
        )

    def test_project_path_not_found(self, tmp_path: Path) -> None:
        project = ProjectConfig(
            alias="test",
            path=tmp_path / "nonexistent",
            worktrees_dir=Path(".worktrees"),
        )
        with pytest.raises(WorktreeError, match="not found"):
            ensure_worktree(project, "feature")

    def test_worktree_already_exists(
        self, project: ProjectConfig, tmp_path: Path
    ) -> None:
        worktree_path = project.worktrees_root / "feature"
        worktree_path.mkdir(parents=True)
        with patch("takopi.worktrees.git_is_worktree", return_value=True):
            result = ensure_worktree(project, "feature")
        assert result == worktree_path

    def test_path_exists_but_not_worktree(
        self, project: ProjectConfig, tmp_path: Path
    ) -> None:
        worktree_path = project.worktrees_root / "feature"
        worktree_path.mkdir(parents=True)
        with patch("takopi.worktrees.git_is_worktree", return_value=False):
            with pytest.raises(WorktreeError, match="not a git worktree"):
                ensure_worktree(project, "feature")

    def test_creates_from_local_branch(
        self, project: ProjectConfig, tmp_path: Path
    ) -> None:
        with (
            patch("takopi.worktrees.git_ok", side_effect=[True, False]),  # local yes
            patch("takopi.worktrees._git_worktree_add") as mock_add,
        ):
            result = ensure_worktree(project, "feature")
        mock_add.assert_called_once()
        assert result == project.worktrees_root / "feature"

    def test_creates_from_remote_branch(
        self, project: ProjectConfig, tmp_path: Path
    ) -> None:
        with (
            patch("takopi.worktrees.git_ok", side_effect=[False, True]),  # remote yes
            patch("takopi.worktrees._git_worktree_add") as mock_add,
        ):
            result = ensure_worktree(project, "feature")
        mock_add.assert_called_once()
        # Should have create_branch=True for remote
        call_kwargs = mock_add.call_args[1]
        assert call_kwargs["create_branch"] is True
        assert call_kwargs["base_ref"] == "origin/feature"

    def test_creates_new_branch(self, project: ProjectConfig, tmp_path: Path) -> None:
        with (
            patch("takopi.worktrees.git_ok", return_value=False),  # no local/remote
            patch("takopi.worktrees.resolve_default_base", return_value="main"),
            patch("takopi.worktrees._git_worktree_add") as mock_add,
        ):
            result = ensure_worktree(project, "feature")
        mock_add.assert_called_once()
        call_kwargs = mock_add.call_args[1]
        assert call_kwargs["base_ref"] == "main"
        assert call_kwargs["create_branch"] is True

    def test_no_base_branch_raises(
        self, project: ProjectConfig, tmp_path: Path
    ) -> None:
        with (
            patch("takopi.worktrees.git_ok", return_value=False),
            patch("takopi.worktrees.resolve_default_base", return_value=None),
        ):
            with pytest.raises(WorktreeError, match="cannot determine base"):
                ensure_worktree(project, "feature")


class TestGitWorktreeAdd:
    """Tests for _git_worktree_add internal function."""

    def test_add_existing_branch(self, tmp_path: Path) -> None:
        from takopi.worktrees import _git_worktree_add

        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("takopi.worktrees.git_run", return_value=mock_result) as mock_git:
            _git_worktree_add(tmp_path, tmp_path / "worktree", "feature")
        # Called with worktree add (no -b)
        call_args = mock_git.call_args[0][0]
        assert "worktree" in call_args
        assert "add" in call_args
        assert "-b" not in call_args

    def test_create_new_branch(self, tmp_path: Path) -> None:
        from takopi.worktrees import _git_worktree_add

        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("takopi.worktrees.git_run", return_value=mock_result) as mock_git:
            _git_worktree_add(
                tmp_path,
                tmp_path / "worktree",
                "feature",
                base_ref="main",
                create_branch=True,
            )
        call_args = mock_git.call_args[0][0]
        assert "-b" in call_args
        assert "feature" in call_args
        assert "main" in call_args

    def test_create_branch_without_base_raises(self, tmp_path: Path) -> None:
        from takopi.worktrees import _git_worktree_add

        with pytest.raises(WorktreeError, match="missing base ref"):
            _git_worktree_add(
                tmp_path,
                tmp_path / "worktree",
                "feature",
                create_branch=True,
            )

    def test_git_not_available(self, tmp_path: Path) -> None:
        from takopi.worktrees import _git_worktree_add

        with patch("takopi.worktrees.git_run", return_value=None):
            with pytest.raises(WorktreeError, match="git not available"):
                _git_worktree_add(tmp_path, tmp_path / "worktree", "feature")

    def test_git_failure(self, tmp_path: Path) -> None:
        from takopi.worktrees import _git_worktree_add

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "fatal: branch already exists"
        mock_result.stdout = ""
        with patch("takopi.worktrees.git_run", return_value=mock_result):
            with pytest.raises(WorktreeError, match="branch already exists"):
                _git_worktree_add(tmp_path, tmp_path / "worktree", "feature")
