"""Tests for backends helpers module."""

from __future__ import annotations

from takopi.backends_helpers import install_issue


class TestInstallIssue:
    """Tests for install_issue function."""

    def test_with_install_cmd(self) -> None:
        issue = install_issue("claude", "npm install -g claude")
        assert issue.title == "install claude"
        assert len(issue.lines) == 1
        assert "npm install" in issue.lines[0]

    def test_without_install_cmd(self) -> None:
        issue = install_issue("myengine", None)
        assert issue.title == "install myengine"
        assert len(issue.lines) == 1
        assert "See engine setup docs" in issue.lines[0]
