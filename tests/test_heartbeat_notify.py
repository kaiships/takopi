"""Tests for heartbeat notification module."""

from __future__ import annotations

import html
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from takopi.heartbeat.executor import HeartbeatResult
from takopi.heartbeat.notify import (
    TELEGRAM_MESSAGE_MAX_CHARS,
    _split_for_html_pre,
    format_notification,
    format_notification_messages,
    send_telegram_notification,
)


class TestFormatNotification:
    """Tests for format_notification function."""

    def test_successful_result_basic(self) -> None:
        result = HeartbeatResult(
            ok=True,
            answer="Task completed successfully.",
            session_id="session-123",
            duration_ms=5000,
            usage=None,
            error=None,
        )
        message = format_notification("test-heartbeat", result)
        assert "✅" in message
        assert "test-heartbeat" in message
        assert "5.0s" in message
        assert "Task completed successfully" in message

    def test_failed_result_with_error(self) -> None:
        result = HeartbeatResult(
            ok=False,
            answer="",
            session_id=None,
            duration_ms=2000,
            usage=None,
            error="Connection timeout",
        )
        message = format_notification("failed-heartbeat", result)
        assert "❌" in message
        assert "failed-heartbeat" in message
        assert "2.0s" in message
        assert "Error:" in message
        assert "Connection timeout" in message

    def test_duration_minutes_format(self) -> None:
        result = HeartbeatResult(
            ok=True,
            answer="Done",
            session_id="sess",
            duration_ms=90000,  # 90 seconds = 1m30s
            usage=None,
            error=None,
        )
        message = format_notification("long-task", result)
        assert "1m30s" in message

    def test_cost_display(self) -> None:
        result = HeartbeatResult(
            ok=True,
            answer="Done",
            session_id="sess",
            duration_ms=10000,
            usage={"total_cost_usd": 0.0523},
            error=None,
        )
        message = format_notification("with-cost", result)
        assert "$0.0523" in message

    def test_summary_truncation(self) -> None:
        # Create a result with many lines
        lines = [f"Line {i}" for i in range(20)]
        result = HeartbeatResult(
            ok=True,
            answer="\n".join(lines),
            session_id="sess",
            duration_ms=1000,
            usage=None,
            error=None,
        )
        # Default summary_lines is 10, so only last 10 should appear
        message = format_notification("truncated", result)
        assert "Line 19" in message
        assert "Line 10" in message
        # Line 9 should not be in the last 10 lines
        assert "Line 9" not in message

    def test_custom_summary_lines(self) -> None:
        lines = [f"Line {i}" for i in range(20)]
        result = HeartbeatResult(
            ok=True,
            answer="\n".join(lines),
            session_id="sess",
            duration_ms=1000,
            usage=None,
            error=None,
        )
        message = format_notification("custom", result, summary_lines=5)
        assert "Line 19" in message
        assert "Line 15" in message
        assert "Line 14" not in message

    def test_html_escaping(self) -> None:
        result = HeartbeatResult(
            ok=True,
            answer="Output with <script>alert('xss')</script>",
            session_id="sess",
            duration_ms=1000,
            usage=None,
            error=None,
        )
        message = format_notification("xss-test", result)
        # HTML should be escaped
        assert "<script>" not in message
        assert "&lt;script&gt;" in message

    def test_name_escaping(self) -> None:
        result = HeartbeatResult(
            ok=True,
            answer="Done",
            session_id="sess",
            duration_ms=1000,
            usage=None,
            error=None,
        )
        message = format_notification("test<name>", result)
        assert "&lt;name&gt;" in message

    def test_empty_answer(self) -> None:
        result = HeartbeatResult(
            ok=True,
            answer="",
            session_id="sess",
            duration_ms=1000,
            usage=None,
            error=None,
        )
        message = format_notification("empty", result)
        # Should still have status and duration
        assert "✅" in message
        assert "1.0s" in message
        # No <pre> block for empty answer
        assert "<pre>" not in message

    def test_error_truncation(self) -> None:
        long_error = "x" * 1000
        result = HeartbeatResult(
            ok=False,
            answer="",
            session_id=None,
            duration_ms=1000,
            usage=None,
            error=long_error,
        )
        message = format_notification("error-trunc", result)
        # Error should be truncated to 500 chars
        assert len(message) < 600

    def test_adds_ellipsis_when_summary_is_long(self) -> None:
        result = HeartbeatResult(
            ok=True,
            answer="a" * 4000,
            session_id="sess",
            duration_ms=1000,
            usage=None,
            error=None,
        )
        message = format_notification("long-summary", result, summary_lines=1)
        assert "…" in message


