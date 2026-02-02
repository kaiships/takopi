"""Tests for commands module."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from takopi.commands import _validate_command_backend, get_command
from takopi.config import ConfigError


class TestValidateCommandBackend:
    """Tests for _validate_command_backend function."""

    def test_not_command_backend_raises(self) -> None:
        mock_backend = MagicMock()  # Not a CommandBackend
        mock_ep = MagicMock()
        mock_ep.value = "some.module:FakeCommand"

        with pytest.raises(TypeError, match="is not a CommandBackend"):
            _validate_command_backend(mock_backend, mock_ep)

    def test_id_mismatch_raises(self) -> None:
        from takopi.commands import CommandBackend

        mock_backend = MagicMock(spec=CommandBackend)
        mock_backend.id = "actual-cmd"

        mock_ep = MagicMock()
        mock_ep.name = "expected-cmd"
        mock_ep.value = "some.module:Cmd"

        with pytest.raises(ValueError, match="does not match entrypoint"):
            _validate_command_backend(mock_backend, mock_ep)


class TestGetCommand:
    """Tests for get_command function."""

    def test_reserved_id_raises(self) -> None:
        from takopi.ids import RESERVED_COMMAND_IDS

        if RESERVED_COMMAND_IDS:
            reserved = next(iter(RESERVED_COMMAND_IDS))
            with pytest.raises(ConfigError, match="reserved"):
                get_command(reserved)
