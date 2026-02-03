"""Telegram notifications for heartbeat results."""

from __future__ import annotations

import html

import httpx

from ..logging import get_logger
from .executor import HeartbeatResult

logger = get_logger(__name__)

TELEGRAM_MESSAGE_MAX_CHARS = 4096
_PRE_OVERHEAD_CHARS = len("<pre></pre>")


def _extract_summary(answer: str, *, summary_lines: int) -> str:
    if not answer:
        return ""
    lines = [line for line in answer.strip().split("\n") if line.strip()]
    if len(lines) > summary_lines:
        lines = lines[-summary_lines:]
    return "\n".join(lines)


def _html_escaped_len(ch: str) -> int:
    match ch:
        case "&":
            return 5  # &amp;
        case "<" | ">":
            return 4  # &lt; / &gt;
        case '"' | "'":
            return 6  # &quot; / &#x27;
        case _:
            return 1


def _split_for_html_pre(text: str, *, max_escaped_chars: int) -> list[str]:
    """Split raw text into chunks that will fit inside `<pre>...</pre>`."""
    if not text:
        return []
    max_escaped_chars = max(1, int(max_escaped_chars))

    chunks: list[str] = []
    start = 0
    while start < len(text):
        escaped_len = 0
        end = start
        last_break: int | None = None
        last_break_escaped_len = 0

        while end < len(text):
            ch = text[end]
            ch_escaped_len = _html_escaped_len(ch)
            if escaped_len + ch_escaped_len > max_escaped_chars:
                break
            escaped_len += ch_escaped_len
            end += 1
            if ch == "\n":
                last_break = end
                last_break_escaped_len = escaped_len

        if end == start:
            end = start + 1
        elif end < len(text) and last_break is not None and last_break > start:
            end = last_break
            escaped_len = last_break_escaped_len

        chunks.append(text[start:end])
        start = end

    return chunks


def format_notification(
    name: str,
    result: HeartbeatResult,
    *,
    summary_lines: int = 10,
) -> str:
    """Format heartbeat result as Telegram message."""
    status_emoji = "\u2705" if result.ok else "\u274c"  # check mark / X

    # Extract summary from answer (last N non-empty lines)
    summary = _extract_summary(result.answer, summary_lines=summary_lines)

    # Format duration
    duration_s = result.duration_ms / 1000
    if duration_s < 60:
        duration_str = f"{duration_s:.1f}s"
    else:
        minutes = int(duration_s // 60)
        seconds = int(duration_s % 60)
        duration_str = f"{minutes}m{seconds}s"

    # Format cost
    cost_str = ""
    if result.usage and "total_cost_usd" in result.usage:
        cost = result.usage["total_cost_usd"]
        cost_str = f" (${cost:.4f})"

    parts = [
        f"<b>{status_emoji} {html.escape(name)}</b>",
        f"Duration: {duration_str}{cost_str}",
    ]

    if summary:
        summary_preview = summary
        if len(summary_preview) > 3000:
            summary_preview = summary_preview[:2999] + "…"
        escaped = html.escape(summary_preview)
        parts.append(f"\n<pre>{escaped}</pre>")

    if result.error:
        escaped_error = html.escape(result.error[:500])
        parts.append(f"\n<b>Error:</b> {escaped_error}")

    return "\n".join(parts)


def format_notification_messages(
    name: str,
    result: HeartbeatResult,
    *,
    summary_lines: int = 10,
) -> list[str]:
    """Format heartbeat result into one or more Telegram-sized HTML messages."""
    status_emoji = "\u2705" if result.ok else "\u274c"  # check mark / X

    # Format duration
    duration_s = result.duration_ms / 1000
    if duration_s < 60:
        duration_str = f"{duration_s:.1f}s"
    else:
        minutes = int(duration_s // 60)
        seconds = int(duration_s % 60)
        duration_str = f"{minutes}m{seconds}s"

    # Format cost
    cost_str = ""
    if result.usage and "total_cost_usd" in result.usage:
        cost = result.usage["total_cost_usd"]
        cost_str = f" (${cost:.4f})"

    parts = [
        f"<b>{status_emoji} {html.escape(name)}</b>",
        f"Duration: {duration_str}{cost_str}",
    ]

    if result.error:
        escaped_error = html.escape(result.error[:500])
        parts.append(f"<b>Error:</b> {escaped_error}")

    messages = ["\n".join(parts)]

    summary = _extract_summary(result.answer, summary_lines=summary_lines)
    if summary:
        max_escaped_chars = TELEGRAM_MESSAGE_MAX_CHARS - _PRE_OVERHEAD_CHARS
        messages.extend(
            [
                f"<pre>{html.escape(chunk)}</pre>"
                for chunk in _split_for_html_pre(
                    summary, max_escaped_chars=max_escaped_chars
                )
            ]
        )

    return messages


async def send_telegram_notification(
    *,
    bot_token: str,
    chat_id: int,
    text: str,
    disable_notification: bool | None = None,
) -> bool:
    """Send notification via Telegram API."""
    async with httpx.AsyncClient() as client:
        try:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            }
            if disable_notification is not None:
                payload["disable_notification"] = disable_notification

            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            ok = data.get("ok", False)
            if ok:
                logger.info("heartbeat.notify.sent", chat_id=chat_id)
            else:
                logger.warning(
                    "heartbeat.notify.failed",
                    chat_id=chat_id,
                    error=data.get("description"),
                )
            return ok
        except Exception as exc:
            logger.error("heartbeat.notify.error", error=str(exc))
            return False
