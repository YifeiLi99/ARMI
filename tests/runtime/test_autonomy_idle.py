from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock
from uuid import uuid7

import pytest
from armi_runtime.application.life_opportunity import RuntimeLifeOpportunityFacts


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_pending,voice_active,reply_pending,opportunity_pending,quiet_seconds,expected",
    [
        (False, False, False, False, 60, True),
        (False, False, False, False, 59, False),
        (True, False, False, False, 300, False),
        (False, True, False, False, 300, False),
        (False, False, True, False, 300, False),
        (False, False, False, True, 300, False),
    ],
)
async def test_only_quiet_completed_human_exchange_is_idle(
    monkeypatch,
    input_pending,
    voice_active,
    reply_pending,
    opportunity_pending,
    quiet_seconds,
    expected,
):
    now = datetime(2026, 9, 21, tzinfo=UTC)
    before = now - timedelta(seconds=quiet_seconds)
    monkeypatch.setattr(
        "armi_interaction.api.human_input_activity",
        AsyncMock(return_value=(input_pending, before)),
    )
    monkeypatch.setattr(
        "armi_live_voice.api.voice_activity",
        AsyncMock(return_value=(voice_active, None)),
    )
    monkeypatch.setattr(
        "armi_effect.api.response_intent_ids", AsyncMock(return_value=())
    )
    monkeypatch.setattr(
        "armi_effect.api.response_delivery_activity",
        AsyncMock(return_value=(reply_pending, before)),
    )
    monkeypatch.setattr(
        "armi_attention.api.human_opportunity_pending",
        AsyncMock(return_value=opportunity_pending),
    )
    transaction = SimpleNamespace(
        execute=AsyncMock(
            return_value=SimpleNamespace(fetchone=AsyncMock(return_value=(now,)))
        )
    )
    facts = RuntimeLifeOpportunityFacts(
        cognition=AsyncMock(),
        interaction=AsyncMock(),
        mind=AsyncMock(),
        focus=AsyncMock(),
        outlet_health=AsyncMock(),
        model_revision=lambda: "test",
    )
    assert (
        await facts.autonomy_idle(cast(Any, transaction), subject_id=uuid7())
        is expected
    )
