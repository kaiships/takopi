from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..classifier import ClassificationResult, classify_task
from ..context import RunContext
from ..logging import get_logger
from ..model import EngineId
from ..transport_runtime import TransportRuntime
from .chat_prefs import ChatPrefsStore
from .topic_state import TopicStateStore

logger = get_logger(__name__)

EngineSource = Literal[
    "directive",
    "topic_default",
    "chat_default",
    "project_default",
    "global_default",
    "auto_classified",
]


@dataclass(frozen=True, slots=True)
class EngineResolution:
    engine: EngineId
    source: EngineSource
    topic_default: EngineId | None
    chat_default: EngineId | None
    project_default: EngineId | None
    classification: ClassificationResult | None = None
    model_override: str | None = None


async def resolve_engine_for_message(
    *,
    runtime: TransportRuntime,
    context: RunContext | None,
    explicit_engine: EngineId | None,
    chat_id: int,
    topic_key: tuple[int, int] | None,
    topic_store: TopicStateStore | None,
    chat_prefs: ChatPrefsStore | None,
    prompt: str | None = None,
    auto_classify: bool = False,
) -> EngineResolution:
    topic_default = None
    if topic_store is not None and topic_key is not None:
        topic_default = await topic_store.get_default_engine(*topic_key)
    chat_default = None
    if chat_prefs is not None:
        chat_default = await chat_prefs.get_default_engine(chat_id)
    project_default = runtime.project_default_engine(context)

    if explicit_engine is not None:
        return EngineResolution(
            engine=explicit_engine,
            source="directive",
            topic_default=topic_default,
            chat_default=chat_default,
            project_default=project_default,
        )
    if topic_default is not None:
        return EngineResolution(
            engine=topic_default,
            source="topic_default",
            topic_default=topic_default,
            chat_default=chat_default,
            project_default=project_default,
        )
    if chat_default is not None:
        return EngineResolution(
            engine=chat_default,
            source="chat_default",
            topic_default=topic_default,
            chat_default=chat_default,
            project_default=project_default,
        )
    if project_default is not None:
        return EngineResolution(
            engine=project_default,
            source="project_default",
            topic_default=topic_default,
            chat_default=chat_default,
            project_default=project_default,
        )

    # Auto-classification: when enabled and no defaults are set, classify the task
    if auto_classify and prompt is not None:
        classification = await classify_task(prompt, use_llm=True)
        logger.info(
            "auto_classify.result",
            task_type=classification.task_type.value,
            engine=classification.engine,
            model=classification.model,
            confidence=classification.confidence,
            reason=classification.reason,
        )
        return EngineResolution(
            engine=classification.engine,
            source="auto_classified",
            topic_default=topic_default,
            chat_default=chat_default,
            project_default=project_default,
            classification=classification,
            model_override=classification.model,
        )

    return EngineResolution(
        engine=runtime.default_engine,
        source="global_default",
        topic_default=topic_default,
        chat_default=chat_default,
        project_default=project_default,
    )
