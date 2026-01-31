"""CLI command for sending Telegram messages."""

from __future__ import annotations

import sys

import anyio
import typer

from ..config import ConfigError
from ..heartbeat.notify import send_telegram_notification
from ..logging import get_logger, setup_logging
from ..settings import load_settings

logger = get_logger(__name__)

app = typer.Typer(help="Send messages via Telegram.")


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


@app.callback(invoke_without_command=True)
def send_main(
    ctx: typer.Context,
    message: str | None = typer.Argument(
        None,
        help="Message to send. Use - to read from stdin.",
    ),
    quiet: bool = typer.Option(
        False,
        "-q",
        "--quiet",
        help="Suppress output.",
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
