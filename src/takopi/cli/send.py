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


def _parse_buttons(buttons_str: str) -> list[list[dict[str, str]]]:
    """Parse button string into inline keyboard markup.

    Format: "label1:data1,label2:data2|label3:data3" where | separates rows
    Example: "Yes:yes,No:no" -> [[{text: Yes, callback_data: yes}, {text: No, callback_data: no}]]
    """
    rows = []
    for row_str in buttons_str.split("|"):
        row = []
        for btn_str in row_str.split(","):
            btn_str = btn_str.strip()
            if ":" in btn_str:
                label, data = btn_str.split(":", 1)
            else:
                label = data = btn_str
            row.append({"text": label.strip(), "callback_data": data.strip()})
        if row:
            rows.append(row)
    return rows


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
    reply_markup: dict[str, Any] | None = None,
) -> int | None:
    """Send message and return the message_id."""
    async with httpx.AsyncClient() as client:
        try:
            payload: dict[str, Any] = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "link_preview_options": {"is_disabled": True},
            }
            if reply_markup is not None:
                payload["reply_markup"] = reply_markup

            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json=payload,
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


async def _answer_callback_query(
    bot_token: str,
    callback_query_id: str,
    text: str | None = None,
) -> None:
    """Answer a callback query to dismiss the loading state."""
    async with httpx.AsyncClient() as client:
        try:
            payload: dict[str, Any] = {"callback_query_id": callback_query_id}
            if text:
                payload["text"] = text
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
                json=payload,
                timeout=10.0,
            )
        except Exception as exc:
            logger.debug("answer_callback.error", error=str(exc))


async def _edit_message_remove_buttons(
    bot_token: str,
    chat_id: int,
    message_id: int,
    text: str,
) -> None:
    """Edit message to remove inline buttons after selection."""
    async with httpx.AsyncClient() as client:
        try:
            await client.post(
                f"https://api.telegram.org/bot{bot_token}/editMessageText",
                json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": text,
                    "parse_mode": "HTML",
                },
                timeout=10.0,
            )
        except Exception as exc:
            logger.debug("edit_message.error", error=str(exc))


async def _poll_for_reply(
    *,
    bot_token: str,
    chat_id: int,
    message_id: int,
    timeout_s: float,
    expect_callback: bool = False,
    original_text: str = "",
) -> str | None:
    """Poll for a reply to the specified message.

    If expect_callback is True, also listen for callback queries (button clicks).
    """
    import time

    start = time.monotonic()
    offset: int | None = None

    allowed = ["message", "callback_query"] if expect_callback else ["message"]

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
                    "allowed_updates": allowed,
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

                    # Handle callback query (button click)
                    if expect_callback and upd.callback_query is not None:
                        cb = upd.callback_query
                        cb_msg = cb.message
                        if cb_msg is not None and cb_msg.message_id == message_id:
                            # Answer the callback to dismiss loading state
                            await _answer_callback_query(bot_token, cb.id)
                            # Edit message to show selection and remove buttons
                            if original_text and cb.data:
                                new_text = f"{original_text}\n\n<i>Selected: {cb.data}</i>"
                                await _edit_message_remove_buttons(
                                    bot_token, chat_id, message_id, new_text
                                )
                            return cb.data

                    # Handle text reply
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
    buttons: str | None = typer.Option(
        None,
        "-b",
        "--buttons",
        help="Inline buttons for --session mode. Format: 'Yes:yes,No:no' or 'A:a|B:b' (| for rows).",
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
        takopi send --session --buttons "Yes:yes,No:no" "Approve this action?"
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
        reply_markup: dict[str, Any] | None = None
        if buttons:
            reply_markup = {"inline_keyboard": _parse_buttons(buttons)}

        async def _run_session() -> str | None:
            msg_id = await _send_message_get_id(
                message,
                bot_token=tg.bot_token,
                chat_id=tg.chat_id,
                reply_markup=reply_markup,
            )
            if msg_id is None:
                return None
            if not quiet:
                mode = "button click or reply" if buttons else "reply"
                typer.echo(f"sent (waiting for {mode}, timeout={timeout}s)", err=True)
            return await _poll_for_reply(
                bot_token=tg.bot_token,
                chat_id=tg.chat_id,
                message_id=msg_id,
                timeout_s=float(timeout),
                expect_callback=buttons is not None,
                original_text=message,
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
