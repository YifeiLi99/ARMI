from __future__ import annotations

import asyncio
from typing import cast
from uuid import uuid7

import pytest
from armi_data_rights.api import EmptyDataRightsParticipant
from armi_mood.api import MoodReadPort
from armi_prompt.api import PromptReadPort
from armi_runtime.composition.owner_roster import compose_runtime_owner_roster
from armi_runtime_foundation import (
    EmptyRecoveryParticipant,
    PostgreSQLTransaction,
    RecoveryContribution,
    RecoveryMetricContribution,
    RecoveryOwnerIdentity,
    RecoveryScope,
)
from armi_subject_state.api import SubjectStateReadPort


def _scope() -> RecoveryScope:
    return RecoveryScope(uuid7(), uuid7(), uuid7(), uuid7(), uuid7(), 1)


def test_runtime_composition_builds_the_fixed_twenty_three_owner_roster() -> None:
    roster = compose_runtime_owner_roster(
        data_rights=EmptyDataRightsParticipant("data-rights"),
        mood_read=cast(MoodReadPort, object()),
        prompt_read=cast(PromptReadPort, object()),
        subject_state_read=cast(SubjectStateReadPort, object()),
    )
    participants = roster.recovery
    expected = roster.expected_recovery_owners

    assert len(participants) == 23
    assert tuple(item.owner_identity for item in participants) == expected
    assert len(set(expected)) == 23
    assert expected == tuple(
        RecoveryOwnerIdentity(value)
        for value in (
            "subject-state",
            "mood",
            "prompt",
            "activity",
            "material",
            "memory",
            "relationship",
            "sleep",
            "context",
            "interaction",
            "perception",
            "live-voice",
            "live-vision",
            "evidence",
            "cognition",
            "experience",
            "opportunity",
            "expression",
            "capability",
            "effect",
            "web-observation",
            "codex",
            "data-rights",
        )
    )


@pytest.mark.parametrize(
    "owner",
    (
        "activity",
        "material",
        "memory",
        "relationship",
        "sleep",
        "context",
        "experience",
        "data-rights",
    ),
)
def test_explicit_empty_participant_is_stable_and_idempotent(owner: str) -> None:
    participant = EmptyRecoveryParticipant(owner)

    first = asyncio.run(
        participant.recover(cast(PostgreSQLTransaction, object()), _scope(), ())
    )
    second = asyncio.run(
        participant.recover(cast(PostgreSQLTransaction, object()), _scope(), ())
    )

    assert first == second == RecoveryContribution(RecoveryOwnerIdentity(owner))


def test_recovery_contribution_rejects_duplicate_or_unnamespaced_tokens() -> None:
    with pytest.raises(ValueError, match="duplicated"):
        RecoveryContribution(
            RecoveryOwnerIdentity("memory"),
            metrics=(
                RecoveryMetricContribution("memory.fact_count", 1),
                RecoveryMetricContribution("memory.fact_count", 2),
            ),
        )
    with pytest.raises(ValueError, match="metric kind"):
        RecoveryMetricContribution("Not A Token", 1)
