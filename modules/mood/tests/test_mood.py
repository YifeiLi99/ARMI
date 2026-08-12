from __future__ import annotations

from typing import Any, cast

import pytest
import rfc8785
from armi_kernel.application import CandidateFactClass
from armi_mood.api import CandidateMoodDraft, MoodViolation, default_mood_cognition


def _candidate(**overrides: Any) -> CandidateMoodDraft:
    values: dict[str, Any] = {
        "proposal_ref": "proposal:1",
        "atomic_group_ref": "group:1",
        "basis_ordinals": (1,),
        "fact_class": CandidateFactClass.SUBJECTIVE_UNDERSTANDING,
        "expected_version": 1,
        "canonical_next_state": rfc8785.dumps(
            {"schema_version": "armi.mood.v1", "emotions": ["期待"], "mood": "平静"}
        ),
    }
    values.update(overrides)
    return CandidateMoodDraft(**values)


def test_mood_owner_draft_round_trip_is_canonical() -> None:
    cognition = default_mood_cognition()
    candidate = _candidate()
    bound = cognition.bind(candidate)
    assert bound.owner == "mood"
    assert cognition.decode(bound.canonical_payload) == candidate
    assert cognition.bind(cognition.decode(bound.canonical_payload)) == bound


@pytest.mark.parametrize(
    "state",
    [
        {"schema_version": "armi.mood.v1", "emotions": [], "mood": ""},
        {"schema_version": "armi.mood.v1", "emotions": [1], "mood": None},
        {"schema_version": "armi.mood.v2", "emotions": [], "mood": None},
    ],
)
def test_mood_rejects_invalid_state(state: object) -> None:
    with pytest.raises(MoodViolation):
        _candidate(canonical_next_state=rfc8785.dumps(cast(Any, state)))


def test_mood_rejects_noncanonical_payload() -> None:
    with pytest.raises(MoodViolation, match="MOOD-CANDIDATE"):
        _candidate(
            canonical_next_state=b'{"schema_version":"armi.mood.v1", "emotions":[],"mood":null}'
        )
