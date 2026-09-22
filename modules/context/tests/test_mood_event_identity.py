"""Intake identity survives light/full stages; new evidence remains a new event."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid7

import pytest
from armi_context._application import _mood_event


def snapshot(kind):
    return SimpleNamespace(
        subject_id=uuid7(),
        opportunity_source_ref=uuid7(),
        opportunity_source_version=3,
        opportunity_source_kind=kind,
        root_opportunity_id=uuid7(),
        evidence=None,
        opportunity_available_after=datetime.now(UTC),
        activity_summary_bytes=b"self-triggered event",
    )


@pytest.mark.parametrize(
    "kind",
    [
        "creator_input",
        "live_voice_turn",
        "external_message",
        "visual_observation",
        "codex_task_result",
    ],
)
def test_evidence_is_evaluated_once_across_cognitive_stages(kind):
    value = snapshot("derived_opportunity")
    value.evidence = SimpleNamespace(
        source_id=uuid7(), source_version=2, source_kind=kind
    )
    first = _mood_event(cast(Any, value), uuid7(), b"actual event")
    value.opportunity_source_ref = uuid7()
    value.opportunity_source_version += 1
    full = _mood_event(cast(Any, value), uuid7(), b"actual event")
    assert full.event_key == first.event_key
    assert full.episode_id != first.episode_id
    assert first.summary == "actual event"
    value.evidence.source_id = uuid7()
    tool_result = _mood_event(cast(Any, value), uuid7(), b"new result")
    assert tool_result.event_key != first.event_key


@pytest.mark.parametrize("kind", ["subject_available", "autonomy_plan"])
def test_self_trigger_uses_root_not_stage_or_plan_revision(kind):
    value = snapshot(kind)
    first = _mood_event(cast(Any, value), uuid7(), None)
    value.opportunity_source_version += 1
    later_stage = _mood_event(cast(Any, value), uuid7(), None)
    assert first.event_key == later_stage.event_key
    value.root_opportunity_id = uuid7()
    next_trigger = _mood_event(cast(Any, value), uuid7(), None)
    assert first.event_key != next_trigger.event_key
    assert first.summary == "self-triggered event"
