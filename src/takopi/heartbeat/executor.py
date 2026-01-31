"""Execute heartbeat tasks via ClaudeRunner."""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..logging import get_logger
from ..model import CompletedEvent, ResumeToken, StartedEvent
from ..runners.claude import ClaudeRunner
from ..settings import HeartbeatSettings
from .state import HeartbeatRun, load_state, save_state

logger = get_logger(__name__)

ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env_vars(text: str) -> str:
    """Expand ${VAR} patterns in text using environment variables.

    Built-in variables:
    - ${TODAY} - Current date (YYYY-MM-DD)
    - ${NOW} - Current time (HH:MM)
    """
    now = datetime.now()
    builtins = {
        "TODAY": now.strftime("%Y-%m-%d"),
        "NOW": now.strftime("%H:%M"),
    }

    def replace(match: re.Match[str]) -> str:
        var = match.group(1)
        # Check builtins first, then environment
        if var in builtins:
            return builtins[var]
        return os.environ.get(var, match.group(0))

    return ENV_VAR_RE.sub(replace, text)


def load_prompt(settings: HeartbeatSettings) -> str:
    """Load and expand prompt from settings."""
    if settings.prompt is not None:
        return expand_env_vars(settings.prompt)

    assert settings.prompt_file is not None
    path = Path(settings.prompt_file).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")

    text = path.read_text(encoding="utf-8")
    return expand_env_vars(text)


@dataclass(slots=True)
class HeartbeatResult:
    """Result of a heartbeat execution."""

    ok: bool
    answer: str
    session_id: str | None
    duration_ms: int
    usage: dict[str, Any] | None
    error: str | None


async def run_heartbeat(
    name: str,
    settings: HeartbeatSettings,
    *,
    resume: bool = True,
) -> HeartbeatResult:
    """Execute a heartbeat and collect results."""
    state = load_state(name)

    # Prepare prompt
    prompt = load_prompt(settings)

    # Prepare resume token
    resume_token: ResumeToken | None = None
    if resume and state.session_id:
        resume_token = ResumeToken(engine="claude", value=state.session_id)
        logger.info(
            "heartbeat.resuming",
            name=name,
            session_id=state.session_id,
        )

    # Build runner
    claude_cmd = shutil.which("claude") or "claude"
    runner = ClaudeRunner(
        claude_cmd=claude_cmd,
        model=settings.model,
        allowed_tools=list(settings.allowed_tools) if settings.allowed_tools else None,
        dangerously_skip_permissions=settings.dangerously_skip_permissions,
        session_title=name,
    )

    # Save original directory
    original_cwd = os.getcwd()

    # Change to working directory if specified
    if settings.cwd:
        cwd = Path(settings.cwd).expanduser()
        if cwd.exists():
            os.chdir(cwd)
            logger.info("heartbeat.cwd", name=name, cwd=str(cwd))
        else:
            logger.warning("heartbeat.cwd.missing", name=name, cwd=str(cwd))

    # Track timing
    start_time = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()

    # Collect events
    session_id: str | None = state.session_id
    answer = ""
    error: str | None = None
    ok = False
    usage: dict[str, Any] | None = None

    try:
        logger.info("heartbeat.started", name=name)
        async for event in runner.run(prompt, resume_token):
            if isinstance(event, StartedEvent):
                session_id = event.resume.value
                logger.info(
                    "heartbeat.session",
                    name=name,
                    session_id=session_id,
                )
            elif isinstance(event, CompletedEvent):
                ok = event.ok
                answer = event.answer
                error = event.error
                usage = event.usage
                if event.resume:
                    session_id = event.resume.value
    except Exception as exc:
        error = str(exc)
        ok = False
        logger.error("heartbeat.error", name=name, error=error)
    finally:
        # Restore original directory
        os.chdir(original_cwd)

    duration_ms = int((time.monotonic() - start_time) * 1000)
    completed_at = datetime.now(timezone.utc).isoformat()

    logger.info(
        "heartbeat.completed",
        name=name,
        ok=ok,
        duration_ms=duration_ms,
        cost=usage.get("total_cost_usd") if usage else None,
    )

    # Update state
    state.session_id = session_id
    state.last_run_at = completed_at
    state.runs.append(
        HeartbeatRun(
            started_at=started_at,
            completed_at=completed_at,
            ok=ok,
            duration_ms=duration_ms,
            usage=usage,
            error=error,
        )
    )
    save_state(state)

    return HeartbeatResult(
        ok=ok,
        answer=answer,
        session_id=session_id,
        duration_ms=duration_ms,
        usage=usage,
        error=error,
    )
