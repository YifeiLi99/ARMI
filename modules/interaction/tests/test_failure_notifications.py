"""Failures retain diagnostics without producing chat messages or effects."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_interaction._failure_notifications import (
    InteractionFailureNotifications,
    NotificationSourceViolation,
    _Source,
)
from armi_kernel.contracts import TraceId


class _Fixture:
    def __init__(self) -> None:
        self.diagnostics: list[str] = []
        self.source = _Source(
            uuid7(),
            uuid7(),
            uuid7(),
            uuid7(),
            uuid7(),
            None,
            "creator_message",
            "text",
            TraceId("a" * 32),
            cast(Any, object()),
        )
        self.execute = AsyncMock()

        @asynccontextmanager
        async def unit_of_work(**kwargs):
            assert kwargs == {"read_only": True}
            yield SimpleNamespace(transaction=SimpleNamespace(execute=self.execute))

        self.voice = AsyncMock()
        self.service = InteractionFailureNotifications(
            factory=cast(Any, SimpleNamespace(unit_of_work=unit_of_work)),
            opportunities=cast(Any, None),
            evidence=cast(Any, None),
            diagnostic=self.diagnostics.append,
            voice_failure=self.voice,
        )
        self.service._source = AsyncMock(return_value=self.source)

    async def notify(self, *, code="CANDIDATE-CONTRACT", unknown=False):
        assert self.source.operation_id is not None
        await self.service.notify_failure(
            opportunity_id=self.source.operation_id,
            failure_code=code,
            send_unknown=unknown,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    [
        "MODEL-RESPONSE-SCHEMA",
        "CANDIDATE-CONTRACT",
        "MODEL-PROVIDER-FAILED",
        "CONTEXT-FAILED",
        "WEB-FAILED",
        "CODEX-FAILED",
        "VISUAL-FAILED",
        "EFFECT-FAILED",
    ],
)
@pytest.mark.parametrize(
    "purpose,binding",
    [
        ("creator_message", False),
        ("other_human_message", False),
        ("creator_message", True),
        ("other_human_message", True),
    ],
)
@pytest.mark.parametrize("unknown", [False, True])
async def test_all_failures_log_without_chat_writes(code, purpose, binding, unknown):
    fixture = _Fixture()
    fixture.source = replace(
        fixture.source, purpose=purpose, binding_id=uuid7() if binding else None
    )
    fixture.service._source = AsyncMock(return_value=fixture.source)
    await fixture.notify(code=code, unknown=unknown)
    fixture.execute.assert_not_awaited()
    fixture.voice.assert_not_awaited()
    assert len(fixture.diagnostics) == 1
    assert f"code={code}" in fixture.diagnostics[0]
    assert str(fixture.source.operation_id) in fixture.diagnostics[0]
    assert f"send_unknown={unknown}" in fixture.diagnostics[0]


@pytest.mark.asyncio
async def test_input_failure_is_silent_before_opportunity_exists():
    fixture = _Fixture()
    fixture.service._voice_failure = None
    await fixture.service.notify_input_failure(
        interaction_id=fixture.source.interaction_id,
        failure_code="EXTERNAL-CONTENT-RECOGNITION",
    )
    fixture.execute.assert_not_awaited()
    assert len(fixture.diagnostics) == 1
    assert str(fixture.source.interaction_id) in fixture.diagnostics[0]


@pytest.mark.asyncio
async def test_background_failure_only_logs():
    fixture = _Fixture()
    fixture.service._source = AsyncMock(return_value=None)
    await fixture.notify()
    fixture.voice.assert_not_awaited()
    fixture.execute.assert_not_awaited()
    assert len(fixture.diagnostics) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "origin_kind", ["external", "background", "cycle", "different_receiver"]
)
async def test_derived_source_follows_owner_origin_and_preserves_receiver(origin_kind):
    fixture = _Fixture()
    service = fixture.service
    del service._source
    original, derived = fixture.source.operation_id, uuid7()
    evidence_id = uuid7()

    async def opportunity(_transaction, *, opportunity_id):
        return SimpleNamespace(
            opportunity_id=opportunity_id,
            root_opportunity_id=opportunity_id,
            evidence_id=evidence_id,
            subject_id=fixture.source.subject_id,
            scene_id=fixture.source.scene_id,
            context_party_id=(
                uuid7()
                if origin_kind == "different_receiver" and opportunity_id == original
                else fixture.source.party_id
            ),
        )

    service._opportunities = cast(Any, SimpleNamespace(context_snapshot=opportunity))
    service._evidence = cast(
        Any,
        SimpleNamespace(
            snapshot=AsyncMock(
                side_effect=[
                    SimpleNamespace(interaction_id=None),
                    SimpleNamespace(interaction_id=fixture.source.interaction_id),
                ]
            )
        ),
    )
    service._derived_origin = AsyncMock(
        return_value=(
            None
            if origin_kind == "background"
            else derived
            if origin_kind == "cycle"
            else original
        )
    )
    source = fixture.source
    uow = cast(
        Any,
        SimpleNamespace(
            runtime_fence=source.runtime_fence,
            transaction=SimpleNamespace(
                execute=AsyncMock(
                    return_value=SimpleNamespace(
                        fetchone=AsyncMock(
                            return_value=(
                                source.subject_id,
                                source.scene_id,
                                source.party_id,
                                source.binding_id,
                                source.purpose,
                                source.modality,
                                source.trace_id.value,
                            )
                        )
                    )
                )
            ),
        ),
    )
    if origin_kind in {"cycle", "different_receiver"}:
        with pytest.raises(NotificationSourceViolation):
            await service._source(uow, derived)
    else:
        result = await service._source(uow, derived)
        assert result == (None if origin_kind == "background" else source)


@pytest.mark.asyncio
async def test_voice_failure_finishes_pending_turn_without_chat_writes():
    fixture = _Fixture()
    fixture.source = replace(fixture.source, modality="live_voice")
    fixture.service._source = AsyncMock(return_value=fixture.source)
    await fixture.notify()
    fixture.voice.assert_awaited_once_with(fixture.source.operation_id)
    fixture.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_voice_cleanup_failure_logs_without_recursive_notification():
    fixture = _Fixture()
    fixture.service._source = AsyncMock(side_effect=OSError("unavailable"))
    await fixture.notify()
    assert len(fixture.diagnostics) == 2
    assert fixture.diagnostics[1] == "interaction.failure_cleanup.failed"
    fixture.execute.assert_not_awaited()
    fixture.voice.assert_not_awaited()
