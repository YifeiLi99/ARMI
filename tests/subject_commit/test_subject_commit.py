"""CON-SUBJECT and T-03 deterministic contract checks."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4, uuid7

import pytest
from armi_kernel.application import (
    CandidateApplicationId,
    CandidateApplicationStatus,
    SubjectCommitId,
    SubjectCommitResult,
    SubjectCommitViolation,
)
from armi_subject_state.api import (
    SubjectComponentSummary,
    SubjectStateKind,
    SubjectStateViolation,
    SubjectSummary,
)


def test_subject_summary_is_private_and_ordered() -> None:
    summary = SubjectSummary(
        2,
        (
            SubjectComponentSummary(SubjectStateKind.SELF, 2, "armi.self.v1"),
            SubjectComponentSummary(SubjectStateKind.MIND, 1, "armi.mind.v2"),
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
