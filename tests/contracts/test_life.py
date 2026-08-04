"""P0-S001 autonomous opportunity source contract checks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid7

import pytest
from armi_kernel.application import (
    LifeOpportunitySourceKind,
    LifeOpportunitySourceSnapshot,
    LifeViolation,
    OpportunityAdmissionOutcome,
    OpportunityAdmissionStatus,
)
from armi_kernel.contracts import ActivityId, Digest


def _source(
    *,
    kind: LifeOpportunitySourceKind = (
        LifeOpportunitySourceKind.LIFE_GENERATION_AVAILABLE
    ),
    activity_id: ActivityId | None = None,
) -> LifeOpportunitySourceSnapshot:
    now = datetime.now(UTC)
    return LifeOpportunitySourceSnapshot(
        subject_id=uuid7(),
        generation_id=uuid7(),
        kind=kind,
        reference=uuid7(),
        version=1,
        digest=Digest.from_bytes(b"source"),
        available_after=now,
        expires_at=now + timedelta(minutes=5),
        activity_id=activity_id,
    )


def test_life_source_requires_normalized_identity_and_valid_expiry() -> None:
    source = _source()
    assert source.kind is LifeOpportunitySourceKind.LIFE_GENERATION_AVAILABLE
    assert source.version == 1

    with pytest.raises(LifeViolation, match="LIFE-SOURCE"):
        LifeOpportunitySourceSnapshot(
            subject_id=source.subject_id,
            generation_id=source.generation_id,
            kind=source.kind,
            reference=source.reference,
            version=0,
            digest=source.digest,
            available_after=source.available_after,
        )
    with pytest.raises(LifeViolation, match="LIFE-SOURCE"):
        LifeOpportunitySourceSnapshot(
            subject_id=source.subject_id,
            generation_id=source.generation_id,
            kind=source.kind,
            reference=source.reference,
            version=1,
            digest=source.digest,
            available_after=source.available_after,
            expires_at=source.available_after,
        )


def test_activity_revision_source_requires_activity_authority() -> None:
    with pytest.raises(LifeViolation, match="LIFE-SOURCE-ACTIVITY"):
        _source(kind=LifeOpportunitySourceKind.ACTIVITY_REVISION)
    activity_id = ActivityId(uuid7())
    source = _source(
        kind=LifeOpportunitySourceKind.ACTIVITY_REVISION,
        activity_id=activity_id,
    )
    assert source.activity_id == activity_id

    with pytest.raises(LifeViolation, match="LIFE-SOURCE-ACTIVITY"):
        _source(activity_id=activity_id)


def test_admission_outcome_preserves_duplicate_identity_and_rejection_reason() -> None:
    opportunity_id = uuid7()
    duplicate = OpportunityAdmissionOutcome(
        OpportunityAdmissionStatus.DUPLICATE,
        opportunity_id,
    )
    rejected = OpportunityAdmissionOutcome(
        OpportunityAdmissionStatus.REJECTED,
        None,
        "LIFE-SOURCE-STALE",
    )
    assert duplicate.opportunity_id == opportunity_id
    assert rejected.reason_code == "LIFE-SOURCE-STALE"

    with pytest.raises(LifeViolation, match="LIFE-ADMISSION"):
        OpportunityAdmissionOutcome(
            OpportunityAdmissionStatus.REJECTED,
            opportunity_id,
            "LIFE-SOURCE-STALE",
        )