class TestSendTelegramNotification:
    """Tests for send_telegram_notification function."""

    @pytest.mark.anyio
    async def test_successful_send(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await send_telegram_notification(
                bot_token="test-token",
                chat_id=123456,
                text="Test message",
            )

        assert result is True

    @pytest.mark.anyio
    async def test_api_returns_not_ok(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "ok": False,
            "description": "Bad Request: chat not found",
        }
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                return_value=mock_response
            )
            result = await send_telegram_notification(
                bot_token="test-token",
                chat_id=999999,
                text="Test message",
            )

        assert result is False

    @pytest.mark.anyio
    async def test_http_error(self) -> None:
        import httpx

        with patch("httpx.AsyncClient") as mock_client:
            mock_client.return_value.__aenter__.return_value.post = AsyncMock(
                side_effect=httpx.HTTPError("Connection failed")
            )
            result = await send_telegram_notification(
                bot_token="test-token",
                chat_id=123456,
                text="Test message",
            )

        assert result is False

    @pytest.mark.anyio
    async def test_request_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await send_telegram_notification(
                bot_token="my-bot-token",
                chat_id=12345,
                text="<b>Hello</b>",
            )

        # Verify the correct URL and payload
        call_args = mock_post.call_args
        assert "bot" in call_args[0][0]
        assert "my-bot-token" in call_args[0][0]
        json_data = call_args[1]["json"]
        assert json_data["chat_id"] == 12345
        assert json_data["text"] == "<b>Hello</b>"
        assert json_data["parse_mode"] == "HTML"

    @pytest.mark.anyio
    async def test_disable_notification_payload(self) -> None:
        mock_response = MagicMock()
        mock_response.json.return_value = {"ok": True}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_post = AsyncMock(return_value=mock_response)
            mock_client.return_value.__aenter__.return_value.post = mock_post

            await send_telegram_notification(
                bot_token="my-bot-token",
                chat_id=12345,
                text="hello",
                disable_notification=True,
            )

        json_data = mock_post.call_args[1]["json"]
        assert json_data["disable_notification"] is True


class TestFormatNotificationMessages:
    """Tests for format_notification_messages function."""

    def test_splits_long_output_into_multiple_messages(self) -> None:
        result = HeartbeatResult(
            ok=True,
            answer="'" * 5000,
            session_id="sess",
            duration_ms=1000,
            usage=None,
            error=None,
        )
        messages = format_notification_messages("long-output", result)
        assert len(messages) > 2
        assert messages[0].startswith("<b>✅")
        for msg in messages:
            assert len(msg) <= TELEGRAM_MESSAGE_MAX_CHARS

        combined = "".join(
            html.unescape(msg.removeprefix("<pre>").removesuffix("</pre>"))
            for msg in messages[1:]
        )
        assert combined == "'" * 5000

    def test_formats_duration_cost_error_and_no_summary(self) -> None:
        result = HeartbeatResult(
            ok=False,
            answer="",
            session_id="sess",
            duration_ms=90000,
            usage={"total_cost_usd": 0.1234},
            error="boom",
        )
        messages = format_notification_messages("failed", result)
        assert messages == [
            "<b>❌ failed</b>\nDuration: 1m30s ($0.1234)\n<b>Error:</b> boom"
        ]

    def test_split_respects_newlines_and_escaping(self) -> None:
        lines = ["a&<>\"'" * 200 for _ in range(10)]
        result = HeartbeatResult(
            ok=True,
            answer="\n".join(lines),
            session_id="sess",
            duration_ms=1000,
            usage=None,
            error=None,
        )
        messages = format_notification_messages("escaped", result)
        assert len(messages) > 2
        assert messages[0].startswith("<b>✅")
        for msg in messages:
            assert len(msg) <= TELEGRAM_MESSAGE_MAX_CHARS
        assert all(msg.startswith("<pre>") for msg in messages[1:])

        combined = "".join(
            html.unescape(msg.removeprefix("<pre>").removesuffix("</pre>"))
            for msg in messages[1:]
        )
        assert combined == "\n".join(lines)

    def test_split_helper_handles_empty_and_tiny_limits(self) -> None:
        assert _split_for_html_pre("", max_escaped_chars=10) == []
        assert _split_for_html_pre("'", max_escaped_chars=1) == ["'"]
