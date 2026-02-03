"""Task classification for intelligent model routing.

Classifies incoming prompts to route them to the optimal engine/model combination:
- coding tasks → codex (gpt-5.2)
- general reasoning → claude (opus)
- quick/simple tasks → claude (haiku)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

import httpx

from .model import EngineId


class TaskType(str, Enum):
    CODING = "coding"
    REASONING = "reasoning"
    QUICK = "quick"


@dataclass(frozen=True, slots=True)
class ClassificationResult:
    """Result of task classification."""

    task_type: TaskType
    engine: EngineId
    model: str | None
    confidence: float
    reason: str


# Default routing table
ROUTING_TABLE: dict[TaskType, tuple[EngineId, str | None]] = {
    TaskType.CODING: ("codex", "gpt-5.2"),
    TaskType.REASONING: ("claude", "claude-opus-4-5-20251101"),
    TaskType.QUICK: ("claude", "claude-3-5-haiku-20241022"),
}


_CLASSIFICATION_PROMPT = """\
Classify this task into exactly one category. Respond with ONLY the category name, nothing else.

Categories:
- CODING: Writing, debugging, refactoring, or analyzing code. File operations. Build/test commands. Git operations. Any task that will modify or create code files.
- REASONING: Complex analysis, research, planning, architecture decisions, explaining concepts in depth, multi-step problem solving.
- QUICK: Simple questions, quick lookups, short explanations, clarifications, yes/no questions, status checks.

Task:
{prompt}

Category:"""


async def classify_with_haiku(prompt: str) -> ClassificationResult:
    """Classify a task using Claude Haiku for fast, cheap classification."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        # Fall back to keyword classification if no API key
        return classify_with_keywords(prompt)

    classification_prompt = _CLASSIFICATION_PROMPT.format(prompt=prompt[:2000])

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-3-5-haiku-20241022",
                    "max_tokens": 20,
                    "messages": [{"role": "user", "content": classification_prompt}],
                },
                timeout=5.0,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("content", [])
            if content and isinstance(content[0], dict):
                text = content[0].get("text", "").strip().upper()
                task_type = _parse_task_type(text)
                engine, model = ROUTING_TABLE[task_type]
                return ClassificationResult(
                    task_type=task_type,
                    engine=engine,
                    model=model,
                    confidence=0.9,
                    reason=f"haiku classified as {task_type.value}",
                )
        except (httpx.HTTPError, KeyError, IndexError):
            pass

    # Fall back to keyword classification on any error
    return classify_with_keywords(prompt)


def _parse_task_type(text: str) -> TaskType:
    """Parse task type from classifier response."""
    text = text.strip().upper()
    if "CODING" in text:
        return TaskType.CODING
    if "REASONING" in text:
        return TaskType.REASONING
    if "QUICK" in text:
        return TaskType.QUICK
    # Default to reasoning for ambiguous cases
    return TaskType.REASONING


def classify_with_keywords(prompt: str) -> ClassificationResult:
    """Fast keyword-based classification as fallback."""
    prompt_lower = prompt.lower()
    prompt_len = len(prompt)

    # Coding signals
    coding_signals = [
        "fix",
        "implement",
        "refactor",
        "debug",
        "test",
        "build",
        "compile",
        "deploy",
        "commit",
        "merge",
        "push",
        "pull",
        "branch",
        "error",
        "bug",
        "exception",
        "traceback",
        "function",
        "class",
        "method",
        "variable",
        "import",
        "module",
        "package",
        "install",
        "dependency",
        "npm",
        "pip",
        "cargo",
        "make",
        "dockerfile",
        "yaml",
        "json",
        "config",
        "api",
        "endpoint",
        "database",
        "query",
        "migration",
        "schema",
        "type",
        "interface",
        "struct",
        "enum",
        "lint",
        "format",
        "prettier",
        "eslint",
        "ruff",
        "mypy",
    ]

    # Quick signals (short prompts with these patterns)
    quick_signals = [
        "what is",
        "what's",
        "how do",
        "how does",
        "explain",
        "summarize",
        "define",
        "meaning of",
        "difference between",
        "why is",
        "can you",
        "is it",
        "are there",
        "does it",
        "should i",
        "status",
        "check",
        "list",
        "show",
    ]

    # Count coding signals
    coding_score = sum(1 for signal in coding_signals if signal in prompt_lower)

    # Check for quick patterns
    quick_match = any(signal in prompt_lower for signal in quick_signals)

    # Classification logic
    if coding_score >= 2:
        task_type = TaskType.CODING
        reason = f"keyword match: {coding_score} coding signals"
    elif prompt_len < 100 and quick_match:
        task_type = TaskType.QUICK
        reason = "short prompt with quick pattern"
    elif prompt_len < 50:
        task_type = TaskType.QUICK
        reason = "very short prompt"
    else:
        task_type = TaskType.REASONING
        reason = "default to reasoning for complex prompts"

    engine, model = ROUTING_TABLE[task_type]
    return ClassificationResult(
        task_type=task_type,
        engine=engine,
        model=model,
        confidence=0.7,
        reason=f"keyword: {reason}",
    )


async def classify_task(
    prompt: str,
    *,
    use_llm: bool = True,
) -> ClassificationResult:
    """Classify a task and return routing information.

    Args:
        prompt: The user's prompt/task description
        use_llm: If True, use Haiku for classification. If False, use keywords only.

    Returns:
        ClassificationResult with engine, model, and metadata
    """
    if use_llm:
        return await classify_with_haiku(prompt)
    return classify_with_keywords(prompt)


def update_routing(
    task_type: TaskType,
    engine: EngineId,
    model: str | None = None,
) -> None:
    """Update the routing table for a task type.

    Allows runtime configuration of which engine/model handles each task type.
    """
    ROUTING_TABLE[task_type] = (engine, model)
