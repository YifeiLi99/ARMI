"""CON-SUBJECT and T-03 deterministic contract checks."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, cast
from uuid import uuid4, uuid7

import pytest
import rfc8785
from armi_kernel.application import (
    CandidateApplicationId,
    CandidateApplicationStatus,
    SubjectCommitId,
    SubjectCommitResult,
    SubjectCommitViolation,
)
from armi_kernel.contracts import Digest
from armi_runtime.composition.subject_commit_contract import parse_subject_change_set
from armi_subject_state.api import (
    SubjectComponentSummary,
    SubjectStateKind,
    SubjectStateViolation,
    SubjectSummary,
    default_subject_state_cognition,
)


def _change_set(*, disposition: str = "change") -> bytes:
    ids = [uuid7() for _ in range(5)]
    next_state = {
        "schema_version": "armi.self.v1",
        "identity_kind": "electronic_person",
        "creator_role_awareness": "unique_primary_creator",
        "name": "A",
        "self_description": None,
        "interests": [],
        "values": [],
        "preferences": [],
        "goals": [],
        "self_narrative": None,
        "tensions": [],
    }
    document: dict[str, object] = {
        "schema_version": "armi.subject-change-set.v1",
        "subject_id": str(ids[0]),
        "generation_id": str(ids[1]),
        "episode_id": str(ids[2]),
        "model_attempt_id": str(ids[3]),
        "base": {
            "subject_version": 0,
            "state_epoch": 0,
            "bundle_activation_id": str(ids[4]),
            "context_digest": Digest.from_bytes(b"context").value,
        },
        "disposition": disposition,
        "experiences": [
            {
                "proposal_ref": "proposal:1",
                "atomic_group_ref": "group:1",
                "basis_ordinals": [2],
                "fact_class": "external_claim",
                "first_person_gist": "I heard the Creator make a claim.",
                "uncertainty": "It remains an external claim.",
                "privacy_scope": "private",
            }
        ],
        "components": [
            {
                "proposal_ref": "proposal:2",
                "atomic_group_ref": "group:1",
                "basis_ordinals": [1, 2],
                "fact_class": "subjective_understanding",
                "owner": "self",
                "expected_version": 1,
                "next_state": next_state,
            }
        ],
        "rejections": [],
    }
    return rfc8785.dumps(cast(Any, document))


def test_change_set_parser_is_strict_and_deterministic() -> None:
    value = _change_set()
    first = parse_subject_change_set(value)
    second = parse_subject_change_set(value)
    assert first.canonical_bytes == second.canonical_bytes == value
    assert first.base_subject_version == 0
    assert len(first.experiences) == 1
    state = tuple(item for item in first.owner_drafts if item.owner == "self")
    assert len(state) == 1
    assert (
        default_subject_state_cognition()
        .decode(state[0].canonical_payload)
        .expected_version
        == 1
    )


def test_legacy_component_is_bound_to_subject_state_owner() -> None:
    change_set = parse_subject_change_set(_change_set())
    draft = change_set.owner_drafts[0]
    assert draft.owner == "self"
    assert (
        default_subject_state_cognition().decode(draft.canonical_payload).kind
        is SubjectStateKind.SELF
    )


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value + b"\n",
        lambda value: value.replace(b'"schema_version"', b'"unknown"', 1),
        lambda value: value.replace(b'"expected_version":1', b'"expected_version":0'),
        lambda value: value.replace(b'"proposal:2"', b'"proposal:1"', 1),
    ),
)
def test_change_set_parser_rejects_drift(mutation: Any) -> None:
    with pytest.raises(SubjectCommitViolation, match="SUBJECT-CHANGE-SET-INVALID"):
        parse_subject_change_set(mutation(_change_set()))


def test_subject_summary_is_private_and_ordered() -> None:
    summary = SubjectSummary(
        2,
        (
            SubjectComponentSummary(SubjectStateKind.SELF, 2, "armi.self.v1"),
            SubjectComponentSummary(SubjectStateKind.MIND, 1, "armi.mind.v1"),
            SubjectComponentSummary(SubjectStateKind.LIFE_MODE, 1, "armi.life-mode.v1"),
        ),
        uuid7(),
        datetime.now(UTC),
    )
    assert summary.subject_version == 2
    assert all(value.content_visibility == "private" for value in summary.components)
    with pytest.raises(SubjectStateViolation, match="SUBJECT-STATE-SUMMARY"):
        SubjectComponentSummary(SubjectStateKind.SELF, 2, "armi.mind.v1")


def test_commit_result_requires_exact_applied_shape_and_redacts_error() -> None:
    result = SubjectCommitResult(
        CandidateApplicationId(uuid7()),
        CandidateApplicationStatus.APPLIED,
        SubjectCommitId(uuid7()),
        1,
    )
    assert result.subject_version == 1
    with pytest.raises(SubjectCommitViolation, match="CON-SUBJECT-COMMIT-RESULT"):
        SubjectCommitResult(
            CandidateApplicationId(uuid7()),
            CandidateApplicationStatus.NO_CHANGE,
            SubjectCommitId(uuid7()),
            1,
        )
    with pytest.raises(SubjectCommitViolation):
        SubjectCommitId(uuid4())
    error = SubjectCommitViolation("SUBJECT-CAS-STALE")
    assert "payload" not in str(error)
    assert "postgres" not in str(error).lower()
