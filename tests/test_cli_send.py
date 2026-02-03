"""Tests for the send CLI command."""

import pytest

from takopi.cli.send import _parse_buttons


class TestParseButtons:
    """Tests for button parsing."""

    def test_single_button(self) -> None:
        """Single button parses correctly."""
        result = _parse_buttons("Yes:yes")
        assert result == [[{"text": "Yes", "callback_data": "yes"}]]

    def test_two_buttons_same_row(self) -> None:
        """Two buttons separated by comma are on same row."""
        result = _parse_buttons("Yes:yes,No:no")
        assert result == [
            [
                {"text": "Yes", "callback_data": "yes"},
                {"text": "No", "callback_data": "no"},
            ]
        ]

    def test_two_rows(self) -> None:
        """Buttons separated by | are on different rows."""
        result = _parse_buttons("Yes:yes|No:no")
        assert result == [
            [{"text": "Yes", "callback_data": "yes"}],
            [{"text": "No", "callback_data": "no"}],
        ]

    def test_button_without_colon(self) -> None:
        """Button without colon uses label as data."""
        result = _parse_buttons("approve")
        assert result == [[{"text": "approve", "callback_data": "approve"}]]

    def test_whitespace_handling(self) -> None:
        """Whitespace is trimmed from labels and data."""
        result = _parse_buttons(" Yes : yes , No : no ")
        assert result == [
            [
                {"text": "Yes", "callback_data": "yes"},
                {"text": "No", "callback_data": "no"},
            ]
        ]

    def test_complex_layout(self) -> None:
        """Complex button layout with multiple rows."""
        result = _parse_buttons("Option A:a,Option B:b|Cancel:cancel")
        assert result == [
            [
                {"text": "Option A", "callback_data": "a"},
                {"text": "Option B", "callback_data": "b"},
            ],
            [{"text": "Cancel", "callback_data": "cancel"}],
        ]
