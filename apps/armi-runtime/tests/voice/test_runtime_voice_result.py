from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_runtime.application.live_voice import RuntimeLiveVoiceResultObserver


class _Unit:
    def __init__(self) -> None:
        self.transaction = object()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Factory:
    def unit_of_work(self, *, read_only: bool = False) -> _Unit:
        assert read_only
        return _Unit()


@pytest.mark.asyncio
async def test_committed_silence_releases_voice_turn_without_audio() -> None:
    turn_id = uuid7()
    service = AsyncMock()
    read = AsyncMock()
    read.turn_for_opportunity.return_value = turn_id
    observer = RuntimeLiveVoiceResultObserver(
        service=service,
        factory=_Factory(),  # type: ignore[arg-type]
        read=read,
    )

    await observer.committed(
        root_opportunity_id=uuid7(), has_reply=False, awaits_followup=False
    )

    service.complete_silently.assert_awaited_once_with(turn_id=turn_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("has_reply,awaits_followup", ((True, False), (False, True)))
async def test_reply_or_query_keeps_voice_turn_waiting(
    has_reply: bool, awaits_followup: bool
) -> None:
    service = AsyncMock()
    read = AsyncMock()
    observer = RuntimeLiveVoiceResultObserver(
        service=service,
        factory=_Factory(),  # type: ignore[arg-type]
        read=read,
    )

    await observer.committed(
        root_opportunity_id=uuid7(),
        has_reply=has_reply,
        awaits_followup=awaits_followup,
    )

    read.turn_for_opportunity.assert_not_awaited()
    service.complete_silently.assert_not_awaited()
