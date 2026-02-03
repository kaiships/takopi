"""CLI command for running heartbeat tasks."""

from __future__ import annotations

import anyio
import typer

from ..config import ConfigError
from ..logging import get_logger, setup_logging
from ..settings import load_settings

logger = get_logger(__name__)

app = typer.Typer(help="Run scheduled heartbeat tasks.")


def _list_heartbeats() -> None:
    """List configured heartbeats."""
    try:
        settings, config_path = load_settings()
    except ConfigError as exc:
        typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if not settings.heartbeats:
        typer.echo("No heartbeats configured.")
        typer.echo(f"\nAdd heartbeats to {config_path}:")
        typer.echo(
            """
[heartbeats.example]
prompt = "Your prompt here"
cwd = "~"
"""
        )
        raise typer.Exit(code=0)

    typer.echo("Configured heartbeats:")
    for name, hb in settings.heartbeats.items():
        source = "inline" if hb.prompt else f"file:{hb.prompt_file}"
        schedule = hb.schedule or "manual"
        typer.echo(f"  {name}: {source} ({schedule})")


def _run_heartbeat(
    name: str,
    *,
    no_notify: bool,
    no_resume: bool,
    quiet: bool,
) -> None:
    """Run a specific heartbeat."""
    from ..heartbeat.executor import run_heartbeat
    from ..heartbeat.notify import format_notification_messages, send_telegram_notification

    try:
        settings, config_path = load_settings()
    except ConfigError as exc:
        if not quiet:
            typer.echo(f"error: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    if name not in settings.heartbeats:
        if not quiet:
            typer.echo(f"error: heartbeat '{name}' not found", err=True)
            if settings.heartbeats:
                typer.echo(f"Available: {', '.join(settings.heartbeats.keys())}")
            else:
                typer.echo("No heartbeats configured.")
        raise typer.Exit(code=1)

    hb_settings = settings.heartbeats[name]

    async def _run() -> int:
        result = await run_heartbeat(
            name,
            hb_settings,
            resume=not no_resume,
        )

        if not quiet:
            status = "ok" if result.ok else "failed"
            typer.echo(f"[{name}] {status} duration={result.duration_ms}ms")
            if result.usage and "total_cost_usd" in result.usage:
                typer.echo(f"[{name}] cost=${result.usage['total_cost_usd']:.4f}")
            if result.error:
                typer.echo(f"[{name}] error: {result.error}", err=True)

        # Determine if we should notify
        should_notify = (
            hb_settings.notify
            and not no_notify
            and (
                (result.ok and hb_settings.notify_on_success)
                or (not result.ok and hb_settings.notify_on_failure)
            )
        )

        if should_notify:
            try:
                tg = settings.transports.telegram
                messages = format_notification_messages(name, result)
                for idx, message in enumerate(messages):
                    ok = await send_telegram_notification(
                        bot_token=tg.bot_token,
                        chat_id=tg.chat_id,
                        text=message,
                        disable_notification=True if idx > 0 else None,
                    )
                    if not ok:
                        break
            except Exception as exc:
                if not quiet:
                    typer.echo(f"[{name}] notification failed: {exc}", err=True)

        return 0 if result.ok else 1

    exit_code = anyio.run(_run)
    raise typer.Exit(code=exit_code)


@app.callback(invoke_without_command=True)
def heartbeat_main(
    ctx: typer.Context,
    name: str | None = typer.Argument(
        None,
        help="Heartbeat name to run. Omit to list available heartbeats.",
    ),
    no_notify: bool = typer.Option(
        False,
        "--no-notify",
        help="Skip Telegram notification.",
    ),
    no_resume: bool = typer.Option(
        False,
        "--no-resume",
        help="Start fresh session instead of resuming.",
    ),
    quiet: bool = typer.Option(
        False,
        "-q",
        "--quiet",
        help="Suppress output (for cron).",
    ),
    debug: bool = typer.Option(
        False,
        "--debug",
        help="Enable debug logging.",
    ),
) -> None:
    """Run a heartbeat task."""
    setup_logging(debug=debug)

    if ctx.invoked_subcommand is not None:
        return

    if name is None:
        _list_heartbeats()
    else:
        _run_heartbeat(name, no_notify=no_notify, no_resume=no_resume, quiet=quiet)
