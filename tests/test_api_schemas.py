"""Tests for telegram API schemas module."""

from __future__ import annotations

from takopi.telegram.api_schemas import decode_update, decode_updates


class TestDecodeUpdate:
    """Tests for decode_update function."""

    def test_decodes_single_update(self) -> None:
        payload = '{"update_id": 123}'
        result = decode_update(payload)
        assert result.update_id == 123

    def test_decodes_bytes(self) -> None:
        payload = b'{"update_id": 456}'
        result = decode_update(payload)
        assert result.update_id == 456


class TestDecodeUpdates:
    """Tests for decode_updates function."""

    def test_decodes_update_list(self) -> None:
        payload = '[{"update_id": 1}, {"update_id": 2}]'
        result = decode_updates(payload)
        assert len(result) == 2
        assert result[0].update_id == 1
        assert result[1].update_id == 2

    def test_decodes_empty_list(self) -> None:
        payload = "[]"
        result = decode_updates(payload)
        assert result == []
