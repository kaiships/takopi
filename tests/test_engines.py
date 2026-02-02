"""Tests for engines module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from takopi.config import ConfigError
from takopi.engines import (
    _validate_engine_backend,
    get_backend,
    list_backend_ids,
    list_backends,
)


class TestValidateEngineBackend:
    """Tests for _validate_engine_backend function."""

    def test_valid_backend(self) -> None:
        from takopi.backends import EngineBackend

        mock_backend = MagicMock(spec=EngineBackend)
        mock_backend.id = "test-engine"

        mock_ep = MagicMock()
        mock_ep.name = "test-engine"
        mock_ep.value = "some.module:TestEngine"

        # Should not raise
        _validate_engine_backend(mock_backend, mock_ep)

    def test_not_engine_backend_raises(self) -> None:
        mock_backend = MagicMock()  # Not an EngineBackend
        mock_ep = MagicMock()
        mock_ep.value = "some.module:FakeEngine"

        with pytest.raises(TypeError, match="is not an EngineBackend"):
            _validate_engine_backend(mock_backend, mock_ep)

    def test_id_mismatch_raises(self) -> None:
        from takopi.backends import EngineBackend

        mock_backend = MagicMock(spec=EngineBackend)
        mock_backend.id = "actual-id"

        mock_ep = MagicMock()
        mock_ep.name = "expected-id"
        mock_ep.value = "some.module:Engine"

        with pytest.raises(ValueError, match="does not match entrypoint"):
            _validate_engine_backend(mock_backend, mock_ep)


class TestGetBackend:
    """Tests for get_backend function."""

    def test_reserved_id_raises(self) -> None:
        from takopi.ids import RESERVED_ENGINE_IDS

        # Pick a reserved ID
        reserved = next(iter(RESERVED_ENGINE_IDS))
        with pytest.raises(ConfigError, match="reserved"):
            get_backend(reserved)

    def test_reserved_id_case_insensitive(self) -> None:
        from takopi.ids import RESERVED_ENGINE_IDS

        reserved = next(iter(RESERVED_ENGINE_IDS))
        with pytest.raises(ConfigError, match="reserved"):
            get_backend(reserved.upper())


class TestListBackends:
    """Tests for list_backends function."""

    def test_no_backends_raises(self) -> None:
        with patch("takopi.engines.list_backend_ids", return_value=[]):
            with pytest.raises(ConfigError, match="No engine backends"):
                list_backends()

    def test_filters_config_errors(self) -> None:
        from takopi.backends import EngineBackend

        mock_backend = MagicMock(spec=EngineBackend)
        mock_backend.id = "valid-engine"

        def mock_get_backend(engine_id, *, allowlist=None):
            if engine_id == "broken":
                raise ConfigError("Engine broken")
            return mock_backend

        with (
            patch("takopi.engines.list_backend_ids", return_value=["broken", "valid"]),
            patch("takopi.engines.get_backend", side_effect=mock_get_backend),
        ):
            backends = list_backends()

        # Only the valid backend should be returned
        assert len(backends) == 1
        assert backends[0] is mock_backend

    def test_returns_all_valid_backends(self) -> None:
        from takopi.backends import EngineBackend

        mock_backend1 = MagicMock(spec=EngineBackend)
        mock_backend2 = MagicMock(spec=EngineBackend)

        backends_map = {"engine1": mock_backend1, "engine2": mock_backend2}

        with (
            patch("takopi.engines.list_backend_ids", return_value=["engine1", "engine2"]),
            patch("takopi.engines.get_backend", side_effect=lambda eid, **kw: backends_map[eid]),
        ):
            backends = list_backends()

        assert len(backends) == 2
        assert mock_backend1 in backends
        assert mock_backend2 in backends


class TestListBackendIds:
    """Tests for list_backend_ids function."""

    def test_calls_list_ids_with_reserved(self) -> None:
        from takopi.ids import RESERVED_ENGINE_IDS
        from takopi.plugins import ENGINE_GROUP

        with patch("takopi.engines.list_ids", return_value=["engine1"]) as mock_list:
            result = list_backend_ids()

        mock_list.assert_called_once_with(
            ENGINE_GROUP,
            allowlist=None,
            reserved_ids=RESERVED_ENGINE_IDS,
        )
        assert result == ["engine1"]

    def test_passes_allowlist(self) -> None:
        with patch("takopi.engines.list_ids", return_value=["allowed"]) as mock_list:
            result = list_backend_ids(allowlist=["allowed"])

        assert mock_list.call_args[1]["allowlist"] == ["allowed"]
