"""Tests for events module."""

from __future__ import annotations

import pytest

from takopi.events import EventFactory
from takopi.model import ResumeToken


class TestEventFactory:
    """Tests for EventFactory class."""

    def test_initial_resume_is_none(self) -> None:
        factory = EventFactory(engine="test")
        assert factory.resume is None

    def test_started_sets_resume(self) -> None:
        factory = EventFactory(engine="test")
        token = ResumeToken(engine="test", value="session-123")
        event = factory.started(token)
        assert factory.resume == token
        assert event.resume == token

    def test_started_wrong_engine_raises(self) -> None:
        factory = EventFactory(engine="test")
        token = ResumeToken(engine="other", value="session-123")
        with pytest.raises(RuntimeError, match="resume token is for engine"):
            factory.started(token)

    def test_started_token_mismatch_raises(self) -> None:
        factory = EventFactory(engine="test")
        token1 = ResumeToken(engine="test", value="session-1")
        token2 = ResumeToken(engine="test", value="session-2")
        factory.started(token1)
        with pytest.raises(RuntimeError, match="resume token mismatch"):
            factory.started(token2)

    def test_started_same_token_ok(self) -> None:
        factory = EventFactory(engine="test")
        token = ResumeToken(engine="test", value="session-123")
        factory.started(token)
        # Same token should not raise
        event = factory.started(token)
        assert event.resume == token
