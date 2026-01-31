"""Telegram notifications for heartbeat results."""

from __future__ import annotations

import html

import httpx

from ..logging import get_logger
from .executor import HeartbeatResult

logger = get_logger(__name__)


def format_notification(
    name: str,
    result: HeartbeatResult,
    *,
    summary_lines: int = 10,
) -> str:
    """Format heartbeat result as Telegram message."""
    status_emoji = "\u2705" if result.ok else "\u274c"  # check mark / X

    # Extract summary from answer (last N non-empty lines)
    summary = ""
    if result.answer:
        lines = [line for line in result.answer.strip().split("\n") if line.strip()]
        if len(lines) > summary_lines:
            lines = lines[-summary_lines:]
        summary = "\n".join(lines)

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
        # Escape HTML and truncate
        escaped = html.escape(summary[:3000])
        parts.append(f"\n<pre>{escaped}</pre>")

    if result.error:
        escaped_error = html.escape(result.error[:500])
        parts.append(f"\n<b>Error:</b> {escaped_error}")

    return "\n".join(parts)


async def send_telegram_notification(
    *,
    bot_token: str,
    chat_id: int,
    text: str,
) -> bool:
    """Send notification via Telegram API."""
    async with httpx.AsyncClient() as client:
        try:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                    "link_preview_options": {"is_disabled": True},
                },
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
