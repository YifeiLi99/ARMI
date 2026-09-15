"""Technical notices are distinct from decisions and bound to one accepted input."""

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
    failure_notification_text,
)
from armi_interaction.api import InteractionEffectRoute
from armi_kernel.contracts import TraceId


class _Fixture:
    def __init__(self) -> None:
        self.notices: list[tuple] = []
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
        self.route = InteractionEffectRoute(
            self.source.scene_id,
            "default",
            "creator_dialogue",
            self.source.party_id,
            "creator_inbox",
            None,
            None,
            None,
            None,
        )

        async def execute(sql, params):
            row = None
            if sql.startswith("SELECT notification_id") and self.notices:
                row = (self.notices[0][0],)
            elif "INSERT INTO armi.system_notifications" in sql and not self.notices:
                self.notices.append(params)
                row = (params[0],)
            return SimpleNamespace(fetchone=AsyncMock(return_value=row))

        @asynccontextmanager
        async def unit_of_work(**_kwargs):
            yield SimpleNamespace(
                transaction=SimpleNamespace(execute=execute),
                audit=SimpleNamespace(append=AsyncMock()),
            )

        self.storage = SimpleNamespace(stage=AsyncMock(), publish=AsyncMock())
        self.effects = SimpleNamespace(register_system_notification=AsyncMock())
        self.routes = SimpleNamespace(effect_route=AsyncMock(return_value=self.route))
        self.voice = AsyncMock()
        self.catalog = SimpleNamespace(
            register=AsyncMock(
                return_value=SimpleNamespace(
                    ref=SimpleNamespace(artifact_id=SimpleNamespace(value=uuid7())),
                    inserted=False,
                )
            )
        )
        self.service = InteractionFailureNotifications(
            factory=cast(Any, SimpleNamespace(unit_of_work=unit_of_work)),
            opportunities=cast(Any, None),
            evidence=cast(Any, None),
            routes=cast(Any, self.routes),
            catalog=cast(Any, self.catalog),
            storage=cast(Any, self.storage),
            effects=cast(Any, self.effects),
            diagnostic=self.diagnostics.append,
            voice_failure=self.voice,
        )
        self.service._source = AsyncMock(return_value=self.source)

    async def notify(self, *, unknown=False):
        assert self.source.operation_id is not None
        await self.service.notify_failure(
            opportunity_id=self.source.operation_id,
            failure_code="CANDIDATE-CONTRACT",
            send_unknown=unknown,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("unknown", [False, True])
async def test_notice_is_registered_once_and_has_no_subject_intent(unknown):
    fixture = _Fixture()
    await fixture.notify(unknown=unknown)
    await fixture.notify(unknown=not unknown)
    assert len(fixture.notices) == 1
    assert fixture.notices[0][7] is unknown
    fixture.effects.register_system_notification.assert_awaited_once()
    draft = fixture.effects.register_system_notification.call_args.args[1]
    assert draft.subject_id == fixture.source.subject_id
    assert draft.route == fixture.route
    assert not hasattr(draft, "action_intent_id")
    fixture.storage.stage.assert_awaited_once()


@pytest.mark.asyncio
async def test_background_failure_has_no_input_and_no_notice():
    fixture = _Fixture()
    fixture.service._source = AsyncMock(return_value=None)
    await fixture.notify()
    fixture.storage.stage.assert_not_awaited()
    fixture.effects.register_system_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_accepted_input_can_fail_before_an_opportunity_exists():
    fixture = _Fixture()
    fixture.service._input_source = AsyncMock(
        return_value=replace(fixture.source, operation_id=None)
    )
    await fixture.service.notify_input_failure(
        interaction_id=fixture.source.interaction_id,
        failure_code="EXTERNAL-CONTENT-RECOGNITION",
    )
    await fixture.notify()
    assert len(fixture.notices) == 1
    assert fixture.notices[0][2] is None
    fixture.effects.register_system_notification.assert_awaited_once()


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
async def test_runtime_change_during_artifact_preparation_ends_notice():
    fixture = _Fixture()
    fixture.service._source = AsyncMock(
        side_effect=[
            fixture.source,
            replace(fixture.source, runtime_fence=cast(Any, object())),
        ]
    )
    await fixture.notify()
    assert not fixture.notices
    fixture.effects.register_system_notification.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_channel_leaves_management_receipt_without_fallback():
    fixture = _Fixture()
    fixture.routes.effect_route.return_value = replace(
        fixture.route, destination_binding_id=uuid7()
    )
    await fixture.notify()
    assert fixture.notices[0][9] == "unavailable"
    fixture.effects.register_system_notification.assert_not_awaited()
    fixture.routes.effect_route.assert_awaited_once()


@pytest.mark.asyncio
async def test_notice_artifact_failure_does_not_recurse():
    fixture = _Fixture()
    fixture.storage.stage.side_effect = OSError("isolated artifact failure")
    await fixture.notify()
    assert fixture.diagnostics == ["interaction.system_notification.failed"]
    fixture.storage.stage.assert_awaited_once()
    assert not fixture.notices


@pytest.mark.asyncio
async def test_voice_uses_current_session_state_and_never_switches_to_text():
    fixture = _Fixture()
    fixture.source = replace(fixture.source, modality="live_voice")
    fixture.service._source = AsyncMock(return_value=fixture.source)
    await fixture.notify()
    await fixture.notify()
    fixture.voice.assert_awaited_once_with(fixture.source.operation_id)
    fixture.routes.effect_route.assert_not_awaited()
    fixture.effects.register_system_notification.assert_not_awaited()


def test_unknown_notice_does_not_claim_the_message_was_not_sent():
    normal = failure_notification_text(send_unknown=False)
    unknown = failure_notification_text(send_unknown=True)
    assert normal.startswith("ARMI 系统提示")
    assert unknown.startswith("ARMI 系统提示")
    assert normal != unknown
    assert "可能已送达" in unknown
