"""CLI command for sending Telegram messages."""

from __future__ import annotations

import sys
from typing import Any

import anyio
import httpx
import typer

from ..config import ConfigError
from ..heartbeat.notify import send_telegram_notification
from ..logging import get_logger, setup_logging
from ..settings import load_settings
from ..telegram.api_schemas import decode_updates

logger = get_logger(__name__)

app = typer.Typer(help="Send messages via Telegram.")

DEFAULT_SESSION_TIMEOUT = 300  # 5 minutes


async def _send_message(
    text: str,
    *,
    bot_token: str,
    chat_id: int,
) -> bool:
    """Send a plain text message via Telegram."""
    return await send_telegram_notification(
        bot_token=bot_token,
        chat_id=chat_id,
        text=text,
    )


async def _send_message_get_id(
    text: str,
    *,
    bot_token: str,
    chat_id: int,
) -> int | None:
    """Send message and return the message_id."""
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
            if data.get("ok"):
                return data["result"]["message_id"]
            return None
        except Exception as exc:
            logger.error("send.error", error=str(exc))
            return None


async def _poll_for_reply(
    *,
    bot_token: str,
    chat_id: int,
    message_id: int,
    timeout_s: float,
) -> str | None:
    """Poll for a reply to the specified message."""
    import time

    start = time.monotonic()
    offset: int | None = None

    async with httpx.AsyncClient() as client:
        while True:
            elapsed = time.monotonic() - start
            if elapsed >= timeout_s:
                return None

            remaining = timeout_s - elapsed
            poll_timeout = min(30, int(remaining))
            if poll_timeout <= 0:
                return None

            try:
                params: dict[str, Any] = {
                    "timeout": poll_timeout,
                    "allowed_updates": ["message"],
                }
                if offset is not None:
                    params["offset"] = offset

                resp = await client.get(
                    f"https://api.telegram.org/bot{bot_token}/getUpdates",
                    params=params,
                    timeout=poll_timeout + 10.0,
                )
                resp.raise_for_status()
                data = resp.json()

                if not data.get("ok"):
                    await anyio.sleep(2)
                    continue

                updates = decode_updates(resp.content)

                for upd in updates:
                    offset = upd.update_id + 1
                    msg = upd.message
                    if msg is None:
                        continue
                    if msg.chat.id != chat_id:
                        continue
                    reply = msg.reply_to_message
                    if reply is not None and reply.message_id == message_id:
                        return msg.text or msg.caption or ""

            except httpx.TimeoutException:
                continue
            except Exception as exc:
                logger.error("poll.error", error=str(exc))
                await anyio.sleep(2)


@app.callback(invoke_without_command=True)
def send_main(
    ctx: typer.Context,
    message: str | None = typer.Argument(
        None,
        help="Message to send. Use - to read from stdin.",
    ),
    session: bool = typer.Option(
        False,
        "-s",
        "--session",
        help="Wait for a reply and output it to stdout.",
    ),
    timeout: int = typer.Option(
        DEFAULT_SESSION_TIMEOUT,
        "-t",
        "--timeout",
        help="Timeout in seconds for --session mode.",
    ),
    quiet: bool = typer.Option(
        False,
        "-q",
        "--quiet",
        help="Suppress output (except reply in session mode).",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging.",
    ),
) -> None:
    """Send a message via Telegram.

    Examples:
        takopi send "Hello from the heartbeat!"
        echo "Pipeline complete" | takopi send -
        takopi send --session "Should I proceed? Reply to this message."
    """
    setup_logging(debug=debug)

    if ctx.invoked_subcommand is not None:
        return

    if message is None:
        typer.echo("error: message required", err=True)
        typer.echo("Usage: takopi send MESSAGE", err=True)
        raise typer.Exit(code=1)

    # Read from stdin if message is "-"
    if message == "-":
        message = sys.stdin.read().strip()
        if not message:
            typer.echo("error: empty message from stdin", err=True)
            raise typer.Exit(code=1)

    try:
        settings, config_path = load_settings()
    except ConfigError as exc:
        if not quiet:
            typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    tg = settings.transports.telegram

    if session:
        # Session mode: send, wait for reply, output reply
        async def _run_session() -> str | None:
            msg_id = await _send_message_get_id(
                message,
                bot_token=tg.bot_token,
                chat_id=tg.chat_id,
            )
            if msg_id is None:
                return None
            if not quiet:
                typer.echo(f"sent (waiting for reply, timeout={timeout}s)", err=True)
            return await _poll_for_reply(
                bot_token=tg.bot_token,
                chat_id=tg.chat_id,
                message_id=msg_id,
                timeout_s=float(timeout),
            )

        reply = anyio.run(_run_session)

        if reply is None:
            if not quiet:
                typer.echo("error: no reply received (timeout)", err=True)
            raise typer.Exit(code=1)
        else:
            typer.echo(reply)
            raise typer.Exit(code=0)
    else:
        # Fire-and-forget mode
        async def _run() -> bool:
            return await _send_message(
                message,
                bot_token=tg.bot_token,
                chat_id=tg.chat_id,
            )

        ok = anyio.run(_run)

        if ok:
            if not quiet:
                typer.echo("sent")
            raise typer.Exit(code=0)
        else:
            if not quiet:
                typer.echo("error: failed to send message", err=True)
            raise typer.Exit(code=1)
